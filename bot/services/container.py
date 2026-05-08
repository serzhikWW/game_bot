"""
Tiny service container for sharing singletons between layers.

Plugins are instantiated by the registry with no constructor args, so they
can't receive dependencies through __init__. Instead, the bot's entrypoint
populates this container at startup, and plugins / handlers import the
accessor functions to reach the shared instances.

Usage:
    from bot.services import container
    container.set_gemini(GeminiService(...))
    ...
    gemini = container.get_gemini()
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from bot.db.database import Database
    from bot.services.gemini import GeminiService


_gemini: "GeminiService | None" = None
_db: "Database | None" = None


def set_gemini(service: "GeminiService") -> None:
    global _gemini
    _gemini = service


def get_gemini() -> "GeminiService":
    if _gemini is None:
        raise RuntimeError(
            "GeminiService not initialised — call container.set_gemini() at startup"
        )
    return _gemini


def set_database(db: "Database") -> None:
    global _db
    _db = db


def get_database() -> "Database":
    if _db is None:
        raise RuntimeError(
            "Database not initialised — call container.set_database() at startup"
        )
    return _db


def reset() -> None:
    """For tests only."""
    global _gemini, _db
    _gemini = None
    _db = None
