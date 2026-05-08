"""
Global PTB error handler.

Catches any unhandled exception that escapes a handler, logs it with
user/chat/update context, and sends a generic apology to the user. We
deliberately do not echo the exception text to the user — it can leak
internal details (file paths, tokens) and is rarely actionable for them.
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.error import (
    BadRequest,
    Forbidden,
    NetworkError,
    TimedOut,
)
from telegram.ext import ContextTypes


logger = logging.getLogger(__name__)


GENERIC_USER_MSG = (
    "⚠️ Something went wrong. Please try again. "
    "If it keeps happening, send /start to reset."
)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err = context.error
    user_id: int | None = None
    chat_id: int | None = None
    if isinstance(update, Update):
        if update.effective_user is not None:
            user_id = update.effective_user.id
        if update.effective_chat is not None:
            chat_id = update.effective_chat.id

    err_type = type(err).__name__ if err else "Unknown"

    # Telegram-side flakiness — log and skip notifying the user. The
    # underlying request usually retries via PTB's update loop.
    if isinstance(err, (NetworkError, TimedOut)):
        logger.warning(
            "tg_transient_error type=%s user_id=%s chat_id=%s msg=%s",
            err_type, user_id, chat_id, str(err),
        )
        return

    # User blocked the bot or chat is gone — nothing useful to do.
    if isinstance(err, (Forbidden, BadRequest)):
        logger.info(
            "tg_client_error type=%s user_id=%s chat_id=%s msg=%s",
            err_type, user_id, chat_id, str(err),
        )
        return

    logger.exception(
        "unhandled_error type=%s user_id=%s chat_id=%s",
        err_type, user_id, chat_id,
        exc_info=err,
    )

    if isinstance(update, Update) and update.effective_message is not None:
        try:
            await update.effective_message.reply_text(GENERIC_USER_MSG)
        except Exception:
            logger.warning("error_reply_failed user_id=%s", user_id)
