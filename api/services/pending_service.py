"""Pending actions management via Supabase."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

import structlog
from supabase import create_client

from config import settings

logger = structlog.get_logger(__name__)


def _get_client():
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def create_pending(action_payload: dict, description: str) -> dict:
    """Create a pending action with expiration."""
    client = _get_client()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.pending_expiration_minutes)

    data = {
        "action_payload": action_payload,
        "description": description,
        "expires_at": expires_at.isoformat(),
    }

    result = client.table("pending_actions").insert(data).execute()
    pending = result.data[0]
    logger.info("pending_create", pending_id=pending["id"], description=description)
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

    If confirmed, returns the action_payload for execution.
    """
    client = _get_client()

    # Fetch the pending action
    result = client.table("pending_actions") \
        .select("*") \
        .eq("id", str(pending_id)) \
        .eq("status", "pending") \
        .execute()

    if not result.data:
        raise ValueError(f"Pending action {pending_id} not found or already resolved")

    pending = result.data[0]

    # Check expiration
    expires_at = datetime.fromisoformat(pending["expires_at"])
    if datetime.now(timezone.utc) > expires_at:
        client.table("pending_actions") \
            .update({"status": "expired"}) \
            .eq("id", str(pending_id)) \
            .execute()
        raise ValueError(f"Pending action {pending_id} has expired")

    # Resolve
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
    }
