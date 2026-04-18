"""Telegram chat ID whitelist security."""

import structlog
from telegram import Update

from config import settings

logger = structlog.get_logger(__name__)


def is_authorized(update: Update) -> bool:
    """Check if the incoming message is from an authorized chat ID.

    Unauthorized messages are silently rejected with a log entry.
    """
    if update.effective_chat is None:
        logger.warning("message_no_chat", update_id=update.update_id)
        return False

    chat_id = update.effective_chat.id

    if chat_id not in settings.allowed_chat_ids_list:
        logger.warning(
            "unauthorized_access_attempt",
            chat_id=chat_id,
            username=getattr(update.effective_user, "username", None),
        )
        return False

    return True
