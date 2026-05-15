"""
Video upload handler for video-based games.

Triggered by `MessageHandler(filters.VIDEO | filters.Document.VIDEO, ...)`.
Validates state, downloads the file from Telegram, calls the analyzer,
and streams the result back as one or more text messages.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from telegram import Update
from telegram.constants import ChatAction
from telegram.error import BadRequest, TimedOut
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


CONTAINER_DATA_ROOT = "/var/lib/telegram-bot-api"


async def _read_local_bot_api_file(
    file_path_or_url: str, host_root: Path
) -> bytes | None:
    """
    Map a Local Bot API file reference to a host path and read it.

    PTB v21 may give us either:
      * the raw container path  `/var/lib/telegram-bot-api/<token>/videos/x.mp4`
      * the full URL with the container path tacked on, e.g.
        `http://localhost:8081/file/bot<token>//var/lib/telegram-bot-api/<token>/videos/x.mp4`

    We just look for the `/var/lib/telegram-bot-api/` marker anywhere in the
    string and take everything after it. Returns None if not found or the
    translated host file doesn't exist (caller falls back to HTTP).
    """
    marker = CONTAINER_DATA_ROOT + "/"
    idx = file_path_or_url.find(marker)
    if idx < 0:
        return None
    rel = file_path_or_url[idx + len(marker):]
    host_path = host_root / rel
    if not host_path.is_file():
        logger.warning(
            "local_bot_api_file_missing host=%s ref=%s",
            host_path, file_path_or_url,
        )
        return None
    data = await asyncio.to_thread(host_path.read_bytes)
    # Best-effort cleanup so the data volume doesn't grow forever.
    try:
        await asyncio.to_thread(host_path.unlink)
    except OSError:
        pass
    return data


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
            tg_file = await media.get_file(read_timeout=300, write_timeout=300)
            logger.info(
                "tg_file_received user_id=%d file_path=%s local_dir=%s",
                user.id, tg_file.file_path,
                settings.telegram_api_local_data_dir,
            )
            # Local Bot API in --local mode writes the file straight to disk
            # and returns its CONTAINER path. Read it from the matching host
            # mount instead of fetching back over HTTP.
            video_bytes_opt: bytes | None = None
            if settings.telegram_api_local_data_dir and tg_file.file_path:
                video_bytes_opt = await _read_local_bot_api_file(
                    tg_file.file_path, settings.telegram_api_local_data_dir
                )
                if video_bytes_opt is not None:
                    logger.info(
                        "local_bot_api_file_read user_id=%d bytes=%d",
                        user.id, len(video_bytes_opt),
                    )
            if video_bytes_opt is None:
                logger.info("falling_back_to_http_download user_id=%d", user.id)
                video_bytes_opt = bytes(
                    await tg_file.download_as_bytearray(read_timeout=300)
                )
            video_bytes = video_bytes_opt
        except TimedOut:
            # In Local Bot API `--local` mode the server downloads the file
            # from MTProto before answering getFile. For larger clips this
            # can exceed even generous timeouts.
            logger.warning(
                "telegram_download_timeout user_id=%d size=%s",
                user.id, media.file_size,
            )
            await progress.edit_text(
                "Downloading your video took too long. "
                "Please try a shorter clip or retry in a moment."
            )
            return
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
