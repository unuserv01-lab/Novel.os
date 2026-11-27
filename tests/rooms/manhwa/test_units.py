import io

import pytest
from PIL import Image
from sqlalchemy import select

from novelos.db import Character, Project, session_scope
from novelos.rooms.manhwa import characters as chars
from novelos.rooms.manhwa.composition import compose, draw_dialog
from novelos.rooms.manhwa.quality import automated_checks
from novelos.libs.models import adapters
from novelos.libs.models.adapters import ProviderError


def png(color=(10, 200, 30), size=(64, 64), noise=False):
    im = Image.new("RGB", size, color)
    if noise:
        for x in range(size[0]):
            im.putpixel((x, x % size[1]), (255, 0, 0))
            im.putpixel((x, (x * 7) % size[1]), (0, 0, 255))
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def test_qc_flags_blank_wrong_size_duplicate_and_garbage():
    good = png(noise=True)
    assert automated_checks(good, (64, 64)) == []
    assert any("blank" in i for i in automated_checks(png(), (64, 64)))
    assert any("wrong size" in i for i in automated_checks(good, (32, 32)))
    assert any("identical" in i for i in automated_checks(good, (64, 64), previous_png=good))
    assert any("unreadable" in i for i in automated_checks(b"not an image", (64, 64)))


def test_character_injuries_accumulate_and_reach_the_prompt(studio):
    with session_scope(studio.factory) as s:
        p = s.scalar(select(Project))
        kael = chars.get_by_code(s, p.id, "CHR_KAEL_001")
        chars.update_state(s, kael, add_injury="scar on left forearm")
        chars.update_state(s, kael, add_injury="broken left horn")
        chars.update_state(s, kael, timeline="post_regression")
        block = chars.prompt_block(kael, emotion="angry")
        assert "scar on left forearm" in block and "broken left horn" in block and "crimson eyes" in block
        assert block.startswith("CHARACTER:CHR_KAEL_001")
        chars.update_state(s, kael, heal_injury="broken left horn")
        assert "broken left horn" not in chars.prompt_block(kael)


def test_sample_characters_have_references(studio):
    with session_scope(studio.factory) as s:
        for c in s.scalars(select(Character)):
            assert c.references and studio.storage.exists(c.references[0].path)


def test_dialog_layer_draws_text_and_reports_overflow():
    base = Image.new("RGB", (800, 300), (40, 40, 40))
    before = base.tobytes()
    assert draw_dialog(base, [{"speaker": "A", "text": "Halo", "kind": "speech"}]) == []
    assert base.tobytes() != before
    tiny = Image.new("RGB", (800, 80), (40, 40, 40))
    warns = draw_dialog(tiny, [{"speaker": "A", "text": "kata " * 30, "kind": "speech"}] * 3)
    assert warns


def test_compose_stacks_panels_with_gaps():
    comp = compose([(png(noise=True, size=(800, 400)), [], 50), (png(noise=True, size=(800, 600)), [], 0)])
    assert comp.image.size == (800, 400 + 50 + 600)
    assert comp.boxes == [(0, 400), (450, 1050)]


def test_gemini_and_openrouter_response_parsing_with_stubbed_http(monkeypatch):
    """Checks OUR parsing of the response shapes we ASSUME. It does not prove the real APIs match."""
    import base64
    from novelos.config import load_settings
    s = load_settings({})
    monkeypatch.setenv("GEMINI_API_KEY", "k"); monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    img = png(noise=True, size=(100, 100))
    b64 = base64.b64encode(img).decode()
    shapes = {
        "generativelanguage": {"candidates": [{"content": {"parts": [{"text": "{\"ok\": true}"}, {"inlineData": {"mimeType": "image/png", "data": b64}}]}}]},
        "openrouter": {"choices": [{"message": {"content": "{\"ok\": true}", "images": [{"image_url": {"url": "data:image/png;base64," + b64}}]}}]},
    }
    monkeypatch.setattr(adapters, "_http_json", lambda url, body, headers, timeout, secret: shapes["generativelanguage" if "generativelanguage" in url else "openrouter"])
    assert adapters.GeminiText(s).complete_json("t", "s", "u", {}) == {"ok": True}
    assert adapters.OpenRouterText(s).complete_json("t", "s", "u", {}) == {"ok": True}
    assert Image.open(io.BytesIO(adapters.GeminiImage(s).generate("p", [img], (80, 120)))).size == (80, 120)
    assert Image.open(io.BytesIO(adapters.OpenRouterImage(s).generate("p", [img], (80, 120)))).size == (80, 120)


def test_missing_key_gives_a_clear_error_without_leaking(monkeypatch):
    from novelos.config import load_settings
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="GEMINI_API_KEY is not set"):
        adapters.GeminiText(load_settings({})).complete_json("t", "s", "u", {})


def test_http_error_scrubs_the_secret(monkeypatch):
    import urllib.error
    def boom(*a, **k):
        raise urllib.error.HTTPError("u", 400, "bad", {}, io.BytesIO(b"key=SUPERSECRET invalid"))
    monkeypatch.setattr(adapters.urllib.request, "urlopen", boom)
    with pytest.raises(ProviderError) as e:
        adapters._http_json("http://x", {}, {}, 1, "SUPERSECRET")
    assert "SUPERSECRET" not in str(e.value)
