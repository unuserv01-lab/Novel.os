"""Registry of project rooms.

Core loads rooms by key, lazily, so core never statically imports a room
(enforced by tests/core/test_import_rules.py). Add a room by adding one
line to _LOADERS; nothing else in core changes.
"""

from __future__ import annotations

import importlib

_LOADERS = {
    "manhwa": "novelos.rooms.manhwa.room",
    "explainer": "novelos.rooms.explainer.room",
}


def available_keys() -> list[str]:
    return sorted(_LOADERS)


def get_room(key: str, pipeline):
    """Instantiate the room for `key`, bound to an already-built pipeline.

    `pipeline` is the room's engine (today: the manhwa Pipeline); the room
    wraps it behind the contract.
    """
    module_path = _LOADERS.get(key)
    if module_path is None:
        raise KeyError(f"unknown project type '{key}' (known: {', '.join(available_keys())})")
    module = importlib.import_module(module_path)
    return module.create_room(pipeline)
