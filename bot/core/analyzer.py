"""
Orchestrator that ties a plugin's `analyze()` call to persistence.

Handlers call `Analyzer.run(...)` and get back a finished `AnalysisResult`.
The analyzer:
  1. Looks up the user (creating if needed) and resets the daily counter
     if `last_analysis_date` is stale.
  2. Calls the plugin.
  3. Persists the result to the analyses table.
  4. Increments the user's usage counters.

Daily-limit *enforcement* lives in `bot.core.usage` and is called by
handlers before they delegate here. Keeping enforcement out of the
analyzer means a single source of truth for the message users see.
"""

from __future__ import annotations

import logging
from datetime import date

from bot.db.database import Database
from bot.games.base import AnalysisResult, BaseGamePlugin


logger = logging.getLogger(__name__)


class Analyzer:
    def __init__(self, db: Database):
        self._db = db

    async def run(
        self,
        plugin: BaseGamePlugin,
        *,
        telegram_id: int,
        username: str | None,
        user_input: str | bytes,
        character: str | None,
        language_code: str = "en",
    ) -> AnalysisResult:
        cfg = plugin.config
        user = await self._db.get_or_create_user(
            telegram_id, username, language_code
        )

        try:
            result = await plugin.analyze(
                user_input, character, telegram_id, language_code
            )
        except Exception as e:
            logger.warning(
                "analysis_failed user_id=%d game=%s character=%s "
                "input_type=%s error_type=%s msg=%s",
                telegram_id, cfg.id, character,
                cfg.input_type.value, type(e).__name__, str(e),
            )
            raise

        await self._db.save_analysis(
            user_id=user.id,
            game_id=result.game_id,
            character=result.character,
            input_type=cfg.input_type.value,
            result=result.raw_text,
            tokens_used=result.tokens_used,
            processing_seconds=result.processing_seconds,
        )
        await self._db.increment_usage(telegram_id, date.today())

        logger.info(
            "analysis_saved user_id=%d game=%s character=%s "
            "input_type=%s tokens=%d seconds=%.2f",
            telegram_id, result.game_id, result.character,
            cfg.input_type.value, result.tokens_used, result.processing_seconds,
        )
        return result
