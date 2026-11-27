"""Wiring: settings -> database, storage, adapters, pipeline."""

from __future__ import annotations

from novelos.config import Settings, load_settings
from novelos.db import init_db, make_engine, session_factory
from novelos.core.storage import Storage
from novelos.libs.models.adapters import make_image, make_text, make_tts
from novelos.pipeline import Pipeline


def build(settings: Settings | None = None) -> Pipeline:
    s = settings or load_settings()
    s.storage_dir.parent.mkdir(parents=True, exist_ok=True)
    engine = make_engine(s.database_url)
    init_db(engine)
    return Pipeline(session_factory(engine), s, make_text(s), make_image(s), make_tts(s), Storage(s.storage_dir))
