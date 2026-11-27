"""The gate: runs a room's steps in order, cutting budget before each step
and stopping at approval gates.

The runner is the only caller of a room's steps. A step never runs without
its cost estimate being reserved first (BudgetGuard.check, which spends
nothing — the step's own charges remain the exact enforcement), and after
a human-gate step the run stops: export is a separate call that requires
human approval (see core/approval.py). A step that returns False stops the
run (e.g. a QA step with blocking issues).
"""

from __future__ import annotations

from .contract import ProjectRoom


class Runner:
    def run(self, room: ProjectRoom, session, episode, guard) -> str:
        """Run the room's steps. Returns 'done', 'stopped', or 'awaiting_approval'."""
        for spec in room.steps():
            guard.check(spec.cost_estimate(session, episode), f"step {spec.name}")
            result = spec.run(session, episode, guard)
            if result is False:
                return "stopped"
            if spec.human_gate:
                return "awaiting_approval"
        return "done"
