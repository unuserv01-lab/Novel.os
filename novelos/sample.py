"""Load a project definition (JSON) into the database, with generated *placeholder* reference sheets."""

from __future__ import annotations

import io
import json
from pathlib import Path

from PIL import Image, ImageDraw
from sqlalchemy import select

from novelos.core.registry import available_keys
from novelos.db import Location, Project, StoryBible, session_scope
from novelos.rooms.manhwa import characters as chars
from novelos.core.storage import Storage
from novelos.libs.models.adapters import _h, load_font


def placeholder_sheet(c) -> bytes:
    """A flat placeholder so the reference mechanism is exercised. Replace with real art via add-reference."""
    col = (_h(c.code) % 156 + 100, _h(c.code, 1) % 156 + 100, _h(c.code, 2) % 156 + 100)
    im = Image.new("RGB", (512, 512), col)
    d = ImageDraw.Draw(im)
    d.text((20, 20), f"PLACEHOLDER\n{c.name}\n" + "\n".join(f"{k}: {v}" for k, v in c.identity.items()), fill=(0, 0, 0), font=load_font(18))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def load_project(factory, storage: Storage, path: Path, project_type: str | None = None) -> str:
    spec = json.loads(Path(path).read_text(encoding="utf-8"))
    ptype = project_type or spec.get("project_type", "manhwa")
    if ptype not in available_keys():
        raise ValueError(f"unknown project type '{ptype}' (known: {', '.join(available_keys())})")
    with session_scope(factory) as s:
        existing = s.scalar(select(Project).where(Project.slug == spec["slug"]))
        if existing is not None:
            if (existing.project_type or "manhwa") != ptype:
                raise ValueError(
                    f"project '{spec['slug']}' already exists as type "
                    f"'{existing.project_type or 'manhwa'}', not '{ptype}'"
                )
            return spec["slug"]
        p = Project(slug=spec["slug"], name=spec["name"], genre=spec.get("genre", "fantasy"),
                    project_type=ptype)
        s.add(p)
        s.flush()
        b = spec["bible"]
        s.add(StoryBible(project_id=p.id, lore=b["lore"], world_rules=b["world_rules"], timeline=b["timeline"], style=b["style"]))
        for loc in spec["locations"]:
            s.add(Location(project_id=p.id, **loc))
        for ch in spec["characters"]:
            c = chars.create_character(s, p, ch["code"], ch["name"], ch["identity"], ch.get("outfits"), ch.get("expressions"), ch.get("state"))
            chars.add_reference(s, storage, c, placeholder_sheet(c), kind="placeholder")
    return spec["slug"]


def ensure_project(factory, slug: str, project_type: str = "manhwa", name: str | None = None,
                   genre: str | None = None) -> str:
    """Create a bare project row if missing (no bible/cast); return its slug.

    Used by CLI/API when an episode is created for a project that does not
    exist yet. If the project already exists its type must match, otherwise
    ValueError — a project never silently changes rooms.
    """
    if project_type not in available_keys():
        raise ValueError(f"unknown project type '{project_type}' (known: {', '.join(available_keys())})")
    with session_scope(factory) as s:
        existing = s.scalar(select(Project).where(Project.slug == slug))
        if existing is not None:
            if (existing.project_type or "manhwa") != project_type:
                raise ValueError(
                    f"project '{slug}' already exists as type "
                    f"'{existing.project_type or 'manhwa'}', not '{project_type}'"
                )
            return slug
        s.add(Project(slug=slug, name=name or slug,
                      genre=genre or ("education" if project_type == "explainer" else "fantasy"),
                      project_type=project_type))
    return slug
