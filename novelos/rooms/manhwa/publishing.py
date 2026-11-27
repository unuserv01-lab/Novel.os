"""Episode Publisher: approval-gated export with an immutable, versioned archive.

v1 (manhwa): long PNG + paged PDF from a PIL Composition.
v2 (video): .mp4 + .srt copied from a VideoComposition.
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

from PIL import Image

from novelos.libs.media.video import VideoComposition
from novelos.rooms.manhwa.composition import Composition

PAGE_H = 1600  # PDF page height at 800 px width; the tallest allowed panel (1.8 x 800 = 1440) fits


def build_pdf(comp: Composition) -> bytes:
    """Pack whole panels into pages so no panel is cut in half."""
    pages, start, end = [], None, 0
    for i, (y0, y1) in enumerate(comp.boxes):
        if start is None:
            start, end = y0, y1
        elif y1 - start <= PAGE_H:
            end = y1
        else:
            pages.append((start, end))
            start, end = y0, y1
    if start is not None:
        pages.append((start, end))
    imgs = []
    for a, b in pages:
        page = Image.new("RGB", (comp.image.width, b - a), (255, 255, 255))
        page.paste(comp.image.crop((0, a, comp.image.width, b)), (0, 0))
        imgs.append(page)
    buf = io.BytesIO()
    imgs[0].save(buf, "PDF", save_all=True, append_images=imgs[1:], resolution=100)
    return buf.getvalue()


def next_export_version(storage, ep_number: int) -> int:
    v = 1
    while storage.exists(f"exports/ep{ep_number:03d}/v{v}/manifest.json"):
        v += 1
    return v


def export(storage, ep_number: int, comp: Composition | VideoComposition, manifest: dict) -> dict:
    v = next_export_version(storage, ep_number)
    base = f"exports/ep{ep_number:03d}/v{v}"
    if isinstance(comp, VideoComposition):
        video_bytes = Path(comp.video_path).read_bytes()
        srt_bytes = Path(comp.srt_path).read_bytes() if Path(comp.srt_path).exists() else b""
        manifest = {**manifest, "version": v, "video_sha256": hashlib.sha256(video_bytes).hexdigest(),
                    "total_duration_sec": comp.total_duration_sec, "warnings": comp.warnings}
        storage.write(f"{base}/episode.mp4", video_bytes)
        storage.write(f"{base}/episode.srt", srt_bytes)
        storage.write(f"{base}/manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False).encode())
        return {"version": v, "video": f"{base}/episode.mp4", "srt": f"{base}/episode.srt",
                "manifest": f"{base}/manifest.json", "video_bytes": len(video_bytes),
                "total_duration_sec": comp.total_duration_sec, "warnings": comp.warnings}
    png = io.BytesIO()
    comp.image.save(png, "PNG")
    png_bytes = png.getvalue()
    pdf_bytes = build_pdf(comp)
    manifest = {**manifest, "version": v, "png_sha256": hashlib.sha256(png_bytes).hexdigest(), "warnings": comp.warnings}
    storage.write(f"{base}/episode.png", png_bytes)
    storage.write(f"{base}/episode.pdf", pdf_bytes)
    storage.write(f"{base}/manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False).encode())
    return {"version": v, "png": f"{base}/episode.png", "pdf": f"{base}/episode.pdf", "manifest": f"{base}/manifest.json",
            "png_bytes": len(png_bytes), "pdf_bytes": len(pdf_bytes), "warnings": comp.warnings}
