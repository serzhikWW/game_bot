"""
Async SQLite database access via aiosqlite.

Holds a single shared connection (`Database.connect()` at startup,
`Database.close()` at shutdown). All public methods are coroutines.
The connection enables foreign keys and uses a row factory so queries
return dict-like rows that we hydrate into dataclasses.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path

import aiosqlite

from bot.db.models import Analysis, User


logger = logging.getLogger(__name__)


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    telegram_id INTEGER UNIQUE NOT NULL,
    username TEXT,
    language_code TEXT NOT NULL DEFAULT 'en',
    analyses_today INTEGER NOT NULL DEFAULT 0,
    last_analysis_date DATE,
    total_analyses INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS analyses (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    game_id TEXT NOT NULL,
    character TEXT,
    input_type TEXT NOT NULL,
    result TEXT NOT NULL,
    tokens_used INTEGER NOT NULL DEFAULT 0,
    processing_seconds REAL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_analyses_user_created
    ON analyses (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_analyses_game
    ON analyses (game_id, created_at DESC);
"""


def _parse_date(value: str | None) -> date | None:
    if value is None:
        return None
    return date.fromisoformat(value)


def _parse_dt(value: str) -> datetime:
    # SQLite CURRENT_TIMESTAMP returns "YYYY-MM-DD HH:MM:SS"
    return datetime.fromisoformat(value.replace(" ", "T"))


def _row_to_user(row: aiosqlite.Row) -> User:
    return User(
        id=row["id"],
        telegram_id=row["telegram_id"],
        username=row["username"],
        language_code=row["language_code"],
        analyses_today=row["analyses_today"],
        last_analysis_date=_parse_date(row["last_analysis_date"]),
        total_analyses=row["total_analyses"],
        created_at=_parse_dt(row["created_at"]),
    )


def _row_to_analysis(row: aiosqlite.Row) -> Analysis:
    return Analysis(
        id=row["id"],
        user_id=row["user_id"],
        game_id=row["game_id"],
        character=row["character"],
        input_type=row["input_type"],
        result=row["result"],
        tokens_used=row["tokens_used"],
        processing_seconds=row["processing_seconds"],
        created_at=_parse_dt(row["created_at"]),
    )


class Database:
    """Owns the single aiosqlite connection. Construct once, share everywhere."""

    def __init__(self, path: Path):
        self._path = path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        if self._conn is not None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(str(self._path))
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys = ON")
        await conn.execute("PRAGMA journal_mode = WAL")
        await conn.executescript(SCHEMA)
        await self._migrate(conn)
        await conn.commit()
        self._conn = conn
        logger.info("database_connected path=%s", self._path)

    async def _migrate(self, conn: aiosqlite.Connection) -> None:
        """Apply lightweight schema additions for existing SQLite files."""
        async with conn.execute("PRAGMA table_info(users)") as cur:
            columns = {row["name"] for row in await cur.fetchall()}
        if "language_code" not in columns:
            await conn.execute(
                "ALTER TABLE users ADD COLUMN language_code TEXT NOT NULL DEFAULT 'en'"
            )
            logger.info("database_migration_added_language_code")

    async def close(self) -> None:
        if self._conn is None:
            return
        await self._conn.close()
        self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database.connect() must be called before use")
        return self._conn

    # --- users ---------------------------------------------------------

    async def get_or_create_user(
        self,
        telegram_id: int,
        username: str | None,
        language_code: str = "en",
    ) -> User:
        """Insert-if-missing, then update username if it changed, and return the row."""
        await self.conn.execute(
            """
            INSERT OR IGNORE INTO users (telegram_id, username, language_code)
            VALUES (?, ?, ?)
            """,
            (telegram_id, username, language_code),
        )
        await self.conn.execute(
            "UPDATE users SET username = ? WHERE telegram_id = ? AND IFNULL(username,'') != IFNULL(?, '')",
            (username, telegram_id, username),
        )
        await self.conn.commit()
        async with self.conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ) as cur:
            row = await cur.fetchone()
        assert row is not None, "row should exist after upsert"
        return _row_to_user(row)

    async def set_user_language(self, telegram_id: int, language_code: str) -> None:
        await self.conn.execute(
            "UPDATE users SET language_code = ? WHERE telegram_id = ?",
            (language_code, telegram_id),
        )
        await self.conn.commit()

    async def get_user(self, telegram_id: int) -> User | None:
        async with self.conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ) as cur:
            row = await cur.fetchone()
        return _row_to_user(row) if row else None

    async def reset_daily_if_stale(self, telegram_id: int, today: date) -> User:
        """If last_analysis_date != today, zero analyses_today. Returns fresh row."""
        await self.conn.execute(
            """
            UPDATE users
               SET analyses_today = 0
             WHERE telegram_id = ?
               AND (last_analysis_date IS NULL OR last_analysis_date < ?)
            """,
            (telegram_id, today.isoformat()),
        )
        await self.conn.commit()
        user = await self.get_user(telegram_id)
        assert user is not None
        return user

    async def increment_usage(self, telegram_id: int, today: date) -> None:
        """Bump analyses_today and total_analyses, set last_analysis_date."""
        await self.conn.execute(
            """
            UPDATE users
               SET analyses_today = analyses_today + 1,
                   total_analyses = total_analyses + 1,
                   last_analysis_date = ?
             WHERE telegram_id = ?
            """,
            (today.isoformat(), telegram_id),
        )
        await self.conn.commit()

    # --- analyses ------------------------------------------------------

    async def save_analysis(
        self,
        *,
        user_id: int,
        game_id: str,
        character: str | None,
        input_type: str,
        result: str,
        tokens_used: int,
        processing_seconds: float | None,
    ) -> int:
        """Insert an analysis row and return its id."""
        cur = await self.conn.execute(
            """
            INSERT INTO analyses
                (user_id, game_id, character, input_type, result, tokens_used, processing_seconds)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                game_id,
                character,
                input_type,
                result,
                tokens_used,
                processing_seconds,
            ),
        )
        await self.conn.commit()
        analysis_id = cur.lastrowid
        await cur.close()
        assert analysis_id is not None
        return analysis_id

    async def recent_analyses(
        self, telegram_id: int, limit: int = 10
    ) -> list[Analysis]:
        async with self.conn.execute(
            """
            SELECT a.*
              FROM analyses a
              JOIN users u ON u.id = a.user_id
             WHERE u.telegram_id = ?
             ORDER BY a.created_at DESC
             LIMIT ?
            """,
            (telegram_id, limit),
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_analysis(r) for r in rows]
