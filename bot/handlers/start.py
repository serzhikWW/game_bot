"""
/start, /help, /games — entry-point commands.

All three render the same game-picker keyboard so the user always lands
in a well-defined flow state regardless of which command they invoke.
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.core.usage import UsageGuard
from bot.handlers import state
from bot.handlers.keyboards import games_keyboard
from bot.services.registry import GameRegistry


logger = logging.getLogger(__name__)


WELCOME = (
    "👋 *GameCoach Bot*\n\n"
    "Pick a game below to get an AI coaching analysis of your gameplay."
)

HELP = (
    "🤖 *How it works*\n\n"
    "1. Pick a game with /games\n"
    "2. For video games — pick your hero, then upload an MP4 clip\n"
    "3. For Dota 2 — send your match ID, then pick which slot was you\n\n"
    "You get a structured analysis with timestamps, mistakes and a "
    "recommendation. Daily free limit applies.\n\n"
    "Commands:\n"
    "/start — start over\n"
    "/games — pick a game\n"
    "/limits — see your daily usage\n"
    "/cancel — cancel the current flow\n"
    "/help — this message"
)


def make_handlers(registry: GameRegistry, usage_guard: UsageGuard):
    async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        state.reset(context.user_data if context.user_data is not None else {})
        user = update.effective_user
        status = await usage_guard.check(user.id, user.username) if user else None
        suffix = f"\n\n_{status.remaining_text()}_" if status else ""
        await update.message.reply_text(
            WELCOME + suffix,
            parse_mode="Markdown",
            reply_markup=games_keyboard(registry.all_games()),
        )

    async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(HELP, parse_mode="Markdown")

    async def games_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        state.reset(context.user_data if context.user_data is not None else {})
        await update.message.reply_text(
            "Choose a game:",
            reply_markup=games_keyboard(registry.all_games()),
        )

    async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        state.reset(context.user_data if context.user_data is not None else {})
        await update.message.reply_text(
            "Cancelled. Send /games to start over."
        )

    async def limits_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if user is None:
            return
        status = await usage_guard.check(user.id, user.username)
        msg = (
            f"📊 *Your usage*\n\n"
            f"{status.remaining_text()}\n"
            f"Lifetime analyses: {status.total_analyses}"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")

    return {
        "start": start_cmd,
        "help": help_cmd,
        "games": games_cmd,
        "cancel": cancel_cmd,
        "limits": limits_cmd,
    }
