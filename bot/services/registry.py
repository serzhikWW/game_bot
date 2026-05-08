"""
GameRegistry — auto-discovers plugin classes in `bot/games/`.

To add a new game: drop a file `bot/games/<my_game>.py` containing a class
that extends `BaseGamePlugin`. The registry imports every non-underscore
module in that directory, scans for concrete `BaseGamePlugin` subclasses,
and registers them by `config.id`. No edits to core code required.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from pathlib import Path

from bot.games.base import BaseGamePlugin, GameConfig


logger = logging.getLogger(__name__)


GAMES_PACKAGE = "bot.games"


class GameRegistry:
    """In-memory registry of game plugins keyed by `GameConfig.id`."""

    def __init__(self) -> None:
        self._plugins: dict[str, BaseGamePlugin] = {}

    def load_all(self) -> None:
        """Import every module under `bot.games` and register plugin classes."""
        package = importlib.import_module(GAMES_PACKAGE)
        package_path = Path(package.__file__).parent  # type: ignore[arg-type]

        for mod_info in pkgutil.iter_modules([str(package_path)]):
            if mod_info.name.startswith("_") or mod_info.name == "base":
                continue
            module_name = f"{GAMES_PACKAGE}.{mod_info.name}"
            try:
                module = importlib.import_module(module_name)
            except Exception:
                logger.exception("plugin_import_failed module=%s", module_name)
                continue

            for _, obj in inspect.getmembers(module, inspect.isclass):
                if obj is BaseGamePlugin:
                    continue
                if not issubclass(obj, BaseGamePlugin):
                    continue
                if inspect.isabstract(obj):
                    continue
                # Only register classes defined in this module (skip re-exports)
                if obj.__module__ != module_name:
                    continue
                self._register(obj)

        logger.info(
            "registry_loaded count=%d ids=%s",
            len(self._plugins),
            sorted(self._plugins),
        )

    def _register(self, cls: type[BaseGamePlugin]) -> None:
        try:
            instance = cls()
        except Exception:
            logger.exception("plugin_instantiation_failed class=%s", cls.__name__)
            return

        cfg = instance.config
        if cfg.id in self._plugins:
            existing = type(self._plugins[cfg.id]).__name__
            logger.error(
                "plugin_id_conflict id=%s existing=%s new=%s — keeping existing",
                cfg.id,
                existing,
                cls.__name__,
            )
            return
        self._plugins[cfg.id] = instance
        logger.info(
            "plugin_registered id=%s class=%s input=%s",
            cfg.id,
            cls.__name__,
            cfg.input_type.value,
        )

    # --- query API ----------------------------------------------------

    def get(self, game_id: str) -> BaseGamePlugin | None:
        return self._plugins.get(game_id)

    def require(self, game_id: str) -> BaseGamePlugin:
        plugin = self._plugins.get(game_id)
        if plugin is None:
            raise KeyError(f"No plugin registered for game_id={game_id!r}")
        return plugin

    def all_games(self) -> list[GameConfig]:
        return [p.config for p in self._plugins.values()]

    def __len__(self) -> int:
        return len(self._plugins)

    def __contains__(self, game_id: object) -> bool:
        return isinstance(game_id, str) and game_id in self._plugins
