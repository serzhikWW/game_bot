"""
Entry point — wires config, services, registry, and handlers, then runs polling.

Run with:
    python -m bot.main
"""

from __future__ import annotations

import asyncio
import logging

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from bot.config import configure_logging, get_settings
from bot.core.analyzer import Analyzer
from bot.core.usage import UsageGuard
from bot.db.database import Database
from bot.handlers import error as error_handler
from bot.handlers import game_select, match_id as match_id_handler, start, video
from bot.services import container
from bot.services.gemini import GeminiService
from bot.services.registry import GameRegistry


logger = logging.getLogger(__name__)


async def _post_init(application: Application) -> None:
    """Connect resources after the event loop is running."""
    db: Database = application.bot_data["db"]
    await db.connect()
    application.bot_data["gemini"].configure()
    container.set_database(db)
    container.set_gemini(application.bot_data["gemini"])
    logger.info("startup_complete games=%d", len(application.bot_data["registry"]))


async def _post_shutdown(application: Application) -> None:
    db: Database | None = application.bot_data.get("db")
    if db is not None:
        await db.close()


def build_application() -> Application:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_file)

    db = Database(settings.db_path)
    gemini = GeminiService(settings.gemini_api_key, model=settings.gemini_model)
    registry = GameRegistry()
    registry.load_all()
    analyzer = Analyzer(db)
    usage_guard = UsageGuard(
        db, settings.free_analyses_per_day, settings.admin_telegram_id
    )

    builder = (
        Application.builder()
        .token(settings.telegram_bot_token)
        # In `--local` mode, the Bot API server downloads the file from
        # MTProto BEFORE answering getFile, so 5s default is way too short
        # for multi-MB clips. Be generous; the bot itself is async anyway.
        .connect_timeout(15.0)
        .read_timeout(300.0)
        .write_timeout(300.0)
        .pool_timeout(15.0)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
    )
    # Point PTB at a self-hosted Local Bot API server when configured.
    # Both base URLs must be set together — they point at /bot and /file
    # routes respectively (see PTB docs on `Application.builder().base_url`).
    if settings.telegram_api_base_url and settings.telegram_api_file_url:
        builder = (
            builder
            .base_url(settings.telegram_api_base_url)
            .base_file_url(settings.telegram_api_file_url)
            .local_mode(True)
        )
        logger.info(
            "telegram_local_api_enabled base=%s",
            settings.telegram_api_base_url,
        )
    application = builder.build()
    application.bot_data.update(
        {"db": db, "gemini": gemini, "registry": registry,
         "analyzer": analyzer, "usage_guard": usage_guard}
    )

    # /start, /help, /games, /language, /cancel, /limits
    cmds = start.make_handlers(registry, usage_guard)
    application.add_handler(CommandHandler("start", cmds["start"]))
    application.add_handler(CommandHandler("help", cmds["help"]))
    application.add_handler(CommandHandler("games", cmds["games"]))
    application.add_handler(CommandHandler("language", cmds["language"]))
    application.add_handler(CommandHandler("lang", cmds["language"]))
    application.add_handler(CommandHandler("cancel", cmds["cancel"]))
    application.add_handler(CommandHandler("limits", cmds["limits"]))

    # Inline keyboard callbacks (game / character / slot picks)
    application.add_handler(
        CallbackQueryHandler(game_select.make_callback_handler(registry, analyzer, usage_guard))
    )

    # Video uploads (both Video and Document-with-video-MIME)
    application.add_handler(
        MessageHandler(
            filters.VIDEO | filters.Document.VIDEO,
            video.make_video_handler(settings, registry, analyzer, usage_guard),
        )
    )

    # Non-video attachments while flow is AWAITING_VIDEO — gentle nudge.
    application.add_handler(
        MessageHandler(
            filters.ATTACHMENT & ~(filters.VIDEO | filters.Document.VIDEO),
            video.make_unsupported_attachment_handler(),
        )
    )

    # Plain text → match-ID flow (also responds to stray text in other states)
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            match_id_handler.make_text_handler(registry),
        )
    )

    # Global error handler — last line of defence
    application.add_error_handler(error_handler.on_error)

    return application


def main() -> None:
    application = build_application()
    application.run_polling(allowed_updates=None)


if __name__ == "__main__":
    main()
