"""Telegram bot entry point with scheduler."""

import pytz
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, MessageHandler, filters

from api.logging_config import setup_logging
from bot.handlers import handle_callback, handle_text, handle_voice
from bot.recap import send_recap
from config import settings

setup_logging(settings.environment)
logger = structlog.get_logger(__name__)


async def post_init(application) -> None:
    """Called after the application is initialized and the event loop is running."""
    tz = pytz.timezone(settings.timezone)
    scheduler = AsyncIOScheduler(timezone=tz)

    async def morning_recap() -> None:
        await send_recap(application.bot, "morning")

    async def afternoon_recap() -> None:
        await send_recap(application.bot, "afternoon")

    scheduler.add_job(
        morning_recap,
        "cron",
        hour=settings.recap_morning_hour,
        minute=0,
        id="morning_recap",
    )
    scheduler.add_job(
        afternoon_recap,
        "cron",
        hour=settings.recap_afternoon_hour,
        minute=0,
        id="afternoon_recap",
    )

    scheduler.start()
    logger.info(
        "scheduler_started",
        morning_hour=settings.recap_morning_hour,
        afternoon_hour=settings.recap_afternoon_hour,
    )


def main() -> None:
    """Start the Telegram bot with scheduled recaps."""

    logger.info(
        "bot_starting",
        environment=settings.environment,
        timezone=settings.timezone,
        allowed_chats=settings.allowed_chat_ids_list,
    )

    # Build the Telegram application
    app = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .post_init(post_init)
        .build()
    )

    # Register handlers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(CallbackQueryHandler(handle_callback))

    # Start polling
    logger.info("bot_polling_started")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
