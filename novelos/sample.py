"""Load a project definition (JSON) into the database, with generated *placeholder* reference sheets."""

from __future__ import annotations

import io
import json
from pathlib import Path

from PIL import Image, ImageDraw
from sqlalchemy import select

from novelos.db import Location, Project, StoryBible, session_scope
from novelos.engine import characters as chars
from novelos.engine.storage import Storage
from novelos.models.adapters import _h, load_font


def placeholder_sheet(c) -> bytes:
    """A flat placeholder so the reference mechanism is exercised. Replace with real art via add-reference."""
    col = (_h(c.code) % 156 + 100, _h(c.code, 1) % 156 + 100, _h(c.code, 2) % 156 + 100)
    im = Image.new("RGB", (512, 512), col)
    d = ImageDraw.Draw(im)
    d.text((20, 20), f"PLACEHOLDER\n{c.name}\n" + "\n".join(f"{k}: {v}" for k, v in c.identity.items()), fill=(0, 0, 0), font=load_font(18))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def load_project(factory, storage: Storage, path: Path) -> str:
    spec = json.loads(Path(path).read_text(encoding="utf-8"))
    with session_scope(factory) as s:
        if s.scalar(select(Project).where(Project.slug == spec["slug"])):
            return spec["slug"]
        p = Project(slug=spec["slug"], name=spec["name"], genre=spec.get("genre", "fantasy"))
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
