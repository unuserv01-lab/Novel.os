"""Explainer room end-to-end: produce -> approve -> export via the studio,
plus the CLI/API wiring for project_type."""

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from novelos import sample
from novelos.db import Episode, Panel, session_scope
from novelos.pipeline import StateError

EXPLAINER_JSON = Path(__file__).resolve().parent.parent.parent.parent / "projects" / "sample-explainer" / "project.json"


@pytest.fixture
def explainer_studio(make_studio):
    st = make_studio()
    sample.ensure_project(st.factory, "sample-explainer", "explainer")
    return st


def test_full_run_reaches_human_gate(explainer_studio):
    st = explainer_studio
    eid = st.create_episode("sample-explainer", "SPLDV bagi permen")
    r = st.produce(eid)
    assert r["status"] == "awaiting_approval"
    assert r["shots"] == 6 and r["passed"] == 6 and r["failed"] == 0
    assert r["first_attempt_pass_rate"] == 1.0
    assert st.storage.exists("previews/ep001.mp4")
    assert st.storage.read("previews/ep001.mp4")[4:8] == b"ftyp"
    with session_scope(st.factory) as s:
        ep = s.get(Episode, eid)
        assert ep.script["solution"] == {"x": 3, "y": 2}
        assert [p.spec["kind"] for p in ep.panels] == [
            "hook", "soal", "substitusi", "eliminasi", "matriks", "kesimpulan"]


def test_export_refused_without_approval_and_works_after(explainer_studio):
    st = explainer_studio
    eid = st.create_episode("sample-explainer", "SPLDV bagi permen")
    st.produce(eid)
    with pytest.raises(StateError):
        st.export(eid)
    st.approve(eid)
    out = st.export(eid)
    assert st.storage.exists(out["video"]) and st.storage.exists(out["srt"]) and st.storage.exists(out["manifest"])
    assert st.storage.read(out["video"])[4:8] == b"ftyp"
    assert out["total_duration_sec"] > 0
    manifest = json.loads(st.storage.read(out["manifest"]))
    assert manifest["episode"] == 1 and manifest["total_duration_sec"] > 0
    assert st.export(eid)["version"] == 2  # versioned, never overwritten


def test_bad_maths_stops_before_any_frame(explainer_studio):
    """A provider script with wrong maths -> needs_attention, no mp4, no frames."""
    from novelos.rooms.explainer import writer as expl_writer

    st = explainer_studio

    class BadMath:
        name = "bad-math"

        def complete_json(self, task, system, user, payload):
            import copy
            d = copy.deepcopy(expl_writer.default_script().model_dump())
            d["methods"][0]["steps"][2]["equation"] = {"x": 0, "y": 2, "const": 5}
            return d

    st.text = BadMath()
    eid = st.create_episode("sample-explainer", "SPLDV bagi permen")
    r = st.produce(eid)
    assert r["status"] == "needs_attention" and r["passed"] == 0
    assert not st.storage.exists("previews/ep001.mp4")


def test_manhwa_and_explainer_coexist(make_studio):
    """Same studio, two projects, two rooms — manhwa behaviour unchanged."""
    st = make_studio()
    sample.ensure_project(st.factory, "sample-explainer", "explainer")
    eid_m = st.create_episode("sample-manhwa", "Kael terbangun tiga tahun sebelum Benteng Reruntuhan jatuh")
    eid_e = st.create_episode("sample-explainer", "SPLDV bagi permen")
    assert st.produce(eid_m)["status"] == "awaiting_approval"
    assert st.produce(eid_e)["status"] == "awaiting_approval"


def test_cli_init_type_and_projects(tmp_path, monkeypatch):
    from novelos import cli

    monkeypatch.setenv("NOVELOS_HOME", str(tmp_path))
    assert cli.main(["init", "--project-file", str(EXPLAINER_JSON), "--type", "explainer"]) == 0
    assert cli.main(["projects"]) == 0
    assert cli.main(["new", "SPLDV bagi permen", "--project", "sample-explainer"]) == 0
    # --type mismatch on an existing project must fail, not silently switch rooms
    assert cli.main(["init", "--project-file", str(EXPLAINER_JSON), "--type", "manhwa"]) == 1


def test_api_projects_and_explainer_episode(explainer_studio, monkeypatch):
    from fastapi.testclient import TestClient

    from novelos import api

    monkeypatch.setattr(api, "_studio", explainer_studio)
    monkeypatch.setenv("NOVELOS_API_TOKEN", "t0ken")
    c = TestClient(api.app)
    h = {"X-Token": "t0ken"}
    r = c.post("/projects", json={"slug": "mat-2", "project_type": "explainer"}, headers=h)
    assert r.status_code == 200 and r.json()["project_type"] == "explainer"
    r = c.get("/projects", headers=h)
    types = {p["slug"]: p["project_type"] for p in r.json()}
    assert types["sample-explainer"] == "explainer" and types["sample-manhwa"] == "manhwa"
    r = c.post("/episodes", json={"project": "mat-2", "premise": "SPLDV"}, headers=h)
    assert r.status_code == 200 and r.json()["episode_id"] == 1
    # unknown type rejected, not stored
    assert c.post("/projects", json={"slug": "bad", "project_type": "nope"}, headers=h).status_code == 422
