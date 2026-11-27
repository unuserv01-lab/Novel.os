"""Manhwa room: the first project room (key 'manhwa').

Wraps the manhwa Pipeline behind the room contract. Steps are the
Pipeline's own step methods; the estimates return 0 for work that is
already finished, so a resumed run is never blocked by a step that would
charge nothing. Each estimate covers one more unit of work (one text call,
one TTS call, one render attempt) — the step's own guard charges remain
the exact enforcement, so a budget pause still lands exactly where the
old code paused it (same passed count, same spent total).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from novelos.core.contract import StepSpec

if TYPE_CHECKING:
    from novelos.rooms.manhwa.pipeline import Pipeline


def _audio_remaining(episode, settings) -> float:
    """Cost of one more TTS call, or 0 when no shot still needs audio."""
    for panel in episode.panels:
        layout = panel.layout or {}
        if layout.get("audio_path") and layout.get("duration_sec"):
            continue
        full_text = " ".join(ln["text"] for ln in panel.dialog if ln.get("kind") != "sfx").strip()
        if full_text:
            return getattr(settings, "est_cost_tts", 0.0)
    return 0.0


def _render_remaining(episode, settings) -> float:
    """Cost of one more render attempt, or 0 when every shot already passed."""
    for panel in episode.panels:
        if not (panel.status == "passed" and panel.current_asset_id):
            return settings.est_cost_image
    return 0.0


class ManhwaRoom:
    key = "manhwa"

    def __init__(self, pipeline: "Pipeline"):
        self.pipeline = pipeline

    def steps(self) -> list[StepSpec]:
        p = self.pipeline
        s = p.settings
        return [
            StepSpec(name="script", est_cost=s.est_cost_text,
                     estimate=lambda ses, ep: 0.0 if ep.script is not None else s.est_cost_text,
                     run=lambda ses, ep, g: p._step_script(ses, ep, g)),
            StepSpec(name="storyboard", est_cost=s.est_cost_text,
                     estimate=lambda ses, ep: 0.0 if all(q.layout for q in ep.panels) else s.est_cost_text,
                     run=lambda ses, ep, g: p._step_storyboard(ses, ep, g)),
            StepSpec(name="narrative_qa", est_cost=0.0,
                     run=lambda ses, ep, g: p._step_narrative_qa(ses, ep)),
            StepSpec(name="audio", est_cost=getattr(s, "est_cost_tts", 0.0),
                     estimate=lambda ses, ep: _audio_remaining(ep, s),
                     run=lambda ses, ep, g: p._step_audio(ses, ep, g)),
            StepSpec(name="render", est_cost=s.est_cost_image,
                     estimate=lambda ses, ep: _render_remaining(ep, s),
                     run=lambda ses, ep, g: self._run_render(ses, ep, g)),
            StepSpec(name="assemble", est_cost=0.0, human_gate=True,
                     run=lambda ses, ep, g: p._step_assemble(ses, ep)),
        ]

    def _run_render(self, session, episode, guard) -> bool:
        """Render, then report whether every shot passed (False stops the run)."""
        self.pipeline._step_render(session, episode, guard)
        return all(p.status == "passed" for p in episode.panels)

    def export(self, episode_id: int) -> dict:
        return self.pipeline.export(episode_id)


def create_room(pipeline: "Pipeline") -> ManhwaRoom:
    return ManhwaRoom(pipeline)
