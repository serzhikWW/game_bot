"""
Marvel Rivals plugin — video-based gameplay analysis.

User uploads an MP4 clip and selects a hero. The plugin builds a hero-specific
coaching prompt and runs the video + prompt through the shared GeminiService.
"""

from __future__ import annotations

import logging

from bot.games.base import (
    AnalysisResult,
    BaseGamePlugin,
    GameConfig,
    InputType,
)
from bot.games.marvel_rivals_hero_docs import HEROES
from bot.games.marvel_rivals_prompts import build_marvel_rivals_prompt
from bot.services import container


logger = logging.getLogger(__name__)


class MarvelRivalsPlugin(BaseGamePlugin):
    """Video clip → Gemini coaching analysis for a single hero."""

    @property
    def config(self) -> GameConfig:
        return GameConfig(
            id="marvel_rivals",
            display_name="Marvel Rivals",
            emoji="🦸",
            input_type=InputType.VIDEO,
            has_characters=True,
            characters=HEROES,
            max_video_mb=200,
            description="Upload a gameplay clip (MP4, max 200MB).",
        )

    def get_prompt(
        self,
        character: str | None,
        language_code: str = "en",
    ) -> str:
        if character is None:
            raise ValueError("Marvel Rivals requires a character selection")
        return build_marvel_rivals_prompt(character, language_code)

    async def analyze(
        self,
        user_input: str | bytes,
        character: str | None,
        user_id: int,
        language_code: str = "en",
    ) -> AnalysisResult:
        if not isinstance(user_input, (bytes, bytearray)):
            raise TypeError(
                f"Marvel Rivals plugin expects video bytes, got {type(user_input).__name__}"
            )
        self.validate_character(character)
        assert character is not None  # validate_character ensures this

        prompt = self.get_prompt(character, language_code)
        gemini = container.get_gemini()

        logger.info(
            "marvel_rivals_analyze_start user_id=%d hero=%s size=%d",
            user_id,
            character,
            len(user_input),
        )
        out = await gemini.analyze_video(bytes(user_input), prompt)
        logger.info(
            "marvel_rivals_analyze_done user_id=%d hero=%s tokens=%d seconds=%.2f",
            user_id,
            character,
            out.tokens_used,
            out.processing_seconds,
        )

        return AnalysisResult(
            game_id=self.config.id,
            character=character,
            raw_text=out.raw_text,
            tokens_used=out.tokens_used,
            processing_seconds=out.processing_seconds,
            source="gemini",
        )
