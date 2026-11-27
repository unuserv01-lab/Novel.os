"""Manhwa room engine: the 9-step video episode workflow as a resumable state machine.

story input -> script -> storyboard -> narrative QA -> TTS audio -> visual render + QC
-> video assembly (FFmpeg) -> FINAL APPROVAL (human) -> export.

The steps run through the room contract (rooms/manhwa/room.py) and the
core Runner, which cuts the budget before each step and stops at the
approval gate. The step implementations below are unchanged from the old
novelos/pipeline.py; only produce()/approve()/export() delegate to core.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from novelos.core import approval
from novelos.core.budget import BudgetExceeded, BudgetGuard
from novelos.core.errors import StateError  # noqa: F401  (re-exported: novelos.pipeline imports it from here)
from novelos.core.manifest import build_manifest
from novelos.core.registry import get_room
from novelos.core.runner import Runner
from novelos.rooms.manhwa.agents import artist, director, reviewer, writer
from novelos.config import Settings
from novelos.db import (Character, Episode, GeneratedAsset, Location, Panel, ProductionJob, Project, QCReport,
                        StoryBible, session_scope)
from novelos.rooms.manhwa import publishing
from novelos.libs.media.video import ShotClip, compose_video
from novelos.core.storage import Storage
from novelos.libs.models.adapters import ProviderError
from novelos.libs.models.schemas import NarrationLine


@dataclass
class Pipeline:
    factory: object  # sessionmaker
    settings: Settings
    text: object
    image: object
    tts: object      # adapter baru untuk Text-to-Speech (misal EdgeTTS / ElevenLabs)
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

    def _project_type(self, s: Session, ep: Episode) -> str:
        """Room key for this episode's project ('manhwa' for legacy rows)."""
        project = s.get(Project, ep.project_id)
        return (project.project_type if project else None) or "manhwa"

    def produce(self, episode_id: int) -> dict:
        t_start = time.time()
        with session_scope(self.factory) as s:
            ep = s.get(Episode, episode_id)
            if ep is None:
                raise StateError("unknown episode")
            if ep.status in ("approved", "exported"):
                raise StateError(f"episode is {ep.status}; edits must go through edit_narration, not produce")
            guard = BudgetGuard(self.settings.max_cost_per_episode, self._spent(s, ep))
            room = get_room(self._project_type(s, ep), self)
            try:
                outcome = Runner().run(room, s, ep, guard)
                if outcome == "stopped" and ep.status != "awaiting_approval":
                    # A step refused to continue (e.g. render QC failed, or the
                    # explainer's math verification rejected the script).
                    ep.status = "needs_attention"
            except BudgetExceeded as e:
                ep.status = "paused_budget"
                self._job(s, ep, "budget", "failed", str(e))
            except (ProviderError, ValueError) as e:
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
            for shot in scene.shots:
                # Tabel Panel dipakai ulang sebagai representasi Shot
                s.add(Panel(episode_id=ep.id, index=idx, scene_no=sc_no,
                            spec={k: v for k, v in shot.model_dump().items() if k != "lines"},
                            dialog=[ln.model_dump() for ln in shot.lines]))
                idx += 1
        s.flush()
        s.refresh(ep)
        ep.status = "scripted"
        self._job(s, ep, "script", "ok", f"{idx} shots", self.settings.est_cost_text, t0)

    def _step_storyboard(self, s: Session, ep: Episode, guard: BudgetGuard) -> None:
        if all(p.layout for p in ep.panels):
            return
        t0 = time.time()
        guard.charge(self.settings.est_cost_text, "storyboard")
        sb, note = director.plan(self.text, [p.spec for p in ep.panels])
        for p, direction in zip(ep.panels, sb.directions):
            p.layout = direction.model_dump()
        ep.status = "storyboarded"
        self._job(s, ep, "storyboard", "ok", note, self.settings.est_cost_text, t0)

    def _step_narrative_qa(self, s: Session, ep: Episode) -> bool:
        names = {c.code: c.name for c in self._cast(s, ep.project_id).values()}
        issues = reviewer.narrative_issues(ep.panels, names)
        self._job(s, ep, "narrative_qa", "failed" if issues else "ok", "; ".join(issues))
        if issues:
            ep.status = "needs_attention"
        return not issues

    def _step_audio(self, s: Session, ep: Episode, guard: BudgetGuard) -> None:
        """Generate TTS audio per shot dan simpan metadata path + durasinya di panel.layout."""
        t0 = time.time()
        cast_all = self._cast(s, ep.project_id)
        generated_count = 0
        est_cost_tts = getattr(self.settings, "est_cost_tts", 0.0)

        for panel in ep.panels:
            layout = dict(panel.layout or {})
            if layout.get("audio_path") and layout.get("duration_sec"):
                continue  # skip jika audio shot ini sudah pernah dibuat

            full_text = " ".join(ln["text"] for ln in panel.dialog if ln.get("kind") != "sfx").strip()
            if not full_text:
                layout["audio_path"] = None
                layout["duration_sec"] = layout.get("min_duration_sec", 3.0)
                panel.layout = layout
                continue

            # Ambil voice_id karakter utama di shot tersebut, atau fallback ke default narrator
            primary_speaker = panel.dialog[0].get("speaker", "narrator")
            voice_id = None
            if primary_speaker in cast_all:
                voice_id = (cast_all[primary_speaker].state or {}).get("voice_id")

            guard.charge(est_cost_tts, f"tts shot {panel.index + 1}")
            wav_bytes, duration_sec = self.tts.synthesize(full_text, voice_id=voice_id)
            rel_audio = self.storage.write(f"audio/ep{ep.number:03d}/s{panel.index + 1:03d}.mp3", wav_bytes)

            layout["audio_path"] = rel_audio
            layout["duration_sec"] = max(round(duration_sec, 2), layout.get("min_duration_sec", 1.5))
            panel.layout = layout
            generated_count += 1
            s.flush()

        if generated_count:
            ep.status = "voiced"
            self._job(s, ep, "audio_tts", "ok", f"{generated_count} shots voiced", generated_count * est_cost_tts, t0)

    def _step_render(self, s: Session, ep: Episode, guard: BudgetGuard) -> None:
        project = s.get(Project, ep.project_id)
        bible = s.scalar(select(StoryBible).where(StoryBible.project_id == project.id))
        style = bible.style if bible else ""
        cast_all = self._cast(s, project.id)
        locs = {x.code: x for x in s.scalars(select(Location).where(Location.project_id == project.id).order_by(Location.id))}
        aspect = (ep.script or {}).get("aspect_ratio", "16:9")
        prev_png: bytes | None = None

        for panel in ep.panels:
            if panel.status == "passed" and panel.current_asset_id:
                prev_png = self.storage.read(s.get(GeneratedAsset, panel.current_asset_id).path)
                continue
            t0, spent_before = time.time(), guard.spent
            cast = [cast_all[c] for c in panel.spec.get("characters", []) if c in cast_all]
            size = (1280, 720) if aspect == "16:9" else (720, 1280)
            notes: list[str] = []
            passed = False

            for attempt in range(1 + self.settings.max_regen_per_panel):
                prompt = artist.build_prompt(style, panel, cast, locs.get(panel.spec["location"]), notes)
                try:
                    guard.charge(self.settings.est_cost_image, f"render shot {panel.index + 1}")
                    png, ref_paths = artist.render(self.image, self.storage, prompt, cast, size)
                except ProviderError as e:
                    notes = [f"provider error: {str(e)[:160]}"]
                    continue
                version = (s.scalar(select(func.max(GeneratedAsset.version)).where(GeneratedAsset.panel_id == panel.id)) or 0) + 1
                rel = self.storage.write(f"shots/ep{ep.number:03d}/s{panel.index + 1:03d}_v{version}.png", png)
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
            self._job(s, ep, f"render_s{panel.index + 1}", "ok" if passed else "failed",
                      "; ".join(notes) if not passed else f"{attempt + 1} attempt(s)", guard.spent - spent_before, t0)
            s.flush()
        ep.status = "rendered"

    def _compose(self, s: Session, ep: Episode):
        aspect = (ep.script or {}).get("aspect_ratio", "16:9")
        clips: list[ShotClip] = []
        for p in ep.panels:
            asset = s.get(GeneratedAsset, p.current_asset_id)
            layout = p.layout or {}
            audio_rel = layout.get("audio_path")
            clips.append(ShotClip(
                image_path=self.storage.full_path(asset.path),
                audio_path=self.storage.full_path(audio_rel) if audio_rel else None,
                duration_sec=layout.get("duration_sec", 3.0),
                motion=layout.get("motion", "zoom_in"),
                transition=layout.get("transition", "cut"),
                subtitles=[ln["text"] for ln in p.dialog if ln.get("kind") != "sfx"],
                subtitle_style=layout.get("subtitle_style", "bottom_box"),
            ))
        out_rel = f"previews/ep{ep.number:03d}.mp4"
        return compose_video(clips, self.storage.full_path(out_rel), aspect_ratio=aspect)

    def _step_assemble(self, s: Session, ep: Episode) -> None:
        t0 = time.time()
        comp = self._compose(s, ep)
        ep.status = "awaiting_approval"
        self._job(s, ep, "assemble", "ok", "; ".join(comp.warnings) or f"{comp.total_duration_sec:.1f}s MP4", 0.0, t0)

    # ------------------------------------------------------------------ human gate, edits, export
    def edit_narration(self, panel_id: int, lines: list[dict]) -> None:
        """Edit narasi/dialog hanya merender ulang TTS shot terkait + recompose MP4, tanpa render ulang gambar."""
        clean = [NarrationLine.model_validate(d).model_dump() for d in lines]
        with session_scope(self.factory) as s:
            panel = s.get(Panel, panel_id)
            if panel is None:
                raise StateError("unknown shot")
            ep = s.get(Episode, panel.episode_id)
            if self._project_type(s, ep) != "manhwa":
                raise StateError("edit_narration is only for manhwa episodes")
            panel.dialog = clean
            layout = dict(panel.layout or {})
            layout.pop("audio_path", None)  # paksa regenerasi TTS hanya untuk shot ini
            layout.pop("duration_sec", None)
            panel.layout = layout

            # _step_audio sets ep.status = "voiced" when it generates audio, so
            # remember the pre-edit state BEFORE calling it, or the re-assemble
            # below would never trigger on an approved episode.
            was_past_gate = ep.status in ("awaiting_approval", "approved", "exported")
            guard = BudgetGuard(self.settings.max_cost_per_episode, self._spent(s, ep))
            self._step_audio(s, ep, guard)

            if was_past_gate:
                ep.approved_at, ep.status = None, "rendered"
                s.flush()
                self._step_assemble(s, ep)

    def approve(self, episode_id: int) -> None:
        with session_scope(self.factory) as s:
            ep = s.get(Episode, episode_id)
            try:
                approval.check_approvable(ep)
            except approval.ApprovalError as e:
                raise StateError(str(e)) from e
            approval.mark_approved(ep)
            self._job(s, ep, "approval", "ok", "approved by human")

    def export(self, episode_id: int) -> dict:
        # Non-manhwa rooms own their export; resolve the room first so the
        # manhwa export path below never touches another room's episode.
        with session_scope(self.factory) as s:
            ep = s.get(Episode, episode_id)
            if ep is None:
                raise StateError("unknown episode")
            ptype = self._project_type(s, ep)
        if ptype != "manhwa":
            return get_room(ptype, self).export(episode_id)
        with session_scope(self.factory) as s:
            ep = s.get(Episode, episode_id)
            try:
                approval.check_exportable(ep)
            except approval.ApprovalError as e:
                raise StateError(str(e)) from e
            comp = self._compose(s, ep)
            manifest = build_manifest(ep, comp.total_duration_sec, self._spent(s, ep))
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
            "episode_id": ep.id, "number": ep.number, "status": ep.status, "shots": len(panels), "passed": passed,
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
