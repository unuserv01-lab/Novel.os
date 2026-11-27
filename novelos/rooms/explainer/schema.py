"""Schemas for the explainer room ("Satu Soal, Tiga Cara").

Structural validation only (shapes, method/scene order, required fields).
Mathematical correctness is NOT checked here — that is math_verify.py's
job, called by the writer and by the room before any frame is drawn.
Keeping the two apart avoids a schema <-> verifier import cycle.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

METHOD_KINDS = ("substitusi", "eliminasi", "matriks")
SCENE_KINDS = ("hook", "soal", "substitusi", "eliminasi", "matriks", "kesimpulan")


class LinEq(BaseModel):
    """One linear equation in standard form: x_coef*x + y_coef*y = const."""

    x: int = 0
    y: int = 0
    const: int = 0


class Relation(BaseModel):
    """var = coeff * other_var + const (e.g. x = 1*y + 1, or y = 0*x + 2)."""

    var: Literal["x", "y"]
    coeff: int = 1
    const: int = 0


class RowOp(BaseModel):
    """R_target <- R_target + factor * R_source, on the augmented matrix."""

    target: int
    source: int
    factor: int


class MathStep(BaseModel):
    """One checkable step of a solution method.

    `sources` indexes earlier steps of the same method — except for
    `given`/`rearrange`, where it indexes the system's equations (0 or 1).
    `factor` is a rational written as a string ("1/2", "-1/2", "2") so the
    verifier can compare exactly with Fractions.
    """

    op: Literal["given", "rearrange", "substitute", "add", "subtract", "scale", "read", "row_op"]
    equation: LinEq
    sources: list[int] = Field(default_factory=list)
    relation: Relation | None = None
    factor: str = "1"
    row_op: RowOp | None = None
    note: str = ""


class Method(BaseModel):
    kind: Literal["substitusi", "eliminasi", "matriks"]
    title: str
    steps: list[MathStep] = Field(min_length=1)
    matrix: list[list[int]] | None = None  # augmented rows; required for matriks
    result: dict[str, int]  # {"x": ..., "y": ...}


class LinearSystem(BaseModel):
    a: int
    b: int
    c: int  # a*x + b*y = c
    d: int
    e: int
    f: int  # d*x + e*y = f
    x_name: str = "x"
    y_name: str = "y"
    x_label: str = "x"
    y_label: str = "y"


class ExplainerScene(BaseModel):
    kind: Literal["hook", "soal", "substitusi", "eliminasi", "matriks", "kesimpulan"]
    title: str
    narration: str = Field(min_length=1)
    board: list[str] = Field(default_factory=list)
    candies: list[tuple[str, int]] = Field(default_factory=list)
    characters: list[str] = Field(default_factory=list)


class ExplainerScript(BaseModel):
    title: str
    problem: str = Field(min_length=1)
    system: LinearSystem
    solution: dict[str, int]  # {"x": ..., "y": ...}
    methods: list[Method] = Field(min_length=3, max_length=3)
    scenes: list[ExplainerScene] = Field(min_length=6, max_length=6)

    @model_validator(mode="after")
    def _check_order(self):
        if [m.kind for m in self.methods] != list(METHOD_KINDS):
            raise ValueError(f"methods must be {list(METHOD_KINDS)} in order")
        if [s.kind for s in self.scenes] != list(SCENE_KINDS):
            raise ValueError(f"scenes must be {list(SCENE_KINDS)} in order")
        for m in self.methods:
            if m.kind == "matriks" and not m.matrix:
                raise ValueError("matriks method needs its augmented matrix")
            if set(m.result) != {"x", "y"}:
                raise ValueError("method result must be exactly {x, y}")
        if set(self.solution) != {"x", "y"}:
            raise ValueError("solution must be exactly {x, y}")
        return self
