"""Scheduled recap generation (7h morning, 13h afternoon)."""

from datetime import datetime, timedelta

import pytz
import structlog

from bot.api_client import api_client
from bot.claude_client import process_message
from config import settings

logger = structlog.get_logger(__name__)


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
            "et rappelle-moi mes règles actives si pertinent. "
            "Formate joliment pour Telegram."
        )
    else:
        tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
        prompt = (
            f"Fais-moi une preview de ma journée de demain ({tomorrow}). "
            "Liste mes événements prévus, mes todos avec deadline demain, "
            "et rappelle-moi s'il y a des règles pertinentes. "
            "Formate joliment pour Telegram."
        )

    try:
        current_date = now.strftime("%Y-%m-%d %H:%M")
        response, _ = await process_message(prompt, current_date)

        for chat_id in settings.allowed_chat_ids_list:
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=response,
                    parse_mode="Markdown",
                )
                logger.info("recap_sent", chat_id=chat_id, type=recap_type)
            except Exception as e:
                logger.error("recap_send_failed", chat_id=chat_id, type=recap_type, error=str(e))

    except Exception as e:
        logger.error("recap_generation_failed", type=recap_type, error=str(e))
