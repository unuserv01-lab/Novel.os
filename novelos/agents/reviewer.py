"""Reviewer Agent: narrative QA on the script, visual QA on each panel."""

from __future__ import annotations

from novelos.db import Panel
from novelos.engine.quality import automated_checks
from novelos.models.adapters import ProviderError
from novelos.models.schemas import Verdict


def narrative_issues(panels: list[Panel], cast_names: dict[str, str]) -> list[str]:
    """Deterministic continuity checks on the script (cheap: runs before any image is paid for)."""
    issues: list[str] = []
    names = set(cast_names.values())
    for p in panels:
        present = {cast_names.get(c, c) for c in p.spec.get("characters", [])}
        for line in p.dialog:
            if line["kind"] in ("speech", "thought") and line.get("speaker"):
                if line["speaker"] not in names:
                    issues.append(f"panel {p.index + 1}: speaker '{line['speaker']}' is not in the cast")
                elif line["speaker"] not in present and line["kind"] == "speech":
                    issues.append(f"panel {p.index + 1}: '{line['speaker']}' speaks but is not in the panel")
    return issues


CHECKLIST = (
    "You are a strict manhwa QA reviewer. Look at the image and the spec. Return ONLY JSON "
    '{"passed": bool, "issues": [str]}. Fail if: anatomy is broken (hands, limbs, faces), the scene does not match '
    "the description, any text/letters appear in the image, or a character does not match its description.\n"
)


def visual_review(image, png: bytes, expected_size, previous_png, spec_text: str) -> tuple[list[str], list[str]]:
    """Returns (automated_issues, model_issues). Model review is best-effort: if it errors, the panel
    is judged on the automated checks alone and the gap is recorded in model_issues as a note."""
    auto = automated_checks(png, expected_size, previous_png)
    model: list[str] = []
    if not auto:
        try:
            raw = image.review(png, CHECKLIST + spec_text)
            if raw is not None:
                v = Verdict.model_validate(raw)
                if not v.passed:
                    model = v.issues or ["model review failed the panel"]
        except (ProviderError, ValueError) as e:
            model = []
            auto_note = f"model review unavailable: {str(e)[:100]}"
            return auto, [f"NOTE {auto_note}"]
    return auto, model
