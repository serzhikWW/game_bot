"""
Per-user conversation state stored in `context.user_data`.

We don't use ConversationHandler — the flow is small enough that an
explicit state machine in user_data is clearer and keeps each handler
independent. Helpers here centralise the keys so we never typo them.
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class FlowState(str, Enum):
    IDLE = "idle"
    AWAITING_HERO = "awaiting_hero"        # video games, after game picked
    AWAITING_VIDEO = "awaiting_video"      # video games, after hero picked
    AWAITING_MATCH_ID = "awaiting_match_id"  # API games, after game picked
    AWAITING_SLOT = "awaiting_slot"        # Dota 2, after match fetched


KEY_STATE = "flow_state"
KEY_GAME_ID = "game_id"
KEY_CHARACTER = "character"
KEY_MATCH_ID = "match_id"


def reset(user_data: dict[str, Any]) -> None:
    for k in (KEY_STATE, KEY_GAME_ID, KEY_CHARACTER, KEY_MATCH_ID):
        user_data.pop(k, None)


def set_state(user_data: dict[str, Any], state: FlowState) -> None:
    user_data[KEY_STATE] = state


def get_state(user_data: dict[str, Any]) -> FlowState:
    return FlowState(user_data.get(KEY_STATE, FlowState.IDLE.value))
