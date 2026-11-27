"""Run the Zeno/Achilles script through the NovelOS v2 pipeline with REAL
images (driver for the real-image run, 23 Nov 2026).

Same flow as run-zeno.py (inject script + panels -> produce -> approve ->
export), but with two differences:

1. Images: a FileImage adapter serves Tuan's 6 Gemini-generated frames
   (~/workspace/your_files/zeno-frames/frame-01.jpg .. frame-06.jpg) instead
   of the MockImage gradient. Mapping is by shot description (see
   novelos/models/file_image.py), so retries can never serve the wrong frame.
2. Narration: the pre-made /tmp/zeno-narration clips were wiped by a VM
   reset, so narration is re-synthesized here with Muse TTS
   (/opt/hatch/bin/tts, language id, voice Helio) into
   zeno-narration-real/ (a permanent dir inside the repo, not /tmp) and
   injected via the pipeline's own skip logic, exactly like run-zeno.py.

The exported mp4 is copied to a permanent location:
~/workspace/your_files/zeno-achilles-ep001-real.mp4
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from novelos.config import load_settings  # noqa: E402
from novelos.db import Episode, Panel, init_db, make_engine, session_factory, session_scope  # noqa: E402
from novelos.core.storage import Storage  # noqa: E402
from novelos.libs.models.adapters import make_text, make_tts  # noqa: E402
from novelos.libs.models.file_image import FileImage  # noqa: E402
from novelos.libs.models.schemas import Script, ShotDirection  # noqa: E402
from novelos.pipeline import Pipeline  # noqa: E402

BASE = Path(__file__).resolve().parent
SCRIPT_PATH = BASE / "zeno-script.json"
FRAMES_DIR = Path.home() / "workspace" / "your_files" / "zeno-frames"
AUDIO_DIR = BASE / "zeno-narration-real"
FINAL_MP4 = Path.home() / "workspace" / "your_files" / "zeno-achilles-ep001-real.mp4"

# (motion, transition) per shot: same as run-zeno.py — crossfades exercise
# the fixed xfade join; shot 5 fade_black makes shot 5 fade out and shot 6
# fade in from black.
DIRECTIONS = [
    ("zoom_in", "crossfade"),
    ("pan_left", "crossfade"),
    ("zoom_out", "crossfade"),
    ("pan_right", "crossfade"),
    ("zoom_in", "fade_black"),
    ("zoom_out", "cut"),
]


def ffprobe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    return round(float(out.stdout.strip()), 2)


def synthesize_narration(script: Script) -> list[Path]:
    """Muse TTS (id, Helio) per shot; skip clips that already exist & play."""
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    clips: list[Path] = []
    idx = 0
    for scene in script.scenes:
        for shot in scene.shots:
            idx += 1
            text = " ".join(ln.text for ln in shot.lines if ln.kind == "narration")
            out = AUDIO_DIR / f"s{idx:02d}.mp3"
            if out.exists():
                try:
                    d = ffprobe_duration(out)
                    if d > 0:
                        print(f"  narration s{idx:02d}: reuse {out.name} ({d}s)", flush=True)
                        clips.append(out)
                        continue
                except subprocess.CalledProcessError:
                    pass
            print(f"  narration s{idx:02d}: synthesizing ({len(text)} chars)...", flush=True)
            r = subprocess.run(
                ["/opt/hatch/bin/tts", "--text", text, "--language", "id",
                 "--voice", "Helio", "--output", str(out)],
                capture_output=True, text=True, timeout=180)
            if r.returncode != 0 or not out.exists():
                raise RuntimeError(f"Muse TTS failed for shot {idx}: {(r.stderr or r.stdout)[-300:]}")
            print(f"  narration s{idx:02d}: done ({ffprobe_duration(out)}s)", flush=True)
            clips.append(out)
    return clips


def build_pipeline(image) -> Pipeline:
    s = load_settings()
    s.storage_dir.parent.mkdir(parents=True, exist_ok=True)
    engine = make_engine(s.database_url)
    init_db(engine)
    return Pipeline(session_factory(engine), s, make_text(s), image, make_tts(s),
                    Storage(s.storage_dir))


def main() -> int:
    script = Script.model_validate(json.loads(SCRIPT_PATH.read_text(encoding="utf-8")))
    shots = [shot for scene in script.scenes for shot in scene.shots]
    print(f"script valid: {script.title!r}, {len(shots)} shots", flush=True)

    frames = [FRAMES_DIR / f"frame-{i + 1:02d}.jpg" for i in range(len(shots))]
    descriptions = [shot.description for shot in shots]
    image = FileImage(frames, descriptions)
    print(f"file-image: {len(frames)} frames from {FRAMES_DIR}", flush=True)

    clips = synthesize_narration(script)

    pipeline = build_pipeline(image)
    ep_id = pipeline.create_episode(
        "sample-manhwa", "Zeno dan Achilles — paradoks tak terhingga (gambar asli)")
    print(f"episode id: {ep_id}", flush=True)

    with session_scope(pipeline.factory) as s:
        ep = s.get(Episode, ep_id)
        ep.script = script.model_dump()
        idx = 0
        for scene_no, scene in enumerate(script.scenes, 1):
            for shot in scene.shots:
                motion, transition = DIRECTIONS[idx]
                direction = ShotDirection(
                    motion=motion, transition=transition,
                    min_duration_sec=3.0, subtitle_style="bottom_box")
                layout = direction.model_dump()
                audio_src = clips[idx]
                rel = pipeline.storage.write(
                    f"audio/ep{ep.number:03d}/s{idx + 1:03d}.mp3",
                    audio_src.read_bytes())
                layout["audio_path"] = rel
                layout["duration_sec"] = max(ffprobe_duration(audio_src), 3.0)
                print(f"  shot {idx + 1}: audio {rel} "
                      f"({layout['duration_sec']}s, {motion}/{transition})", flush=True)
                s.add(Panel(
                    episode_id=ep.id, index=idx, scene_no=scene_no,
                    spec={k: v for k, v in shot.model_dump().items()
                          if k != "lines"},
                    dialog=[ln.model_dump() for ln in shot.lines],
                    layout=layout))
                idx += 1
        s.flush()
    print("injected script + panels", flush=True)

    summary = pipeline.produce(ep_id)
    print("produce:", json.dumps(summary, indent=2, ensure_ascii=False), flush=True)
    if summary["status"] != "awaiting_approval":
        print("produce did not reach awaiting_approval; stopping", flush=True)
        return 1
    pipeline.approve(ep_id)
    print("approved", flush=True)
    out = pipeline.export(ep_id)
    print("export:", json.dumps(out, indent=2, ensure_ascii=False), flush=True)
    src = pipeline.storage.full_path(out["video"])
    print("video at:", src, flush=True)
    shutil.copy2(src, FINAL_MP4)
    print(f"copied to permanent location: {FINAL_MP4} "
          f"({FINAL_MP4.stat().st_size} bytes)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
