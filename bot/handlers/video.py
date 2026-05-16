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
from bot.core.i18n import get_user_language, t
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
    language_code: str = "en",
) -> None:
    """Send the analysis as one or more plain-text chunks within Telegram limits."""
    chunks = format_result(result)
    for chunk in chunks:
        await chat.send_message(chunk)
    footer_parts = [
        t(
            language_code,
            "footer",
            tokens=result.tokens_used,
            seconds=result.processing_seconds,
            source=result.source,
        )
    ]
    if usage_guard is not None and telegram_id is not None:
        status = await usage_guard.check(telegram_id, username, language_code)
        footer_parts.append(status.remaining_text(language_code))
    await chat.send_message("\n".join(footer_parts))


def make_unsupported_attachment_handler():
    """Reply 'video please' if the user sent a non-video while we wait on a clip."""
    async def on_unsupported(update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.message
        if message is None:
            return
        user_data = context.user_data if context.user_data is not None else {}
        lang = await get_user_language(context, update.effective_user)
        if state.get_state(user_data) != state.FlowState.AWAITING_VIDEO:
            return
        await message.reply_text(t(lang, "unsupported_attachment"))
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
        lang = await get_user_language(context, update.effective_user)

        if state.get_state(user_data) != state.FlowState.AWAITING_VIDEO:
            await message.reply_text(t(lang, "send_games_first"))
            return

        game_id = user_data.get(state.KEY_GAME_ID)
        character = user_data.get(state.KEY_CHARACTER)
        plugin = registry.get(game_id) if game_id else None
        if plugin is None:
            state.reset(user_data)
            await message.reply_text(t(lang, "unknown_current_game"))
            return

        # Pick the right file object — Telegram delivers some clips as Video,
        # others (especially desktop uploads) as Document with a video MIME.
        media = message.video or (
            message.document if (message.document and (message.document.mime_type or "").startswith("video/")) else None
        )
        if media is None:
            await message.reply_text(t(lang, "send_video"))
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
                    t(
                        lang,
                        "telegram_limit_hint",
                        limit_mb=settings.telegram_file_limit_mb,
                    )
                )
            await message.reply_text(
                t(
                    lang,
                    "clip_too_large",
                    actual_mb=actual_mb,
                    max_mb=effective_mb,
                    hint=hint,
                )
            )
            return

        # Limit check
        user = update.effective_user
        assert user is not None
        status = await usage_guard.check(user.id, user.username, lang)
        if status.is_exhausted:
            await message.reply_text(t(lang, "daily_limit", limit=status.limit))
            return

        await message.chat.send_action(ChatAction.TYPING)
        progress = await message.reply_text(t(lang, "analyzing_video"))

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
                t(lang, "download_timeout")
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
                    t(
                        lang,
                        "telegram_file_too_big",
                        limit_mb=settings.telegram_file_limit_mb,
                    )
                )
            else:
                logger.exception("telegram_download_failed user_id=%d", user.id)
                await progress.edit_text(t(lang, "download_failed"))
            return
        except Exception:
            logger.exception("telegram_download_failed user_id=%d", user.id)
            await progress.edit_text(t(lang, "download_failed"))
            return

        # Hand off to plugin via analyzer
        try:
            result = await analyzer.run(
                plugin,
                telegram_id=user.id,
                username=user.username,
                user_input=video_bytes,
                character=character,
                language_code=lang,
            )
        except GeminiTimeoutError:
            await progress.edit_text(t(lang, "analysis_timeout"))
            return
        except GeminiUploadFailedError:
            await progress.edit_text(t(lang, "video_processing_failed"))
            return
        except GeminiError as e:
            logger.exception("gemini_error user_id=%d", user.id)
            await progress.edit_text(t(lang, "analysis_failed", error=e))
            return
        except ValueError as e:
            await progress.edit_text(f"⚠️ {e}")
            return
        except Exception:
            logger.exception("video_analyze_failed user_id=%d game=%s", user.id, game_id)
            await progress.edit_text(t(lang, "generic_analysis_failed"))
            return

        state.reset(user_data)
        await progress.delete()
        await send_analysis_chunks(
            message.chat,
            result,
            usage_guard=usage_guard,
            telegram_id=user.id,
            username=user.username,
            language_code=lang,
        )

    return on_video
