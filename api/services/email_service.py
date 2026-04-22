"""Zimbra mail service — IMAP fetch + Supabase cache.

Fetches the most recent UNSEEN emails from Zimbra over IMAPS and stores them
in Supabase. Donna reads exclusively from Supabase, never triggers an IMAP
fetch herself.

Security:
- IMAPS only (TLS-encrypted on port 993), never IMAP cleartext.
- Password is read from settings and never logged.
- BODY.PEEK[] keeps server-side unread status untouched.
- No attachments are stored (plain-text / html-to-text only).
"""

from __future__ import annotations

import email
import imaplib
import re
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parseaddr, parsedate_to_datetime
from typing import Any
from uuid import UUID

import html2text
import structlog
from supabase import create_client

from config import settings

logger = structlog.get_logger(__name__)

# Cap on the body size we store. Body is truncated safely at this limit —
# rare emails exceeding it are still usable for search/preview.
_MAX_BODY_CHARS = 200_000

_html_converter = html2text.HTML2Text()
_html_converter.ignore_images = True
_html_converter.ignore_links = False
_html_converter.body_width = 0  # don't rewrap lines


def _get_client():
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def is_configured() -> bool:
    """Check if IMAP mail sync is configured."""
    return bool(
        settings.zimbra_imap_host
        and settings.zimbra_user
        and settings.zimbra_password
    )


def _decode_header(raw: Any) -> str:
    """Decode an RFC 2047 encoded email header to a plain string."""
    if raw is None:
        return ""
    try:
        return str(make_header(decode_header(str(raw))))
    except Exception:
        return str(raw)


def _extract_body(msg: Message) -> str:
    """Extract body as plain text. Prefers text/plain, falls back to html2text.

    Skips attachments (any part with Content-Disposition: attachment).
    """
    plain_parts: list[str] = []
    html_parts: list[str] = []

    if msg.is_multipart():
        for part in msg.walk():
            if part.is_multipart():
                continue

            disposition = (part.get("Content-Disposition") or "").lower()
            if "attachment" in disposition:
                continue

            ctype = (part.get_content_type() or "").lower()
            if ctype not in ("text/plain", "text/html"):
                continue

            try:
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                text = payload.decode(charset, errors="replace")
            except Exception:
                continue

            if ctype == "text/plain":
                plain_parts.append(text)
            else:
                html_parts.append(text)
    else:
        try:
            payload = msg.get_payload(decode=True) or b""
            charset = msg.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
        except Exception:
            text = ""

        ctype = (msg.get_content_type() or "").lower()
        if ctype == "text/html":
            html_parts.append(text)
        else:
            plain_parts.append(text)

    if plain_parts:
        body = "\n".join(p.strip() for p in plain_parts if p.strip())
    elif html_parts:
        body = _html_converter.handle("\n".join(html_parts))
    else:
        body = ""

    body = body.strip()
    if len(body) > _MAX_BODY_CHARS:
        body = body[:_MAX_BODY_CHARS] + "\n...[tronqué]"
    return body


def _parse_received_at(msg: Message) -> datetime:
    """Parse the Date header into a UTC datetime. Falls back to now()."""
    raw = msg.get("Date")
    if raw:
        try:
            dt = parsedate_to_datetime(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass
    return datetime.now(timezone.utc)


def _extract_message_id(msg: Message, uid: str) -> str:
    """Return the RFC 822 Message-ID, or a synthetic fallback based on the UID."""
    raw = msg.get("Message-ID") or msg.get("Message-Id")
    if raw:
        mid = str(raw).strip().strip("<>").strip()
        if mid:
            return mid
    return f"zimbra-uid-{uid}"


def _parse_email(raw_bytes: bytes, uid: str) -> dict:
    """Parse a raw RFC 822 message into a dict ready for Supabase upsert."""
    msg = email.message_from_bytes(raw_bytes)

    from_header = _decode_header(msg.get("From"))
    sender_name, sender_email = parseaddr(from_header)
    sender_name = sender_name.strip() or None

    subject = _decode_header(msg.get("Subject")).strip() or None
    body = _extract_body(msg)
    received_at = _parse_received_at(msg)
    message_id = _extract_message_id(msg, uid)

    return {
        "message_id": message_id,
        "sender_name": sender_name,
        "sender_email": (sender_email or "").strip().lower() or "unknown@unknown",
        "subject": subject,
        "body": body,
        "received_at": received_at.isoformat(),
    }


def _fetch_recent_unread_via_imap(limit: int) -> list[dict]:
    """Connect to Zimbra IMAPS, fetch up to `limit` most recent UNSEEN messages.

    Returns a list of parsed email dicts. Never raises — returns [] on error.
    The password is never logged.
    """
    if not is_configured():
        logger.info("imap_not_configured")
        return []

    host = settings.zimbra_imap_host
    port = settings.zimbra_imap_port
    user = settings.zimbra_user

    parsed: list[dict] = []
    conn: imaplib.IMAP4_SSL | None = None
    try:
        conn = imaplib.IMAP4_SSL(host, port, timeout=20)
        conn.login(user, settings.zimbra_password)
        conn.select("INBOX", readonly=True)

        status, data = conn.search(None, "UNSEEN")
        if status != "OK":
            logger.warning("imap_search_failed", status=status)
            return []

        ids_raw = (data[0] or b"").split()
        if not ids_raw:
            logger.info("imap_no_unseen")
            return []

        # IMAP returns ascending IDs; newest are at the end
        recent_ids = ids_raw[-limit:]
        recent_ids.reverse()

        for raw_id in recent_ids:
            uid = raw_id.decode(errors="replace")
            status, fetched = conn.fetch(raw_id, "(BODY.PEEK[])")
            if status != "OK" or not fetched:
                continue

            raw_bytes: bytes | None = None
            for part in fetched:
                if isinstance(part, tuple) and len(part) >= 2 and isinstance(part[1], (bytes, bytearray)):
                    raw_bytes = bytes(part[1])
                    break
            if raw_bytes is None:
                continue

            try:
                parsed.append(_parse_email(raw_bytes, uid))
            except Exception as e:
                logger.error("imap_parse_failed", uid=uid, error=str(e))

        logger.info("imap_fetched", count=len(parsed), host=host)
    except imaplib.IMAP4.error as e:
        logger.error("imap_protocol_error", host=host, error=str(e))
    except Exception as e:
        logger.error("imap_unexpected_error", host=host, error=str(e))
    finally:
        if conn is not None:
            try:
                conn.logout()
            except Exception:
                pass
    return parsed


def _upsert_email(client, data: dict) -> bool:
    """Insert an email if its message_id doesn't exist yet. Returns True if inserted."""
    existing = (
        client.table("emails")
        .select("id")
        .eq("message_id", data["message_id"])
        .limit(1)
        .execute()
    )
    if existing.data:
        return False

    client.table("emails").insert(data).execute()
    return True


def _trim_cache(client, max_size: int) -> int:
    """Keep only the `max_size` most recent emails (by received_at). Returns deleted count."""
    result = (
        client.table("emails")
        .select("id")
        .order("received_at", desc=True)
        .limit(max_size)
        .execute()
    )
    keep_ids = [row["id"] for row in result.data]
    if not keep_ids:
        return 0

    deleted = (
        client.table("emails")
        .delete()
        .not_.in_("id", keep_ids)
        .execute()
    )
    return len(deleted.data) if deleted.data else 0


def sync_recent_unread(limit: int = 5) -> dict:
    """Fetch the `limit` most recent UNSEEN emails and upsert into Supabase.

    Trims the cache to `zimbra_emails_cache_size` afterwards.
    Returns {"fetched": N, "inserted": N, "trimmed": N, "configured": bool}.
    """
    if not is_configured():
        return {"fetched": 0, "inserted": 0, "trimmed": 0, "configured": False}

    fetched = _fetch_recent_unread_via_imap(limit)
    if not fetched:
        return {"fetched": 0, "inserted": 0, "trimmed": 0, "configured": True}

    client = _get_client()
    inserted_count = 0
    for data in fetched:
        try:
            if _upsert_email(client, data):
                inserted_count += 1
        except Exception as e:
            logger.error(
                "email_upsert_failed",
                message_id=data.get("message_id"),
                error=str(e),
            )

    trimmed = 0
    try:
        trimmed = _trim_cache(client, settings.zimbra_emails_cache_size)
    except Exception as e:
        logger.error("email_trim_failed", error=str(e))

    logger.info(
        "emails_synced",
        fetched=len(fetched),
        inserted=inserted_count,
        trimmed=trimmed,
    )
    return {
        "fetched": len(fetched),
        "inserted": inserted_count,
        "trimmed": trimmed,
        "configured": True,
    }


def _serialize(row: dict, include_body: bool) -> dict:
    out = {
        "id": row.get("id"),
        "message_id": row.get("message_id"),
        "sender_name": row.get("sender_name"),
        "sender_email": row.get("sender_email"),
        "subject": row.get("subject"),
        "received_at": row.get("received_at"),
        "notified_in_recap": row.get("notified_in_recap", False),
    }
    if include_body:
        out["body"] = row.get("body")
    return out


_ILIKE_WILDCARDS = re.compile(r"[%_\\]")
# PostgREST `or=` filter is comma-separated and uses parens for grouping,
# so we strip those characters from user input before interpolating.
_PG_FILTER_BREAKERS = re.compile(r"[,()\"]")


def _sanitize_ilike(value: str) -> str:
    """Prepare a user string for ILIKE inside a PostgREST `or_` filter.

    - Escapes ILIKE wildcards so they match literally.
    - Strips characters that would break the `or=(...)` filter syntax.
    """
    escaped = _ILIKE_WILDCARDS.sub(lambda m: "\\" + m.group(0), value)
    return _PG_FILTER_BREAKERS.sub(" ", escaped).strip()


def search_emails(
    query: str | None = None,
    received_after: datetime | None = None,
    received_before: datetime | None = None,
    limit: int = 10,
) -> list[dict]:
    """Search cached emails by substring on sender/subject and/or date range."""
    client = _get_client()
    limit = max(1, min(limit, 30))

    q = client.table("emails").select("*")

    if query:
        safe = _sanitize_ilike(query.strip())
        if safe:
            pattern = f"%{safe}%"
            q = q.or_(
                f"sender_name.ilike.{pattern},"
                f"sender_email.ilike.{pattern},"
                f"subject.ilike.{pattern}"
            )

    if received_after is not None:
        q = q.gte("received_at", received_after.isoformat())
    if received_before is not None:
        q = q.lte("received_at", received_before.isoformat())

    result = q.order("received_at", desc=True).limit(limit).execute()
    logger.info("emails_search", query=query, count=len(result.data))
    return [_serialize(r, include_body=False) for r in result.data]


def get_email(email_id: UUID) -> dict | None:
    """Return a single email including its body, or None if not found."""
    client = _get_client()
    result = (
        client.table("emails")
        .select("*")
        .eq("id", str(email_id))
        .limit(1)
        .execute()
    )
    if not result.data:
        return None
    return _serialize(result.data[0], include_body=True)


def list_unread_emails(days: int = 2, limit: int = 10) -> list[dict]:
    """List cached emails received in the last `days` days, newest first."""
    client = _get_client()
    days = max(1, min(days, 30))
    limit = max(1, min(limit, 30))

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result = (
        client.table("emails")
        .select("*")
        .gte("received_at", cutoff.isoformat())
        .order("received_at", desc=True)
        .limit(limit)
        .execute()
    )
    logger.info("emails_list_unread", days=days, count=len(result.data))
    return [_serialize(r, include_body=False) for r in result.data]


def get_recap_emails() -> dict:
    """Return up to 5 emails not yet notified, received in the last 2 days.

    Also returns `extra_count`: number of additional non-notified emails in the
    same window beyond the 5 shown.
    """
    client = _get_client()
    cutoff = datetime.now(timezone.utc) - timedelta(days=2)

    result = (
        client.table("emails")
        .select("*")
        .eq("notified_in_recap", False)
        .gte("received_at", cutoff.isoformat())
        .order("received_at", desc=True)
        .execute()
    )
    rows = result.data or []
    top = rows[:5]
    extra = max(0, len(rows) - len(top))

    logger.info("emails_recap", shown=len(top), extra=extra)
    return {
        "emails": [_serialize(r, include_body=False) for r in top],
        "extra_count": extra,
    }


def mark_as_notified(email_ids: list[UUID]) -> int:
    """Mark the given emails as notified_in_recap=true. Returns updated count."""
    if not email_ids:
        return 0
    client = _get_client()
    ids_str = [str(i) for i in email_ids]
    result = (
        client.table("emails")
        .update({"notified_in_recap": True})
        .in_("id", ids_str)
        .execute()
    )
    count = len(result.data) if result.data else 0
    logger.info("emails_mark_notified", count=count)
    return count
