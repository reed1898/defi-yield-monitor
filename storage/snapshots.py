"""Snapshot persistence for report deltas."""

from __future__ import annotations

import json
from pathlib import Path


def load_previous_snapshot(path: str) -> dict | None:
    p = Path(path)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def save_snapshot(path: str, snapshot: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(snapshot, ensure_ascii=True, indent=2), encoding="utf-8")
