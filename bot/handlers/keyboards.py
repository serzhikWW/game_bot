"""
Inline keyboard builders shared across handlers.

Callback-data conventions (kept short to fit Telegram's 64-byte limit):
  * `g:<game_id>`              — user picked a game
  * `c:<game_id>:<char_idx>`   — user picked a character (index into config.characters)
  * `s:<match_id>:<slot>`      — user picked a Dota 2 player slot 1-10
  * `back:games`               — return to the game-list keyboard
  * `back:matchid`             — re-prompt for the match ID (from slot picker)
  * `cancel`                   — user cancels current flow
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.games.base import GameConfig


_BACK_GAMES = InlineKeyboardButton("← Back", callback_data="back:games")
_BACK_MATCHID = InlineKeyboardButton("← Back", callback_data="back:matchid")
_CANCEL = InlineKeyboardButton("✖️ Cancel", callback_data="cancel")


def games_keyboard(games: list[GameConfig]) -> InlineKeyboardMarkup:
    """One game per row — keeps it readable even with long names + emoji."""
    rows = [
        [InlineKeyboardButton(f"{g.emoji} {g.display_name}", callback_data=f"g:{g.id}")]
        for g in games
    ]
    return InlineKeyboardMarkup(rows)


def characters_keyboard(
    game_id: str, characters: list[str], per_row: int = 2
) -> InlineKeyboardMarkup:
    """Grid of characters. Index encoded in callback to keep payload small."""
    buttons = [
        InlineKeyboardButton(name, callback_data=f"c:{game_id}:{idx}")
        for idx, name in enumerate(characters)
    ]
    rows: list[list[InlineKeyboardButton]] = [
        buttons[i : i + per_row] for i in range(0, len(buttons), per_row)
    ]
    rows.append([_BACK_GAMES, _CANCEL])
    return InlineKeyboardMarkup(rows)


def match_id_prompt_keyboard() -> InlineKeyboardMarkup:
    """Shown together with the 'send your match ID' prompt for API games."""
    return InlineKeyboardMarkup([[_BACK_GAMES, _CANCEL]])


def slot_picker_keyboard(match_id: int, summaries) -> InlineKeyboardMarkup:
    """Dota 2 slot picker — 10 buttons + Back/Cancel row."""
    rows: list[list[InlineKeyboardButton]] = []
    for s in summaries:
        label = f"{s.slot}. {s.team[0]} · {s.hero} ({s.kda})"
        rows.append([InlineKeyboardButton(label, callback_data=f"s:{match_id}:{s.slot}")])
    rows.append([_BACK_MATCHID, _CANCEL])
    return InlineKeyboardMarkup(rows)
