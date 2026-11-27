"""Explainer room: "Satu Soal, Tiga Cara" (key 'explainer').

One maths problem, three solution methods, stickman frames + narration
assembled into a vertical 9:16 mp4. Steps run through the core Runner, so
the budget pre-check and the human gate apply exactly as they do for
manhwa; the maths is verified twice (writer + verify step) before any
frame is drawn, and a failed verification stops the run (Runner returns
'stopped' -> episode goes to needs_attention, no video is produced).

State lives in the shared Episode/Panel tables, one Panel per scene:
spec = scene dict, dialog = [narration line], layout = audio metadata.
"""

from __future__ import annotations

import time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from novelos.core import approval
from novelos.core.budget import BudgetGuard
from novelos.core.contract import StepSpec
from novelos.core.errors import StateError
from novelos.core.manifest import build_manifest
from novelos.db import Episode, GeneratedAsset, Panel, ProductionJob, session_scope

from . import assemble, writer
from .math_verify import verify_script
from .schema import ExplainerScene, ExplainerScript
from .stickman_draw import draw_scene


class ExplainerRoom:
    key = "explainer"

    def __init__(self, engine):
        # `engine` is the studio Pipeline: it already carries factory,
        # settings, text/tts adapters and storage. The room borrows them;
        # it does not import the manhwa room (not even for typing — the
        # dependency rule counts TYPE_CHECKING imports too).
        self.engine = engine

    # ------------------------------------------------------------------ steps
    def steps(self) -> list[StepSpec]:
        s = self.engine.settings
        tts_cost = getattr(s, "est_cost_tts", 0.0)
        return [
            StepSpec(name="script", est_cost=s.est_cost_text,
                     estimate=lambda ses, ep: 0.0 if ep.script is not None else s.est_cost_text,
                     run=lambda ses, ep, g: self._step_script(ses, ep, g)),
            StepSpec(name="verify", est_cost=0.0,
                     run=lambda ses, ep, g: self._step_verify(ses, ep)),
            StepSpec(name="audio", est_cost=tts_cost,
                     estimate=lambda ses, ep: self._audio_remaining(ep, tts_cost),
                     run=lambda ses, ep, g: self._step_audio(ses, ep, g)),
            StepSpec(name="draw", est_cost=0.0,
                     run=lambda ses, ep, g: self._step_draw(ses, ep)),
            StepSpec(name="assemble", est_cost=0.0, human_gate=True,
                     run=lambda ses, ep, g: self._step_assemble(ses, ep)),
        ]

    # ------------------------------------------------------------------ helpers
    def _job(self, s: Session, ep: Episode, step: str, status: str, detail: str = "",
             cost: float = 0.0, t0: float | None = None):
        s.add(ProductionJob(episode_id=ep.id, step=step, status=status, detail=detail[:2000],
                            cost=cost, seconds=round(time.time() - t0, 3) if t0 else 0.0))
        s.flush()

    def _spent(self, s: Session, ep: Episode) -> float:
        return float(s.scalar(select(func.coalesce(func.sum(ProductionJob.cost), 0.0))
                              .where(ProductionJob.episode_id == ep.id)))

    @staticmethod
    def _audio_remaining(ep: Episode, tts_cost: float) -> float:
        for p in ep.panels:
            layout = p.layout or {}
            if layout.get("audio_path") and layout.get("duration_sec"):
                continue
            if any(ln.get("text") for ln in p.dialog):
                return tts_cost
        return 0.0

    # ------------------------------------------------------------------ step impls
    def _step_script(self, s: Session, ep: Episode, guard: BudgetGuard) -> None:
        if ep.script is not None:
            return
        t0 = time.time()
        guard.charge(self.engine.settings.est_cost_text, "explainer script")
        script = writer.write_script(self.engine.text, ep.premise)
        ep.script = script.model_dump()
        for idx, scene in enumerate(script.scenes):
            s.add(Panel(episode_id=ep.id, index=idx, scene_no=idx + 1,
                        spec=scene.model_dump(),
                        dialog=[{"speaker": "narrator", "text": scene.narration, "kind": "narration"}]))
        s.flush()
        s.refresh(ep)
        ep.status = "scripted"
        self._job(s, ep, "script", "ok", f"{len(script.scenes)} scenes, 3 methods",
                  self.engine.settings.est_cost_text, t0)

    def _step_verify(self, s: Session, ep: Episode) -> bool:
        """Re-derive every method from the stored script; False stops the run."""
        t0 = time.time()
        try:
            script = ExplainerScript.model_validate(ep.script or {})
            issues = verify_script(script)
        except Exception as e:  # malformed stored script counts as failed verification
            issues = [f"invalid stored script: {e}"]
        self._job(s, ep, "math_verify", "failed" if issues else "ok", "; ".join(issues)[:2000], 0.0, t0)
        if issues:
            ep.status = "needs_attention"
        return not issues

    def _step_audio(self, s: Session, ep: Episode, guard: BudgetGuard) -> None:
        t0 = time.time()
        est_cost_tts = getattr(self.engine.settings, "est_cost_tts", 0.0)
        made = 0
        for panel in ep.panels:
            layout = dict(panel.layout or {})
            if layout.get("audio_path") and layout.get("duration_sec"):
                continue
            text = " ".join(ln.get("text", "") for ln in panel.dialog).strip()
            if not text:
                layout["audio_path"] = None
                layout["duration_sec"] = 3.0
                panel.layout = layout
                continue
            guard.charge(est_cost_tts, f"tts scene {panel.index + 1}")
            audio_bytes, duration = self.engine.tts.synthesize(text)
            rel = self.engine.storage.write(f"audio/ep{ep.number:03d}/s{panel.index + 1:03d}.mp3", audio_bytes)
            layout["audio_path"] = rel
            layout["duration_sec"] = max(round(duration, 2), 2.0)
            panel.layout = layout
            made += 1
            s.flush()
        if made:
            ep.status = "voiced"
            self._job(s, ep, "audio_tts", "ok", f"{made} scenes voiced", made * est_cost_tts, t0)

    def _step_draw(self, s: Session, ep: Episode) -> None:
        t0 = time.time()
        for panel in ep.panels:
            if panel.status == "passed" and panel.current_asset_id:
                continue
            scene = ExplainerScene.model_validate(panel.spec)
            png = draw_scene(scene)
            version = (s.scalar(select(func.max(GeneratedAsset.version))
                                .where(GeneratedAsset.panel_id == panel.id)) or 0) + 1
            rel = self.engine.storage.write(f"frames/ep{ep.number:03d}/s{panel.index + 1:03d}_v{version}.png", png)
            asset = GeneratedAsset(panel_id=panel.id, version=version, path=rel,
                                   prompt=f"{scene.title}: " + " | ".join(scene.board),
                                   model="stickman-draw", references=[], cost=0.0)
            s.add(asset)
            s.flush()
            panel.status, panel.current_asset_id = "passed", asset.id
            self._job(s, ep, f"draw_s{panel.index + 1}", "ok", f"{len(png)} bytes", 0.0, t0)
            s.flush()
        ep.status = "rendered"

    def _step_assemble(self, s: Session, ep: Episode) -> None:
        t0 = time.time()
        comp = assemble.assemble_preview(self.engine.storage, s, ep)
        ep.status = "awaiting_approval"
        self._job(s, ep, "assemble", "ok",
                  "; ".join(comp.warnings) or f"{comp.total_duration_sec:.1f}s MP4", 0.0, t0)

    # ------------------------------------------------------------------ export
    def export(self, episode_id: int) -> dict:
        with session_scope(self.engine.factory) as s:
            ep = s.get(Episode, episode_id)
            if ep is None:
                raise StateError("unknown episode")
            try:
                approval.check_exportable(ep)
            except approval.ApprovalError as e:
                raise StateError(str(e)) from e
            comp = assemble.assemble_preview(self.engine.storage, s, ep)
            manifest = build_manifest(ep, comp.total_duration_sec, self._spent(s, ep))
            out = assemble.export_episode(self.engine.storage, ep.number, comp, manifest)
            ep.status = "exported"
            self._job(s, ep, "export", "ok", f"v{out['version']}")
            return out


def create_room(pipeline) -> ExplainerRoom:
    return ExplainerRoom(pipeline)
