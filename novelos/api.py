"""FastAPI surface. Binds to localhost by default; set NOVELOS_API_TOKEN to require `X-Token`.
Do NOT expose this to the internet as-is: there are no user accounts."""

from __future__ import annotations

import hmac
import os

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from novelos import sample
from novelos.db import Character, Episode, Panel, Project, session_scope
from novelos.libs.models.adapters import ProviderError
from novelos.pipeline import StateError
from novelos.studio import build

app = FastAPI(title="Novel.os", version="0.1.0")
_studio = None


def studio():
    global _studio
    if _studio is None:
        _studio = build()
    return _studio


def auth(x_token: str | None = Header(default=None)):
    want = os.environ.get("NOVELOS_API_TOKEN")
    if want and not (x_token and hmac.compare_digest(x_token, want)):
        raise HTTPException(401, "bad token")


class NewEpisode(BaseModel):
    project: str = "sample-manhwa"
    premise: str
    project_type: str | None = None  # only used when the project does not exist yet


class NewProject(BaseModel):
    slug: str
    name: str | None = None
    genre: str | None = None
    project_type: str = "manhwa"


def _wrap(fn):
    try:
        return fn()
    except StateError as e:
        raise HTTPException(409, str(e)) from None
    except (ProviderError, ValueError) as e:
        raise HTTPException(422, str(e)) from None


@app.get("/projects", dependencies=[Depends(auth)])
def list_projects():
    with session_scope(studio().factory) as s:
        rows = s.scalars(select(Project).order_by(Project.id)).all()
        return [{"slug": p.slug, "name": p.name, "genre": p.genre,
                 "project_type": p.project_type or "manhwa"} for p in rows]


@app.post("/projects", dependencies=[Depends(auth)])
def new_project(b: NewProject):
    _wrap(lambda: sample.ensure_project(studio().factory, b.slug, b.project_type, b.name, b.genre))
    return {"project": b.slug, "project_type": b.project_type}


@app.post("/episodes", dependencies=[Depends(auth)])
def new_episode(b: NewEpisode):
    def _create():
        if b.project_type is not None:
            sample.ensure_project(studio().factory, b.project, b.project_type)
        return studio().create_episode(b.project, b.premise)
    return {"episode_id": _wrap(_create)}


@app.post("/episodes/{eid}/produce", dependencies=[Depends(auth)])
def produce(eid: int):
    return _wrap(lambda: studio().produce(eid))


@app.get("/episodes/{eid}", dependencies=[Depends(auth)])
def status(eid: int):
    return _wrap(lambda: studio().status(eid))


@app.post("/episodes/{eid}/approve", dependencies=[Depends(auth)])
def approve(eid: int):
    _wrap(lambda: studio().approve(eid))
    return {"approved": eid}


@app.post("/episodes/{eid}/export", dependencies=[Depends(auth)])
def export(eid: int):
    return _wrap(lambda: studio().export(eid))


@app.put("/shots/{pid}/narration", dependencies=[Depends(auth)])
def edit_narration(pid: int, lines: list[dict]):
    _wrap(lambda: studio().edit_narration(pid, lines))
    return {"updated_panel": pid, "approval_reset": True}


@app.put("/panels/{pid}/dialog", dependencies=[Depends(auth)])
def edit_dialog(pid: int, dialog: list[dict]):
    """Deprecated alias of /shots/{pid}/narration (v1 route, same behaviour)."""
    _wrap(lambda: studio().edit_narration(pid, dialog))
    return {"updated_panel": pid, "approval_reset": True}


@app.get("/episodes/{eid}/panels", dependencies=[Depends(auth)])
def panels(eid: int):
    with session_scope(studio().factory) as s:
        rows = s.scalars(select(Panel).where(Panel.episode_id == eid).order_by(Panel.index)).all()
        return [{"id": p.id, "index": p.index + 1, "status": p.status, "spec": p.spec, "dialog": p.dialog} for p in rows]


@app.get("/projects/{slug}/characters", dependencies=[Depends(auth)])
def characters(slug: str):
    from novelos.db import Project
    with session_scope(studio().factory) as s:
        p = s.scalar(select(Project).where(Project.slug == slug))
        if not p:
            raise HTTPException(404, "unknown project")
        return [{"code": c.code, "name": c.name, "identity": c.identity, "state": c.state,
                 "references": [{"path": r.path, "kind": r.kind} for r in c.references]}
                for c in s.scalars(select(Character).where(Character.project_id == p.id))]
