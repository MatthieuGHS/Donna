"""Shared Telegram message formatters for emails and todos.

Used by the direct-send path (claude_client display_* tools and recap), so the
bot can render without having Claude echo the content — this is the core of
the token-saving design.
"""

from __future__ import annotations

from datetime import datetime

import pytz

from config import settings

# Leave margin below Telegram's 4096 hard cap
TELEGRAM_MESSAGE_LIMIT = 4000

# Max non-whitespace chars to keep in an email body when displaying
EMAIL_BODY_VISIBLE_CHARS = 500


def _local_timezone():
    return pytz.timezone(settings.timezone)


def _format_datetime(iso: str, fmt: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone(_local_timezone()).strftime(fmt)
    except Exception:
        return iso


def _truncate_body(body: str, max_non_whitespace: int = EMAIL_BODY_VISIBLE_CHARS) -> str:
    """Keep at most `max_non_whitespace` visible chars, cut at word boundary."""
    if not body:
        return ""

    count = 0
    cut_at = len(body)
    for i, ch in enumerate(body):
        if not ch.isspace():
            count += 1
            if count > max_non_whitespace:
                cut_at = i
                break

    if cut_at >= len(body):
        return body

    return body[:cut_at].rstrip() + "\n\n...[tronqué]"


def format_full_email(mail: dict) -> str:
    """Render a full email as a plain-text Telegram message (truncated for display)."""
    sender_name = (mail.get("sender_name") or "").strip()
    sender_email = (mail.get("sender_email") or "").strip()
    if sender_name and sender_email:
        from_line = f"De : {sender_name} <{sender_email}>"
    else:
        from_line = f"De : {sender_name or sender_email or 'inconnu'}"

    subject = (mail.get("subject") or "(sans sujet)").strip()
    date_line = _format_datetime(mail.get("received_at") or "", "%d/%m/%Y %H:%M")

    body = _truncate_body((mail.get("body") or "").strip() or "(corps vide)")

    header = f"{from_line}\nDate : {date_line}\nSujet : {subject}\n\n"
    # Extra safety net against Telegram's hard cap
    budget = TELEGRAM_MESSAGE_LIMIT - len(header) - len("\n\n...[tronqué]")
    if len(body) > budget:
        body = body[:budget] + "\n\n...[tronqué]"
    return header + body


def format_emails_list(emails: list[dict], header: str | None = None) -> str:
    """Render a list of emails: 'JJ/MM HH:MM — Expéditeur' then subject line."""
    if not emails:
        return header or "Aucun mail."

    lines: list[str] = []
    if header:
        lines.append(header)
        lines.append("")

    entries: list[str] = []
    for mail in emails:
        when = _format_datetime(mail.get("received_at") or "", "%d/%m %H:%M")
        sender = (mail.get("sender_name") or mail.get("sender_email") or "?").strip()
        subject = (mail.get("subject") or "(sans sujet)").strip()
        if len(subject) > 80:
            subject = subject[:77] + "..."
        entries.append(f"{when} — {sender}\n{subject}")

    lines.append("\n\n".join(entries))
    return "\n".join(lines)


def format_todos_list(todos: list[dict], header: str | None = None) -> str:
    """Render todos as '• Titre — AAAA-MM-JJ' (deadline only if set)."""
    if not todos:
        return header_with_empty(header, "Aucune todo.")

    lines: list[str] = []
    if header:
        lines.append(header)

    for todo in todos:
        title = (todo.get("title") or "").strip() or "(sans titre)"
        deadline = todo.get("deadline")
        suffix = f" — {deadline}" if deadline else ""
        lines.append(f"• {title}{suffix}")

    return "\n".join(lines)


def header_with_empty(header: str | None, empty_message: str) -> str:
    if header:
        return f"{header}\n{empty_message}"
    return empty_message
