"""Schema tests: shape validation only (maths lives in test_math_verify)."""

import copy

import pytest
from pydantic import ValidationError

from novelos.rooms.explainer.schema import ExplainerScript
from novelos.rooms.explainer.writer import default_script


def _dump():
    return copy.deepcopy(default_script().model_dump())


def test_default_script_validates():
    s = default_script()
    assert s.title == "Satu Soal, Tiga Cara"
    assert [m.kind for m in s.methods] == ["substitusi", "eliminasi", "matriks"]
    assert [sc.kind for sc in s.scenes] == ["hook", "soal", "substitusi", "eliminasi", "matriks", "kesimpulan"]
    assert s.solution == {"x": 3, "y": 2}


def test_wrong_method_order_rejected():
    d = _dump()
    d["methods"] = [d["methods"][1], d["methods"][0], d["methods"][2]]
    with pytest.raises(ValidationError):
        ExplainerScript.model_validate(d)


def test_missing_method_rejected():
    d = _dump()
    d["methods"] = d["methods"][:2]
    with pytest.raises(ValidationError):
        ExplainerScript.model_validate(d)


def test_matriks_without_matrix_rejected():
    d = _dump()
    d["methods"][2]["matrix"] = None
    with pytest.raises(ValidationError):
        ExplainerScript.model_validate(d)


def test_wrong_scene_order_rejected():
    d = _dump()
    d["scenes"] = [d["scenes"][1], d["scenes"][0]] + d["scenes"][2:]
    with pytest.raises(ValidationError):
        ExplainerScript.model_validate(d)


def test_unknown_method_kind_rejected():
    d = _dump()
    d["methods"][2]["kind"] = "grafik"
    with pytest.raises(ValidationError):
        ExplainerScript.model_validate(d)


def test_empty_narration_rejected():
    d = _dump()
    d["scenes"][0]["narration"] = ""
    with pytest.raises(ValidationError):
        ExplainerScript.model_validate(d)
