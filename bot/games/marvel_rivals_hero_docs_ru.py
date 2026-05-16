"""Compact Russian hero-kit descriptions for Marvel Rivals prompts."""

from __future__ import annotations

from bot.games.marvel_rivals_hero_docs import (
    HERO_ACTIONS,
    get_hero_actions,
    resolve_hero_name,
)


KIND_RU: dict[str, str] = {
    "normal_attack": "атака",
    "ability": "скилл",
    "ultimate": "ульт",
    "passive": "пассивка",
    "team_up": "team-up",
}

VIS_RU: dict[str, str] = {
    "a straight beam or energy line": "луч/энерголиния",
    "projectile, bullet, or weapon-fire VFX": "снаряды/пули/стрельба",
    "a visible shield, guard, or barrier": "щит/блок/барьер",
    "a portal, rift, or dimensional doorway": "портал/разлом",
    "a sudden movement burst, dash, leap, or pounce": "рывок/прыжок",
    "a close melee swing or hit animation": "ближний удар",
    "healing light, revive VFX, or ally recovery effects": "хил/рес/восстановление",
    "a persistent area, aura, or ground field": "зона/аура/поле",
    "a summoned/deployed object or companion": "призыв/поставленный объект",
    "the hero fading, cloaking, or becoming hard to see": "инвиз/маскировка",
    "flight or hovering movement": "полет/зависание",
    "web strands, spider-tech, or cyber-web effects": "паутина/spider-tech",
    "ice, snow, or freezing VFX": "лед/снег/заморозка",
    "fire, flame, or explosive heat VFX": "огонь/взрыв",
    "lightning, wind, or storm VFX": "молния/ветер/шторм",
    "cosmic, soul, or gold energy VFX": "космос/души/золото",
    "dark, shadow, lunar, or abyssal VFX": "тень/луна/тьма",
    "passive self-healing status; infer from health recovery": "пассивный реген",
    "large Q/ultimate animation; verify by the named VFX and fight impact": "крупная Q-анимация",
    "named ability animation; verify by button timing, hero pose, and effect": "анимация скилла",
    "passive effect; infer from status changes rather than a single cast": "пассивный эффект",
}

ROLE_RU: dict[str, str] = {
    "Vanguard": "авангард",
    "Duelist": "дуэлянт",
    "Strategist": "стратег",
    "Multi-Role": "мульти-роль",
}


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


def _vis(visual: str) -> str:
    if visual.startswith("major Q/ultimate animation with "):
        cue = visual.removeprefix("major Q/ultimate animation with ")
        return "крупная Q-анимация+" + VIS_RU.get(cue, cue)
    return VIS_RU.get(visual, visual)


def _effect(effect: str) -> str:
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


def format_hero_kit_reference_ru(
    hero: str,
    *,
    include_team_ups: bool = True,
) -> str:
    """Render one hero's kit as compact Russian prompt facts."""
    official_name = resolve_hero_name(hero)
    data = HERO_ACTIONS.get(official_name)
    if not data:
        return f"{hero}: кит недоступен."

    role = (
        ROLE_RU.get(data["role"], data["role"])
        if official_name == hero
        else f"{hero}; офиц={official_name}"
    )
    lines = [f"{hero}({role})"]
    for action in get_hero_actions(hero):
        if action["kind"] == "team_up" and not include_team_ups:
            continue
        lines.append(
            "{button}|{name}|{kind}|вид:{visual}|делает:{effect}".format(
                button=action["button"],
                name=action["name"],
                kind=KIND_RU.get(action["kind"], action["kind"].replace("_", " ")),
                visual=_vis(action["visual"]),
                # Official effect summaries stay in English to preserve exact facts.
                effect=_effect(action["effect"]),
            )
        )
    return "\n".join(lines)
