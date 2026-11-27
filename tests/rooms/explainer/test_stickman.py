"""Stickman drawing: every scene renders a real 720x1280 PNG frame."""

import io

from PIL import Image

from novelos.rooms.explainer.stickman_draw import draw_scene
from novelos.rooms.explainer.writer import default_script


def test_all_scenes_draw_720x1280():
    script = default_script()
    for scene in script.scenes:
        png = draw_scene(scene)
        assert len(png) > 10_000, f"{scene.kind}: frame suspiciously small"
        im = Image.open(io.BytesIO(png))
        assert im.size == (720, 1280) and im.mode == "RGB"
        # not a blank page: the frame must contain dark line art
        hist = im.convert("L").histogram()
        assert sum(hist[:80]) > 1_000, f"{scene.kind}: frame looks blank"


def test_drawing_is_deterministic():
    script = default_script()
    assert draw_scene(script.scenes[1]) == draw_scene(script.scenes[1])


def test_candy_counts_match_the_problem():
    """Soal scene: Doni 3 candies, Dina 2 — count pink pixels per half."""
    from novelos.rooms.explainer.bible import CANDY

    script = default_script()
    im = Image.open(io.BytesIO(draw_scene(script.scenes[1]))).convert("RGB")
    px = im.load()
    left = right = 0
    for y in range(im.height):
        for x in range(im.width):
            r, g, b = px[x, y]
            if abs(r - CANDY[0]) < 12 and abs(g - CANDY[1]) < 12 and abs(b - CANDY[2]) < 12:
                if x < im.width // 2:
                    left += 1
                else:
                    right += 1
    assert left > right > 0, "Doni (left) must show more candy than Dina (right)"
