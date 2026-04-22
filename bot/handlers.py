"""Telegram message handlers for text, voice, and inline button callbacks."""

import os
import tempfile
from datetime import datetime

import pytz
import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.api_client import api_client
from bot.claude_client import process_message, process_voice_message
from bot.security import is_authorized
from config import settings

logger = structlog.get_logger(__name__)


def _get_current_date() -> str:
    """Get current date in user's timezone."""
    tz = pytz.timezone(settings.timezone)
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M")


def _build_pending_keyboard(pending_id: str) -> InlineKeyboardMarkup:
    """Build inline keyboard with Confirm/Cancel buttons for a pending action."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Confirmer", callback_data=f"confirm:{pending_id}"),
            InlineKeyboardButton("Annuler", callback_data=f"cancel:{pending_id}"),
        ]
    ])


async def _send_response(
    update: Update,
    text: str,
    pending_actions: list[dict],
    display_messages: list[str] | None = None,
) -> None:
    """Send the text reply, then any pre-rendered display messages (no Markdown),
    then inline-button prompts for pending actions."""
    if text:
        await update.message.reply_text(text, parse_mode="Markdown")

    for msg in display_messages or []:
        try:
            await update.message.reply_text(msg)
        except Exception as e:
            logger.error("send_display_message_failed", error=str(e))

    for pending in pending_actions:
        keyboard = _build_pending_keyboard(pending["id"])
        await update.message.reply_text(
            f"Action en attente : {pending['description']}",
            reply_markup=keyboard,
        )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming text messages."""
    if not is_authorized(update):
        return

    user_message = update.message.text
    chat_id = update.effective_chat.id

    logger.info("text_message_received", chat_id=chat_id, length=len(user_message))

    await update.message.chat.send_action("typing")

    try:
        response_text, pending_actions, display_messages = await process_message(user_message, _get_current_date())
        await _send_response(update, response_text, pending_actions, display_messages)
    except Exception as e:
        logger.error("text_handler_error", chat_id=chat_id, error=str(e))
        await update.message.reply_text(
            "Désolée, une erreur est survenue. Réessaie dans un instant."
        )


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming voice messages."""
    if not is_authorized(update):
        return

    chat_id = update.effective_chat.id
    logger.info("voice_message_received", chat_id=chat_id)

    await update.message.chat.send_action("typing")

    tmp_path = None
    try:
        voice = update.message.voice
        file = await context.bot.get_file(voice.file_id)

        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp_path = tmp.name
            await file.download_to_drive(tmp_path)

        with open(tmp_path, "rb") as f:
            audio_data = f.read()

        logger.info("voice_downloaded", chat_id=chat_id, size_bytes=len(audio_data))

        response_text, pending_actions, display_messages = await process_voice_message(audio_data, _get_current_date())
        await _send_response(update, response_text, pending_actions, display_messages)

    except Exception as e:
        logger.error("voice_handler_error", chat_id=chat_id, error=str(e))
        await update.message.reply_text(
            "Désolée, je n'ai pas pu traiter ton message vocal. Réessaie."
        )
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
            logger.info("voice_temp_cleaned", path=tmp_path)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline button clicks (confirm/cancel pending actions)."""
    query = update.callback_query
    await query.answer()

    if not update.effective_chat or update.effective_chat.id not in settings.allowed_chat_ids_list:
        logger.warning("unauthorized_callback", chat_id=getattr(update.effective_chat, "id", None))
        return

    data = query.data
    if ":" not in data:
        return

    choice, pending_id = data.split(":", 1)

    if choice not in ("confirm", "cancel"):
        return

    logger.info("pending_action_callback", pending_id=pending_id, choice=choice)

    try:
        result = await api_client.call("/pending/resolve", {
            "pending_id": pending_id,
            "choice": choice,
        })

        if result.get("success"):
            if choice == "confirm":
                # Execute the actual action from the payload
                action_data = result.get("data", {})
                action_payload = action_data.get("action_payload")

                if action_payload:
                    action_type = action_payload.get("action")
                    exec_result = await _execute_pending_action(action_payload)
                    if exec_result:
                        await query.edit_message_text(f"Fait. {exec_result}")
                    else:
                        await query.edit_message_text("Action confirmée et exécutée.")
                else:
                    await query.edit_message_text("Action confirmée.")
            else:
                await query.edit_message_text("Action annulée.")
        else:
            error = result.get("error", "Erreur inconnue")
            await query.edit_message_text(f"Erreur : {error}")

    except Exception as e:
        logger.error("callback_error", pending_id=pending_id, error=str(e))
        await query.edit_message_text("Erreur lors du traitement.")


async def _execute_pending_action(payload: dict) -> str | None:
    """Execute the action stored in a pending action's payload.

    Handles multiple payload formats since Claude may structure them differently:
    - {"action": "delete_event", "event_id": "..."}
    - {"function": "delete_event", "params": {"event_id": "..."}}
    """
    # Normalize: support both "action" and "function" keys, and flat/nested params
    action = payload.get("action") or payload.get("function")
    params = payload.get("params") or {}

    def get(key):
        value = payload.get(key)
        return value if value is not None else params.get(key)

    try:
        if action == "delete_event":
            event_id = get("event_id")
            if event_id:
                await api_client.call("/calendar/delete_event", {"event_id": event_id})
                return "Événement supprimé."

        elif action == "delete_todo":
            todo_id = get("todo_id")
            if todo_id:
                await api_client.call("/todos/delete", {"todo_id": todo_id})
                return await _todo_message("Todo supprimée.")

        elif action == "delete_rule":
            rule_id = get("rule_id")
            if rule_id:
                await api_client.call("/rules/delete", {"rule_id": rule_id})
                return "Règle supprimée."

        elif action == "create_event":
            event_body = {
                "title": get("title"),
                "start": get("start"),
                "end": get("end"),
                "description": get("description"),
                "attendees": get("attendees"),
                "force": True,
            }
            event_body = {k: v for k, v in event_body.items() if v is not None}
            result = await api_client.call("/calendar/create_event", event_body)
            if result.get("success"):
                return "Événement créé."
            return f"Impossible de créer l'événement : {result.get('error', 'erreur inconnue')}"

    except Exception as e:
        logger.error("execute_pending_failed", action=action, error=str(e))
        return f"Erreur lors de l'exécution : action {action}"

    return None


async def _todo_message(prefix: str) -> str:
    """Return prefix followed by the current pending todos list."""
    todos_block = await _format_pending_todos()
    if todos_block:
        return f"{prefix}\n\n{todos_block}"
    return prefix


async def _format_pending_todos() -> str | None:
    """Fetch pending todos and format them as a plain bullet list."""
    try:
        result = await api_client.call("/todos/list", {"filter": "pending"})
        if not result.get("success"):
            return None
        todos = result.get("data", {}).get("todos", [])
        if not todos:
            return "Aucune todo en cours."
        lines = ["Todos en cours :"]
        for t in todos:
            title = t.get("title", "")
            deadline = t.get("deadline")
            suffix = f" — {deadline}" if deadline else ""
            lines.append(f"• {title}{suffix}")
        return "\n".join(lines)
    except Exception as e:
        logger.error("format_todos_failed", error=str(e))
        return None
