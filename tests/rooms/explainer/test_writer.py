"""Writer tests: mock -> verified sample; a provider returning bad maths
must raise instead of producing a video that teaches something false."""

import copy

import pytest

from novelos.rooms.explainer.writer import default_script, write_script


class FakeText:
    """Stand-in provider returning a fixed script dict."""

    name = "fake"

    def __init__(self, script_dict):
        self._script = script_dict

    def complete_json(self, task, system, user, payload):
        assert task == "explainer_script"
        return copy.deepcopy(self._script)


def _other_system_script():
    """A second, independently correct SPLDV: 3x + y = 10, x - y = 2 -> (3, 1)."""
    d = copy.deepcopy(default_script().model_dump())
    d["system"] = {"a": 3, "b": 1, "c": 10, "d": 1, "e": -1, "f": 2,
                   "x_name": "Doni", "y_name": "Dina", "x_label": "x", "y_label": "y"}
    d["solution"] = {"x": 3, "y": 1}
    # substitusi: eq2 -> x = y + 2; into eq1 -> 4y = 4; y = 1; back -> x = 3
    d["methods"][0]["steps"] = [
        {"op": "given", "equation": {"x": 1, "y": -1, "const": 2}, "sources": [1],
         "relation": None, "factor": "1", "row_op": None, "note": ""},
        {"op": "given", "equation": {"x": 3, "y": 1, "const": 10}, "sources": [0],
         "relation": None, "factor": "1", "row_op": None, "note": ""},
        {"op": "substitute", "equation": {"x": 0, "y": 4, "const": 4}, "sources": [1],
         "relation": {"var": "x", "coeff": 1, "const": 2}, "factor": "1", "row_op": None, "note": ""},
        {"op": "read", "equation": {"x": 0, "y": 1, "const": 1}, "sources": [2],
         "relation": None, "factor": "1/4", "row_op": None, "note": ""},
        {"op": "substitute", "equation": {"x": 1, "y": 0, "const": 3}, "sources": [0],
         "relation": {"var": "y", "coeff": 0, "const": 1}, "factor": "1", "row_op": None, "note": ""},
    ]
    d["methods"][0]["result"] = {"x": 3, "y": 1}
    # eliminasi: eq1 + eq2 -> 4x = 12; x = 3; back into eq2 -> y = 1
    d["methods"][1]["steps"] = [
        {"op": "given", "equation": {"x": 3, "y": 1, "const": 10}, "sources": [0],
         "relation": None, "factor": "1", "row_op": None, "note": ""},
        {"op": "given", "equation": {"x": 1, "y": -1, "const": 2}, "sources": [1],
         "relation": None, "factor": "1", "row_op": None, "note": ""},
        {"op": "add", "equation": {"x": 4, "y": 0, "const": 12}, "sources": [0, 1],
         "relation": None, "factor": "1", "row_op": None, "note": ""},
        {"op": "read", "equation": {"x": 1, "y": 0, "const": 3}, "sources": [2],
         "relation": None, "factor": "1/4", "row_op": None, "note": ""},
        {"op": "substitute", "equation": {"x": 0, "y": -1, "const": -1}, "sources": [1],
         "relation": {"var": "x", "coeff": 0, "const": 3}, "factor": "1", "row_op": None, "note": ""},
        {"op": "read", "equation": {"x": 0, "y": 1, "const": 1}, "sources": [4],
         "relation": None, "factor": "-1", "row_op": None, "note": ""},
    ]
    d["methods"][1]["result"] = {"x": 3, "y": 1}
    # matriks: [[3,1|10],[1,-1|2]]; R1 <- R1 + R2 -> 4x = 12; x = 3; back -> y = 1
    d["methods"][2]["matrix"] = [[3, 1, 10], [1, -1, 2]]
    d["methods"][2]["steps"] = [
        {"op": "given", "equation": {"x": 3, "y": 1, "const": 10}, "sources": [0],
         "relation": None, "factor": "1", "row_op": None, "note": ""},
        {"op": "given", "equation": {"x": 1, "y": -1, "const": 2}, "sources": [1],
         "relation": None, "factor": "1", "row_op": None, "note": ""},
        {"op": "row_op", "equation": {"x": 4, "y": 0, "const": 12}, "sources": [0],
         "relation": None, "factor": "1", "row_op": {"target": 0, "source": 1, "factor": 1}, "note": ""},
        {"op": "read", "equation": {"x": 1, "y": 0, "const": 3}, "sources": [2],
         "relation": None, "factor": "1/4", "row_op": None, "note": ""},
        {"op": "substitute", "equation": {"x": 0, "y": -1, "const": -1}, "sources": [1],
         "relation": {"var": "x", "coeff": 0, "const": 3}, "factor": "1", "row_op": None, "note": ""},
        {"op": "read", "equation": {"x": 0, "y": 1, "const": 1}, "sources": [4],
         "relation": None, "factor": "-1", "row_op": None, "note": ""},
    ]
    d["methods"][2]["result"] = {"x": 3, "y": 1}
    return d


def test_mock_text_returns_verified_sample(studio):
    s = write_script(studio.text, "SPLDV bagi permen")
    assert s.solution == {"x": 3, "y": 2}
    assert len(s.scenes) == 6


def test_provider_script_accepted_when_maths_is_right():
    s = write_script(FakeText(_other_system_script()), "other problem")
    assert s.solution == {"x": 3, "y": 1}


def test_provider_script_with_wrong_maths_rejected():
    bad = _other_system_script()
    bad["methods"][0]["steps"][2]["equation"] = {"x": 0, "y": 4, "const": 5}  # 4y = 5 is false
    with pytest.raises(ValueError, match="math verification"):
        write_script(FakeText(bad), "other problem")


def test_provider_script_with_bad_shape_rejected():
    bad = _other_system_script()
    bad["methods"] = bad["methods"][:2]
    with pytest.raises(ValueError, match="schema validation"):
        write_script(FakeText(bad), "other problem")
