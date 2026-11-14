"""Typed contracts between agents. Anything an LLM returns is validated against these."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class DialogLine(BaseModel):
    speaker: str = ""
    text: str = Field(min_length=1, max_length=160)
    kind: Literal["speech", "thought", "narration", "sfx"] = "speech"


class ScriptPanel(BaseModel):
    characters: list[str] = []  # character codes, e.g. CHR_KAEL_001
    location: str  # location code
    camera: str = "medium shot"
    emotion: str = "neutral"
    description: str = Field(min_length=3)
    dialog: list[DialogLine] = []


class ScriptScene(BaseModel):
    summary: str
    panels: list[ScriptPanel] = Field(min_length=1)


class Script(BaseModel):
    title: str
    scenes: list[ScriptScene] = Field(min_length=1)

    @field_validator("scenes")
    @classmethod
    def _panel_count(cls, v):
        n = sum(len(s.panels) for s in v)
        if not 1 <= n <= 30:
            raise ValueError(f"script has {n} panels; expected 1..30")
        return v


class Layout(BaseModel):
    height_ratio: float = Field(ge=0.4, le=1.8)  # panel height as a multiple of its width
    gap: int = Field(ge=0, le=240)  # empty space (px) after the panel: pacing


class Storyboard(BaseModel):
    layouts: list[Layout]


class Verdict(BaseModel):
    passed: bool
    issues: list[str] = []
