"""Compact English hero-kit descriptions for Marvel Rivals prompts."""

from __future__ import annotations

from bot.games.marvel_rivals_hero_docs import (
    HERO_ACTIONS,
    get_hero_actions,
    resolve_hero_name,
)


NOISY_EFFECT_FIELDS = (
    "cooldown",
    "damage",
    "range",
    "radius",
    "energy cost",
    "ability duration",
    "interval",
    "speed",
    "max distance",
    "health",
)


def _compact_effect(effect: str) -> str:
    """Keep ability meaning, drop stat-heavy details that burn prompt tokens."""
    if "(" not in effect:
        return effect[:120]

    flavor, details = effect.split("(", 1)
    kept: list[str] = []
    for item in details.rstrip(")").split(";"):
        item = item.strip()
        if not item:
            continue
        head = item.split(":", 1)[0].strip().lower()
        if any(field in head for field in NOISY_EFFECT_FIELDS):
            continue
        item = (
            item.replace("Casting: ", "")
            .replace("Special Effect: ", "")
            .replace("Ability Duration: ", "")
        )
        kept.append(item)
        if len(kept) == 2:
            break

    compact = "; ".join(kept) or flavor.strip()
    return compact[:120]


def format_hero_kit_reference_en(
    hero: str,
    *,
    include_team_ups: bool = True,
) -> str:
    """Render one hero's kit as compact prompt facts."""
    official_name = resolve_hero_name(hero)
    data = HERO_ACTIONS.get(official_name)
    if not data:
        return f"{hero}: kit unavailable."

    role = (
        data["role"]
        if official_name == hero
        else f"{hero}; official={official_name}"
    )
    lines = [f"{hero}({role})"]
    for action in get_hero_actions(hero):
        if action["kind"] == "team_up" and not include_team_ups:
            continue
        kind = action["kind"].replace("_", " ")
        lines.append(
            "{button}|{name}|{kind}|vis:{visual}|does:{effect}".format(
                button=action["button"],
                name=action["name"],
                kind=kind,
                visual=action["visual"],
                effect=_compact_effect(action["effect"]),
            )
        )
    return "\n".join(lines)
