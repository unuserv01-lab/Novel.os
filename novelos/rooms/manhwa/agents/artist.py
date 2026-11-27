"""Artist Agent: shot spec + character identity + references -> image prompt -> image frame."""

from __future__ import annotations

from novelos.db import Character, Location, Panel
from novelos.rooms.manhwa import characters as chars
from novelos.core.storage import Storage

# Video frame sizes (v2 pipeline passes the size explicitly; kept here for callers that need a default).
FRAME_16_9: tuple[int, int] = (1280, 720)
FRAME_9_16: tuple[int, int] = (720, 1280)


def panel_size(panel: Panel, aspect_ratio: str = "16:9") -> tuple[int, int]:
    """Frame size for a shot. The v2 pipeline computes this itself; kept for
    backward compatibility with callers that sized panels from the layout."""
    return FRAME_9_16 if aspect_ratio == "9:16" else FRAME_16_9


def build_prompt(style: str, panel: Panel, cast: list[Character], location: Location | None, notes: list[str]) -> str:
    spec = panel.spec
    parts = [
        f"Video frame for a narrated story video, full colour, cinematic. Style: {style}",
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
