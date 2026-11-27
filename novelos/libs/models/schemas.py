"""Typed contracts between agents for Video Production (NovelOS v2)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class NarrationLine(BaseModel):
    speaker: str = "narrator"  # "narrator" atau kode karakter (e.g., CHR_KAEL_001)
    text: str = Field(min_length=1, max_length=400)
    kind: Literal["narration", "dialogue", "sfx"] = "narration"
    emotion_tone: str = "calm"  # petunjuk intonasi untuk TTS


class ScriptShot(BaseModel):
    characters: list[str] = []  # character codes, e.g. CHR_KAEL_001
    location: str  # location code
    camera: str = "medium shot"
    emotion: str = "neutral"
    description: str = Field(min_length=3)  # prompt visual dasar
    lines: list[NarrationLine] = Field(min_length=1)


class ScriptScene(BaseModel):
    summary: str
    shots: list[ScriptShot] = Field(min_length=1)


class Script(BaseModel):
    title: str
    aspect_ratio: Literal["16:9", "9:16"] = "16:9"
    scenes: list[ScriptScene] = Field(min_length=1)

    @field_validator("scenes")
    @classmethod
    def _shot_count(cls, v):
        n = sum(len(s.shots) for s in v)
        if not 1 <= n <= 150:
            raise ValueError(f"script has {n} shots; expected 1..150")
        return v


class ShotDirection(BaseModel):
    """Pengganti Layout: mengatur gerak kamera & transisi tiap adegan."""
    motion: Literal["zoom_in", "zoom_out", "pan_left", "pan_right", "static", "ai_video"] = "zoom_in"
    transition: Literal["cut", "crossfade", "fade_black"] = "cut"
    min_duration_sec: float = Field(default=3.0, ge=1.0, le=15.0)
    subtitle_style: Literal["bottom_box", "word_highlight", "none"] = "bottom_box"


class Storyboard(BaseModel):
    directions: list[ShotDirection]


class Verdict(BaseModel):
    passed: bool
    issues: list[str] = []
