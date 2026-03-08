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

    # Backward compatible: merge old history with new snapshots timeline.
    timeline = list(previous.get("snapshots") or previous.get("history") or [])
    # Per-protocol breakdown for historical yield tracking
    protocol_snapshot = {}
    for key, data in (report.get("protocol_breakdown") or {}).items():
        protocol_snapshot[key] = {
            "assets_usd": data.get("assets_usd", 0.0),
            "debt_usd": data.get("debt_usd", 0.0),
            "net_value_usd": data.get("net_value_usd", 0.0),
            "apy_supply": data.get("apy_supply"),
            "apy_borrow": data.get("apy_borrow"),
        }

    timeline.append(
        {
            "timestamp": report.get("generated_at"),
            "net_value_usd": report.get("net_value_usd", 0.0),
            "total_assets_usd": report.get("total_assets_usd", 0.0),
            "total_debt_usd": report.get("total_debt_usd", 0.0),
            "protocols": protocol_snapshot,
        }
    )
    timeline = [row for row in timeline if row.get("timestamp")]
    timeline = timeline[-180:]

    payload = {
        "generated_at": report.get("generated_at"),
        "net_value_usd": report.get("net_value_usd", 0.0),
        "history": [{"timestamp": t.get("timestamp"), "net_value_usd": t.get("net_value_usd", 0.0)} for t in timeline],
        "snapshots": timeline,
        "last_report": report,
    }

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
