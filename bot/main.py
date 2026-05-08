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
    gemini = GeminiService(settings.gemini_api_key)
    registry = GameRegistry()
    registry.load_all()
    analyzer = Analyzer(db)
    usage_guard = UsageGuard(
        db, settings.free_analyses_per_day, settings.admin_telegram_id
    )

    application = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    application.bot_data.update(
        {"db": db, "gemini": gemini, "registry": registry,
         "analyzer": analyzer, "usage_guard": usage_guard}
    )

    # /start, /help, /games, /cancel, /limits
    cmds = start.make_handlers(registry, usage_guard)
    application.add_handler(CommandHandler("start", cmds["start"]))
    application.add_handler(CommandHandler("help", cmds["help"]))
    application.add_handler(CommandHandler("games", cmds["games"]))
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
