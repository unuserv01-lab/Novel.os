"""Assembly for the explainer room: stickman frames + narration -> mp4.

Frames are drawn by stickman_draw (PIL), narration is synthesised by the
room's TTS adapter (MockTTS in tests — real silent MP3s with honest
durations), and the join is libs/media compose_video (ffmpeg), the same
assembler the manhwa room uses. 9:16, one clip per scene, static motion so
the board equations stay legible.

Export is a small local copy of the versioned-export shape (never overwrite
an older version). It is deliberately NOT imported from rooms/manhwa:
rooms must not import each other (see tests/core/test_import_rules.py).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sqlalchemy import select

from novelos.db import Episode, GeneratedAsset, Panel
from novelos.libs.media.video import ShotClip, VideoComposition, compose_video

from .stickman_draw import draw_scene


def clips_for_episode(storage, session, ep: Episode) -> list[ShotClip]:
    """One ShotClip per scene panel: drawn frame + TTS audio + narration."""
    clips: list[ShotClip] = []
    for p in sorted(ep.panels, key=lambda p: p.index):
        asset = session.get(GeneratedAsset, p.current_asset_id) if p.current_asset_id else None
        if asset is None:
            raise ValueError(f"scene {p.index + 1} has no drawn frame yet")
        layout = p.layout or {}
        narration = " ".join(ln.get("text", "") for ln in p.dialog).strip()
        audio_rel = layout.get("audio_path")
        clips.append(ShotClip(
            image_path=storage.full_path(asset.path),
            audio_path=storage.full_path(audio_rel) if audio_rel else None,
            duration_sec=float(layout.get("duration_sec") or 3.0),
            motion="static",
            transition="cut",
            subtitles=[narration] if narration else [],
            subtitle_style="bottom_box",
        ))
    if not clips:
        raise ValueError("cannot assemble an episode with 0 scenes")
    return clips


def assemble_preview(storage, session, ep: Episode) -> VideoComposition:
    """Render previews/epNNN.mp4 (9:16) from the episode's drawn scenes."""
    out_rel = f"previews/ep{ep.number:03d}.mp4"
    return compose_video(clips_for_episode(storage, session, ep),
                         storage.full_path(out_rel), aspect_ratio="9:16")


def next_export_version(storage, ep_number: int) -> int:
    v = 1
    while storage.exists(f"exports/ep{ep_number:03d}/v{v}/manifest.json"):
        v += 1
    return v


def export_episode(storage, ep_number: int, comp: VideoComposition, manifest: dict) -> dict:
    """Copy the assembled mp4 + srt + manifest into versioned export dir."""
    v = next_export_version(storage, ep_number)
    base = f"exports/ep{ep_number:03d}/v{v}"
    video_bytes = Path(comp.video_path).read_bytes()
    srt_bytes = Path(comp.srt_path).read_bytes() if Path(comp.srt_path).exists() else b""
    manifest = {**manifest, "version": v, "video_sha256": hashlib.sha256(video_bytes).hexdigest(),
                "total_duration_sec": comp.total_duration_sec, "warnings": comp.warnings}
    storage.write(f"{base}/episode.mp4", video_bytes)
    storage.write(f"{base}/episode.srt", srt_bytes)
    storage.write(f"{base}/manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False).encode())
    return {"version": v, "video": f"{base}/episode.mp4", "srt": f"{base}/episode.srt",
            "manifest": f"{base}/manifest.json", "total_duration_sec": comp.total_duration_sec}
