"""
Text-message handler for API-based games (match-ID flow).

When the user is in `AWAITING_MATCH_ID` state, treat their next message
as a match ID. Fetch the match summary, then show a slot picker. The
slot picker is consumed by `game_select.on_callback`'s `s:` route.
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.core.i18n import get_user_language, t
from bot.handlers import state
from bot.handlers.keyboards import slot_picker_keyboard
from bot.games.dota2 import (
    Dota2Error,
    Dota2Plugin,
    MatchNotFoundError,
    OpenDotaUnavailable,
    PlayerSlotRequired,
    _parse_input,
)
from bot.services.registry import GameRegistry


logger = logging.getLogger(__name__)


def make_text_handler(registry: GameRegistry):
    async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.message
        if message is None or not message.text:
            return
        user_data = context.user_data if context.user_data is not None else {}
        lang = await get_user_language(context, update.effective_user)

        flow = state.get_state(user_data)
        if flow == state.FlowState.AWAITING_VIDEO:
            await message.reply_text(t(lang, "waiting_video"))
            return
        if flow == state.FlowState.AWAITING_HERO:
            await message.reply_text(t(lang, "waiting_hero"))
            return
        if flow == state.FlowState.AWAITING_SLOT:
            await message.reply_text(t(lang, "waiting_slot"))
            return
        if flow == state.FlowState.IDLE:
            await message.reply_text(t(lang, "idle_text"))
            return
        if flow != state.FlowState.AWAITING_MATCH_ID:
            return

        game_id = user_data.get(state.KEY_GAME_ID)
        if game_id != "dota2":
            return  # only Dota 2 uses this flow today

        plugin = registry.get("dota2")
        if not isinstance(plugin, Dota2Plugin):
            await message.reply_text(t(lang, "dota_unavailable"))
            return

        # Validate match-id format up front so we can show a clear error
        try:
            match_id, _ = _parse_input(message.text)
        except Dota2Error as e:
            await message.reply_text(f"⚠️ {e}")
            return

        progress = await message.reply_text(t(lang, "fetching_match"))

        try:
            summaries = await plugin.summarize_match(match_id)
        except MatchNotFoundError as e:
            await progress.edit_text(str(e))
            return
        except OpenDotaUnavailable as e:
            await progress.edit_text(str(e))
            return
        except Dota2Error as e:
            await progress.edit_text(f"⚠️ {e}")
            return
        except Exception:
            logger.exception("opendota_fetch_failed match_id=%d", match_id)
            await progress.edit_text(t(lang, "dota_failed"))
            return

        state.set_state(user_data, state.FlowState.AWAITING_SLOT)
        user_data[state.KEY_MATCH_ID] = match_id

        await progress.edit_text(
            t(lang, "match_found", match_id=match_id),
            parse_mode="Markdown",
            reply_markup=slot_picker_keyboard(
                match_id,
                summaries,
                language_code=lang,
            ),
        )

    return on_text


# Re-export so the unused-import linter doesn't flag PlayerSlotRequired.
__all__ = ["make_text_handler", "PlayerSlotRequired"]
