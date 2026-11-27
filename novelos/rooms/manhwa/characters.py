"""Character Identity System: IDs, identity, outfits, current state and visual references.

A seed does not make a character consistent. Consistency comes from reference images sent with every
panel, a prompt block built from this record, and a QC pass over the result.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from novelos.db import Character, CharacterReference, Project
from novelos.core.storage import Storage, sha256


def create_character(s: Session, project: Project, code: str, name: str, identity: dict, outfits: dict | None = None,
                     expressions: list | None = None, state: dict | None = None) -> Character:
    c = Character(project_id=project.id, code=code, name=name, identity=identity, outfits=outfits or {},
                  expressions=expressions or [], state=state or {})
    s.add(c)
    s.flush()
    return c


def get_by_code(s: Session, project_id: int, code: str) -> Character | None:
    return s.scalar(select(Character).where(Character.project_id == project_id, Character.code == code))


def update_state(s: Session, c: Character, **patch) -> Character:
    """Merge state. Injuries are cumulative and only leave when explicitly healed."""
    state = dict(c.state or {})
    for k, v in patch.items():
        if k == "add_injury":
            state["injuries"] = sorted(set(state.get("injuries", [])) | {v})
        elif k == "heal_injury":
            state["injuries"] = [i for i in state.get("injuries", []) if i != v]
        else:
            state[k] = v
    c.state = state  # reassign so SQLAlchemy sees the JSON change
    s.flush()
    return c


def add_reference(s: Session, storage: Storage, c: Character, data: bytes, kind: str = "reference") -> CharacterReference:
    digest = sha256(data)
    rel = storage.write(f"references/{c.code}/{digest[:16]}.png", data)
    ref = CharacterReference(character_id=c.id, path=rel, sha256=digest, kind=kind)
    s.add(ref)
    s.flush()
    return ref


def reference_bytes(storage: Storage, c: Character, limit: int = 3) -> list[tuple[str, bytes]]:
    return [(r.path, storage.read(r.path)) for r in c.references[:limit] if storage.exists(r.path)]


def prompt_block(c: Character, outfit: str | None = None, emotion: str | None = None) -> str:
    ident = ", ".join(f"{k}: {v}" for k, v in c.identity.items())
    parts = [f"CHARACTER:{c.code} {c.name} — {ident}"]
    wear = c.outfits.get(outfit) if outfit else next(iter(c.outfits.values()), None)
    if wear:
        parts.append(f"outfit: {wear}")
    if emotion:
        parts.append(f"expression: {emotion}")
    st = c.state or {}
    if st.get("injuries"):
        parts.append("visible injuries that must persist: " + "; ".join(st["injuries"]))
    if st.get("timeline"):
        parts.append(f"story state: {st['timeline']}")
    return " | ".join(parts)
