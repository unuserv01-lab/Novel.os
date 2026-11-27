"""Tests for the v2 video assembler (FFmpeg): SRT timing, transitions, ai_video fallback."""

import subprocess
from pathlib import Path

import pytest
from PIL import Image

from novelos.libs.media.video import ShotClip, build_srt, compose_video
from novelos.libs.models.adapters import MockTTS


def _png(path: Path, color=(40, 90, 160), size=(1280, 720)) -> Path:
    Image.new("RGB", size, color).save(path, "PNG")
    return path


def _mp3(path: Path, text: str) -> Path:
    data, _dur = MockTTS().synthesize(text)
    path.write_bytes(data)
    return path


def _clip(tmp: Path, name: str, duration: float = 2.0, motion: str = "zoom_in",
          transition: str = "cut", text: str = "Halo dunia.", color=(40, 90, 160)) -> ShotClip:
    img = _png(tmp / f"{name}.png", color)
    audio = _mp3(tmp / f"{name}.mp3", text * 2)  # ~2s of speech
    return ShotClip(image_path=img, audio_path=audio, duration_sec=duration,
                    motion=motion, transition=transition, subtitles=[text])


def _probe_duration(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                       capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def test_build_srt_timing_accounts_for_crossfade_overlap(tmp_path):
    c1 = _clip(tmp_path, "a", duration=3.0, transition="crossfade")
    c2 = _clip(tmp_path, "b", duration=4.0, transition="cut")
    total = build_srt([c1, c2], tmp_path / "out.srt")
    assert total == pytest.approx(6.5)  # 3 + 4 - 0.5s crossfade overlap
    srt = (tmp_path / "out.srt").read_text()
    assert "00:00:00,000 --> 00:00:03,000" in srt
    assert "00:00:02,500 --> 00:00:06,500" in srt  # second clip starts 0.5s early


def test_compose_video_produces_playable_mp4(tmp_path):
    clips = [_clip(tmp_path, "a", text="Satu."), _clip(tmp_path, "b", text="Dua.", motion="pan_left")]
    comp = compose_video(clips, tmp_path / "ep.mp4")
    assert comp.video_path.exists() and comp.srt_path.exists()
    assert _probe_duration(comp.video_path) == pytest.approx(4.0, abs=0.5)
    assert comp.total_duration_sec == pytest.approx(4.0)
    assert (tmp_path / "ep.srt").read_text().count(" --> ") == 2


def test_crossfade_shortens_total_duration(tmp_path):
    clips = [_clip(tmp_path, "a", duration=3.0, transition="crossfade"),
             _clip(tmp_path, "b", duration=3.0, transition="cut")]
    comp = compose_video(clips, tmp_path / "ep.mp4", burn_subtitles=False)
    assert comp.total_duration_sec == pytest.approx(5.5)
    assert _probe_duration(comp.video_path) == pytest.approx(5.5, abs=0.5)


def test_fade_black_does_not_change_duration(tmp_path):
    clips = [_clip(tmp_path, "a", duration=3.0, transition="fade_black"),
             _clip(tmp_path, "b", duration=3.0, transition="cut")]
    comp = compose_video(clips, tmp_path / "ep.mp4", burn_subtitles=False)
    assert comp.total_duration_sec == pytest.approx(6.0)
    assert _probe_duration(comp.video_path) == pytest.approx(6.0, abs=0.5)


def test_ai_video_warns_and_falls_back_to_zoom_in(tmp_path):
    clips = [_clip(tmp_path, "a", motion="ai_video")]
    comp = compose_video(clips, tmp_path / "ep.mp4", burn_subtitles=False)
    assert any("ai_video" in w and "not implemented" in w for w in comp.warnings)
    assert _probe_duration(comp.video_path) > 0
