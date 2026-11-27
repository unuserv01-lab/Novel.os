"""Run the Zeno/Achilles script through the NovelOS v2 pipeline (driver).

Injects a pre-written, schema-validated Script + per-shot layouts into a fresh
episode, then runs produce -> approve -> export.

Narration audio is pre-made with Muse TTS (id) and injected via the pipeline's
own skip logic: _step_audio skips any panel that already has audio_path +
duration_sec in its layout. This is used because edge-tts (the pipeline's live
TTS path) is blocked in this VM: its endpoint needs the egress proxy + the
system CA bundle, and even with both, Microsoft 403s the WSS handshake from
this VM. See BUILD-LOG.md §8.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from novelos.db import Episode, Panel, session_scope  # noqa: E402
from novelos.libs.models.schemas import Script, ShotDirection  # noqa: E402
from novelos.studio import build  # noqa: E402

SCRIPT_PATH = Path(__file__).resolve().parent / "zeno-script.json"
AUDIO_DIR = Path("/tmp/zeno-narration")

# (motion, transition) per shot: crossfades exercise the fixed xfade join;
# shot 5 fade_black makes shot 5 fade out and shot 6 fade in from black.
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


def main() -> int:
    script = Script.model_validate(json.loads(SCRIPT_PATH.read_text(encoding="utf-8")))
    n_shots = sum(len(s.shots) for s in script.scenes)
    print(f"script valid: {script.title!r}, {n_shots} shots", flush=True)

    pipeline = build()
    ep_id = pipeline.create_episode(
        "sample-manhwa", "Zeno dan Achilles — paradoks tak terhingga")
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
                # Pre-made narration audio for this shot.
                audio_src = AUDIO_DIR / f"s{idx + 1:02d}.mp3"
                if audio_src.exists():
                    rel = pipeline.storage.write(
                        f"audio/ep{ep.number:03d}/s{idx + 1:03d}.mp3",
                        audio_src.read_bytes())
                    layout["audio_path"] = rel
                    layout["duration_sec"] = max(
                        ffprobe_duration(audio_src), 3.0)
                    print(f"  shot {idx + 1}: audio {rel} "
                          f"({layout['duration_sec']}s, {motion}/{transition})",
                          flush=True)
                else:
                    print(f"  shot {idx + 1}: NO AUDIO FILE, will use MockTTS",
                          flush=True)
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
    print("video at:", pipeline.storage.full_path(out["video"]), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
