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


def _back_games(language_code: str) -> InlineKeyboardButton:
    label = "← Назад" if language_code == "ru" else "← Back"
    return InlineKeyboardButton(label, callback_data="back:games")


def _back_matchid(language_code: str) -> InlineKeyboardButton:
    label = "← Назад" if language_code == "ru" else "← Back"
    return InlineKeyboardButton(label, callback_data="back:matchid")


def _cancel(language_code: str) -> InlineKeyboardButton:
    label = "✖️ Отмена" if language_code == "ru" else "✖️ Cancel"
    return InlineKeyboardButton(label, callback_data="cancel")


def games_keyboard(
    games: list[GameConfig],
    *,
    language_code: str = "en",
) -> InlineKeyboardMarkup:
    """One game per row — keeps it readable even with long names + emoji."""
    rows = [
        [InlineKeyboardButton(f"{g.emoji} {g.display_name}", callback_data=f"g:{g.id}")]
        for g in games
    ]
    lang_label = "🌐 Language" if language_code != "ru" else "🌐 Язык"
    rows.append([InlineKeyboardButton(lang_label, callback_data="lang:menu")])
    return InlineKeyboardMarkup(rows)


def characters_keyboard(
    game_id: str,
    characters: list[str],
    per_row: int = 2,
    language_code: str = "en",
) -> InlineKeyboardMarkup:
    """Grid of characters. Index encoded in callback to keep payload small."""
    buttons = [
        InlineKeyboardButton(name, callback_data=f"c:{game_id}:{idx}")
        for idx, name in enumerate(characters)
    ]
    rows: list[list[InlineKeyboardButton]] = [
        buttons[i : i + per_row] for i in range(0, len(buttons), per_row)
    ]
    rows.append([_back_games(language_code), _cancel(language_code)])
    return InlineKeyboardMarkup(rows)


def match_id_prompt_keyboard(language_code: str = "en") -> InlineKeyboardMarkup:
    """Shown together with the 'send your match ID' prompt for API games."""
    return InlineKeyboardMarkup([[_back_games(language_code), _cancel(language_code)]])


def language_keyboard(current: str = "en") -> InlineKeyboardMarkup:
    """Language picker keyboard."""
    en = "✓ English" if current == "en" else "English"
    ru = "✓ Русский" if current == "ru" else "Русский"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(en, callback_data="lang:set:en")],
            [InlineKeyboardButton(ru, callback_data="lang:set:ru")],
            [_back_games(current), _cancel(current)],
        ]
    )


def slot_picker_keyboard(
    match_id: int,
    summaries,
    language_code: str = "en",
) -> InlineKeyboardMarkup:
    """Dota 2 slot picker — 10 buttons + Back/Cancel row."""
    rows: list[list[InlineKeyboardButton]] = []
    for s in summaries:
        label = f"{s.slot}. {s.team[0]} · {s.hero} ({s.kda})"
        rows.append([InlineKeyboardButton(label, callback_data=f"s:{match_id}:{s.slot}")])
    rows.append([_back_matchid(language_code), _cancel(language_code)])
    return InlineKeyboardMarkup(rows)
