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


def _local_timezone():
    return pytz.timezone(settings.timezone)


def _format_datetime(iso: str, fmt: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone(_local_timezone()).strftime(fmt)
    except Exception:
        return iso


def format_full_email(mail: dict) -> str:
    """Render a full email as a plain-text Telegram message.

    Only constraint is Telegram's 4096-char hard cap; if a body exceeds it,
    the excess is cut with a '[tronqué]' marker (rare for normal mail).
    """
    sender_name = (mail.get("sender_name") or "").strip()
    sender_email = (mail.get("sender_email") or "").strip()
    if sender_name and sender_email:
        from_line = f"De : {sender_name} <{sender_email}>"
    else:
        from_line = f"De : {sender_name or sender_email or 'inconnu'}"

    subject = (mail.get("subject") or "(sans sujet)").strip()
    date_line = _format_datetime(mail.get("received_at") or "", "%d/%m/%Y %H:%M")

    body = (mail.get("body") or "").strip() or "(corps vide)"

    header = f"{from_line}\nDate : {date_line}\nSujet : {subject}\n\n"
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


def format_events_list(events: list[dict], header: str | None = None) -> str:
    """Render a list of calendar events for direct Telegram delivery.

    Used by the recap so the agenda doesn't need to round-trip through Claude.
    Format: 'EMOJI HHhMM-HHhMM — Titre' per line, in chronological order.
    Emoji follows the SYSTEM_PROMPT convention: 📚 for Zimbra (school), 🗓️ for
    Google (perso). The `events` list is expected sorted by start time, which
    is what the API returns.
    """
    if not events:
        return header_with_empty(header, "Rien.")

    lines: list[str] = []
    if header:
        lines.append(header)
        lines.append("")

    for ev in events:
        emoji = "📚" if ev.get("source") == "zimbra" else "🗓️"
        start = ev.get("start") or ""
        end = ev.get("end") or ""
        when = _format_event_range(start, end)
        title = (ev.get("title") or "(sans titre)").strip() or "(sans titre)"
        if len(title) > 80:
            title = title[:77] + "..."
        lines.append(f"{emoji} {when} — {title}")

    return "\n".join(lines)


def _format_event_range(start_iso: str, end_iso: str) -> str:
    """'HHhMM-HHhMM' if same day, else 'JJ/MM HHhMM-JJ/MM HHhMM'."""
    try:
        s = datetime.fromisoformat(start_iso.replace("Z", "+00:00")).astimezone(_local_timezone())
        e = datetime.fromisoformat(end_iso.replace("Z", "+00:00")).astimezone(_local_timezone())
    except Exception:
        return f"{start_iso} — {end_iso}"
    if s.date() == e.date():
        return f"{s.strftime('%Hh%M')}-{e.strftime('%Hh%M')}"
    return f"{s.strftime('%d/%m %Hh%M')}-{e.strftime('%d/%m %Hh%M')}"


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
