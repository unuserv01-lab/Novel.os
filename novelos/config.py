"""Settings come from environment variables only. API keys are never stored in files or logged."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str
    storage_dir: Path
    text_provider: str  # mock | gemini | openrouter
    image_provider: str  # mock | gemini | openrouter
    gemini_text_model: str
    gemini_image_model: str
    openrouter_text_model: str
    openrouter_image_model: str
    max_regen_per_panel: int  # extra attempts after the first render
    max_cost_per_episode: float  # USD, compared against the estimated cost below
    est_cost_text: float  # USD per text call (0 on a free tier)
    est_cost_image: float  # USD per image call (0 on a free tier)
    http_timeout: float


def load_settings(env: dict | None = None) -> Settings:
    e = os.environ if env is None else env
    home = Path(e.get("NOVELOS_HOME", "data")).resolve()
    return Settings(
        database_url=e.get("DATABASE_URL", f"sqlite:///{home / 'novelos.db'}"),
        storage_dir=home / "storage",
        text_provider=e.get("NOVELOS_TEXT_PROVIDER", "mock"),
        image_provider=e.get("NOVELOS_IMAGE_PROVIDER", "mock"),
        # Model names are defaults only: check the provider's current model list and override.
        gemini_text_model=e.get("GEMINI_TEXT_MODEL", "gemini-2.5-flash"),
        gemini_image_model=e.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image"),
        openrouter_text_model=e.get("OPENROUTER_TEXT_MODEL", "google/gemini-2.5-flash"),
        openrouter_image_model=e.get("OPENROUTER_IMAGE_MODEL", "google/gemini-2.5-flash-image"),
        max_regen_per_panel=int(e.get("NOVELOS_MAX_REGEN", "2")),
        max_cost_per_episode=float(e.get("NOVELOS_MAX_COST_USD", "0.50")),
        est_cost_text=float(e.get("NOVELOS_EST_COST_TEXT", "0")),
        est_cost_image=float(e.get("NOVELOS_EST_COST_IMAGE", "0")),
        http_timeout=float(e.get("NOVELOS_HTTP_TIMEOUT", "120")),
    )
