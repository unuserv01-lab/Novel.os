"""Test the B-2-style illustrator on one script (episode 4, Regresi Sang Pedang).

Reads the 12 panels of episode 4 from the DB, builds one illustration
prompt per panel with the style config from Tuan's B-2 screenshot
(dark mode, accent Orange, character mode ancient), and writes the prompts
to ~/workspace/your_files/novelos-v1-illustrator-prompts.txt.

No image is generated here — this is the prompt output only, for Tuan to
review before any render.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from novelos.rooms.manhwa.agents.illustrator import StyleConfig, illustration_prompt  # noqa: E402
from novelos.db import Character, Episode, Location, StoryBible, session_scope  # noqa: E402
from novelos.studio import build  # noqa: E402

OUT_PATH = Path.home() / "workspace" / "your_files" / "novelos-v1-illustrator-prompts.txt"

# Style config = B-2 screenshot (23 Nov 23:10): Dark Mode, Orange, Ancient.
CONFIG = StyleConfig(mode="dark", accent_color="Orange", character_mode="ancient")


def main() -> int:
    p = build()
    lines: list[str] = []
    with session_scope(p.factory) as s:
        ep = s.get(Episode, 4)
        proj = ep.project_id
        sb = s.query(StoryBible).filter_by(project_id=proj).first()
        style = (
            getattr(sb, "style", "")
            or "2D illustrated manhwa, clean line art, cel shading, dramatic "
            "lighting, rich saturated colours, consistent character design, "
            "vertical webtoon framing"
        )
        locs = {l.code: l for l in s.query(Location).filter_by(project_id=proj).all()}
        chs = {c.code: c for c in s.query(Character).filter_by(project_id=proj).all()}

        lines.append("NOVELOS v1 — ILLUSTRATOR TEST (B-2 style)")
        lines.append("Script: " + str((ep.script or {}).get("title", "")))
        lines.append("Episode: 4 — Regresi Sang Pedang (12 panel)")
        lines.append(
            f"Style config: mode={CONFIG.mode}, accent={CONFIG.accent_color}, "
            f"character_mode={CONFIG.character_mode}"
        )
        lines.append("Style global (bible): " + style)
        lines.append("")
        for pn in ep.panels:
            spec = pn.spec or {}
            cast = [chs[c] for c in spec.get("characters", []) if c in chs]
            loc = locs.get(spec.get("location", ""))
            prompt = illustration_prompt(style, pn, cast, loc, CONFIG)
            lines.append("=" * 70)
            lines.append(
                f"PANEL {pn.index + 1} — Scene {pn.scene_no} | "
                f"Kamera: {spec.get('camera', '')} | Emosi: {spec.get('emotion', '')}"
            )
            lines.append("=" * 70)
            lines.append(prompt)
            lines.append("")
    OUT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT_PATH} ({len(lines)} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
