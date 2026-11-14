"""Artist Agent: panel spec + character identity + references -> image prompt -> image."""

from __future__ import annotations

from novelos.db import Character, Location, Panel
from novelos.engine import characters as chars
from novelos.engine.composition import WIDTH
from novelos.engine.storage import Storage


def panel_size(panel: Panel) -> tuple[int, int]:
    return WIDTH, round(WIDTH * panel.layout.get("height_ratio", 0.9))


def build_prompt(style: str, panel: Panel, cast: list[Character], location: Location | None, notes: list[str]) -> str:
    spec = panel.spec
    parts = [
        f"Vertical-scroll manhwa panel, full colour. Style: {style}",
        f"Scene: {spec['description']}",
        f"Camera: {spec['camera']}. Mood: {spec['emotion']}.",
    ]
    if location:
        parts.append(f"Location {location.code}: {location.name}. {location.description}")
    parts += [chars.prompt_block(c, emotion=spec["emotion"]) for c in cast]
    parts.append("Keep each character's face, hair, eye colour and body proportions identical to the attached reference images.")
    parts.append("Do NOT draw any text, speech bubbles, captions or sound effects in the image.")
    if notes:
        parts.append("REVISION — fix these problems from the previous attempt: " + "; ".join(notes))
    return "\n".join(parts)


def render(image, storage: Storage, prompt: str, cast: list[Character], size: tuple[int, int]) -> tuple[bytes, list[str]]:
    refs = [pair for c in cast for pair in chars.reference_bytes(storage, c)]
    png = image.generate(prompt, [b for _, b in refs], size)
    return png, [p for p, _ in refs]
