"""Export manifest: the approval-stamped record of a finished episode.

Pure function over the episode object (no I/O, no database writes), so
every room builds the same manifest shape.
"""

from __future__ import annotations


def build_manifest(episode, total_duration_sec: float, spent: float) -> dict:
    return {
        "episode": episode.number,
        "title": (episode.script or {}).get("title"),
        "approved_at": episode.approved_at.isoformat(),
        "total_duration_sec": total_duration_sec,
        "shots": [
            {"index": p.index + 1, "asset_id": p.current_asset_id, "lines": p.dialog, "layout": p.layout}
            for p in episode.panels
        ],
        "cost_usd_estimated": spent,
    }
