"""Stickman frame drawing for the explainer room (PIL only).

Draws the "Satu Soal, Tiga Cara" look from the 25 Nov keyframes with code,
not a model: off-white paper, Doni (orange stickman, small hat), Dina (blue
stickman, two pigtails), pink candy circles, and a whiteboard carrying the
scene's equations. Deterministic — the same scene always draws the same
frame. No new dependency: matplotlib is NOT installed in the venv and is
not needed for this.
"""

from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont

from novelos.libs.models.adapters import load_font

from .bible import ACCENT, BOARD_BG, BOARD_BORDER, CANDY, CHARACTERS, DINA, DONI, FRAME_SIZE, INK, PAPER
from .schema import ExplainerScene

W, H = FRAME_SIZE


def _text(draw: ImageDraw.ImageDraw, xy, text: str, size: int, fill=INK, anchor="mm"):
    draw.text(xy, text, font=load_font(size), fill=fill, anchor=anchor)


def draw_stickman(draw: ImageDraw.ImageDraw, cx: int, feet_y: int, scale: float, color, hat=False,
                  pigtails=False) -> None:
    """One stick figure, feet at (cx, feet_y), ~300*scale px tall."""
    w = 6
    head_r = int(34 * scale)
    head_cy = feet_y - int(300 * scale) + head_r
    # head
    draw.ellipse([cx - head_r, head_cy - head_r, cx + head_r, head_cy + head_r],
                 outline=color, width=w)
    # smile
    draw.arc([cx - head_r // 2, head_cy - 4, cx + head_r // 2, head_cy + head_r // 2],
             start=15, end=165, fill=color, width=3)
    # eyes
    for dx in (-12, 12):
        draw.ellipse([cx + dx * scale - 3, head_cy - 8, cx + dx * scale + 3, head_cy - 2], fill=color)
    if hat:  # Doni's small hat
        brim_y = head_cy - head_r + 6
        draw.line([cx - head_r - 8, brim_y, cx + head_r + 8, brim_y], fill=color, width=w)
        draw.arc([cx - head_r + 6, brim_y - head_r, cx + head_r - 6, brim_y + 10],
                 start=180, end=360, fill=color, width=w)
    if pigtails:  # Dina's two pigtails
        for sgn in (-1, 1):
            x0 = cx + sgn * head_r
            draw.line([x0, head_cy - 6, x0 + sgn * 26, head_cy - 52], fill=color, width=5)
            draw.ellipse([x0 + sgn * 26 - 9, head_cy - 61, x0 + sgn * 26 + 9, head_cy - 43],
                         fill=color)
    neck_y = head_cy + head_r
    hip_y = feet_y - int(110 * scale)
    # body, arms (waving), legs
    draw.line([cx, neck_y, cx, hip_y], fill=color, width=w)
    draw.line([cx, neck_y + 30, cx - int(52 * scale), neck_y - 10], fill=color, width=w)
    draw.line([cx, neck_y + 30, cx + int(52 * scale), neck_y - 34], fill=color, width=w)
    draw.line([cx, hip_y, cx - int(42 * scale), feet_y], fill=color, width=w)
    draw.line([cx, hip_y, cx + int(42 * scale), feet_y], fill=color, width=w)


def draw_candy(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int) -> None:
    """One pink candy: round body + twist wrappers."""
    draw.polygon([(cx - r - 12, cy - 6), (cx - r + 2, cy), (cx - r - 12, cy + 6)], fill=CANDY)
    draw.polygon([(cx + r + 12, cy - 6), (cx + r - 2, cy), (cx + r + 12, cy + 6)], fill=CANDY)
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=CANDY, outline=(214, 90, 140), width=3)
    draw.ellipse([cx - r // 2, cy - r // 2, cx - r // 4, cy - r // 4], fill=(255, 205, 225))


def draw_board(draw: ImageDraw.ImageDraw, lines: list[str]) -> None:
    """Whiteboard with the scene's equations, top half of the frame."""
    x0, y0, x1, y1 = 40, 120, W - 40, 540
    draw.rounded_rectangle([x0, y0, x1, y1], radius=18, fill=BOARD_BG,
                           outline=BOARD_BORDER, width=5)
    draw.line([x0 + 20, y0 + 14, x1 - 20, y0 + 14], fill=(200, 200, 200), width=3)
    n = max(len(lines), 1)
    for i, line in enumerate(lines):
        cy = y0 + (y1 - y0) * (i + 1) / (n + 1)
        size = 44 if len(line) <= 22 else 36
        _text(draw, ((x0 + x1) // 2, cy), line, size)


def draw_scene(scene: ExplainerScene, size: tuple[int, int] = FRAME_SIZE) -> bytes:
    """Render one scene to PNG bytes (exactly `size`, RGB)."""
    im = Image.new("RGB", size, PAPER)
    d = ImageDraw.Draw(im)
    sx, sy = size[0] / W, size[1] / H
    # title bar
    _text(d, (size[0] // 2, int(58 * sy)), scene.title, int(46 * sy))
    d.line([60, int(96 * sy), size[0] - 60, int(96 * sy)], fill=(200, 190, 170), width=3)
    # board
    draw_board(d, scene.board)
    # ground line
    ground_y = int(1080 * sy)
    d.line([60, ground_y, size[0] - 60, ground_y], fill=(190, 175, 150), width=4)
    # characters, spread across the stage
    chars = scene.characters or ["doni", "dina"]
    positions = [int(size[0] * f) for f in (0.30, 0.70)][:len(chars)]
    if len(chars) == 1:
        positions = [size[0] // 2]
    for code, cx in zip(chars, positions):
        c = CHARACTERS.get(code, CHARACTERS["doni"])
        draw_stickman(d, cx, ground_y, 1.0, c["color"], hat=c["hat"], pigtails=c["pigtails"])
        _text(d, (cx, int(ground_y + 44 * sy)), c["name"], int(36 * sy), fill=c["color"])
    # candy piles under their owner
    for who, count in scene.candies:
        base_x = int(size[0] * 0.30) if who == "doni" else int(size[0] * 0.70)
        if len(chars) == 1:
            base_x = size[0] // 2
        for i in range(count):
            draw_candy(d, base_x + (i - (count - 1) / 2) * 64, int(ground_y - 150 * sy), 24)
    # footer: scene kind + question mark for the hook
    _text(d, (size[0] // 2, int(1215 * sy)), "Satu Soal, Tiga Cara", int(30 * sy),
          fill=(150, 140, 125))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()
