"""Telegram bot entry point with scheduler."""

import pytz
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, MessageHandler, filters

from api.logging_config import setup_logging
from bot.api_client import api_client
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

    async def sync_emails_job() -> None:
        try:
            await api_client.call("/emails/sync", {})
        except Exception as e:
            logger.error("scheduled_email_sync_failed", error=str(e))

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
    # Email sync 3x/day — runs slightly before recaps so recap sees fresh data.
    for hour, job_id in ((7, "emails_sync_morning"), (12, "emails_sync_noon"), (17, "emails_sync_evening")):
        scheduler.add_job(
            sync_emails_job,
            "cron",
            hour=hour,
            minute=0,
            id=job_id,
        )

    scheduler.start()
    logger.info(
        "scheduler_started",
        morning_hour=settings.recap_morning_hour,
        afternoon_hour=settings.recap_afternoon_hour,
        email_sync_hours=[7, 12, 17],
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
