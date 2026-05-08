"""
Video upload handler for video-based games.

Triggered by `MessageHandler(filters.VIDEO | filters.Document.VIDEO, ...)`.
Validates state, downloads the file from Telegram, calls the analyzer,
and streams the result back as one or more text messages.
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ChatAction
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from bot.config import Settings
from bot.core.analyzer import Analyzer
from bot.core.formatter import format_result
from bot.core.usage import UsageGuard
from bot.games.base import AnalysisResult
from bot.handlers import state
from bot.services.gemini import (
    GeminiError,
    GeminiTimeoutError,
    GeminiUploadFailedError,
)
from bot.services.registry import GameRegistry


logger = logging.getLogger(__name__)


async def send_analysis_chunks(
    chat,
    result: AnalysisResult,
    usage_guard: UsageGuard | None = None,
    telegram_id: int | None = None,
    username: str | None = None,
) -> None:
    """Send the analysis as one or more plain-text chunks within Telegram limits."""
    chunks = format_result(result)
    for chunk in chunks:
        await chat.send_message(chunk)
    footer_parts = [
        f"— tokens: {result.tokens_used} · "
        f"{result.processing_seconds:.1f}s · source: {result.source}"
    ]
    if usage_guard is not None and telegram_id is not None:
        status = await usage_guard.check(telegram_id, username)
        footer_parts.append(status.remaining_text())
    await chat.send_message("\n".join(footer_parts))


def make_unsupported_attachment_handler():
    """Reply 'video please' if the user sent a non-video while we wait on a clip."""
    async def on_unsupported(update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.message
        if message is None:
            return
        user_data = context.user_data if context.user_data is not None else {}
        if state.get_state(user_data) != state.FlowState.AWAITING_VIDEO:
            return
        await message.reply_text(
            "Please send a video file (MP4). Photos, audio and other files "
            "aren't supported for analysis."
        )
    return on_unsupported


def make_video_handler(
    settings: Settings,
    registry: GameRegistry,
    analyzer: Analyzer,
    usage_guard: UsageGuard,
):
    async def on_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.message
        if message is None:
            return
        user_data = context.user_data if context.user_data is not None else {}

        if state.get_state(user_data) != state.FlowState.AWAITING_VIDEO:
            await message.reply_text(
                "Send /games first, pick a game and a hero, then upload the clip."
            )
            return

        game_id = user_data.get(state.KEY_GAME_ID)
        character = user_data.get(state.KEY_CHARACTER)
        plugin = registry.get(game_id) if game_id else None
        if plugin is None:
            state.reset(user_data)
            await message.reply_text("Unknown game in current flow. Send /games.")
            return

        # Pick the right file object — Telegram delivers some clips as Video,
        # others (especially desktop uploads) as Document with a video MIME.
        media = message.video or (
            message.document if (message.document and (message.document.mime_type or "").startswith("video/")) else None
        )
        if media is None:
            await message.reply_text("Please send a video file (MP4).")
            return

        effective_mb = settings.effective_video_mb(plugin.config.max_video_mb)
        max_bytes = effective_mb * 1024 * 1024
        if media.file_size and media.file_size > max_bytes:
            actual_mb = media.file_size // (1024 * 1024)
            hint = ""
            if effective_mb < plugin.config.max_video_mb:
                # The bot would in principle accept up to plugin.max, but
                # Telegram's standard Bot API caps downloads at 20 MB.
                hint = (
                    "\n\nTelegram's Bot API limits file downloads to "
                    f"{settings.telegram_file_limit_mb} MB. To process larger "
                    "clips, run a Local Bot API server (see README)."
                )
            await message.reply_text(
                f"Your clip is {actual_mb} MB — too large. "
                f"Please send a shorter clip (max {effective_mb} MB).{hint}"
            )
            return

        # Limit check
        user = update.effective_user
        assert user is not None
        status = await usage_guard.check(user.id, user.username)
        if status.is_exhausted:
            await message.reply_text(
                f"⛔️ Daily limit reached ({status.limit}/day). Try again tomorrow."
            )
            return

        await message.chat.send_action(ChatAction.TYPING)
        progress = await message.reply_text(
            "⏳ Analyzing... ~30-60 seconds. Please wait."
        )

        try:
            tg_file = await media.get_file()
            video_bytes = bytes(await tg_file.download_as_bytearray())
        except BadRequest as e:
            # Most common cause: file is larger than Telegram's getFile cap
            # (20 MB on the standard Bot API). We pre-check size, but the
            # cap can also bite when `file_size` is missing/inaccurate.
            msg = str(e).lower()
            if "too big" in msg or "file is too big" in msg:
                logger.warning(
                    "telegram_file_too_big user_id=%d size=%s limit_mb=%d",
                    user.id, media.file_size, settings.telegram_file_limit_mb,
                )
                await progress.edit_text(
                    f"This file is too big for Telegram's Bot API to deliver "
                    f"(limit ~{settings.telegram_file_limit_mb} MB). "
                    "Please send a shorter clip."
                )
            else:
                logger.exception("telegram_download_failed user_id=%d", user.id)
                await progress.edit_text(
                    "Couldn't download your video from Telegram. Please try again."
                )
            return
        except Exception:
            logger.exception("telegram_download_failed user_id=%d", user.id)
            await progress.edit_text(
                "Couldn't download your video from Telegram. Please try again."
            )
            return

        # Hand off to plugin via analyzer
        try:
            result = await analyzer.run(
                plugin,
                telegram_id=user.id,
                username=user.username,
                user_input=video_bytes,
                character=character,
            )
        except GeminiTimeoutError:
            await progress.edit_text(
                "Analysis taking too long, please retry with a shorter clip."
            )
            return
        except GeminiUploadFailedError:
            await progress.edit_text(
                "Couldn't process the video. Try a different file or shorter clip."
            )
            return
        except GeminiError as e:
            logger.exception("gemini_error user_id=%d", user.id)
            await progress.edit_text(f"Analysis failed: {e}")
            return
        except ValueError as e:
            await progress.edit_text(f"⚠️ {e}")
            return
        except Exception:
            logger.exception("video_analyze_failed user_id=%d game=%s", user.id, game_id)
            await progress.edit_text(
                "Something went wrong while analyzing. Please try again."
            )
            return

        state.reset(user_data)
        await progress.delete()
        await send_analysis_chunks(
            message.chat,
            result,
            usage_guard=usage_guard,
            telegram_id=user.id,
            username=user.username,
        )

    return on_video
