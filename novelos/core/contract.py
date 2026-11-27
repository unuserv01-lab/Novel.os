"""Project room contract: the small interface every room must provide.

A room is one project type (manhwa, explainer, ...). It declares its steps
with a cost estimate and a human-gate flag, and it knows how to export a
finished episode. The runner (core/runner.py) drives the steps; the room
never runs a step on its own, so it cannot bypass the budget cut or the
approval gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol


@dataclass
class StepSpec:
    """One step of a room's pipeline.

    `run(session, episode, guard)` does the work; returning False stops the
    run (e.g. a QA step that found blocking issues). `estimate(session,
    episode)` is the cost the runner reserves BEFORE the step runs — it must
    return 0 when the step has nothing left to do, so a resumed run is never
    blocked by work that is already finished. When `estimate` is None the
    fixed `est_cost` is used.
    """

    name: str
    run: Callable
    est_cost: float = 0.0
    human_gate: bool = False
    estimate: Callable | None = None

    def cost_estimate(self, session, episode) -> float:
        if self.estimate is not None:
            return self.estimate(session, episode)
        return self.est_cost


class ProjectRoom(Protocol):
    """Interface every room implements (structural: no inheritance needed)."""

    key: str

    def steps(self) -> list[StepSpec]:
        """Ordered steps of this room's pipeline."""
        ...

    def export(self, episode_id: int) -> dict:
        """Export a human-approved episode; returns the export record."""
        ...
