"""
Application configuration loaded from environment variables.

Reads .env (if present) and exposes a single immutable Settings instance
that the rest of the bot imports via `from bot.config import settings`.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

load_dotenv(PROJECT_ROOT / ".env")


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Required env var '{name}' is missing or empty")
    return value


def _optional_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"Env var '{name}' must be an integer, got {raw!r}") from exc


def _optional_str(name: str, default: str) -> str:
    raw = os.getenv(name)
    return raw.strip() if raw and raw.strip() else default


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    gemini_api_key: str
    free_analyses_per_day: int
    max_video_size_mb: int
    telegram_file_limit_mb: int
    telegram_api_base_url: str | None
    telegram_api_file_url: str | None
    telegram_api_local_data_dir: Path | None
    admin_telegram_id: int | None
    log_level: str
    db_path: Path
    log_file: Path
    project_root: Path = field(default=PROJECT_ROOT)

    @property
    def max_video_size_bytes(self) -> int:
        return self.max_video_size_mb * 1024 * 1024

    def effective_video_mb(self, plugin_max_mb: int) -> int:
        """The real cap users must respect: min(game spec, telegram getFile limit)."""
        return min(plugin_max_mb, self.telegram_file_limit_mb)


def _load_settings() -> Settings:
    admin_raw = os.getenv("ADMIN_TELEGRAM_ID", "").strip()
    admin_id: int | None = int(admin_raw) if admin_raw else None

    db_path = PROJECT_ROOT / _optional_str("DB_PATH", "data/bot.db")
    log_file = PROJECT_ROOT / _optional_str("LOG_FILE", "logs/bot.log")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    return Settings(
        telegram_bot_token=_require("TELEGRAM_BOT_TOKEN"),
        gemini_api_key=_require("GEMINI_API_KEY"),
        free_analyses_per_day=_optional_int("FREE_ANALYSES_PER_DAY", 2),
        max_video_size_mb=_optional_int("MAX_VIDEO_SIZE_MB", 200),
        # Telegram's standard Bot API caps `getFile` downloads at 20 MB.
        # Override to 2000 if you run a self-hosted Local Bot API server.
        telegram_file_limit_mb=_optional_int("TELEGRAM_FILE_LIMIT_MB", 20),
        # Set both to point PTB at a Local Bot API server. Leave blank to
        # use the default https://api.telegram.org cloud endpoint.
        telegram_api_base_url=_optional_str("TELEGRAM_API_BASE_URL", "") or None,
        telegram_api_file_url=_optional_str("TELEGRAM_API_FILE_URL", "") or None,
        # In `--local` mode the Bot API server returns a CONTAINER path like
        # /var/lib/telegram-bot-api/<token>/videos/file_1.mp4. We translate
        # that to the HOST mount so we can read the file directly off disk.
        telegram_api_local_data_dir=(
            Path(_optional_str("TELEGRAM_API_LOCAL_DATA_DIR", "")).expanduser()
            if _optional_str("TELEGRAM_API_LOCAL_DATA_DIR", "") else None
        ),
        admin_telegram_id=admin_id,
        log_level=_optional_str("LOG_LEVEL", "INFO").upper(),
        db_path=db_path,
        log_file=log_file,
    )


def configure_logging(level: str, log_file: Path) -> None:
    """Configure root logger with rotating file handler + stderr."""
    from logging.handlers import RotatingFileHandler

    root = logging.getLogger()
    root.setLevel(getattr(logging, level, logging.INFO))

    fmt = logging.Formatter(
        '{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":%(message)r}'
    )

    file_handler = RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(fmt)

    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(stream_handler)


settings: Settings | None = None


def get_settings() -> Settings:
    """Lazy accessor — call once at startup, then import `settings`."""
    global settings
    if settings is None:
        settings = _load_settings()
    return settings
