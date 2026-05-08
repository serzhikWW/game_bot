"""
Game / character / slot picker callback handlers.

Routes:
  * `g:<game_id>`              → set state, show heroes (or ask for match ID)
  * `c:<game_id>:<idx>`        → store hero, ask for video upload
  * `s:<match_id>:<slot>`      → resume Dota 2 analyze with the chosen slot
  * `cancel`                   → reset state
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.core.analyzer import Analyzer
from bot.core.usage import UsageGuard
from bot.handlers import state
from bot.handlers.keyboards import (
    characters_keyboard,
    games_keyboard,
    match_id_prompt_keyboard,
)
from bot.handlers.video import send_analysis_chunks
from bot.games.base import InputType
from bot.games.dota2 import (
    Dota2Error,
    Dota2Plugin,
    MatchNotFoundError,
    OpenDotaUnavailable,
)
from bot.services.registry import GameRegistry


logger = logging.getLogger(__name__)


def make_callback_handler(
    registry: GameRegistry,
    analyzer: Analyzer,
    usage_guard: UsageGuard,
):
    async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if query is None or query.data is None:
            return
        await query.answer()
        data = query.data
        # PTB always provides a dict here; never use `or {}` — empty dict is falsy
        # and that would silently discard our mutations.
        user_data = context.user_data if context.user_data is not None else {}

        if data == "cancel":
            state.reset(user_data)
            await query.edit_message_text("Cancelled. Send /games to start over.")
            return

        if data == "back:games":
            await _on_back_to_games(query, user_data, registry)
            return

        if data == "back:matchid":
            await _on_back_to_matchid(query, user_data, registry)
            return

        if data.startswith("g:"):
            await _on_game_pick(query, user_data, data[2:], registry)
            return

        if data.startswith("c:"):
            await _on_character_pick(query, user_data, data[2:], registry)
            return

        if data.startswith("s:"):
            await _on_slot_pick(
                query, user_data, data[2:], registry, analyzer, usage_guard
            )
            return

        logger.warning("unknown_callback data=%s", data)

    return on_callback


async def _on_back_to_games(query, user_data, registry):
    """Reset flow + show the game-list keyboard again."""
    state.reset(user_data)
    await query.edit_message_text(
        "Choose a game:",
        reply_markup=games_keyboard(registry.all_games()),
    )


async def _on_back_to_matchid(query, user_data, registry):
    """Drop the slot picker and re-prompt for a match ID."""
    game_id = user_data.get(state.KEY_GAME_ID, "dota2")
    plugin = registry.get(game_id)
    if plugin is None:
        await _on_back_to_games(query, user_data, registry)
        return
    user_data.pop(state.KEY_MATCH_ID, None)
    state.set_state(user_data, state.FlowState.AWAITING_MATCH_ID)
    cfg = plugin.config
    await query.edit_message_text(
        f"{cfg.emoji} *{cfg.display_name}*\n\n{cfg.description}",
        parse_mode="Markdown",
        reply_markup=match_id_prompt_keyboard(),
    )


async def _on_game_pick(query, user_data, game_id, registry):
    plugin = registry.get(game_id)
    if plugin is None:
        await query.edit_message_text("Unknown game. Send /games to start over.")
        return

    cfg = plugin.config
    user_data[state.KEY_GAME_ID] = game_id

    if cfg.has_characters:
        state.set_state(user_data, state.FlowState.AWAITING_HERO)
        await query.edit_message_text(
            f"{cfg.emoji} *{cfg.display_name}*\n\nPick your hero:",
            parse_mode="Markdown",
            reply_markup=characters_keyboard(game_id, cfg.characters),
        )
        return

    if cfg.input_type == InputType.MATCH_ID:
        state.set_state(user_data, state.FlowState.AWAITING_MATCH_ID)
        await query.edit_message_text(
            f"{cfg.emoji} *{cfg.display_name}*\n\n{cfg.description}",
            parse_mode="Markdown",
            reply_markup=match_id_prompt_keyboard(),
        )
        return

    state.set_state(user_data, state.FlowState.AWAITING_VIDEO)
    await query.edit_message_text(
        f"{cfg.emoji} *{cfg.display_name}*\n\n{cfg.description}",
        parse_mode="Markdown",
        reply_markup=match_id_prompt_keyboard(),
    )


async def _on_character_pick(query, user_data, payload, registry):
    try:
        game_id, idx_str = payload.split(":", 1)
        idx = int(idx_str)
    except (ValueError, IndexError):
        await query.edit_message_text("Invalid selection. Send /games to start over.")
        return

    plugin = registry.get(game_id)
    if plugin is None:
        await query.edit_message_text("Unknown game. Send /games to start over.")
        return

    chars = plugin.config.characters
    if not 0 <= idx < len(chars):
        await query.edit_message_text("Invalid character. Send /games to start over.")
        return

    character = chars[idx]
    user_data[state.KEY_GAME_ID] = game_id
    user_data[state.KEY_CHARACTER] = character
    state.set_state(user_data, state.FlowState.AWAITING_VIDEO)

    cfg = plugin.config
    await query.edit_message_text(
        f"{cfg.emoji} *{cfg.display_name}* — {character}\n\n"
        f"Now upload your gameplay clip (MP4, max {cfg.max_video_mb}MB).",
        parse_mode="Markdown",
    )


async def _on_slot_pick(query, user_data, payload, registry, analyzer, usage_guard):
    try:
        match_id_str, slot_str = payload.split(":", 1)
        match_id = int(match_id_str)
        slot = int(slot_str)
    except (ValueError, IndexError):
        await query.edit_message_text("Invalid selection. Send /games to start over.")
        return

    plugin = registry.get("dota2")
    if not isinstance(plugin, Dota2Plugin):
        await query.edit_message_text("Dota 2 plugin not available right now.")
        return

    user = query.from_user
    status = await usage_guard.check(user.id, user.username)
    if status.is_exhausted:
        await query.edit_message_text(
            f"⛔️ Daily limit reached ({status.limit}/day). Try again tomorrow."
        )
        state.reset(user_data)
        return

    state.reset(user_data)
    await query.edit_message_text("⏳ Analyzing match... ~10-30 seconds")

    try:
        result = await analyzer.run(
            plugin,
            telegram_id=user.id,
            username=user.username,
            user_input=f"{match_id} {slot}",
            character=None,
        )
    except MatchNotFoundError as e:
        await query.message.reply_text(str(e))
        return
    except OpenDotaUnavailable as e:
        await query.message.reply_text(str(e))
        return
    except Dota2Error as e:
        await query.message.reply_text(f"⚠️ {e}")
        return
    except Exception:
        logger.exception("dota2_slot_analyze_failed user_id=%d match_id=%d slot=%d",
                         user.id, match_id, slot)
        await query.message.reply_text(
            "Something went wrong while analyzing. Please try again."
        )
        return

    await send_analysis_chunks(
        query.message.chat,
        result,
        usage_guard=usage_guard,
        telegram_id=user.id,
        username=user.username,
    )
