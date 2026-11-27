"""math_verify tests — the most important file in this room.

The verifier must ACCEPT the true script and REJECT every wrong variant:
wrong final answer, wrong intermediate step, wrong row operation, wrong
read-off, and a system with no unique solution.
"""

import copy

import pytest

from novelos.rooms.explainer.math_verify import solve_system, verify_script
from novelos.rooms.explainer.schema import ExplainerScript
from novelos.rooms.explainer.writer import default_script


def _script_with(mutate):
    d = copy.deepcopy(default_script().model_dump())
    mutate(d)
    return ExplainerScript.model_validate(d)


def test_correct_script_passes():
    assert verify_script(default_script()) == []
    assert solve_system(default_script().system) == {"x": 3, "y": 2}


def test_wrong_final_answer_rejected():
    s = _script_with(lambda d: d.update(solution={"x": 4, "y": 1}))
    issues = verify_script(s)
    assert issues, "solution x=4, y=1 must be rejected"
    assert any("solution" in i for i in issues)


def test_wrong_substitution_step_rejected():
    # 2y = 4 is the true substitution result; 2y = 5 is not derivable.
    s = _script_with(lambda d: d["methods"][0]["steps"][2].update(
        equation={"x": 0, "y": 2, "const": 5}))
    issues = verify_script(s)
    assert any("substitut" in i for i in issues)


def test_wrong_elimination_add_rejected():
    # eq1 + eq2 = 2x = 6, not 2x = 7.
    s = _script_with(lambda d: d["methods"][1]["steps"][2].update(
        equation={"x": 2, "y": 0, "const": 7}))
    issues = verify_script(s)
    assert any("add" in i for i in issues)


def test_wrong_read_off_rejected():
    # 2y = 4 scaled by 1/2 reads y = 2, not y = 3.
    s = _script_with(lambda d: d["methods"][0]["steps"][3].update(
        equation={"x": 0, "y": 1, "const": 3}))
    issues = verify_script(s)
    assert any("read" in i for i in issues)


def test_wrong_matrix_row_op_rejected():
    # R2 <- R2 - R1 gives -2y = -4, not -2y = -3.
    s = _script_with(lambda d: d["methods"][2]["steps"][2].update(
        equation={"x": 0, "y": -2, "const": -3}))
    issues = verify_script(s)
    assert any("row operation" in i for i in issues)


def test_wrong_matrix_rejected():
    s = _script_with(lambda d: d["methods"][2].update(matrix=[[1, 1, 5], [1, -1, 2]]))
    issues = verify_script(s)
    assert any("matrix is not the system" in i for i in issues)


def test_method_result_must_match_solution():
    s = _script_with(lambda d: d["methods"][1].update(result={"x": 3, "y": 3}))
    issues = verify_script(s)
    assert any("eliminasi" in i and "result" in i for i in issues)


def test_singular_system_rejected():
    # x + y = 5 and 2x + 2y = 10 are the same line: no unique solution.
    s = _script_with(lambda d: d["system"].update(d=2, e=2, f=10))
    assert any("no unique solution" in i for i in verify_script(s))


def test_false_relation_rejected():
    # Claiming x = y + 2 (instead of y + 1) is false at the solution.
    s = _script_with(lambda d: d["methods"][0]["steps"][2].update(
        relation={"var": "x", "coeff": 1, "const": 2}))
    issues = verify_script(s)
    assert any("relation" in i for i in issues)
