"""Enforce the rooms dependency rules (one import test, per the design):

- rooms may use core and libs (and the shared db/config modules);
- core never imports rooms (it loads them lazily through the registry);
- rooms never import each other;
- libs never import rooms (tools are leaves).

Only static imports are checked: the registry's lazy importlib load is the
sanctioned way core reaches a room, so the string in _LOADERS is fine.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent / "novelos"


def _novelos_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    targets = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("novelos"):
            targets.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("novelos"):
                    targets.add(alias.name)
    return targets


def _zone(path: Path) -> tuple[str, str | None]:
    """('core', None) | ('libs', None) | ('rooms', name) | ('top', None)."""
    rel = path.relative_to(ROOT)
    if rel.parts[0] == "core":
        return "core", None
    if rel.parts[0] == "libs":
        return "libs", None
    if rel.parts[0] == "rooms":
        return "rooms", rel.parts[1]
    return "top", None


def _is_rooms_import(target: str) -> bool:
    return target == "novelos.rooms" or target.startswith("novelos.rooms.")


def test_dependency_direction():
    violations = []
    for path in sorted(ROOT.rglob("*.py")):
        zone, room = _zone(path)
        for target in sorted(_novelos_imports(path)):
            if zone in ("core", "libs") and _is_rooms_import(target):
                violations.append(f"{path}: {zone} must not import rooms ({target})")
            elif zone == "rooms":
                if _is_rooms_import(target) and not target.startswith(f"novelos.rooms.{room}"):
                    violations.append(f"{path}: room '{room}' must not import another room ({target})")
                if target == "novelos.pipeline":
                    violations.append(f"{path}: room '{room}' must not import the top-level pipeline shim")
    assert not violations, "\n".join(violations)
