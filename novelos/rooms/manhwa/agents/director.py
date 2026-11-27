"""Director Agent: script -> storyboard directions (camera motion, transitions, pacing)."""

from __future__ import annotations

from pydantic import ValidationError

from novelos.libs.models.adapters import ProviderError
from novelos.libs.models.schemas import ShotDirection, Storyboard

SYSTEM = (
    'You are the Director Agent of a narrated video studio. Return ONLY JSON '
    '{"directions": [{"motion": "zoom_in"|"zoom_out"|"pan_left"|"pan_right"|"static"|"ai_video", '
    '"transition": "cut"|"crossfade"|"fade_black", "min_duration_sec": 1.0-15.0, '
    '"subtitle_style": "bottom_box"|"word_highlight"|"none"}]} '
    "with exactly one entry per shot, in order. Use slow zoom_out for wide/establishing shots, "
    "zoom_in for close-ups and dramatic beats, pans for travelling shots; use crossfade for soft "
    "scene changes and fade_black for act breaks; keep min_duration_sec around 3 seconds unless a "
    "line clearly needs longer."
)


def default_direction(camera: str) -> ShotDirection:
    c = camera.lower()
    if "wide" in c or "establishing" in c:
        return ShotDirection(motion="zoom_out", transition="cut", min_duration_sec=3.0, subtitle_style="bottom_box")
    if "close" in c:
        return ShotDirection(motion="zoom_in", transition="cut", min_duration_sec=3.0, subtitle_style="bottom_box")
    return ShotDirection(motion="zoom_in", transition="cut", min_duration_sec=3.0, subtitle_style="bottom_box")


def plan(text, shots: list[dict]) -> tuple[Storyboard, str]:
    """Returns (storyboard, note). Falls back to deterministic directions if the model output is unusable."""
    payload = {"shots": [{"camera": p["camera"], "emotion": p["emotion"], "description": p["description"]} for p in shots]}
    try:
        sb = Storyboard.model_validate(text.complete_json("storyboard", SYSTEM, str(payload), payload))
        if len(sb.directions) == len(shots):
            return sb, "model directions"
        note = f"model returned {len(sb.directions)} directions for {len(shots)} shots"
    except (ValidationError, ProviderError) as e:
        note = f"model directions unusable: {str(e)[:120]}"
    return Storyboard(directions=[default_direction(p["camera"]) for p in shots]), "fallback directions (" + note + ")"
