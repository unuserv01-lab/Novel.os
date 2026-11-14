from dataclasses import replace
from pathlib import Path

import pytest

from novelos import sample
from novelos.config import load_settings
from novelos.studio import build

SAMPLE = Path(__file__).resolve().parent.parent / "projects" / "sample-manhwa" / "project.json"
PREMISE = "Kael terbangun tiga tahun sebelum Benteng Reruntuhan jatuh dan harus mencegah pengkhianatan Vorn"


@pytest.fixture
def make_studio(tmp_path, monkeypatch):
    def _make(**overrides):
        monkeypatch.setenv("NOVELOS_MOCK_FAIL_EVERY", str(overrides.pop("fail_every", 0)))
        s = replace(load_settings({"NOVELOS_HOME": str(tmp_path)}), **overrides)
        studio = build(s)
        sample.load_project(studio.factory, studio.storage, SAMPLE)
        return studio
    return _make


@pytest.fixture
def studio(make_studio):
    return make_studio()
