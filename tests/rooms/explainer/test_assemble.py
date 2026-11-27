"""Assemble: stickman frames + MockTTS narration -> a playable 9:16 mp4.

Uses short test narrations so the render stays fast; the full-length
narration path is covered by the end-to-end room test.
"""

import subprocess

from PIL import Image

from novelos.libs.media.video import ShotClip, compose_video
from novelos.rooms.explainer.stickman_draw import draw_scene
from novelos.rooms.explainer.writer import default_script


def _ffprobe_duration(path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True).stdout.strip()
    return float(out)


def test_compose_video_from_stickman_frames(make_studio, tmp_path):
    st = make_studio()
    script = default_script()
    clips = []
    for i, scene in enumerate(script.scenes[:2]):
        frame = tmp_path / f"f{i}.png"
        frame.write_bytes(draw_scene(scene))
        audio_bytes, dur = st.tts.synthesize("Halo.")
        audio = tmp_path / f"a{i}.mp3"
        audio.write_bytes(audio_bytes)
        clips.append(ShotClip(image_path=frame, audio_path=audio, duration_sec=dur,
                              motion="static", transition="cut",
                              subtitles=["Halo."], subtitle_style="bottom_box"))
    out = tmp_path / "out.mp4"
    comp = compose_video(clips, out, aspect_ratio="9:16")
    assert out.read_bytes()[4:8] == b"ftyp"
    assert comp.total_duration_sec > 0
    assert _ffprobe_duration(out) > 0
    assert comp.srt_path.exists() and comp.srt_path.read_text().strip() != ""


def test_compose_video_rejects_zero_clips(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        compose_video([], tmp_path / "out.mp4", aspect_ratio="9:16")
