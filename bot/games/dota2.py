"""
Dota 2 plugin — API-based analysis via OpenDota + Gemini text generation.

User flow (driven by the handler):
  1. User picks Dota 2 → bot asks for match ID.
  2. User sends "<match_id>" or "<match_id> <slot>" where slot is 1-10
     (1-5 = radiant pos 1-5, 6-10 = dire pos 1-5 in match-listing order).
  3. If the slot is missing the handler can call `summarize_match()` to show
     a hero-list picker, then re-call `analyze()` with the chosen slot.

The plugin is self-contained: OpenDota client, constants caching, and the
prompt builder all live in this file. Hero/item lookups use OpenDota's
public `/constants/*` endpoints, fetched once and cached in module state.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any

import aiohttp

from bot.games.base import (
    AnalysisResult,
    BaseGamePlugin,
    GameConfig,
    InputType,
)
from bot.services import container


logger = logging.getLogger(__name__)


OPENDOTA_BASE = "https://api.opendota.com/api"
HTTP_TIMEOUT_S = 20.0


# --- exceptions -----------------------------------------------------------


class Dota2Error(RuntimeError):
    """User-presentable Dota 2 plugin error."""


class MatchNotFoundError(Dota2Error):
    pass


class OpenDotaUnavailable(Dota2Error):
    pass


class PlayerSlotRequired(Dota2Error):
    """Raised when no slot is provided; handler should prompt the user."""

    def __init__(self, match_id: int, summaries: list["PlayerSummary"]):
        super().__init__("Player slot required")
        self.match_id = match_id
        self.summaries = summaries


# --- constants cache ------------------------------------------------------


_heroes_cache: dict[int, str] | None = None
_items_cache: dict[int, str] | None = None
_cache_lock: asyncio.Lock | None = None


def _get_lock() -> asyncio.Lock:
    global _cache_lock
    if _cache_lock is None:
        _cache_lock = asyncio.Lock()
    return _cache_lock


async def _ensure_constants(session: aiohttp.ClientSession) -> None:
    """Fetch hero + item id→name mappings once, cache in module state."""
    global _heroes_cache, _items_cache
    if _heroes_cache is not None and _items_cache is not None:
        return
    async with _get_lock():
        if _heroes_cache is not None and _items_cache is not None:
            return

        async with session.get(f"{OPENDOTA_BASE}/constants/heroes") as r:
            r.raise_for_status()
            heroes_json = await r.json()
        async with session.get(f"{OPENDOTA_BASE}/constants/items") as r:
            r.raise_for_status()
            items_json = await r.json()

        # heroes_json: {"1": {"id":1,"localized_name":"Anti-Mage",...}, ...}
        _heroes_cache = {
            int(v["id"]): v.get("localized_name") or v.get("name") or f"Hero {v['id']}"
            for v in heroes_json.values()
        }
        # items_json: {"blink": {"id":1,"dname":"Blink Dagger",...}, ...}
        _items_cache = {
            int(v["id"]): v.get("dname") or k.replace("_", " ").title()
            for k, v in items_json.items()
            if v.get("id") is not None
        }
        _items_cache[0] = "—"
        logger.info(
            "opendota_constants_loaded heroes=%d items=%d",
            len(_heroes_cache),
            len(_items_cache),
        )


# --- data shapes ----------------------------------------------------------


@dataclass
class PlayerSummary:
    """Lightweight per-player snapshot for the slot picker."""

    slot: int  # 1..10 (UX numbering)
    team: str  # "Radiant" | "Dire"
    hero: str
    kda: str  # "K/D/A"


@dataclass
class _PlayerDetail:
    summary: PlayerSummary
    raw: dict[str, Any]


# --- helpers --------------------------------------------------------------


_SLOT_TO_TEAM_AND_INDEX = {
    1: ("Radiant", 0), 2: ("Radiant", 1), 3: ("Radiant", 2),
    4: ("Radiant", 3), 5: ("Radiant", 4),
    6: ("Dire", 0), 7: ("Dire", 1), 8: ("Dire", 2),
    9: ("Dire", 3), 10: ("Dire", 4),
}


def _parse_input(text: str) -> tuple[int, int | None]:
    """Parse '<match_id>' or '<match_id> <slot>'. Returns (match_id, slot|None)."""
    parts = re.split(r"[\s:,]+", text.strip())
    parts = [p for p in parts if p]
    if not parts or not parts[0].isdigit():
        raise Dota2Error(
            "Invalid input. Send a numeric match ID, e.g. '7891234567'."
        )
    match_id = int(parts[0])
    if match_id <= 0:
        raise Dota2Error("Match ID must be a positive number.")

    slot: int | None = None
    if len(parts) >= 2:
        if not parts[1].isdigit():
            raise Dota2Error("Slot must be a number 1-10.")
        slot = int(parts[1])
        if not 1 <= slot <= 10:
            raise Dota2Error("Slot must be between 1 and 10.")
    return match_id, slot


def _resolve_player(match_json: dict[str, Any], slot: int) -> _PlayerDetail:
    """Pick the player at UX slot (1-10) from match.players[]."""
    team_name, idx = _SLOT_TO_TEAM_AND_INDEX[slot]
    is_dire = team_name == "Dire"

    # OpenDota: player_slot bit 128 = dire team; lower bits = position 0-4.
    candidates = [
        p for p in match_json.get("players", [])
        if bool(p.get("player_slot", 0) & 128) == is_dire
        and (p.get("player_slot", 0) & 7) == idx
    ]
    if not candidates:
        raise Dota2Error(f"Could not find player at slot {slot} in this match.")
    p = candidates[0]
    hero_id = int(p.get("hero_id") or 0)
    hero = (_heroes_cache or {}).get(hero_id, f"Hero #{hero_id}")
    kda = f"{p.get('kills', 0)}/{p.get('deaths', 0)}/{p.get('assists', 0)}"
    return _PlayerDetail(
        summary=PlayerSummary(slot=slot, team=team_name, hero=hero, kda=kda),
        raw=p,
    )


def _player_summaries(match_json: dict[str, Any]) -> list[PlayerSummary]:
    """All 10 players summarized for the slot picker."""
    out: list[PlayerSummary] = []
    heroes = _heroes_cache or {}
    for slot, (team_name, idx) in _SLOT_TO_TEAM_AND_INDEX.items():
        is_dire = team_name == "Dire"
        for p in match_json.get("players", []):
            if bool(p.get("player_slot", 0) & 128) != is_dire:
                continue
            if (p.get("player_slot", 0) & 7) != idx:
                continue
            hero_id = int(p.get("hero_id") or 0)
            out.append(
                PlayerSummary(
                    slot=slot,
                    team=team_name,
                    hero=heroes.get(hero_id, f"Hero #{hero_id}"),
                    kda=f"{p.get('kills', 0)}/{p.get('deaths', 0)}/{p.get('assists', 0)}",
                )
            )
            break
    return out


_LANE_ROLE = {1: "Safe lane", 2: "Mid lane", 3: "Offlane", 4: "Jungle"}


def _format_duration(seconds: int) -> str:
    m, s = divmod(int(seconds or 0), 60)
    return f"{m}:{s:02d}"


def _build_match_data(detail: _PlayerDetail, match_json: dict[str, Any]) -> dict:
    """Compact, prompt-ready summary of the player's match performance."""
    p = detail.raw
    radiant_win = bool(match_json.get("radiant_win"))
    is_radiant = detail.summary.team == "Radiant"
    won = radiant_win == is_radiant

    items = (_items_cache or {})
    item_names = [
        items.get(int(p.get(f"item_{i}", 0) or 0), "—") for i in range(6)
    ]
    backpack = [
        items.get(int(p.get(f"backpack_{i}", 0) or 0), "—") for i in range(3)
    ]
    neutral = items.get(int(p.get("item_neutral", 0) or 0), "—")

    return {
        "match_id": match_json.get("match_id"),
        "duration": _format_duration(match_json.get("duration", 0)),
        "result": "WIN" if won else "LOSS",
        "team": detail.summary.team,
        "hero": detail.summary.hero,
        "lane": _LANE_ROLE.get(int(p.get("lane_role") or 0), "Unknown"),
        "kda": detail.summary.kda,
        "gpm": p.get("gold_per_min"),
        "xpm": p.get("xp_per_min"),
        "last_hits": p.get("last_hits"),
        "denies": p.get("denies"),
        "hero_damage": p.get("hero_damage"),
        "tower_damage": p.get("tower_damage"),
        "hero_healing": p.get("hero_healing"),
        "net_worth": p.get("net_worth") or p.get("total_gold"),
        "items": item_names,
        "backpack": backpack,
        "neutral_item": neutral,
        "benchmarks": p.get("benchmarks"),  # may be None
        "parsed": match_json.get("version") is not None,
    }


# --- plugin ---------------------------------------------------------------


class Dota2Plugin(BaseGamePlugin):
    """Match ID → OpenDota fetch → structured stats → Gemini coaching."""

    @property
    def config(self) -> GameConfig:
        return GameConfig(
            id="dota2",
            display_name="Dota 2",
            emoji="🗡️",
            input_type=InputType.MATCH_ID,
            has_characters=False,
            characters=[],
            description=(
                "Send your match ID (find it in Main Menu → Profile → Matches). "
                "After fetching the match you'll pick which slot was you."
            ),
        )

    def get_prompt(self, character: str | None) -> str:
        # Returned for completeness; the actual prompt sent to Gemini is built
        # inside `_build_full_prompt` once we have the match data.
        return _PROMPT_TEMPLATE

    async def analyze(
        self,
        user_input: str | bytes,
        character: str | None,
        user_id: int,
    ) -> AnalysisResult:
        if not isinstance(user_input, str):
            raise TypeError(
                f"Dota 2 plugin expects a string match ID, got {type(user_input).__name__}"
            )
        if character is not None:
            raise ValueError("Dota 2 does not take a character argument")

        match_id, slot = _parse_input(user_input)
        logger.info(
            "dota2_analyze_start user_id=%d match_id=%d slot=%s",
            user_id, match_id, slot,
        )

        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_S)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            match_json = await self._fetch_match(session, match_id)
            await _ensure_constants(session)

        if slot is None:
            raise PlayerSlotRequired(match_id, _player_summaries(match_json))

        detail = _resolve_player(match_json, slot)
        match_data = _build_match_data(detail, match_json)
        prompt = _build_full_prompt(match_data)

        out = await container.get_gemini().analyze_text(prompt)
        logger.info(
            "dota2_analyze_done user_id=%d match_id=%d hero=%s tokens=%d seconds=%.2f",
            user_id, match_id, detail.summary.hero,
            out.tokens_used, out.processing_seconds,
        )

        return AnalysisResult(
            game_id=self.config.id,
            character=detail.summary.hero,
            raw_text=out.raw_text,
            tokens_used=out.tokens_used,
            processing_seconds=out.processing_seconds,
            source="hybrid",
        )

    # --- public helper for the handler's slot-picker step --------------

    async def summarize_match(self, match_id: int) -> list[PlayerSummary]:
        """Fetch the match + return one summary per slot for the slot picker."""
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_S)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            match_json = await self._fetch_match(session, match_id)
            await _ensure_constants(session)
        return _player_summaries(match_json)

    # --- internals -----------------------------------------------------

    async def _fetch_match(
        self, session: aiohttp.ClientSession, match_id: int
    ) -> dict[str, Any]:
        url = f"{OPENDOTA_BASE}/matches/{match_id}"
        try:
            async with session.get(url) as r:
                if r.status == 404:
                    raise MatchNotFoundError(
                        f"Match {match_id} not found. Check the ID and try again."
                    )
                if r.status >= 500:
                    raise OpenDotaUnavailable(
                        "Dota 2 stats unavailable, try again later."
                    )
                r.raise_for_status()
                data = await r.json()
        except asyncio.TimeoutError as e:
            raise OpenDotaUnavailable(
                "Dota 2 stats request timed out, try again later."
            ) from e
        except aiohttp.ClientError as e:
            raise OpenDotaUnavailable(
                "Dota 2 stats unavailable, try again later."
            ) from e

        if not data or "match_id" not in data:
            raise MatchNotFoundError(
                f"Match {match_id} not found. Check the ID and try again."
            )
        return data


# --- prompt ---------------------------------------------------------------


_PROMPT_TEMPLATE = """\
You are a professional Dota 2 coach.
Below is structured match data for one player.

Analyze performance and respond in this EXACT format:

🗡️ HERO: {hero}
📊 MATCH RESULT: {result} ({duration})

❌ TOP 3 ISSUES:
1. [Category] — [Problem] → [What to do instead]
2. [Category] — [Problem] → [What to do instead]
3. [Category] — [Problem] → [What to do instead]

✅ STRENGTHS:
1. [Specific positive stat or decision]
2. [Specific positive stat or decision]

💡 MAIN RECOMMENDATION:
[One concrete improvement for next game]

📊 PERFORMANCE SCORE: [X/10]

Match data:
{match_data_json}
"""


def _build_full_prompt(match_data: dict) -> str:
    import json

    # Render the template with hero/result/duration so they show in the header,
    # and dump the whole structured payload for the model.
    return _PROMPT_TEMPLATE.format(
        hero=match_data["hero"],
        result=match_data["result"],
        duration=match_data["duration"],
        match_data_json=json.dumps(match_data, indent=2, ensure_ascii=False),
    )
