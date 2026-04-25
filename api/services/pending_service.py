"""Pending actions management via Supabase.

Fix 2 — payload binding:

The server validates `action_payload` against `PendingActionPayload`
(discriminated by `action`). This whitelists which actions a pending may
carry and enforces required fields per type, so a compromised model cannot
inject arbitrary keys via `create_pending`.

The user-facing `display_description` is generated server-side from the
validated payload + real data fetched from Google Calendar / Supabase.
The free-text description sent by Claude is stored only for audit and is
NEVER displayed on the inline button. This breaks the "Confirmer le
RDV dentiste" / payload=delete-wedding spoofing primitive.

When the referenced object cannot be fetched (event removed, todo deleted,
etc.), the row is stored with `executable=false` so /pending/resolve later
refuses `confirm` while still allowing `cancel`.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytz
import structlog
from pydantic import ValidationError
from supabase import create_client

from api.services import calendar_service, rules_service, todos_service, zimbra_service
from config import settings
from db.models import PendingActionPayload, PendingActionType

logger = structlog.get_logger(__name__)


def _get_client():
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def _format_local_dt(dt: datetime) -> str:
    """Format a datetime as 'JJ/MM HHhMM' in the user's local timezone."""
    tz = pytz.timezone(settings.timezone)
    if dt.tzinfo is None:
        dt = tz.localize(dt)
    return dt.astimezone(tz).strftime("%d/%m %Hh%M")


def _format_event_when(start_iso: str) -> str:
    """Best-effort local format of an ISO start time. Falls back to the raw string."""
    try:
        return _format_local_dt(datetime.fromisoformat(start_iso.replace("Z", "+00:00")))
    except Exception:
        return start_iso


def _truncate(s: str, limit: int = 80) -> str:
    s = s.strip()
    if len(s) <= limit:
        return s
    return s[: limit - 3] + "..."


def _build_display_description(p: PendingActionPayload) -> tuple[str, bool]:
    """Generate (display_description, executable) from a validated payload.

    The display string is what the user sees on the inline button. It is
    derived from real data so a compromised model cannot mislabel the action.
    """
    a = p.action

    if a == PendingActionType.DELETE_EVENT:
        try:
            event = calendar_service.get_event(p.event_id)
        except Exception as e:
            logger.error("pending_fetch_event_failed", error=str(e))
            return "[Pending obsolète : impossible de fetch l'event]", False
        if not event:
            return "[Pending obsolète : event introuvable]", False
        when = _format_event_when(event.get("start", ""))
        title = _truncate(event.get("title") or "(sans titre)")
        return f"Supprimer '{title}' le {when}", True

    if a == PendingActionType.DELETE_TODO:
        try:
            todo = todos_service.get_todo(p.todo_id)
        except Exception as e:
            logger.error("pending_fetch_todo_failed", error=str(e))
            return "[Pending obsolète : impossible de fetch la todo]", False
        if not todo:
            return "[Pending obsolète : todo introuvable]", False
        return f"Supprimer la todo '{_truncate(todo.get('title') or '(sans titre)')}'", True

    if a == PendingActionType.DELETE_RULE:
        try:
            rule = rules_service.get_rule(p.rule_id)
        except Exception as e:
            logger.error("pending_fetch_rule_failed", error=str(e))
            return "[Pending obsolète : impossible de fetch la règle]", False
        if not rule:
            return "[Pending obsolète : règle introuvable]", False
        return f"Supprimer la règle '{_truncate(rule.get('rule_text') or '(sans texte)')}'", True

    if a == PendingActionType.CREATE_EVENT:
        conflicts, check_failed = _detect_conflicts(p.start, p.end)
        when = f"{_format_local_dt(p.start)}–{_format_local_dt(p.end).split(' ')[-1]}"
        title = _truncate(p.title or "(sans titre)")
        base = f"Créer '{title}' le {when}"
        if p.attendees:
            attendees_short = ", ".join(_truncate(a, 60) for a in p.attendees[:5])
            notify_label = "envoi d'invitations" if p.notify_attendees else "sans envoi d'invitation"
            base = f"{base} (invités : {attendees_short} — {notify_label})"
        if conflicts:
            conflict_str = ", ".join(f"'{_truncate(c, 40)}'" for c in conflicts[:3])
            base = f"{base} ⚠ chevauche : {conflict_str}"
        elif check_failed:
            # The availability check is informational UX, not a security gate;
            # a freeBusy / Zimbra outage must not block pending creation.
            base = f"{base} ⚠ [chevauchement non vérifié — appel calendrier en échec]"
        return base, True

    if a == PendingActionType.UPDATE_EVENT:
        try:
            event = calendar_service.get_event(p.event_id)
        except Exception as e:
            logger.error("pending_fetch_event_failed", error=str(e))
            return "[Pending obsolète : impossible de fetch l'event]", False
        if not event:
            return "[Pending obsolète : event introuvable]", False
        title = _truncate(event.get("title") or "(sans titre)")
        changes = _summarize_update_fields(p.fields or {})
        return f"Modifier '{title}' : {changes}", True

    return "Action inconnue", False


def _detect_conflicts(start: datetime, end: datetime) -> tuple[list[str], bool]:
    """Return (overlap_titles, check_failed) across Google + Zimbra.

    `check_failed` is true if any backend raised — so the caller can surface
    "[chevauchement non vérifié]" rather than implying a clean check. We never
    propagate the exception: pending creation must remain available even when
    Google freeBusy / Zimbra is temporarily down.
    """
    titles: list[str] = []
    check_failed = False
    try:
        for ev in calendar_service.list_overlapping_events(start, end):
            titles.append(ev.get("title") or "(sans titre)")
    except Exception as e:
        logger.warning("pending_conflict_check_google_failed", error=str(e))
        check_failed = True

    if zimbra_service.is_configured():
        try:
            for ev in zimbra_service.check_availability(start, end):
                titles.append(ev.get("title") or "(cours sans titre)")
        except Exception as e:
            logger.warning("pending_conflict_check_zimbra_failed", error=str(e))
            check_failed = True
    return titles, check_failed


def _summarize_update_fields(fields: dict) -> str:
    parts: list[str] = []
    if "title" in fields:
        parts.append(f"titre → '{_truncate(str(fields['title']), 40)}'")
    if "start" in fields:
        parts.append(f"début → {_format_event_when(str(fields['start']))}")
    if "end" in fields:
        parts.append(f"fin → {_format_event_when(str(fields['end']))}")
    if "description" in fields:
        parts.append("description modifiée")
    return ", ".join(parts) if parts else "modification"


def create_pending(action_payload: dict, description: str) -> dict:
    """Create a pending action with expiration.

    Validates `action_payload` against the PendingActionPayload enum/shape;
    raises ValueError on invalid shape (the route surfaces this to the model).

    The user-facing `display_description` is generated server-side from the
    validated payload — the free-text `description` provided by Claude is
    only stored for audit and never shown to the user.
    """
    try:
        validated = PendingActionPayload.model_validate(action_payload)
    except ValidationError as e:
        logger.warning("pending_invalid_payload", errors=e.errors())
        raise ValueError("Payload de pending invalide ou incomplet")

    display_description, executable = _build_display_description(validated)

    canonical_payload = validated.model_dump(mode="json", exclude_none=True)

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.pending_expiration_minutes)
    data = {
        "action_payload": canonical_payload,
        "description": description,
        "display_description": display_description,
        "executable": executable,
        "expires_at": expires_at.isoformat(),
    }

    client = _get_client()
    result = client.table("pending_actions").insert(data).execute()
    pending = result.data[0]
    logger.info(
        "pending_create",
        pending_id=pending["id"],
        action=validated.action.value,
        executable=executable,
    )
    return pending


def list_pending() -> list[dict]:
    """List non-expired pending actions."""
    client = _get_client()
    now = datetime.now(timezone.utc).isoformat()

    # First, expire old pending actions
    client.table("pending_actions") \
        .update({"status": "expired"}) \
        .eq("status", "pending") \
        .lt("expires_at", now) \
        .execute()

    # Then fetch remaining pending
    result = client.table("pending_actions") \
        .select("*") \
        .eq("status", "pending") \
        .order("created_at", desc=True) \
        .execute()

    logger.info("pending_list", count=len(result.data))
    return result.data


def resolve_pending(pending_id: UUID, choice: str) -> dict:
    """Resolve a pending action (confirm or cancel).

    Refuses `confirm` on a non-executable (obsolete) pending. `cancel` is
    always allowed so the user can clean up.

    On confirm, returns the canonical action_payload for execution.
    """
    client = _get_client()

    result = client.table("pending_actions") \
        .select("*") \
        .eq("id", str(pending_id)) \
        .eq("status", "pending") \
        .execute()

    if not result.data:
        raise ValueError(f"Pending action {pending_id} not found or already resolved")

    pending = result.data[0]

    expires_at = datetime.fromisoformat(pending["expires_at"])
    if datetime.now(timezone.utc) > expires_at:
        client.table("pending_actions") \
            .update({"status": "expired"}) \
            .eq("id", str(pending_id)) \
            .execute()
        raise ValueError(f"Pending action {pending_id} has expired")

    if choice == "confirm" and not pending.get("executable", True):
        raise ValueError(f"Pending action {pending_id} is obsolete and cannot be confirmed")

    new_status = "resolved" if choice == "confirm" else "cancelled"
    client.table("pending_actions") \
        .update({
            "status": new_status,
            "resolved_at": datetime.now(timezone.utc).isoformat(),
        }) \
        .eq("id", str(pending_id)) \
        .execute()

    logger.info("pending_resolve", pending_id=str(pending_id), choice=choice)

    return {
        "pending_id": str(pending_id),
        "choice": choice,
        "action_payload": pending["action_payload"] if choice == "confirm" else None,
        "display_description": pending.get("display_description"),
        "executable": pending.get("executable", True),
    }


def mark_obsolete(pending_id: UUID) -> dict:
    """Flip `executable` to false on a pending. Used when execution discovers
    that the underlying object has disappeared since the pending was created."""
    client = _get_client()
    client.table("pending_actions") \
        .update({"executable": False}) \
        .eq("id", str(pending_id)) \
        .execute()
    logger.info("pending_mark_obsolete", pending_id=str(pending_id))
    return {"pending_id": str(pending_id), "executable": False}
