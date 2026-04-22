"""Scheduled recap generation (7h morning, 13h afternoon)."""

from datetime import datetime, timedelta

import pytz
import structlog

from bot.api_client import api_client
from bot.claude_client import process_message
from config import settings

logger = structlog.get_logger(__name__)


def _format_received_at(iso: str) -> str:
    """Format a stored ISO datetime as 'JJ/MM HH:MM' in the user's timezone."""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        tz = pytz.timezone(settings.timezone)
        local = dt.astimezone(tz)
        return local.strftime("%d/%m %H:%M")
    except Exception:
        return iso


def _format_email_section(emails: list[dict], extra_count: int) -> str | None:
    """Format the email section for recaps. Returns None if nothing to show."""
    if not emails and extra_count == 0:
        return None

    lines = ["📧 Mails non-lus :"]
    for mail in emails:
        sender = (mail.get("sender_name") or mail.get("sender_email") or "?").strip()
        subject = (mail.get("subject") or "(sans sujet)").strip()
        received = _format_received_at(mail.get("received_at", ""))
        # Trim subject to keep the line short
        if len(subject) > 70:
            subject = subject[:67] + "..."
        lines.append(f"• {sender} — {subject} ({received})")

    if extra_count > 0:
        lines.append(f"(+ {extra_count} autres mails non-lus des 2 derniers jours)")

    return "\n".join(lines)


async def _build_email_section() -> tuple[str | None, list[str]]:
    """Fetch the recap emails and render the section.

    Returns (text or None, list of email ids shown to mark as notified).
    """
    try:
        result = await api_client.call("/emails/recap", {})
    except Exception as e:
        logger.error("recap_email_fetch_failed", error=str(e))
        return None, []

    if not result.get("success"):
        return None, []

    data = result.get("data") or {}
    emails = data.get("emails") or []
    extra = data.get("extra_count", 0)

    text = _format_email_section(emails, extra)
    shown_ids = [e["id"] for e in emails if e.get("id")]
    return text, shown_ids


async def _mark_emails_notified(email_ids: list[str]) -> None:
    if not email_ids:
        return
    try:
        await api_client.call("/emails/mark_notified", {"email_ids": email_ids})
    except Exception as e:
        logger.error("recap_mark_notified_failed", error=str(e))


async def send_recap(bot, recap_type: str) -> None:
    """Generate and send a recap to all authorized chats.

    Args:
        bot: Telegram bot instance
        recap_type: "morning" or "afternoon"
    """
    tz = pytz.timezone(settings.timezone)
    now = datetime.now(tz)

    if recap_type == "morning":
        target_date = now.strftime("%Y-%m-%d")
        prompt = (
            f"Fais-moi un récap complet de ma journée du {target_date}. "
            "Liste mes événements du calendrier, mes todos en cours (surtout celles qui ont une deadline aujourd'hui), "
            "Formate simplement et compacte pour Telegram."
        )
    else:
        tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
        prompt = (
            f"Fais-moi une preview de ma journée de demain ({tomorrow}). "
            "Liste mes événements prévus, mes todos avec deadline demain, "
            "Formate simplement et compacte pour Telegram."
        )

    try:
        current_date = now.strftime("%Y-%m-%d %H:%M")
        response, _ = await process_message(prompt, current_date)

        email_section, shown_ids = await _build_email_section()
        if email_section:
            response = f"{response}\n\n{email_section}"

        delivered = False
        for chat_id in settings.allowed_chat_ids_list:
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=response,
                    parse_mode="Markdown",
                )
                delivered = True
                logger.info("recap_sent", chat_id=chat_id, type=recap_type)
            except Exception as e:
                logger.error("recap_send_failed", chat_id=chat_id, type=recap_type, error=str(e))

        if delivered and shown_ids:
            await _mark_emails_notified(shown_ids)

    except Exception as e:
        logger.error("recap_generation_failed", type=recap_type, error=str(e))
