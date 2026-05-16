"""Language dispatcher for Marvel Rivals prompt builders."""

from __future__ import annotations

from bot.core.i18n import normalize_language_code
from bot.games.marvel_rivals_prompts_en import build_prompt_en
from bot.games.marvel_rivals_prompts_ru import build_prompt_ru


def build_marvel_rivals_prompt(
    character: str,
    language_code: str = "en",
) -> str:
    """Build a localized Gemini prompt for a selected Marvel Rivals hero."""
    if normalize_language_code(language_code) == "ru":
        return build_prompt_ru(character)
    return build_prompt_en(character)
