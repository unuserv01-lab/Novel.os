import hashlib

import pytest
from sqlalchemy import select

from novelos.db import Episode, GeneratedAsset, Panel, session_scope
from novelos.pipeline import StateError
from tests.conftest import PREMISE


def episode(studio):
    return studio.create_episode("sample-manhwa", PREMISE)


def test_full_run_reaches_human_gate(studio):
    r = studio.produce(episode(studio))
    assert r["status"] == "awaiting_approval"
    assert 10 <= r["panels"] <= 15 and r["passed"] == r["panels"] and r["failed"] == 0
    assert studio.storage.exists("previews/ep001.png")


def test_export_is_refused_without_approval_and_works_after(studio):
    eid = episode(studio)
    studio.produce(eid)
    with pytest.raises(StateError):
        studio.export(eid)
    studio.approve(eid)
    out = studio.export(eid)
    assert studio.storage.exists(out["png"]) and studio.storage.exists(out["pdf"]) and studio.storage.exists(out["manifest"])
    assert studio.storage.read(out["pdf"]).startswith(b"%PDF")
    assert studio.export(eid)["version"] == 2  # exports are versioned, never overwritten


def test_cannot_approve_before_render(studio):
    with pytest.raises(StateError):
        studio.approve(episode(studio))


def test_regeneration_keeps_old_versions(make_studio):
    st = make_studio(fail_every=3)
    r = st.produce(episode(st))
    assert r["status"] == "awaiting_approval"
    assert r["renders"] > r["panels"]  # some panels were rendered again
    assert r["first_attempt_pass_rate"] < 1
    with session_scope(st.factory) as s:
        multi = [p for p in s.scalars(select(Panel)) if len(s.scalars(select(GeneratedAsset).where(GeneratedAsset.panel_id == p.id)).all()) > 1]
        assert multi
        for p in multi:
            for a in s.scalars(select(GeneratedAsset).where(GeneratedAsset.panel_id == p.id)):
                assert st.storage.exists(a.path)  # the bad version is still on disk
            assert p.current_asset_id == max(a.id for a in s.scalars(select(GeneratedAsset).where(GeneratedAsset.panel_id == p.id)))


def test_regeneration_is_bounded(make_studio, monkeypatch):
    st = make_studio(max_regen_per_panel=1)

    class AlwaysBlank:
        name = "blank"
        def generate(self, prompt, refs, size):
            from novelos.models.adapters import MockImage
            return MockImage._blank(size)
        def review(self, image, checklist):
            return None
    st.image = AlwaysBlank()
    r = st.produce(episode(st))
    assert r["status"] == "needs_attention" and r["passed"] == 0
    assert r["renders"] == r["panels"] * 2  # 1 try + 1 regeneration per panel, then it gives up


def test_budget_stop_then_resume_keeps_finished_panels(make_studio):
    st = make_studio(est_cost_image=0.10, est_cost_text=0.0, max_cost_per_episode=0.45)
    eid = episode(st)
    r1 = st.produce(eid)
    assert r1["status"] == "paused_budget" and r1["passed"] == 4 and r1["estimated_cost_usd"] <= 0.45
    object.__setattr__(st.settings, "max_cost_per_episode", 5.0)
    r2 = st.produce(eid)
    assert r2["status"] == "awaiting_approval"
    assert r2["renders"] == r2["panels"]  # the 4 finished panels were NOT rendered (or paid for) again


def test_dialog_edit_does_not_touch_art_and_cancels_approval(studio):
    eid = episode(studio)
    studio.produce(eid)
    studio.approve(eid)
    with session_scope(studio.factory) as s:
        p = s.scalars(select(Panel).where(Panel.episode_id == eid).order_by(Panel.index)).first()
        pid, path, n_assets = p.id, s.get(GeneratedAsset, p.current_asset_id).path, len(s.scalars(select(GeneratedAsset)).all())
    before = hashlib.sha256(studio.storage.read(path)).hexdigest()
    studio.edit_dialog(pid, [{"speaker": "", "text": "Teks baru.", "kind": "narration"}])
    assert hashlib.sha256(studio.storage.read(path)).hexdigest() == before  # stored art has no text baked in
    with session_scope(studio.factory) as s:
        assert len(s.scalars(select(GeneratedAsset)).all()) == n_assets  # nothing regenerated
        ep = s.get(Episode, eid)
        assert ep.status == "awaiting_approval" and ep.approved_at is None  # human must look again
    with pytest.raises(StateError):
        studio.export(eid)


def test_bad_script_fails_before_any_image_is_paid_for(studio):
    class BadWriter:
        name = "bad"
        def complete_json(self, task, system, user, payload):
            return {"title": "x", "scenes": [{"summary": "s", "panels": [{"characters": ["CHR_NOPE_999"], "location": "LOC_RUINED_KEEP", "description": "abc"}]}]}
    studio.text = BadWriter()
    r = studio.produce(episode(studio))
    assert r["status"] == "needs_attention" and r["renders"] == 0


def test_speaker_not_in_cast_is_caught_by_narrative_qa(studio):
    class Ghost:
        name = "ghost"
        def complete_json(self, task, system, user, payload):
            if task == "storyboard":
                return {"layouts": [{"height_ratio": 1, "gap": 10}]}
            return {"title": "x", "scenes": [{"summary": "s", "panels": [{"characters": ["CHR_KAEL_001"], "location": "LOC_RUINED_KEEP", "description": "abc",
                    "dialog": [{"speaker": "Hantu", "text": "Boo", "kind": "speech"}]}]}]}
    studio.text = Ghost()
    r = studio.produce(episode(studio))
    assert r["status"] == "needs_attention" and r["renders"] == 0
