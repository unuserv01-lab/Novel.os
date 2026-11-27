"""FileImage: an image adapter that serves pre-made frame files (one per shot).

Used for the Zeno/Achilles real-image run (23 Nov 2026): Tuan generated 6
frames with Gemini and the driver feeds them to the pipeline in shot order.

Mapping is by shot description, not by call order: `build_prompt` embeds the
panel spec as "Scene: {description}", and each shot description is unique.
This makes the mapping robust against pipeline retries (a retry for the same
panel re-sends the same prompt and gets the same frame back). If a prompt
matches no known description, generate() raises ProviderError instead of
silently serving the wrong frame.
"""

from __future__ import annotations

from pathlib import Path

from novelos.libs.models.adapters import ProviderError, normalize_image


class FileImage:
    name = "file-image"

    def __init__(self, frames: list[Path], descriptions: list[str]):
        if len(frames) != len(descriptions):
            raise ValueError("frames and descriptions must have the same length")
        self.frames = [Path(f) for f in frames]
        self.descriptions = list(descriptions)
        for f in self.frames:
            if not f.is_file():
                raise FileNotFoundError(f"frame file missing: {f}")
        self.calls = 0

    def _match(self, prompt: str) -> int:
        # Full description first, then a 60-char prefix (in case a prompt is
        # ever truncated upstream).
        for i, desc in enumerate(self.descriptions):
            if desc and desc in prompt:
                return i
        for i, desc in enumerate(self.descriptions):
            if desc and desc[:60] in prompt:
                return i
        raise ProviderError(
            "file-image: prompt matches no known shot description "
            f"(prompt head: {prompt[:160]!r})"
        )

    def generate(self, prompt: str, references: list[bytes], size: tuple[int, int]) -> bytes:
        idx = self._match(prompt)
        self.calls += 1
        print(f"  file-image: call {self.calls}: shot {idx + 1} -> "
              f"{self.frames[idx].name}", flush=True)
        return normalize_image(self.frames[idx].read_bytes(), size)

    def review(self, image: bytes, checklist: str) -> dict | None:
        return None  # a file cannot judge pictures; only the automated checks run
