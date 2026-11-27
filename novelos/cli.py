"""novelos CLI. Typical run:  novelos init && novelos new "premis" && novelos produce 1 && novelos approve 1 && novelos export 1"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from novelos import sample
from novelos.libs.models.adapters import ProviderError
from novelos.pipeline import StateError
from novelos.studio import build

SAMPLE = Path(__file__).resolve().parent.parent / "projects" / "sample-manhwa" / "project.json"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="novelos")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("init", help="create the database and load the sample project")
    pi.add_argument("--project-file", default=str(SAMPLE))
    pi.add_argument("--type", dest="project_type", default=None,
                    help="room for the loaded project: manhwa (default) or explainer")
    pn = sub.add_parser("new", help="create an episode from a premise")
    pn.add_argument("premise")
    pn.add_argument("--project", default="sample-manhwa")
    pn.add_argument("--type", dest="project_type", default=None,
                    help="room to use when the named project does not exist yet (creates it)")
    sub.add_parser("projects", help="list projects with their room type")
    for name in ("produce", "approve", "export", "status"):
        sub.add_parser(name).add_argument("episode", type=int)
    pd = sub.add_parser("edit-narration", help="replace a shot's narration lines (JSON list); only re-renders TTS, never the art")
    pd.add_argument("panel", type=int)
    pd.add_argument("json")
    pd_old = sub.add_parser("edit-dialog", help="(deprecated alias of edit-narration)")
    pd_old.add_argument("panel", type=int)
    pd_old.add_argument("json")
    sub.add_parser("selftest-live", help="one tiny text call + one image call against the configured providers")
    a = ap.parse_args(argv)
    try:
        studio = build()
        if a.cmd == "init":
            slug = sample.load_project(studio.factory, studio.storage, Path(a.project_file),
                                       project_type=a.project_type)
            print(json.dumps({"project": slug, "storage": str(studio.settings.storage_dir)}))
        elif a.cmd == "projects":
            from novelos.db import Project, session_scope
            from sqlalchemy import select
            with session_scope(studio.factory) as s:
                rows = s.scalars(select(Project).order_by(Project.id)).all()
                print(json.dumps([{"slug": p.slug, "name": p.name, "project_type": p.project_type or "manhwa"}
                                  for p in rows], indent=2))
        elif a.cmd == "new":
            if a.project_type is not None:
                sample.ensure_project(studio.factory, a.project, a.project_type)
            print(json.dumps({"episode_id": studio.create_episode(a.project, a.premise)}))
        elif a.cmd == "produce":
            print(json.dumps(studio.produce(a.episode), indent=2))
        elif a.cmd == "status":
            print(json.dumps(studio.status(a.episode), indent=2))
        elif a.cmd == "approve":
            studio.approve(a.episode)
            print(json.dumps({"approved": a.episode}))
        elif a.cmd == "export":
            print(json.dumps(studio.export(a.episode), indent=2))
        elif a.cmd in ("edit-narration", "edit-dialog"):
            studio.edit_narration(a.panel, json.loads(a.json))
            print(json.dumps({"updated_panel": a.panel, "approval_reset": True}))
        elif a.cmd == "selftest-live":
            r = studio.text.complete_json("review", "Return JSON {\"ok\": true}.", "ping", {})
            png = studio.image.generate("A simple red circle on white. No text.", [], (256, 256))
            print(json.dumps({"text_ok": r, "image_bytes": len(png)}))
    except (StateError, ProviderError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
