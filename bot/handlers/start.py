"""
/start, /help, /games — entry-point commands.

All three render the same game-picker keyboard so the user always lands
in a well-defined flow state regardless of which command they invoke.
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.core.i18n import (
    get_user_language,
    t,
)
from bot.core.usage import UsageGuard
from bot.handlers import state
from bot.handlers.keyboards import games_keyboard, language_keyboard
from bot.services.registry import GameRegistry


logger = logging.getLogger(__name__)


def make_handlers(registry: GameRegistry, usage_guard: UsageGuard):
    async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        state.reset(context.user_data if context.user_data is not None else {})
        user = update.effective_user
        lang = await get_user_language(context, user)
        status = (
            await usage_guard.check(user.id, user.username, lang)
            if user else None
        )
        suffix = f"\n\n_{status.remaining_text(lang)}_" if status else ""
        await update.message.reply_text(
            t(lang, "welcome") + suffix,
            parse_mode="Markdown",
            reply_markup=games_keyboard(registry.all_games(), language_code=lang),
        )

    async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        lang = await get_user_language(context, update.effective_user)
        await update.message.reply_text(t(lang, "help"), parse_mode="Markdown")

    async def games_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        state.reset(context.user_data if context.user_data is not None else {})
        lang = await get_user_language(context, update.effective_user)
        await update.message.reply_text(
            t(lang, "choose_game"),
            reply_markup=games_keyboard(registry.all_games(), language_code=lang),
        )

    async def language_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        lang = await get_user_language(context, update.effective_user)
        await update.message.reply_text(
            t(lang, "choose_language"),
            reply_markup=language_keyboard(lang),
        )

    async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        state.reset(context.user_data if context.user_data is not None else {})
        lang = await get_user_language(context, update.effective_user)
        await update.message.reply_text(t(lang, "cancelled"))

    async def limits_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if user is None:
            return
        lang = await get_user_language(context, user)
        status = await usage_guard.check(user.id, user.username, lang)
        msg = (
            f"{t(lang, 'limits_title')}\n\n"
            f"{status.remaining_text(lang)}\n"
            f"{t(lang, 'lifetime_analyses', count=status.total_analyses)}"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")

    return {
        "start": start_cmd,
        "help": help_cmd,
        "games": games_cmd,
        "language": language_cmd,
        "cancel": cancel_cmd,
        "limits": limits_cmd,
    }
