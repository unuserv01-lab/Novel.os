"""Orchestrator: the 8-step episode workflow as a resumable state machine.

story input -> script -> storyboard -> narrative QA -> panel render + QC (+bounded regeneration)
-> assembly -> FINAL APPROVAL (human) -> export.
Every step is recorded in production_jobs; re-running `produce` skips finished work, so a crash, a
budget stop or a failed panel never throws away panels that already passed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from novelos.agents import artist, director, reviewer, writer
from novelos.config import Settings
from novelos.db import (Character, Episode, GeneratedAsset, Location, Panel, ProductionJob, Project, QCReport,
                        StoryBible, session_scope)
from novelos.engine import characters as chars
from novelos.engine import publishing
from novelos.engine.budget import BudgetExceeded, BudgetGuard
from novelos.engine.composition import compose
from novelos.engine.storage import Storage
from novelos.models.adapters import ProviderError
from novelos.models.schemas import DialogLine


class StateError(RuntimeError):
    pass


@dataclass
class Pipeline:
    factory: object  # sessionmaker
    settings: Settings
    text: object
    image: object
    storage: Storage

    # ------------------------------------------------------------------ helpers
    def _job(self, s: Session, ep: Episode, step: str, status: str, detail: str = "", cost: float = 0.0, t0: float | None = None):
        s.add(ProductionJob(episode_id=ep.id, step=step, status=status, detail=detail[:2000], cost=cost,
                            seconds=round(time.time() - t0, 3) if t0 else 0.0))
        s.flush()

    def _spent(self, s: Session, ep: Episode) -> float:
        return float(s.scalar(select(func.coalesce(func.sum(ProductionJob.cost), 0.0)).where(ProductionJob.episode_id == ep.id)))

    def _cast(self, s: Session, project_id: int) -> dict[str, Character]:
        return {c.code: c for c in s.scalars(select(Character).where(Character.project_id == project_id).order_by(Character.id))}

    # ------------------------------------------------------------------ episodes
    def create_episode(self, project_slug: str, premise: str) -> int:
        with session_scope(self.factory) as s:
            p = s.scalar(select(Project).where(Project.slug == project_slug))
            if p is None:
                raise StateError(f"unknown project '{project_slug}'")
            n = (s.scalar(select(func.max(Episode.number)).where(Episode.project_id == p.id)) or 0) + 1
            ep = Episode(project_id=p.id, number=n, premise=premise.strip())
            s.add(ep)
            s.flush()
            return ep.id

    def produce(self, episode_id: int) -> dict:
        t_start = time.time()
        with session_scope(self.factory) as s:
            ep = s.get(Episode, episode_id)
            if ep is None:
                raise StateError("unknown episode")
            if ep.status in ("approved", "exported"):
                raise StateError(f"episode is {ep.status}; edits must go through recompose, not produce")
            guard = BudgetGuard(self.settings.max_cost_per_episode, self._spent(s, ep))
            try:
                self._step_script(s, ep, guard)
                self._step_storyboard(s, ep, guard)
                if not self._step_narrative_qa(s, ep):
                    return self._summary(s, ep, t_start)
                self._step_render(s, ep, guard)
                if all(p.status == "passed" for p in ep.panels):
                    self._step_assemble(s, ep)
                else:
                    ep.status = "needs_attention"
            except BudgetExceeded as e:
                ep.status = "paused_budget"
                self._job(s, ep, "budget", "failed", str(e))
            except ProviderError as e:
                ep.status = "needs_attention"
                self._job(s, ep, "provider", "failed", str(e))
            return self._summary(s, ep, t_start)

    # ------------------------------------------------------------------ steps
    def _step_script(self, s: Session, ep: Episode, guard: BudgetGuard) -> None:
        if ep.script is not None:
            return
        t0 = time.time()
        project = s.get(Project, ep.project_id)
        bible = s.scalar(select(StoryBible).where(StoryBible.project_id == project.id))
        cast = list(self._cast(s, project.id).values())
        locs = list(s.scalars(select(Location).where(Location.project_id == project.id).order_by(Location.id)))
        guard.charge(self.settings.est_cost_text, "script generation")
        script = writer.write_script(
            self.text, ep.premise,
            {"genre": project.genre, "lore": bible.lore if bible else "", "rules": bible.world_rules if bible else [],
             "timeline": bible.timeline if bible else [], "style": bible.style if bible else ""},
            [{"code": c.code, "name": c.name, "identity": c.identity, "state": c.state} for c in cast],
            [{"code": x.code, "name": x.name, "description": x.description} for x in locs],
        )
        ep.script = script.model_dump()
        idx = 0
        for sc_no, scene in enumerate(script.scenes, 1):
            for sp in scene.panels:
                s.add(Panel(episode_id=ep.id, index=idx, scene_no=sc_no,
                            spec={k: v for k, v in sp.model_dump().items() if k != "dialog"},
                            dialog=[d.model_dump() for d in sp.dialog]))
                idx += 1
        s.flush()
        s.refresh(ep)
        ep.status = "scripted"
        self._job(s, ep, "script", "ok", f"{idx} panels", self.settings.est_cost_text, t0)

    def _step_storyboard(self, s: Session, ep: Episode, guard: BudgetGuard) -> None:
        if all(p.layout for p in ep.panels):
            return
        t0 = time.time()
        guard.charge(self.settings.est_cost_text, "storyboard")
        sb, note = director.plan(self.text, [p.spec for p in ep.panels])
        for p, lay in zip(ep.panels, sb.layouts):
            p.layout = lay.model_dump()
        ep.status = "storyboarded"
        self._job(s, ep, "storyboard", "ok", note, self.settings.est_cost_text, t0)

    def _step_narrative_qa(self, s: Session, ep: Episode) -> bool:
        names = {c.code: c.name for c in self._cast(s, ep.project_id).values()}
        issues = reviewer.narrative_issues(ep.panels, names)
        self._job(s, ep, "narrative_qa", "failed" if issues else "ok", "; ".join(issues))
        if issues:
            ep.status = "needs_attention"  # fail before any image is paid for
        return not issues

    def _step_render(self, s: Session, ep: Episode, guard: BudgetGuard) -> None:
        project = s.get(Project, ep.project_id)
        bible = s.scalar(select(StoryBible).where(StoryBible.project_id == project.id))
        style = bible.style if bible else ""
        cast_all = self._cast(s, project.id)
        locs = {x.code: x for x in s.scalars(select(Location).where(Location.project_id == project.id).order_by(Location.id))}
        prev_png: bytes | None = None
        for panel in ep.panels:
            if panel.status == "passed" and panel.current_asset_id:
                prev_png = self.storage.read(s.get(GeneratedAsset, panel.current_asset_id).path)
                continue
            t0, spent_before = time.time(), guard.spent
            cast = [cast_all[c] for c in panel.spec.get("characters", []) if c in cast_all]
            size = artist.panel_size(panel)
            notes: list[str] = []
            passed = False
            for attempt in range(1 + self.settings.max_regen_per_panel):
                prompt = artist.build_prompt(style, panel, cast, locs.get(panel.spec["location"]), notes)
                try:
                    guard.charge(self.settings.est_cost_image, f"render panel {panel.index + 1}")
                    png, ref_paths = artist.render(self.image, self.storage, prompt, cast, size)
                except ProviderError as e:
                    notes = [f"provider error: {str(e)[:160]}"]
                    continue
                version = (s.scalar(select(func.max(GeneratedAsset.version)).where(GeneratedAsset.panel_id == panel.id)) or 0) + 1
                rel = self.storage.write(f"panels/ep{ep.number:03d}/p{panel.index + 1:02d}_v{version}.png", png)
                asset = GeneratedAsset(panel_id=panel.id, version=version, path=rel, prompt=prompt,
                                       model=getattr(self.image, "name", "?"), references=ref_paths,
                                       cost=self.settings.est_cost_image)
                s.add(asset)
                s.flush()
                guard.charge(self.settings.est_cost_text, "model review")
                auto, model = reviewer.visual_review(self.image, png, size, prev_png, f"Spec: {panel.spec}")
                blocking_model = [m for m in model if not m.startswith("NOTE ")]
                s.add(QCReport(panel_id=panel.id, asset_id=asset.id, kind="automated", passed=not auto, issues=auto))
                if model:
                    s.add(QCReport(panel_id=panel.id, asset_id=asset.id, kind="model", passed=not blocking_model, issues=model))
                if not auto and not blocking_model:
                    panel.status, panel.current_asset_id, passed, prev_png = "passed", asset.id, True, png
                    break
                notes = auto + blocking_model
            if not passed:
                panel.status = "failed"
            self._job(s, ep, f"render_p{panel.index + 1}", "ok" if passed else "failed",
                      "; ".join(notes) if not passed else f"{attempt + 1} attempt(s)", guard.spent - spent_before, t0)
            s.flush()  # keep finished panels even if a later one raises BudgetExceeded
        ep.status = "rendered"

    def _compose(self, s: Session, ep: Episode):
        data = []
        for p in ep.panels:
            asset = s.get(GeneratedAsset, p.current_asset_id)
            data.append((self.storage.read(asset.path), p.dialog, p.layout.get("gap", 30)))
        return compose(data)

    def _step_assemble(self, s: Session, ep: Episode) -> None:
        t0 = time.time()
        comp = self._compose(s, ep)
        import io
        buf = io.BytesIO()
        comp.image.save(buf, "PNG")
        self.storage.write(f"previews/ep{ep.number:03d}.png", buf.getvalue())
        ep.status = "awaiting_approval"
        self._job(s, ep, "assemble", "ok", "; ".join(comp.warnings) or f"{comp.image.height}px tall", 0.0, t0)

    # ------------------------------------------------------------------ human gate, edits, export
    def edit_dialog(self, panel_id: int, dialog: list[dict]) -> None:
        """Editing text never regenerates art. It does cancel any approval: a human must look again."""
        clean = [DialogLine.model_validate(d).model_dump() for d in dialog]
        with session_scope(self.factory) as s:
            panel = s.get(Panel, panel_id)
            if panel is None:
                raise StateError("unknown panel")
            panel.dialog = clean
            ep = s.get(Episode, panel.episode_id)
            if ep.status in ("awaiting_approval", "approved", "exported"):
                ep.approved_at, ep.status = None, "rendered"
                s.flush()
                s.refresh(ep)
                self._step_assemble(s, ep)

    def approve(self, episode_id: int) -> None:
        from datetime import datetime, timezone
        with session_scope(self.factory) as s:
            ep = s.get(Episode, episode_id)
            if ep is None or ep.status != "awaiting_approval":
                raise StateError(f"only an episode awaiting approval can be approved (status: {ep.status if ep else 'missing'})")
            ep.status, ep.approved_at = "approved", datetime.now(timezone.utc)
            self._job(s, ep, "approval", "ok", "approved by human")

    def export(self, episode_id: int) -> dict:
        with session_scope(self.factory) as s:
            ep = s.get(Episode, episode_id)
            if ep is None or ep.status not in ("approved", "exported") or ep.approved_at is None:
                raise StateError("export requires human approval first (run approve)")
            comp = self._compose(s, ep)
            manifest = {
                "episode": ep.number, "title": (ep.script or {}).get("title"), "approved_at": ep.approved_at.isoformat(),
                "panels": [{"index": p.index + 1, "asset_id": p.current_asset_id, "dialog": p.dialog} for p in ep.panels],
                "cost_usd_estimated": self._spent(s, ep),
            }
            out = publishing.export(self.storage, ep.number, comp, manifest)
            ep.status = "exported"
            self._job(s, ep, "export", "ok", f"v{out['version']}")
            return out

    # ------------------------------------------------------------------ reporting
    def _summary(self, s: Session, ep: Episode, t_start: float) -> dict:
        panels = ep.panels
        reports = s.scalars(select(QCReport).join(Panel, Panel.id == QCReport.panel_id).where(Panel.episode_id == ep.id)).all()
        assets = s.scalars(select(GeneratedAsset).join(Panel, Panel.id == GeneratedAsset.panel_id).where(Panel.episode_id == ep.id)).all()
        passed = sum(p.status == "passed" for p in panels)
        first_try = sum(1 for p in panels if p.status == "passed" and sum(a.panel_id == p.id for a in assets) == 1)
        return {
            "episode_id": ep.id, "number": ep.number, "status": ep.status, "panels": len(panels), "passed": passed,
            "failed": sum(p.status == "failed" for p in panels),
            "first_attempt_pass_rate": round(first_try / len(panels), 3) if panels else None,
            "renders": len(assets), "qc_reports": len(reports),
            "estimated_cost_usd": round(self._spent(s, ep), 4), "seconds_this_run": round(time.time() - t_start, 2),
        }

    def status(self, episode_id: int) -> dict:
        with session_scope(self.factory) as s:
            ep = s.get(Episode, episode_id)
            if ep is None:
                raise StateError("unknown episode")
            return self._summary(s, ep, time.time())
