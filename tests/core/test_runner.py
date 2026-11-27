"""Runner + registry behaviour (fast unit tests, no pipeline run)."""

import pytest

from novelos.core.budget import BudgetExceeded, BudgetGuard
from novelos.core.contract import StepSpec
from novelos.core.registry import available_keys, get_room
from novelos.core.runner import Runner


class FakeRoom:
    key = "fake"

    def __init__(self, specs):
        self._specs = specs

    def steps(self):
        return self._specs

    def export(self, episode_id):
        return {"ok": True}


def test_runner_stops_after_human_gate():
    calls = []

    def step_a(s, e, g):
        calls.append("a")

    def step_gate(s, e, g):
        calls.append("gate")

    def step_b(s, e, g):
        calls.append("b")

    specs = [
        StepSpec(name="a", run=step_a),
        StepSpec(name="gate", human_gate=True, run=step_gate),
        StepSpec(name="b", run=step_b),
    ]
    assert Runner().run(FakeRoom(specs), None, None, BudgetGuard(10.0)) == "awaiting_approval"
    assert calls == ["a", "gate"]


def test_runner_stops_when_step_returns_false():
    calls = []

    def step_qa(s, e, g):
        calls.append("qa")
        return False

    def step_b(s, e, g):
        calls.append("b")

    specs = [StepSpec(name="qa", run=step_qa), StepSpec(name="b", run=step_b)]
    assert Runner().run(FakeRoom(specs), None, None, BudgetGuard(10.0)) == "stopped"
    assert calls == ["qa"]


def test_runner_precheck_blocks_step_it_cannot_afford():
    ran = []

    def step_pricey(s, e, g):
        ran.append("pricey")

    specs = [StepSpec(name="pricey", est_cost=0.20, run=step_pricey)]
    guard = BudgetGuard(0.10)
    with pytest.raises(BudgetExceeded):
        Runner().run(FakeRoom(specs), None, None, guard)
    assert ran == [] and guard.spent == 0.0  # nothing ran, nothing spent


def test_runner_precheck_zero_for_finished_work():
    ran = []

    def step_done(s, e, g):
        ran.append("done")

    specs = [StepSpec(name="done", est_cost=0.50, estimate=lambda s, e: 0.0, run=step_done)]
    guard = BudgetGuard(0.10, spent=0.09)
    assert Runner().run(FakeRoom(specs), None, None, guard) == "done"
    assert ran == ["done"]


def test_runner_returns_done_when_no_gate():
    specs = [StepSpec(name="a", run=lambda s, e, g: None)]
    assert Runner().run(FakeRoom(specs), None, None, BudgetGuard(1.0)) == "done"


def test_registry_loads_manhwa_room(studio):
    room = get_room("manhwa", studio)
    assert room.key == "manhwa"
    assert [s.name for s in room.steps()] == ["script", "storyboard", "narrative_qa", "audio", "render", "assemble"]
    assert room.steps()[-1].human_gate is True
    assert "manhwa" in available_keys()
    with pytest.raises(KeyError):
        get_room("nope", studio)
