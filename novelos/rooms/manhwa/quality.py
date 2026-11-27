"""Automated QC: cheap deterministic checks that run before (and without) any model-based review."""

from __future__ import annotations

import io

from PIL import Image, ImageStat


def automated_checks(png: bytes, expected_size: tuple[int, int], previous_png: bytes | None = None) -> list[str]:
    issues: list[str] = []
    try:
        im = Image.open(io.BytesIO(png))
        im.load()
    except Exception as e:  # corrupt or non-image bytes
        return [f"unreadable image: {e}"]
    if im.size != expected_size:
        issues.append(f"wrong size {im.size}, expected {expected_size}")
    gray = im.convert("L")
    std = ImageStat.Stat(gray).stddev[0]
    if std < 6:
        issues.append("image is blank or nearly one flat colour")
    if previous_png is not None and previous_png == png:
        issues.append("identical to the previous panel (generator stuck?)")
    return issues
