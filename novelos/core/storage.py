"""Local filesystem asset storage (swap for S3 later behind the same three methods)."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path


class Storage:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _safe(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if self.root != p and self.root not in p.parents:
            raise ValueError(f"path escapes storage: {rel}")
        return p

    def write(self, rel: str, data: bytes) -> str:
        p = self._safe(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, p)  # atomic: a crash never leaves a half-written asset
        return rel

    def read(self, rel: str) -> bytes:
        return self._safe(rel).read_bytes()

    def exists(self, rel: str) -> bool:
        return self._safe(rel).exists()

    def full_path(self, rel: str) -> Path:
        """Absolute on-disk path for a stored relative path (FFmpeg needs real
        files, not bytes in memory). Same traversal guard as read/write."""
        return self._safe(rel)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
