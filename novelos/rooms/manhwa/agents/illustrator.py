"""B-2-style scene illustrator for NovelOS v1.

Takes a panel (script scene) + a style config and produces one specific
illustration prompt for the image generator (Gemini / Pollinations / Flow).

Style config mirrors the B-2 Illustrator tool Tuan showed (23 Nov 23:10):
- mode: light | dark
- accent_color: e.g. Orange
- character_mode: profession | ancient

The prompt itself reuses artist.build_prompt (scene + camera + mood +
location + character identity blocks + no-text rule) and adds the style
config + per-scene palette on top. Palette per scene is derived from the
location (see PALETTES); a caller may override it per panel.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from novelos.rooms.manhwa.agents import artist
from novelos.db import Character, Location, Panel

# Per-location palette (derived from location description + mood).
# The v1/v2 pipeline has no per-scene palette field yet; this map is the
# illustrator's own table, overrideable per call.
PALETTES: dict[str, str] = {
    "LOC_RUINED_KEEP": "cold black stone, grey-blue, thin white fog, crimson accent on Kael's eyes",
    "LOC_CRIMSON_FOREST": "blood-red leaves, dusk orange light, deep violet shadows",
}


@dataclass
class StyleConfig:
    mode: str = "dark"  # light | dark
    accent_color: str = "Orange"
    character_mode: str = "ancient"  # profession | ancient
    palette_overrides: dict[str, str] = field(default_factory=dict)

    def palette_for(self, location_code: str) -> str:
        return self.palette_overrides.get(location_code) or PALETTES.get(
            location_code, "(style global)"
        )


MODE_LINES = {
    "dark": "Lighting: dark mode — deep shadows, moody low-key lighting, dark background.",
    "light": "Lighting: light mode — bright, airy, high-key lighting, light background.",
}

CHARACTER_MODE_LINES = {
    "ancient": "Character mode: ancient — period/fantasy attire, classical proportions, timeless setting.",
    "profession": "Character mode: profession — modern professional attire, contemporary setting.",
}


def illustration_prompt(
    style: str,
    panel: Panel,
    cast: list[Character],
    location: Location | None,
    config: StyleConfig,
    notes: list[str] | None = None,
) -> str:
    """One B-2-style illustration prompt for a single panel."""
    base = artist.build_prompt(style, panel, cast, location, notes or [])
    spec = panel.spec or {}
    loc_code = spec.get("location", "")
    extras = [
        MODE_LINES.get(config.mode, MODE_LINES["dark"]),
        f"Accent colour: {config.accent_color} — use it for key highlights and focal details.",
        CHARACTER_MODE_LINES.get(
            config.character_mode, CHARACTER_MODE_LINES["ancient"]
        ),
        f"Palette: {config.palette_for(loc_code)}.",
    ]
    return base + "\n" + "\n".join(extras)
