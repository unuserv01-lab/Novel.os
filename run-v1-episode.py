"""Run a NovelOS v1-style manhwa episode (vertical PNG + paged PDF).

What this is (honest):
- The pipeline underneath is v2 (Shot schemas, video assembly also runs as a
  by-product). The v1 *export path* is the untouched v1 code: PIL
  `compose()` (vertical stack + dialog bubbles) and `publishing.export()`
  (episode.png + episode.pdf + manifest). Nothing frozen was modified.
- The script content is the real MockText writer's 12 beats for the sample
  project ("Regresi Sang Pedang"), injected with aspect_ratio "9:16" so the
  renders come out portrait (720x1280) like a real webtoon panel. The v1
  drawer then resizes each tile to width 800.
- Dialog kinds: v2 collapsed speech+thought into "dialogue", so the driver
  maps every "dialogue" line to a v1 "speech" bubble (no thought clouds).
  "narration" and "sfx" pass through unchanged.
- Images are MockImage gradients (mock art, same as v1 mock). No API keys used.

Flow: create episode -> inject 9:16 script + panels -> produce (mock) ->
approve -> v1 compose + export -> copy PNG/PDF to ~/workspace/your_files/.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sqlalchemy import select  # noqa: E402

from novelos.rooms.manhwa.agents import director, writer  # noqa: E402
from novelos.db import (  # noqa: E402
    Character,
    Episode,
    GeneratedAsset,
    Location,
    Panel,
    Project,
    StoryBible,
    session_scope,
)
from novelos.rooms.manhwa import publishing  # noqa: E402
from novelos.rooms.manhwa.composition import compose  # noqa: E402
from novelos.studio import build  # noqa: E402

PREMISE = (
    "Kael terbangun tiga tahun sebelum kehancuran, membawa ingatan tentang "
    "kematiannya di Benteng Reruntuhan, dan harus mencegah Pedang Fajar retak."
)
GAP_PX = 12
KIND_MAP = {"dialogue": "speech", "narration": "narration", "sfx": "sfx",
            "thought": "thought", "speech": "speech"}

OUT_DIR = Path.home() / "workspace" / "your_files"


def main() -> int:
    pipeline = build()
    s = pipeline.settings
    print(f"providers: text={s.text_provider} image={s.image_provider} "
          f"tts={s.tts_provider} (must all be mock)", flush=True)
    assert s.text_provider == "mock" and s.image_provider == "mock", \
        "refusing to run: providers are not mock"

    ep_id = pipeline.create_episode("sample-manhwa", PREMISE)
    print(f"episode id: {ep_id}", flush=True)

    # --- inject the mock script with portrait aspect (run-zeno.py pattern) ---
    with session_scope(pipeline.factory) as sess:
        ep = sess.get(Episode, ep_id)
        project = sess.get(Project, ep.project_id)
        bible = sess.scalar(select(StoryBible).where(StoryBible.project_id == project.id))
        cast = list(sess.scalars(select(Character).where(Character.project_id == project.id).order_by(Character.id)))
        locs = list(sess.scalars(select(Location).where(Location.project_id == project.id).order_by(Location.id)))
        script = writer.write_script(
            pipeline.text, ep.premise,
            {"genre": project.genre, "lore": bible.lore if bible else "",
             "rules": bible.world_rules if bible else [], "timeline": bible.timeline if bible else [],
             "style": bible.style if bible else ""},
            [{"code": c.code, "name": c.name, "identity": c.identity, "state": c.state} for c in cast],
            [{"code": x.code, "name": x.name, "description": x.description} for x in locs],
        )
        script.aspect_ratio = "9:16"
        ep.script = script.model_dump()
        idx = 0
        for sc_no, scene in enumerate(script.scenes, 1):
            for shot in scene.shots:
                sess.add(Panel(episode_id=ep.id, index=idx, scene_no=sc_no,
                               spec={k: v for k, v in shot.model_dump().items() if k != "lines"},
                               dialog=[ln.model_dump() for ln in shot.lines]))
                idx += 1
        sess.flush()
    print(f"injected script: {script.title!r}, {idx} shots, aspect 9:16", flush=True)

    # --- run the real pipeline (storyboard, QA, audio, render, assemble) ---
    summary = pipeline.produce(ep_id)
    print("produce:", json.dumps(summary, indent=2, ensure_ascii=False), flush=True)
    if summary["status"] != "awaiting_approval":
        print("produce did not reach awaiting_approval; stopping", flush=True)
        return 1
    pipeline.approve(ep_id)
    print("approved", flush=True)

    # --- v1 export: PIL compose + publishing.export (PNG + PDF) ---
    with session_scope(pipeline.factory) as sess:
        ep = sess.get(Episode, ep_id)
        panels = []
        for p in sorted(ep.panels, key=lambda x: x.index):
            asset = sess.get(GeneratedAsset, p.current_asset_id)
            if asset is None:
                print(f"  panel {p.index + 1}: NO ASSET, skipping", flush=True)
                continue
            png = pipeline.storage.read(asset.path)
            dialog = [{**ln, "kind": KIND_MAP.get(ln.get("kind", "speech"), "speech")}
                      for ln in p.dialog]
            panels.append((png, dialog, GAP_PX))
            print(f"  panel {p.index + 1}: asset {asset.path} "
                  f"({len(png)} bytes, {len(dialog)} dialog lines)", flush=True)
        if not panels:
            print("no rendered panels; stopping", flush=True)
            return 1
        comp = compose(panels)
        print(f"composed: {comp.image.size[0]}x{comp.image.size[1]} px, "
              f"{len(comp.boxes)} panels, warnings={comp.warnings}", flush=True)
        manifest = {
            "episode": ep.number, "title": (ep.script or {}).get("title"),
            "approved_at": ep.approved_at.isoformat() if ep.approved_at else None,
            "format": "v1-manhwa", "aspect_ratio": "9:16", "panels": len(panels),
            "panel_boxes": comp.boxes,
        }
        out = publishing.export(pipeline.storage, ep.number, comp, manifest)
        print("v1 export:", json.dumps(out, indent=2, ensure_ascii=False), flush=True)
        png_src = pipeline.storage.full_path(out["png"])
        pdf_src = pipeline.storage.full_path(out["pdf"])
        png_dst = OUT_DIR / "novelos-v1-episode.png"
        pdf_dst = OUT_DIR / "novelos-v1-episode.pdf"
        shutil.copyfile(png_src, png_dst)
        shutil.copyfile(pdf_src, pdf_dst)
        print(f"copied:\n  {png_dst} ({png_dst.stat().st_size} bytes)"
              f"\n  {pdf_dst} ({pdf_dst.stat().st_size} bytes)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
