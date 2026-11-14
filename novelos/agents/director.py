"""Director Agent: script -> storyboard layout (panel proportions and pacing gaps)."""

from __future__ import annotations

from pydantic import ValidationError

from novelos.models.adapters import ProviderError
from novelos.models.schemas import Layout, Storyboard

SYSTEM = (
    'You are the Director Agent. Return ONLY JSON {"layouts": [{"height_ratio": 0.4-1.8, "gap": 0-240}]} '
    "with exactly one entry per panel, in order. Wide shots are short, close-ups and dramatic beats taller; "
    "use bigger gaps for pauses and smaller gaps inside action."
)


def default_layout(camera: str) -> Layout:
    c = camera.lower()
    if "wide" in c or "establishing" in c:
        return Layout(height_ratio=0.7, gap=40)
    if "close" in c:
        return Layout(height_ratio=1.1, gap=20)
    return Layout(height_ratio=0.9, gap=30)


def plan(text, panels: list[dict]) -> tuple[Storyboard, str]:
    """Returns (storyboard, note). Falls back to deterministic layout if the model output is unusable."""
    payload = {"panels": [{"camera": p["camera"], "emotion": p["emotion"], "description": p["description"]} for p in panels]}
    try:
        sb = Storyboard.model_validate(text.complete_json("storyboard", SYSTEM, str(payload), payload))
        if len(sb.layouts) == len(panels):
            return sb, "model layout"
        note = f"model returned {len(sb.layouts)} layouts for {len(panels)} panels"
    except (ValidationError, ProviderError) as e:
        note = f"model layout unusable: {str(e)[:120]}"
    return Storyboard(layouts=[default_layout(p["camera"]) for p in panels]), "fallback layout (" + note + ")"
