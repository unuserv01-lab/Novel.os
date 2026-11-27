"""Langkah 3: project_type on Project + safe migration of old DBs."""

import pytest
from sqlalchemy import create_engine, inspect, select, text

from novelos import sample
from novelos.core.registry import available_keys, get_room
from novelos.db import Project, init_db, session_factory, session_scope


def test_new_project_defaults_to_manhwa(studio):
    with session_scope(studio.factory) as s:
        p = s.scalar(select(Project).where(Project.slug == "sample-manhwa"))
        assert p.project_type == "manhwa"


def test_migration_adds_column_to_old_db(tmp_path):
    """A DB created before langkah 3 (no project_type column) gains the
    column via init_db, keeps its rows, and reads them back as 'manhwa'."""
    db_path = tmp_path / "old.db"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE projects (id INTEGER PRIMARY KEY, slug VARCHAR(80) UNIQUE, "
            "name VARCHAR(200), genre VARCHAR(80), created_at DATETIME)"))
        conn.execute(text(
            "INSERT INTO projects (slug, name, genre, created_at) "
            "VALUES ('legacy', 'Legacy', 'fantasy', '2026-01-01 00:00:00')"))
    assert "project_type" not in {c["name"] for c in inspect(engine).get_columns("projects")}
    init_db(engine)  # create_all alone would NOT add the column; migration must
    assert "project_type" in {c["name"] for c in inspect(engine).get_columns("projects")}
    with session_scope(session_factory(engine)) as s:
        p = s.scalar(select(Project).where(Project.slug == "legacy"))
        assert p.project_type == "manhwa"
    # second init is a no-op (idempotent)
    init_db(engine)
    with session_scope(session_factory(engine)) as s:
        assert s.scalar(select(Project).where(Project.slug == "legacy")).project_type == "manhwa"


def test_unknown_project_type_rejected(make_studio):
    st = make_studio()
    with pytest.raises(ValueError):
        sample.ensure_project(st.factory, "x", "nope")
    assert "explainer" in available_keys() and "manhwa" in available_keys()


def test_explainer_room_registered_and_shaped(studio):
    room = get_room("explainer", studio)
    assert room.key == "explainer"
    assert [s.name for s in room.steps()] == ["script", "verify", "audio", "draw", "assemble"]
    assert room.steps()[-1].human_gate is True
    assert all(s.name != "assemble" for s in room.steps()[:-1] if s.human_gate)
    with pytest.raises(KeyError):
        get_room("nope", studio)


def test_ensure_project_type_mismatch_rejected(make_studio):
    st = make_studio()
    sample.ensure_project(st.factory, "p1", "explainer")
    with pytest.raises(ValueError):
        sample.ensure_project(st.factory, "p1", "manhwa")
    # same type again is fine (idempotent)
    assert sample.ensure_project(st.factory, "p1", "explainer") == "p1"
