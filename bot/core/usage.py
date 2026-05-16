"""
Per-user daily usage limits.

`free_analyses_per_day` is configurable via env var (default 2). The counter
is shared across ALL games — one global daily budget per user. The lazy
midnight reset is handled by `Database.reset_daily_if_stale`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from bot.db.database import Database


logger = logging.getLogger(__name__)


@dataclass
class UsageStatus:
    used_today: int
    limit: int
    total_analyses: int = 0
    is_admin: bool = False

    @property
    def remaining(self) -> int:
        if self.is_admin:
            return -1  # unlimited sentinel
        return max(0, self.limit - self.used_today)

    @property
    def is_exhausted(self) -> bool:
        if self.is_admin:
            return False
        return self.used_today >= self.limit

    def remaining_text(self, language_code: str = "en") -> str:
        """Human-readable line for footers and /limits."""
        from bot.core.i18n import t

        if self.is_admin:
            return t(language_code, "limit_admin")
        return t(
            language_code,
            "limit_remaining",
            remaining=self.remaining,
            limit=self.limit,
        )


class UsageGuard:
    """Reads + tracks the daily limit. Mutation happens in Analyzer."""

    def __init__(
        self,
        db: Database,
        daily_limit: int,
        admin_telegram_id: int | None = None,
    ):
        self._db = db
        self._limit = daily_limit
        self._admin_id = admin_telegram_id

    @property
    def limit(self) -> int:
        return self._limit

    async def check(
        self,
        telegram_id: int,
        username: str | None,
        language_code: str = "en",
    ) -> UsageStatus:
        """Returns the user's current usage for today (after midnight reset)."""
        await self._db.get_or_create_user(telegram_id, username, language_code)
        user = await self._db.reset_daily_if_stale(telegram_id, date.today())
        return UsageStatus(
            used_today=user.analyses_today,
            limit=self._limit,
            total_analyses=user.total_analyses,
            is_admin=(self._admin_id is not None and telegram_id == self._admin_id),
        )
