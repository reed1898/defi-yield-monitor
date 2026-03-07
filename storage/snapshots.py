from __future__ import annotations

import json
from pathlib import Path


def load_previous_snapshot(path: str) -> dict | None:
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_snapshot(path: str, report: dict, previous: dict | None = None) -> None:
    previous = previous or {}
    history = list(previous.get("history") or [])
    history.append({"timestamp": report.get("generated_at"), "net_value_usd": report.get("net_value_usd", 0.0)})
    history = history[-60:]

    payload = {
        "generated_at": report.get("generated_at"),
        "net_value_usd": report.get("net_value_usd", 0.0),
        "history": history,
        "last_report": report,
    }

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
