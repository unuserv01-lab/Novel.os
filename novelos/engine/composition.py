"""Composition Engine: stack panels vertically and draw dialog/SFX as a separate layer.

Stored panel images never contain text. Bubbles are drawn here from `panel.dialog`, so editing a line
and recomposing does not regenerate (or pay for) any picture.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

from PIL import Image, ImageDraw

from novelos.models.adapters import load_font

WIDTH = 800


@dataclass
class Composition:
    image: Image.Image
    boxes: list[tuple[int, int]] = field(default_factory=list)  # (y0, y1) of each panel in the long image
    warnings: list[str] = field(default_factory=list)


def _wrap(d: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if d.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    return lines + ([cur] if cur else [])


def draw_dialog(img: Image.Image, dialog: list[dict]) -> list[str]:
    """Draw bubbles onto `img` in place. Returns warnings (e.g. text that did not fit)."""
    warnings: list[str] = []
    d = ImageDraw.Draw(img)
    w, h = img.size
    y = 34
    for i, line in enumerate(dialog):
        kind, text, speaker = line.get("kind", "speech"), line["text"], line.get("speaker", "")
        if kind == "sfx":
            f = load_font(72)
            tw = d.textlength(text, font=f)
            d.text(((w - tw) / 2, h - 150), text, font=f, fill=(255, 230, 0), stroke_width=6, stroke_fill=(0, 0, 0))
            continue
        size = 26
        while True:
            f = load_font(size)
            wrapped = _wrap(d, text, f, int(w * 0.55))
            bw = int(max(d.textlength(t, font=f) for t in wrapped)) + 36
            bh = len(wrapped) * (size + 6) + 28
            if y + bh < h - 10 or size <= 16:
                break
            size -= 2
        if y + bh >= h - 10:
            warnings.append(f"dialog line {i} overflows the panel")
        if kind == "narration":
            x0, fill, outline, rad = 16, (255, 245, 200), (90, 70, 20), 4
        else:
            x0 = 24 if i % 2 == 0 else w - bw - 24
            fill, outline, rad = (255, 255, 255), (0, 0, 0), 26
        d.rounded_rectangle([x0, y, x0 + bw, y + bh], rad, fill=fill, outline=outline, width=3)
        ty = y + 14
        for t in wrapped:
            d.text((x0 + 18, ty), t, font=f, fill=(20, 20, 20))
            ty += size + 6
        if kind == "thought":
            d.ellipse([x0 + 20, y + bh + 2, x0 + 34, y + bh + 14], fill=fill, outline=outline, width=2)
        elif kind == "speech" and speaker:
            d.text((x0 + 8, y - 20), speaker, font=load_font(16), fill=(255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0))
        y += bh + 34
    return warnings


def compose(panels: list[tuple[bytes, list[dict], int]]) -> Composition:
    """panels: [(png_bytes, dialog, gap_after_px)] in reading order."""
    tiles, warns = [], []
    for n, (png, dialog, _gap) in enumerate(panels, 1):
        tile = Image.open(io.BytesIO(png)).convert("RGB")
        if tile.width != WIDTH:
            tile = tile.resize((WIDTH, round(tile.height * WIDTH / tile.width)))
        warns += [f"panel {n}: {m}" for m in draw_dialog(tile, dialog)]
        tiles.append(tile)
    total = sum(t.height for t in tiles) + sum(g for _, _, g in panels)
    out = Image.new("RGB", (WIDTH, max(total, 1)), (255, 255, 255))
    y, boxes = 0, []
    for tile, (_, _, gap) in zip(tiles, panels):
        out.paste(tile, (0, y))
        boxes.append((y, y + tile.height))
        y += tile.height + gap
    return Composition(out, boxes, warns)
