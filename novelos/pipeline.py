"""Backward-compatible re-export: the Pipeline now lives in the manhwa room.

`novelos.pipeline` stays importable so the CLI, API, studio wiring and
tests keep working unchanged; new code should import from
`novelos.rooms.manhwa.pipeline` (or go through the room registry).
"""

from __future__ import annotations

from novelos.rooms.manhwa.pipeline import Pipeline, StateError

__all__ = ["Pipeline", "StateError"]
