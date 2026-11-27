"""Writer for the explainer room: problem -> verified ExplainerScript.

Mock-first, like the manhwa room: the deterministic sample script (the
25 Nov "Satu Soal, Tiga Cara" episode 1, SPLDV x+y=5 / x-y=1) is the
default. A real text provider may supply its own script JSON, but whatever
it returns is validated against the schema AND re-derived by math_verify —
a script with wrong maths raises ValueError and the episode goes to
needs_attention instead of producing a video that teaches something false.
"""

from __future__ import annotations

import json

from pydantic import ValidationError

from .bible import NARRATION, PROBLEM_TEXT, SAMPLE_SOLUTION, SAMPLE_SYSTEM, SCENES, TITLE
from .math_verify import verify_script
from .schema import ExplainerScene, ExplainerScript, LinearSystem, LinEq, MathStep, Method, Relation, RowOp

SYSTEM = (
    "You are the Writer Agent of a maths explainer studio (YouTube Shorts, "
    "vertical 9:16, stickman style). Return ONLY JSON for an ExplainerScript: "
    '{"title": str, "problem": str, "system": {"a": int, "b": int, "c": int, '
    '"d": int, "e": int, "f": int, "x_name": str, "y_name": str}, '
    '"solution": {"x": int, "y": int}, "methods": [{"kind": '
    '"substitusi"|"eliminasi"|"matriks", "title": str, "steps": [{"op": '
    '"given"|"rearrange"|"substitute"|"add"|"subtract"|"scale"|"read"|"row_op", '
    '"equation": {"x": int, "y": int, "const": int}, "sources": [int], '
    '"relation": {"var": "x"|"y", "coeff": int, "const": int}, "factor": str, '
    '"row_op": {"target": int, "source": int, "factor": int}, "note": str}], '
    '"matrix": [[int]], "result": {"x": int, "y": int}}], '
    '"scenes": [{"kind": "hook"|"soal"|"substitusi"|"eliminasi"|"matriks"|'
    '"kesimpulan", "title": str, "narration": str, "board": [str], '
    '"candies": [["doni"|"dina", int]], "characters": [str]}]}. '
    "Methods in order: substitusi, eliminasi, matriks. Scenes in order: hook, "
    "soal, substitusi, eliminasi, matriks, kesimpulan. Every step must be "
    "arithmetically derivable from the system — the verifier re-derives them."
)


def _step(op, x=0, y=0, const=0, sources=(), relation=None, factor="1", row_op=None, note=""):
    return MathStep(op=op, equation=LinEq(x=x, y=y, const=const), sources=list(sources),
                    relation=relation, factor=factor, row_op=row_op, note=note)


def default_script() -> ExplainerScript:
    """The verified episode-1 script (SPLDV, Doni 3 / Dina 2).

    Steps (system x+y=5, x-y=1, solution x=3, y=2):
    - substitusi: eq2 -> x = y+1; into eq1 -> 2y = 4; y = 2; back into eq2 -> x = 3.
    - eliminasi: eq1 + eq2 -> 2x = 6; x = 3; back into eq1 -> y = 2.
    - matriks: [[1,1|5],[1,-1|1]]; R2 <- R2 - R1 -> -2y = -4; y = 2; back -> x = 3.
    """
    system = LinearSystem(**SAMPLE_SYSTEM)
    methods = [
        Method(kind="substitusi", title="Cara 1: Substitusi", result=dict(SAMPLE_SOLUTION), steps=[
            _step("given", 1, -1, 1, sources=[1], note="x - y = 1"),
            _step("given", 1, 1, 5, sources=[0], note="x + y = 5"),
            _step("substitute", 0, 2, 4, sources=[1],
                  relation=Relation(var="x", coeff=1, const=1), note="x = y + 1 ke total"),
            _step("read", 0, 1, 2, sources=[2], factor="1/2", note="Dina punya 2 permen"),
            _step("substitute", 1, 0, 3, sources=[0],
                  relation=Relation(var="y", coeff=0, const=2), note="y = 2 ke x - y = 1"),
        ]),
        Method(kind="eliminasi", title="Cara 2: Eliminasi", result=dict(SAMPLE_SOLUTION), steps=[
            _step("given", 1, 1, 5, sources=[0], note="x + y = 5"),
            _step("given", 1, -1, 1, sources=[1], note="x - y = 1"),
            _step("add", 2, 0, 6, sources=[0, 1], note="y saling menghapus"),
            _step("read", 1, 0, 3, sources=[2], factor="1/2", note="Doni punya 3 permen"),
            _step("substitute", 0, 1, 2, sources=[0],
                  relation=Relation(var="x", coeff=0, const=3), note="x = 3 ke x + y = 5"),
        ]),
        Method(kind="matriks", title="Cara 3: Matriks", result=dict(SAMPLE_SOLUTION),
               matrix=[[1, 1, 5], [1, -1, 1]], steps=[
            _step("given", 1, 1, 5, sources=[0], note="baris 1: [1 1 | 5]"),
            _step("given", 1, -1, 1, sources=[1], note="baris 2: [1 -1 | 1]"),
            _step("row_op", 0, -2, -4, sources=[1],
                  row_op=RowOp(target=1, source=0, factor=-1), note="R2 <- R2 - R1"),
            _step("read", 0, 1, 2, sources=[2], factor="-1/2", note="Dina = 2"),
            _step("substitute", 1, 0, 3, sources=[0],
                  relation=Relation(var="y", coeff=0, const=2), note="y = 2 ke baris 1"),
        ]),
    ]
    scenes = [ExplainerScene(kind=s["kind"], title=s["title"], narration=s["narration"],
                             board=s["board"], candies=[tuple(c) for c in s["candies"]],
                             characters=s["characters"]) for s in SCENES]
    script = ExplainerScript(title=TITLE, problem=PROBLEM_TEXT, system=system,
                             solution=dict(SAMPLE_SOLUTION), methods=methods, scenes=scenes)
    issues = verify_script(script)
    if issues:  # the built-in script must never ship broken — fail loudly
        raise AssertionError(f"built-in sample script failed verification: {issues}")
    return script


def write_script(text, premise: str) -> ExplainerScript:
    """Build the script for `premise`.

    The premise names the problem; for now every premise resolves to the
    verified episode-1 script (the room's first problem). A text provider
    that answers the `explainer_script` task may return a different SPLDV
    problem, but it is schema-validated AND math-verified before use.
    """
    _ = premise  # reserved: future problems are selected by premise
    if getattr(text, "name", "") == "mock-text":
        # The mock provider has no explainer task — deterministic sample.
        return default_script()
    try:
        raw = text.complete_json("explainer_script", SYSTEM,
                                 "Write the explainer episode.\n" + json.dumps(
                                     {"problem": PROBLEM_TEXT, "system": SAMPLE_SYSTEM},
                                     ensure_ascii=False), {})
    except Exception as e:
        # A real provider that fails must fail loudly, not silently swap in
        # a different problem: the episode goes to needs_attention.
        raise ValueError(f"explainer text provider failed: {e}") from e
    try:
        script = ExplainerScript.model_validate(raw)
    except ValidationError as e:
        raise ValueError(f"explainer script failed schema validation: {e}") from e
    issues = verify_script(script)
    if issues:
        raise ValueError(f"explainer script failed math verification: {'; '.join(issues)}")
    return script
