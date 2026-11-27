import pytest
from fastapi.testclient import TestClient

from novelos import api
from tests.conftest import PREMISE


@pytest.fixture
def client(studio, monkeypatch):
    monkeypatch.setattr(api, "_studio", studio)
    monkeypatch.setenv("NOVELOS_API_TOKEN", "t0ken")
    return TestClient(api.app)


H = {"X-Token": "t0ken"}


def test_requires_token(client):
    assert client.post("/episodes", json={"premise": "x"}).status_code == 401
    assert client.post("/episodes", json={"premise": "x"}, headers={"X-Token": "wrong"}).status_code == 401


def test_full_flow_over_http(client):
    eid = client.post("/episodes", json={"premise": PREMISE}, headers=H).json()["episode_id"]
    assert client.post(f"/episodes/{eid}/produce", headers=H).json()["status"] == "awaiting_approval"
    assert client.post(f"/episodes/{eid}/export", headers=H).status_code == 409  # gate holds over HTTP too
    assert client.post(f"/episodes/{eid}/approve", headers=H).status_code == 200
    assert client.post(f"/episodes/{eid}/export", headers=H).json()["version"] == 1
    panels = client.get(f"/episodes/{eid}/panels", headers=H).json()
    r = client.put(f"/shots/{panels[0]['id']}/narration", json=[{"text": "x" * 500, "kind": "dialogue"}], headers=H)
    assert r.status_code == 422  # invalid narration (over 400 chars) is rejected, not stored
