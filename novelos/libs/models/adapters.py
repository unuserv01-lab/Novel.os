"""Pluggable model adapters. Swap provider with NOVELOS_TEXT_PROVIDER / NOVELOS_IMAGE_PROVIDER.

`mock` is deterministic, offline and free: it is what the test-suite and the sample run use.
`gemini` and `openrouter` follow the providers' public REST shapes but have NOT been verified against
the live APIs (they could not be reached from the build sandbox). Run `novelos selftest-live` once.
`edge-tts` (Microsoft Edge TTS) is 100% free with no API key; it has NOT been verified live either
(it needs network access to Microsoft's endpoint).
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from novelos.config import Settings


class ProviderError(RuntimeError):
    pass


FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]


def load_font(size: int):
    for p in FONT_PATHS:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def normalize_image(data: bytes, size: tuple[int, int]) -> bytes:
    """Any provider image -> RGB PNG of exactly `size` (cover + centre crop)."""
    im = Image.open(io.BytesIO(data)).convert("RGB")
    w, h = size
    scale = max(w / im.width, h / im.height)
    im = im.resize((max(w, round(im.width * scale)), max(h, round(im.height * scale))), Image.LANCZOS)
    left, top = (im.width - w) // 2, (im.height - h) // 2
    out = io.BytesIO()
    im.crop((left, top, left + w, top + h)).save(out, "PNG")
    return out.getvalue()


# ---------------------------------------------------------------- mock (offline, deterministic)


def _h(*parts) -> int:
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest(), 16)


class MockText:
    name = "mock-text"

    def complete_json(self, task: str, system: str, user: str, payload: dict) -> dict:
        if task == "script":
            return self._script(payload)
        if task == "storyboard":
            return self._storyboard(payload)
        if task == "review":
            return {"passed": True, "issues": []}
        raise ProviderError(f"mock: unknown task {task}")

    @staticmethod
    def _script(p: dict) -> dict:
        chars = p["characters"]  # [{"code","name"}]
        locs = [x["code"] for x in p["locations"]] or ["LOC_UNKNOWN"]
        lead, other = chars[0], chars[1 if len(chars) > 1 else 0]
        premise = p["premise"].strip().rstrip(".")
        beats = [
            ("Pembukaan", "wide establishing shot", "calm", "{a} berdiri di {loc}, membawa beban premis: {premise}.", [("narration", "", "Semuanya dimulai di sini.")]),
            ("Pembukaan", "close-up", "tense", "Wajah {a} mengeras ketika ia menyadari ada yang salah.", [("thought", "{a}", "Ini tidak seharusnya terjadi.")]),
            ("Pembukaan", "medium shot", "alert", "{b} muncul dari balik bayangan di {loc}.", [("speech", "{b}", "Kau terlambat.")]),
            ("Pembukaan", "over-the-shoulder", "defiant", "{a} menatap {b} tanpa mundur.", [("speech", "{a}", "Aku tidak datang untuk mundur.")]),
            ("Konflik", "low angle", "angry", "{b} mengangkat tangan; udara di sekitar mereka bergetar.", [("sfx", "", "ZZZRRT")]),
            ("Konflik", "dynamic wide shot", "fierce", "{a} menghindar dan melompat melintasi {loc}.", [("speech", "{a}", "Kali ini aku siap!")]),
            ("Konflik", "close-up", "pained", "Tangan {a} terluka; darah menetes ke tanah.", [("thought", "{a}", "Sakit... tapi masih bisa.")]),
            ("Konflik", "medium shot", "cold", "{b} tersenyum tipis, tak terpengaruh.", [("speech", "{b}", "Itu saja?")]),
            ("Konflik", "extreme close-up", "resolute", "Mata {a} menyala, tekadnya bulat.", [("sfx", "", "DEG")]),
            ("Puncak", "wide shot", "dramatic", "{a} melancarkan serangan terakhir ke arah {b}.", [("sfx", "", "BOOOM")]),
            ("Puncak", "high angle", "stunned", "Debu mengendap; {b} berlutut, terkejut.", [("speech", "{b}", "Mustahil...")]),
            ("Penutup", "medium shot", "quiet", "{a} berdiri sendirian di {loc}, napas tersengal.", [("narration", "", "Tapi ini baru permulaan.")]),
        ]
        # v1 kinds (speech/thought) map to the v2 narration kinds.
        kind_map = {"speech": "dialogue", "thought": "dialogue", "narration": "narration", "sfx": "sfx"}
        scenes: dict[str, list] = {}
        for i, (sc, cam, emo, desc, dlg) in enumerate(beats):
            loc = locs[i % len(locs)] if sc != "Pembukaan" else locs[0]
            fmt = dict(a=lead["name"], b=other["name"], loc=loc, premise=premise)
            lines = [
                {"speaker": (s.format(**fmt) if s else "narrator"), "text": t.format(**fmt),
                 "kind": kind_map[k], "emotion_tone": emo} for k, s, t in dlg
            ]
            scenes.setdefault(sc, []).append(
                {
                    "characters": [lead["code"]] if i in (1, 6, 8, 11) else [lead["code"], other["code"]],
                    "location": loc,
                    "camera": cam,
                    "emotion": emo,
                    "description": desc.format(**fmt),
                    "lines": lines,
                }
            )
        return {
            "title": f"Episode: {premise[:60]}",
            "scenes": [{"summary": name, "shots": ps} for name, ps in scenes.items()],
        }

    @staticmethod
    def _storyboard(p: dict) -> dict:
        out = []
        for shot in p.get("shots", p.get("panels", [])):
            cam = shot["camera"]
            if "wide" in cam or "establishing" in cam:
                motion = "zoom_out"
            elif "close" in cam:
                motion = "zoom_in"
            elif "low" in cam or "high" in cam:
                motion = "pan_left"
            else:
                motion = "zoom_in"
            out.append({"motion": motion, "transition": "cut", "min_duration_sec": 3.0,
                        "subtitle_style": "bottom_box"})
        return {"directions": out}


class MockImage:
    name = "mock-image"

    def __init__(self, fail_every: int = 0):
        self.fail_every = fail_every

    def generate(self, prompt: str, references: list[bytes], size: tuple[int, int]) -> bytes:
        w, h = size
        seed = _h(prompt.split("REVISION")[0])
        im = Image.new("RGB", size)
        d = ImageDraw.Draw(im)
        c1 = ((seed >> 8) % 120 + 40, (seed >> 16) % 120 + 40, (seed >> 24) % 120 + 80)
        for y in range(h):  # vertical gradient
            t = y / max(h - 1, 1)
            d.line([(0, y), (w, y)], fill=tuple(int(c * (1 - 0.5 * t)) for c in c1))
        if self.fail_every and "REVISION" not in prompt and seed % self.fail_every == 0:
            return normalize_image(self._blank(size), size)  # simulates a broken render
        names = re.findall(r"CHARACTER:(\w+)", prompt)
        for i, code in enumerate(names):
            cx = int(w * (i + 1) / (len(names) + 1))
            col = (_h(code) % 156 + 100, _h(code, 1) % 156 + 100, _h(code, 2) % 156 + 100)
            d.ellipse([cx - 60, h // 3 - 60, cx + 60, h // 3 + 60], fill=col, outline=(255, 255, 255), width=4)
            d.rounded_rectangle([cx - 80, h // 3 + 70, cx + 80, h - 80], 30, fill=col, outline=(255, 255, 255), width=4)
            d.text((cx - 70, h // 3 + 90), code.replace("CHR_", "")[:12], fill=(0, 0, 0), font=load_font(22))
        d.text((24, 20), f"MOCK PANEL  refs={len(references)}", fill=(255, 255, 255), font=load_font(20))
        buf = io.BytesIO()
        im.save(buf, "PNG")
        return buf.getvalue()

    @staticmethod
    def _blank(size) -> bytes:
        buf = io.BytesIO()
        Image.new("RGB", size, (0, 0, 0)).save(buf, "PNG")
        return buf.getvalue()

    def review(self, image: bytes, checklist: str) -> dict | None:
        return None  # a mock cannot judge pictures; only the automated checks run


class MockTTS:
    """Offline deterministic TTS: a silent MP3 of a plausible spoken duration.

    No network, no key. Duration is estimated from text length (~13 chars/sec
    of Indonesian speech) and the audio is real silence generated with ffmpeg,
    so the video assembler can decode it exactly like real TTS output.
    """
    name = "mock-tts"

    def synthesize(self, text: str, voice_id: str | None = None) -> tuple[bytes, float]:
        duration = max(1.0, round(len(text) / 13.0, 2))
        with tempfile.TemporaryDirectory(prefix="novelos_mocktts_") as tmp:
            out = Path(tmp) / "silent.mp3"
            r = subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                 "-t", f"{duration:.2f}", "-c:a", "libmp3lame", "-q:a", "9", str(out)],
                capture_output=True, text=True)
            if r.returncode != 0 or not out.exists():
                raise ProviderError(f"mock TTS could not render silence: {(r.stderr or '')[-200:]}")
            return out.read_bytes(), duration


# ---------------------------------------------------------------- real providers (not live-verified)


def _http_json(url: str, body: dict, headers: dict, timeout: float, secret: str) -> dict:
    data = json.dumps(body).encode()
    last = ""
    for attempt in range(3):
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **headers})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {e.read()[:300].decode('utf-8', 'replace')}"
            if e.code not in (429, 500, 502, 503, 504):
                break
        except (urllib.error.URLError, TimeoutError) as e:
            last = f"network error: {e}"
        time.sleep(2**attempt)
    raise ProviderError(last.replace(secret, "***") if secret else last)


def _key(name: str) -> str:
    v = os.environ.get(name, "")
    if not v:
        raise ProviderError(f"{name} is not set (put it in your shell or .env; never in the repo)")
    return v


def _loads(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except ValueError as e:
        raise ProviderError(f"model did not return valid JSON: {e}") from None


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


class GeminiText:
    def __init__(self, s: Settings):
        self.s, self.name = s, s.gemini_text_model

    def complete_json(self, task, system, user, payload):
        key = _key("GEMINI_API_KEY")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.s.gemini_text_model}:generateContent"
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        }
        r = _http_json(url, body, {"x-goog-api-key": key}, self.s.http_timeout, key)
        try:
            return _loads(r["candidates"][0]["content"]["parts"][0]["text"])
        except (KeyError, IndexError):
            raise ProviderError(f"unexpected Gemini response shape: {str(r)[:200]}") from None


class GeminiImage:
    def __init__(self, s: Settings):
        self.s, self.name = s, s.gemini_image_model

    def generate(self, prompt, references, size):
        key = _key("GEMINI_API_KEY")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.s.gemini_image_model}:generateContent"
        parts = [{"text": prompt}] + [{"inline_data": {"mime_type": "image/png", "data": _b64(b)}} for b in references]
        body = {"contents": [{"role": "user", "parts": parts}], "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}}
        r = _http_json(url, body, {"x-goog-api-key": key}, self.s.http_timeout, key)
        for cand in r.get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                blob = part.get("inlineData") or part.get("inline_data")
                if blob:
                    return normalize_image(base64.b64decode(blob["data"]), size)
        raise ProviderError(f"Gemini returned no image: {str(r)[:200]}")

    def review(self, image, checklist):
        key = _key("GEMINI_API_KEY")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.s.gemini_text_model}:generateContent"
        parts = [{"text": checklist}, {"inline_data": {"mime_type": "image/png", "data": _b64(image)}}]
        body = {"contents": [{"role": "user", "parts": parts}], "generationConfig": {"responseMimeType": "application/json"}}
        r = _http_json(url, body, {"x-goog-api-key": key}, self.s.http_timeout, key)
        try:
            return _loads(r["candidates"][0]["content"]["parts"][0]["text"])
        except (KeyError, IndexError):
            raise ProviderError("unexpected Gemini review response") from None


class OpenRouterText:
    def __init__(self, s: Settings):
        self.s, self.name = s, s.openrouter_text_model

    def complete_json(self, task, system, user, payload):
        key = _key("OPENROUTER_API_KEY")
        body = {
            "model": self.s.openrouter_text_model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_object"},
        }
        r = _http_json("https://openrouter.ai/api/v1/chat/completions", body, {"Authorization": f"Bearer {key}"}, self.s.http_timeout, key)
        try:
            return _loads(r["choices"][0]["message"]["content"])
        except (KeyError, IndexError):
            raise ProviderError(f"unexpected OpenRouter response shape: {str(r)[:200]}") from None


class OpenRouterImage:
    def __init__(self, s: Settings):
        self.s, self.name = s, s.openrouter_image_model

    def _chat(self, model, content, extra=None):
        key = _key("OPENROUTER_API_KEY")
        body = {"model": model, "messages": [{"role": "user", "content": content}], **(extra or {})}
        return _http_json("https://openrouter.ai/api/v1/chat/completions", body, {"Authorization": f"Bearer {key}"}, self.s.http_timeout, key)

    @staticmethod
    def _img(b: bytes):
        return {"type": "image_url", "image_url": {"url": "data:image/png;base64," + _b64(b)}}

    def generate(self, prompt, references, size):
        content = [{"type": "text", "text": prompt}] + [self._img(b) for b in references]
        r = self._chat(self.s.openrouter_image_model, content, {"modalities": ["image", "text"]})
        try:
            url = r["choices"][0]["message"]["images"][0]["image_url"]["url"]
            return normalize_image(base64.b64decode(url.split(",", 1)[1]), size)
        except (KeyError, IndexError):
            raise ProviderError(f"OpenRouter returned no image: {str(r)[:200]}") from None

    def review(self, image, checklist):
        r = self._chat(self.s.openrouter_text_model, [{"type": "text", "text": checklist}, self._img(image)], {"response_format": {"type": "json_object"}})
        try:
            return _loads(r["choices"][0]["message"]["content"])
        except (KeyError, IndexError):
            raise ProviderError("unexpected OpenRouter review response") from None


def _ffprobe_duration(path: Path) -> float | None:
    """Duration in seconds via ffprobe (already installed on the VM). None if unreadable."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=30)
        return float(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else None
    except (subprocess.SubprocessError, ValueError, OSError):
        return None


class TTSAdapter:
    """Microsoft Edge TTS (edge-tts): 100% free, no API key.

    NOT verified live (it needs network access to Microsoft's TTS endpoint).
    `voice_id` is an Edge voice name (e.g. "id-ID-ArdiNeural"); when a
    character has no voice_id, the configured default voice is used.
    """
    name = "edge-tts"
    DEFAULT_VOICE = "id-ID-ArdiNeural"

    def __init__(self, s: Settings):
        self.s = s

    def synthesize(self, text: str, voice_id: str | None = None) -> tuple[bytes, float]:
        try:
            import asyncio
            import edge_tts
        except ImportError as e:
            raise ProviderError("edge-tts is not installed (pip install edge-tts)") from e
        voice = voice_id or self.s.tts_voice or self.DEFAULT_VOICE
        with tempfile.TemporaryDirectory(prefix="novelos_tts_") as tmp:
            out = Path(tmp) / "speech.mp3"
            try:
                asyncio.run(edge_tts.Communicate(text, voice).save(str(out)))
            except Exception as e:
                raise ProviderError(f"edge-tts failed for voice {voice!r}: {e}") from None
            if not out.exists() or out.stat().st_size == 0:
                raise ProviderError("edge-tts returned no audio")
            duration = _ffprobe_duration(out)
            if duration is None:
                duration = max(1.0, round(len(text) / 13.0, 2))  # fallback estimate
            return out.read_bytes(), duration


def make_text(s: Settings):
    return {"mock": lambda: MockText(), "gemini": lambda: GeminiText(s), "openrouter": lambda: OpenRouterText(s)}[s.text_provider]()


def make_image(s: Settings):
    fail = int(os.environ.get("NOVELOS_MOCK_FAIL_EVERY", "0"))
    return {"mock": lambda: MockImage(fail), "gemini": lambda: GeminiImage(s), "openrouter": lambda: OpenRouterImage(s)}[s.image_provider]()


def make_tts(s: Settings):
    return {"mock": lambda: MockTTS(), "edge-tts": lambda: TTSAdapter(s)}[s.tts_provider]()
