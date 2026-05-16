"""
Marvel Rivals plugin — video-based gameplay analysis.

User uploads an MP4 clip and selects a hero. The plugin builds a hero-specific
coaching prompt and runs the video + prompt through the shared GeminiService.
"""

from __future__ import annotations

import logging

from bot.games.base import (
    AnalysisResult,
    BaseGamePlugin,
    GameConfig,
    InputType,
)
from bot.services import container


logger = logging.getLogger(__name__)


HEROES: list[str] = [
    # Vanguards (14 — includes Devil Dinosaur added in Season 8 + Deadpool variant)
    "Angela",
    "Captain America",
    "Deadpool (Vanguard)",
    "Devil Dinosaur",
    "Doctor Strange",
    "Emma Frost",
    "Groot",
    "Hulk",
    "Magneto",
    "Peni Parker",
    "Rogue",
    "The Thing",
    "Thor",
    "Venom",
    # Duelists (26 — includes Deadpool (Duelist))
    "Black Cat",
    "Black Panther",
    "Black Widow",
    "Blade",
    "Daredevil",
    "Deadpool (Duelist)",
    "Elsa Bloodstone",
    "Hawkeye",
    "Hela",
    "Human Torch",
    "Iron Fist",
    "Iron Man",
    "Magik",
    "Mr. Fantastic",
    "Moon Knight",
    "Namor",
    "Phoenix",
    "Psylocke",
    "Scarlet Witch",
    "Spider-Man",
    "Squirrel Girl",
    "Star-Lord",
    "Storm",
    "The Punisher",
    "Winter Soldier",
    "Wolverine",
    # Strategists (12 — includes Deadpool (Strategist))
    "Adam Warlock",
    "Cloak & Dagger",
    "Deadpool (Strategist)",
    "Gambit",
    "Invisible Woman",
    "Jeff the Land Shark",
    "Loki",
    "Luna Snow",
    "Mantis",
    "Rocket Raccoon",
    "Ultron",
    "White Fox",
]


# Hero kit briefs injected into the Gemini prompt to anchor it on real facts
# and prevent confident hallucinations like inventing ultimate names.
#
# Only fill in entries you have verified — Gemini will fall back to its own
# (often incorrect) knowledge for heroes missing here. Better to leave a hero
# absent than to put wrong data in the brief.
#
# Format guidance: short bullet-style sentences. Mention role, primary +
# secondary attack, named abilities, ultimate, key passive. Avoid HP/CD
# numbers (they change often with patches).
HERO_BRIEFS: dict[str, str] = {
    "Deadpool (Duelist)": (
        "Role: Duelist (dive / off-tank brawler).\n"
        "Loadout: Twin Pistols (ranged, primary fire) AND dual Katanas "
        "(close-range melee, separate input). Switches weapons based on range.\n"
        "Mobility: short dash (LShift). Has 'Selfie' / Pose ability — brief "
        "self-heal + iframes used to escape or save low HP.\n"
        "Ultimate: katana spin/dash burst — very high damage in close range, "
        "weak at distance. NOT 'Good Morning Sunshine'.\n"
        "Passive: Healing Factor — regen out of combat.\n"
        "Playstyle: dive support / pick off low-HP backline, NOT a frontline tank."
    ),
    "Deadpool (Vanguard)": (
        "Role: Vanguard (frontline / tank variant).\n"
        "Heavier weapon focus on katanas for melee pressure and zone control. "
        "Healing Factor passive lets him soak damage and disengage.\n"
        "Has Selfie / Pose for self-heal + iframes; dash for repositioning.\n"
        "Playstyle: hold space, body-block, NOT a ranged duelist — he expects "
        "to be in melee taking damage."
    ),
    "Deadpool (Strategist)": (
        "Role: Strategist (support variant).\n"
        "Focuses on enabling allies — healing pose, utility from chimichangas "
        "or similar throwable item, peeling for backline.\n"
        "Still has pistols + katanas but used reactively, not as primary DPS.\n"
        "Playstyle: peel for allies, top up health with utility, NOT solo carry."
    ),
    "Devil Dinosaur": (
        "Role: Vanguard (released Season 8, May 2026).\n"
        "Frontline beast — bleeding bite attacks as primary, large hitbox, "
        "forcefield shield ability for damage mitigation.\n"
        "Ultimate transforms him into a larger, more aggressive form ('Behemoth' "
        "rampage style) with increased damage.\n"
        "Team-up: 'Primal Punishment' with The Punisher — Punisher can ride "
        "on his back.\n"
        "Playstyle: aggressive frontline brawler, dive enemy backline with bleed."
    ),
}


class MarvelRivalsPlugin(BaseGamePlugin):
    """Video clip → Gemini coaching analysis for a single hero."""

    @property
    def config(self) -> GameConfig:
        return GameConfig(
            id="marvel_rivals",
            display_name="Marvel Rivals",
            emoji="🦸",
            input_type=InputType.VIDEO,
            has_characters=True,
            characters=HEROES,
            max_video_mb=200,
            description="Upload a gameplay clip (MP4, max 200MB).",
        )

    def get_prompt(self, character: str | None) -> str:
        if character is None:
            raise ValueError("Marvel Rivals requires a character selection")

        brief = HERO_BRIEFS.get(character)
        brief_block = (
            f"\nHERO BRIEF (use these as facts — do NOT contradict them):\n"
            f"{brief}\n"
        ) if brief else ""

        return (
            "You are a professional Marvel Rivals coach analyzing a gameplay "
            f"clip from the player's first-person perspective.\n\n"
            f"The player selected: {character}\n"
            f"{brief_block}\n"
            "=== ANTI-HALLUCINATION RULES (read carefully) ===\n"
            "1. If you are NOT 100% sure which enemy hero is on screen, "
            "describe what you observe (e.g. 'a support hero with a white "
            "outfit and ice effects') instead of guessing a name. "
            "Many heroes look visually similar (Emma Frost vs Doctor Strange, "
            "Iron Man vs War Machine, etc.) — don't guess.\n"
            "2. NEVER invent ability or ultimate names. If the player's hero "
            "has a HERO BRIEF above, use ONLY ability names from it. If no "
            "brief is provided, use generic descriptions ('the dash', 'the "
            "ultimate', 'the self-heal') rather than fabricating names.\n"
            "3. Distinguish the player's hero from enemy heroes — the "
            "player's HUD (health bar, ability icons at the bottom) belongs "
            "to the player, not to enemies they're looking at.\n"
            "4. If you cannot tell what happened at a moment, say 'unclear "
            "moment' rather than fabricate a narrative.\n"
            "5. Pay attention to the ACTUAL target the player is shooting "
            "at, not who appears nearby. Crosshair placement and damage "
            "numbers (if visible) tell the truth.\n"
            "6. NEVER invent HP percentages, exact damage numbers, or "
            "cooldown timers if they are not clearly visible on screen. "
            "Many clips are REPLAYS where a playback control bar covers the "
            "bottom HUD — in that case the player's HP/ability icons are "
            "hidden. Use qualitative terms instead ('low HP', 'mid HP', "
            "'critically low', 'full HP', 'just used ultimate') rather than "
            "fabricated percentages like '60% → 80%'.\n\n"
            "=== ANALYSIS METHOD (follow this order) ===\n"
            "Step 1: First, fill the KEY EVENTS section — list every "
            "observable event in chronological order. ONLY facts you see, "
            "no judgment yet. Each entry: timestamp + what happened.\n"
            "Step 2: Then, base your MISTAKES and STRENGTHS sections "
            "STRICTLY on the events you listed in step 1. Do NOT introduce "
            "new events in those sections.\n"
            "Step 3: All sections MUST be mutually consistent. If KEY "
            "EVENTS shows the player used Selfie at 00:09, do NOT claim in "
            "MISTAKES that the player 'failed to use Selfie'.\n\n"
            "=== RESPOND IN THIS EXACT FORMAT ===\n\n"
            f"🎯 HERO: {character}\n"
            "⏱ CLIP DURATION: [X min Y sec]\n\n"
            "📋 KEY EVENTS (chronological, facts only — no judgment):\n"
            "- [MM:SS] [What happened — e.g., 'engaged enemy at mid-range "
            "with pistols', 'used Selfie/Pose', 'switched to katanas', "
            "'killed an enemy', 'took heavy damage', 'died']\n"
            "- [MM:SS] [next event]\n"
            "- ...continue until the end of the clip\n\n"
            "❌ TOP 3 MISTAKES (must reference events from KEY EVENTS above):\n"
            "1. [MM:SS] — [What happened] → [What to do instead]\n"
            "2. [MM:SS] — [What happened] → [What to do instead]\n"
            "3. [MM:SS] — [What happened] → [What to do instead]\n\n"
            "✅ WHAT YOU DID WELL (must reference events from KEY EVENTS above):\n"
            "1. [MM:SS] — [Specific moment]\n"
            "2. [MM:SS] — [Specific moment]\n\n"
            "💡 MAIN RECOMMENDATION:\n"
            "[One concrete tip — 2-3 sentences]\n\n"
            "📊 DECISION QUALITY: [X/10]\n\n"
            "=== STYLE RULES ===\n"
            "- TIMESTAMPS: use MM:SS format ONLY. Examples: '00:05', "
            "'00:23', '01:14'. DO NOT use HH:MM:SS like '00:00:05' — clips "
            "are short and seconds-relative-to-start is enough.\n"
            "- Reference abilities by names from HERO BRIEF (or use generic "
            "descriptions if no brief).\n"
            "- Use numbers ONLY when clearly visible (visible kill count, "
            "visible damage popup). For HP and cooldowns prefer qualitative "
            "terms unless the HUD is unambiguously readable.\n"
            "- Avoid vague phrases like 'play better' or 'position well'.\n"
            "- If uncertain about an event, prefix with 'Likely:' or "
            "'Possibly:' rather than stating it as fact."
        )

    async def analyze(
        self,
        user_input: str | bytes,
        character: str | None,
        user_id: int,
    ) -> AnalysisResult:
        if not isinstance(user_input, (bytes, bytearray)):
            raise TypeError(
                f"Marvel Rivals plugin expects video bytes, got {type(user_input).__name__}"
            )
        self.validate_character(character)
        assert character is not None  # validate_character ensures this

        prompt = self.get_prompt(character)
        gemini = container.get_gemini()

        logger.info(
            "marvel_rivals_analyze_start user_id=%d hero=%s size=%d",
            user_id,
            character,
            len(user_input),
        )
        out = await gemini.analyze_video(bytes(user_input), prompt)
        logger.info(
            "marvel_rivals_analyze_done user_id=%d hero=%s tokens=%d seconds=%.2f",
            user_id,
            character,
            out.tokens_used,
            out.processing_seconds,
        )

        return AnalysisResult(
            game_id=self.config.id,
            character=character,
            raw_text=out.raw_text,
            tokens_used=out.tokens_used,
            processing_seconds=out.processing_seconds,
            source="gemini",
        )
