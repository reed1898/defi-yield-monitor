from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _find_baseline(history: list[dict], now: datetime, delta: timedelta) -> float | None:
    cutoff = now - delta
    candidates = [h for h in history if _parse_ts(h.get("timestamp")) and _parse_ts(h.get("timestamp")) <= cutoff]
    if not candidates:
        return None
    latest = sorted(candidates, key=lambda x: _parse_ts(x.get("timestamp")))[-1]
    return float(latest.get("net_value_usd") or 0.0)


def aggregate_positions(rows: list[dict], previous: dict | None = None, thresholds: dict | None = None) -> dict:
    previous = previous or {}
    thresholds = thresholds or {}

    total_assets = sum(float(r.get("supplied_usd") or 0.0) for r in rows)
    total_debt = sum(float(r.get("borrowed_usd") or 0.0) for r in rows)
    net_value = total_assets - total_debt
    rewards_24h = sum(float(r.get("rewards_usd_24h") or 0.0) for r in rows)

    by_protocol = defaultdict(lambda: {"assets_usd": 0.0, "debt_usd": 0.0, "net_value_usd": 0.0})
    for r in rows:
        key = f"{r.get('chain')}:{r.get('protocol')}"
        by_protocol[key]["assets_usd"] += float(r.get("supplied_usd") or 0.0)
        by_protocol[key]["debt_usd"] += float(r.get("borrowed_usd") or 0.0)
        by_protocol[key]["net_value_usd"] += float(r.get("net_value_usd") or 0.0)

    now = datetime.now(timezone.utc)
    history = list(previous.get("history") or [])
    base_24h = _find_baseline(history, now, timedelta(hours=24))
    base_7d = _find_baseline(history, now, timedelta(days=7))

    pnl_24h = (net_value - base_24h) if base_24h is not None else None
    pnl_7d = (net_value - base_7d) if base_7d is not None else None

    min_hf = thresholds.get("min_health_factor")
    risk_rows = []
    for r in rows:
        hf = r.get("health_factor")
        if hf is None:
            continue
        try:
            hf_val = float(hf)
        except Exception:
            continue
        if min_hf is not None and hf_val < float(min_hf):
            risk_rows.append({"wallet": r.get("wallet"), "protocol": r.get("protocol"), "chain": r.get("chain"), "health_factor": hf_val})

    return {
        "generated_at": now.replace(microsecond=0).isoformat(),
        "positions": rows,
        "total_assets_usd": total_assets,
        "total_debt_usd": total_debt,
        "net_value_usd": net_value,
        "pnl_24h_usd": pnl_24h,
        "pnl_7d_usd": pnl_7d,
        "rewards_24h_usd": rewards_24h,
        "protocol_breakdown": dict(by_protocol),
        "risk_flags": risk_rows,
        "notes": {
            "pnl_24h": "insufficient history" if pnl_24h is None else "ok",
            "pnl_7d": "insufficient history" if pnl_7d is None else "ok",
        },
    }
