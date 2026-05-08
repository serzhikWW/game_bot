"""
Plain dataclasses mirroring rows in the `users` and `analyses` tables.

These are returned from `database.py` queries — keep them as data containers,
no behavior. SQL lives in `database.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass
class User:
    id: int
    telegram_id: int
    username: str | None
    analyses_today: int
    last_analysis_date: date | None
    total_analyses: int
    created_at: datetime


@dataclass
class Analysis:
    id: int
    user_id: int
    game_id: str
    character: str | None
    input_type: str  # "video" | "match_id"
    result: str
    tokens_used: int
    processing_seconds: float | None
    created_at: datetime
