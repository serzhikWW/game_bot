"""
Plugin interface every game must implement.

A game plugin is a self-contained file in `bot/games/` that subclasses
`BaseGamePlugin`. The registry auto-discovers any concrete subclass and
makes it available to the bot. Adding a new game = creating one file here;
no changes to core bot logic are required.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class InputType(str, Enum):
    """How the user supplies data for analysis."""

    VIDEO = "video"
    MATCH_ID = "match_id"
    BOTH = "both"


@dataclass(frozen=True)
class GameConfig:
    """
    Static description of a game shown to the user and consumed by handlers.

    `id` must be stable — it's persisted in the analyses table and used as
    the callback-data key in inline keyboards.
    """

    id: str
    display_name: str
    emoji: str
    input_type: InputType
    has_characters: bool
    characters: list[str] = field(default_factory=list)
    max_video_mb: int = 200
    description: str = ""

    def __post_init__(self) -> None:
        if self.has_characters and not self.characters:
            raise ValueError(
                f"Game '{self.id}' declares has_characters=True but characters list is empty"
            )
        if not self.has_characters and self.characters:
            raise ValueError(
                f"Game '{self.id}' declares has_characters=False but characters list is non-empty"
            )
        if not self.id or not self.id.replace("_", "").isalnum():
            raise ValueError(
                f"Game id must be non-empty alphanumeric/underscore, got {self.id!r}"
            )


@dataclass
class AnalysisResult:
    """Output of a single analysis run; persisted to the analyses table."""

    game_id: str
    character: str | None
    raw_text: str
    tokens_used: int = 0
    processing_seconds: float = 0.0
    source: str = "gemini"  # "gemini" | "api" | "hybrid"


class BaseGamePlugin(ABC):
    """
    Abstract base class for all game plugins.

    Subclasses must:
      1. Expose a `config` property returning a `GameConfig`.
      2. Implement `analyze()` to run the actual coaching logic.
      3. Implement `get_prompt()` to return the Gemini prompt template.
    """

    @property
    @abstractmethod
    def config(self) -> GameConfig:
        """Return the static configuration describing this game."""

    @abstractmethod
    async def analyze(
        self,
        user_input: str | bytes,
        character: str | None,
        user_id: int,
        language_code: str = "en",
    ) -> AnalysisResult:
        """
        Run analysis and return the result.

        `user_input` is either:
          - a match-id string (for InputType.MATCH_ID plugins), or
          - raw video bytes (for InputType.VIDEO plugins).

        `character` is the user-selected hero/champion when
        `config.has_characters` is True, otherwise None.

        `user_id` is the Telegram user id, useful for logging/tracing.

        `language_code` controls the language of generated coaching text
        for plugins that support localization.
        """

    @abstractmethod
    def get_prompt(
        self,
        character: str | None,
        language_code: str = "en",
    ) -> str:
        """Return the Gemini prompt template for this game/character."""

    def validate_character(self, character: str | None) -> None:
        """Raise ValueError if the character is invalid for this game."""
        cfg = self.config
        if cfg.has_characters:
            if character is None:
                raise ValueError(f"{cfg.display_name} requires a character selection")
            if character not in cfg.characters:
                raise ValueError(
                    f"Unknown character {character!r} for {cfg.display_name}"
                )
        elif character is not None:
            raise ValueError(
                f"{cfg.display_name} does not support character selection"
            )

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} id={self.config.id!r}>"
