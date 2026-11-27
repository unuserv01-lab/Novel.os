"""Video composition: assemble shot images, TTS audio, camera motion,
transitions and subtitles into one .mp4 via FFmpeg."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------- v2: video composition (FFmpeg)


# Length (seconds) of a crossfade / fade-to-black transition.
FADE_SEC = 0.5


@dataclass
class ShotClip:
    image_path: Path
    audio_path: Path | None
    duration_sec: float
    motion: str = "zoom_in"
    transition: str = "cut"
    subtitles: list[str] = field(default_factory=list)
    subtitle_style: str = "bottom_box"


@dataclass
class VideoComposition:
    video_path: Path
    srt_path: Path
    total_duration_sec: float
    warnings: list[str] = field(default_factory=list)


def _fmt_srt_time(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    hrs, ms = divmod(ms, 3_600_000)
    mins, ms = divmod(ms, 60_000)
    secs, ms = divmod(ms, 1000)
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{ms:03d}"


def _fade_for(d_prev: float, d_next: float) -> float:
    """Crossfade overlap for one join: at most FADE_SEC, at most half the shorter clip."""
    return min(FADE_SEC, 0.5 * min(d_prev, d_next))


def _timeline(clips: list[ShotClip]) -> tuple[list[float], list[float], float]:
    """Effective start time of each clip in the final video, the crossfade
    overlap after each clip, and the total duration.

    A `crossfade` transition overlaps the next clip by `_fade_for(...)`;
    `cut` and `fade_black` do not change durations (fade-to-black is baked
    into the segments themselves). `starts[i]` is shared by the subtitle
    builder and the assembler so both agree on the timeline.
    """
    starts: list[float] = []
    overlaps: list[float] = []
    cursor = 0.0
    for i, clip in enumerate(clips):
        starts.append(cursor)
        if i + 1 < len(clips) and clip.transition == "crossfade":
            ov = _fade_for(clip.duration_sec, clips[i + 1].duration_sec)
        else:
            ov = 0.0
        overlaps.append(ov)
        cursor += clip.duration_sec - ov
    return starts, overlaps, cursor


def build_srt(clips: list[ShotClip], srt_path: Path) -> float:
    """Build the .srt subtitle file on the effective (crossfade-aware) timeline.
    Returns the total video duration in seconds."""
    starts, _, total = _timeline(clips)
    entries: list[str] = []
    idx = 1
    for clip, start in zip(clips, starts):
        end = start + clip.duration_sec
        text = " ".join(clip.subtitles).strip()
        if text and clip.subtitle_style != "none":
            entries.append(f"{idx}\n{_fmt_srt_time(start)} --> {_fmt_srt_time(end)}\n{text}\n")
            idx += 1
    srt_path.parent.mkdir(parents=True, exist_ok=True)
    srt_path.write_text("\n".join(entries), encoding="utf-8")
    return total


def _motion_filter(motion: str, w: int, h: int, frames: int, fps: int) -> str:
    """FFmpeg zoompan filter so a static image feels alive.

    NOTE: `ai_video` is NOT a real motion here — compose_video maps it to
    `zoom_in` and records a warning. True AI video clips (Veo/Kling) are a
    future mode, not implemented in this assembler.
    """
    scale_base = f"scale={w*2}:{h*2}:force_original_aspect_ratio=increase,crop={w*2}:{h*2}"
    if motion == "zoom_out":
        zp = f"zoompan=z='max(1.0,1.15-0.15*on/{frames})':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={fps}"
    elif motion == "pan_left":
        zp = f"zoompan=z='1.12':x='(iw-iw/zoom)*(1-on/{frames})':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={fps}"
    elif motion == "pan_right":
        zp = f"zoompan=z='1.12':x='(iw-iw/zoom)*(on/{frames})':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={fps}"
    elif motion == "static":
        return f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,fps={fps}"
    else:  # zoom_in (and ai_video, mapped by the caller with a warning)
        zp = f"zoompan=z='min(1.15,1.0+0.15*on/{frames})':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={fps}"
    return f"{scale_base},{zp}"


def _run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed ({' '.join(cmd[:6])}...): {(r.stderr or '')[-400:]}")


def _render_segment(clip: ShotClip, index: int, total: int, prev_transition: str | None,
                    w: int, h: int, fps: int, seg_path: Path, warnings: list[str]) -> None:
    """Render one shot to a standalone .mp4 segment (motion + optional fade-to-black)."""
    motion = clip.motion
    if motion == "ai_video":
        warnings.append(f"shot {index + 1}: motion 'ai_video' is not implemented yet — falling back to zoom_in")
        motion = "zoom_in"
    frames = max(int(round(clip.duration_sec * fps)), 1)
    vf = _motion_filter(motion, w, h, frames, fps)
    # fade-to-black: fade in if the previous clip fades out into this one,
    # fade out if this clip fades into the next one. Durations are unchanged.
    fd = min(FADE_SEC, clip.duration_sec / 2)
    if prev_transition == "fade_black":
        vf += f",fade=t=in:st=0:d={fd:.3f}"
    if index + 1 < total and clip.transition == "fade_black":
        vf += f",fade=t=out:st={clip.duration_sec - fd:.3f}:d={fd:.3f}"
    af_parts: list[str] = []
    if prev_transition == "fade_black":
        af_parts.append(f"afade=t=in:st=0:d={fd:.3f}")
    if index + 1 < total and clip.transition == "fade_black":
        af_parts.append(f"afade=t=out:st={clip.duration_sec - fd:.3f}:d={fd:.3f}")

    cmd = ["ffmpeg", "-y", "-loop", "1", "-i", str(clip.image_path)]
    if clip.audio_path and clip.audio_path.exists():
        cmd += ["-i", str(clip.audio_path)]
    else:
        cmd += ["-f", "lavfi", "-t", str(clip.duration_sec), "-i", "anullsrc=r=44100:cl=stereo"]
        warnings.append(f"shot {index + 1}: using silent audio track")
    cmd += [
        "-vf", vf,
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
    ]
    if af_parts:
        cmd += ["-af", ",".join(af_parts)]
    cmd += ["-t", f"{clip.duration_sec:.3f}", str(seg_path)]
    _run(cmd)


def _concat_copy(inputs: list[Path], out_path: Path) -> None:
    """Join files with the concat demuxer (stream copy: no re-encode)."""
    lst = out_path.with_suffix(".txt")
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in inputs), encoding="utf-8")
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(out_path)])


def _xfade_join(a_path: Path, b_path: Path, fade: float, out_path: Path) -> None:
    """Join two files with a real crossfade (xfade + acrossfade, re-encoded
    with the same codec parameters as the segments so later concat-copy
    joins keep working)."""
    a_dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(a_path)],
        capture_output=True, text=True, check=True).stdout.strip())
    offset = max(a_dur - fade, 0.0)
    _run([
        "ffmpeg", "-y", "-i", str(a_path), "-i", str(b_path),
        "-filter_complex",
        f"[0:v][1:v]xfade=transition=fade:duration={fade:.3f}:offset={offset:.3f}[v];"
        f"[0:a][1:a]acrossfade=d={fade:.3f}[a]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
        str(out_path),
    ])


def compose_video(
    clips: list[ShotClip],
    output_path: Path,
    aspect_ratio: str = "16:9",
    fps: int = 24,
    burn_subtitles: bool = True,
) -> VideoComposition:
    """Render each shot to an .mp4 segment, then join them honouring each
    clip's `transition`: `cut` and `fade_black` join by stream copy,
    `crossfade` joins with a real xfade/acrossfade. Subtitles are burned
    from the .srt built on the same effective timeline."""
    if not clips:
        raise ValueError("cannot compose video with 0 clips")
    output_path = Path(output_path)
    w, h = (1280, 720) if aspect_ratio == "16:9" else (720, 1280)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    srt_path = output_path.with_suffix(".srt")
    starts, overlaps, total_dur = _timeline(clips)
    build_srt(clips, srt_path)
    warnings: list[str] = []

    with tempfile.TemporaryDirectory(prefix="novelos_render_") as tmp:
        tmp_dir = Path(tmp)
        seg_paths: list[Path] = []
        for i, clip in enumerate(clips):
            seg_path = tmp_dir / f"seg_{i:04d}.mp4"
            _render_segment(clip, i, len(clips),
                            clips[i - 1].transition if i > 0 else None,
                            w, h, fps, seg_path, warnings)
            seg_paths.append(seg_path)

        # Sequential joins: current holds clips[0..i] joined so far.
        current = seg_paths[0]
        for i in range(1, len(clips)):
            joined = tmp_dir / f"join_{i:04d}.mp4"
            if clips[i - 1].transition == "crossfade":
                _xfade_join(current, seg_paths[i], overlaps[i - 1], joined)
            else:
                _concat_copy([current, seg_paths[i]], joined)
            current = joined

        if burn_subtitles and srt_path.exists() and srt_path.stat().st_size > 0:
            escaped_srt = srt_path.as_posix().replace(":", "\\:")
            style = "FontSize=20,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=3,Outline=1,MarginV=28"
            _run([
                "ffmpeg", "-y", "-i", str(current),
                "-vf", f"subtitles='{escaped_srt}':force_style='{style}'",
                "-c:v", "libx264", "-preset", "veryfast", "-c:a", "copy",
                str(output_path),
            ])
        else:
            shutil.copyfile(current, output_path)

    return VideoComposition(video_path=output_path, srt_path=srt_path, total_duration_sec=total_dur, warnings=warnings)
