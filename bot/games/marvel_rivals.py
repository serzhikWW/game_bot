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
from bot.services import container


logger = logging.getLogger(__name__)


HEROES: list[str] = [
    # Vanguards (12)
    "Angela",
    "Captain America",
    "Doctor Strange",
    "Emma Frost",
    "Groot",
    "Hulk",
    "Magneto",
    "Peni Parker",
    "Rogue",
    "The Thing",
    "Thor",
    "Venom",
    # Duelists (25)
    "Black Cat",
    "Black Panther",
    "Black Widow",
    "Blade",
    "Daredevil",
    "Elsa Bloodstone",
    "Hawkeye",
    "Hela",
    "Human Torch",
    "Iron Fist",
    "Iron Man",
    "Magik",
    "Mr. Fantastic",
    "Moon Knight",
    "Namor",
    "Phoenix",
    "Psylocke",
    "Scarlet Witch",
    "Spider-Man",
    "Squirrel Girl",
    "Star-Lord",
    "Storm",
    "The Punisher",
    "Winter Soldier",
    "Wolverine",
    # Strategists (11)
    "Adam Warlock",
    "Cloak & Dagger",
    "Gambit",
    "Invisible Woman",
    "Jeff the Land Shark",
    "Loki",
    "Luna Snow",
    "Mantis",
    "Rocket Raccoon",
    "Ultron",
    "White Fox",
    # Multi-Role (1)
    "Deadpool",
]


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

    def get_prompt(self, character: str | None) -> str:
        if character is None:
            raise ValueError("Marvel Rivals requires a character selection")

        return (
            f"You are a professional Marvel Rivals coach.\n"
            f"The player is playing as {character}.\n\n"
            "Analyze the video and respond in this EXACT format:\n\n"
            f"🎯 HERO: {character}\n"
            "⏱ CLIP DURATION: [X min Y sec]\n\n"
            "❌ TOP 3 MISTAKES:\n"
            "1. [MM:SS] — [What happened] → [What to do instead]\n"
            "2. [MM:SS] — [What happened] → [What to do instead]\n"
            "3. [MM:SS] — [What happened] → [What to do instead]\n\n"
            "✅ WHAT YOU DID WELL:\n"
            "1. [MM:SS] — [Specific moment]\n"
            "2. [MM:SS] — [Specific moment]\n\n"
            "💡 MAIN RECOMMENDATION:\n"
            "[One concrete tip — 2-3 sentences]\n\n"
            "📊 DECISION QUALITY: [X/10]\n\n"
            "Rules: always use MM:SS timestamps from the clip; "
            "name abilities specifically (e.g. ultimate names, dash, shield); "
            "use numbers where possible (HP, distance, cooldowns); "
            "avoid vague phrases like \"play better\" or \"position well\"."
        )

    async def analyze(
        self,
        user_input: str | bytes,
        character: str | None,
        user_id: int,
    ) -> AnalysisResult:
        if not isinstance(user_input, (bytes, bytearray)):
            raise TypeError(
                f"Marvel Rivals plugin expects video bytes, got {type(user_input).__name__}"
            )
        self.validate_character(character)
        assert character is not None  # validate_character ensures this

        prompt = self.get_prompt(character)
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
