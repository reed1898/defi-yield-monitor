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
    candidates = []
    for item in history:
        ts = _parse_ts(item.get("timestamp"))
        if ts and ts <= cutoff:
            candidates.append((ts, item))
    if not candidates:
        return None
    latest = sorted(candidates, key=lambda x: x[0])[-1][1]
    return float(latest.get("net_value_usd") or 0.0)


def aggregate_positions(rows: list[dict], previous: dict | None = None, thresholds: dict | None = None) -> dict:
    previous = previous or {}
    thresholds = thresholds or {}

    total_assets = sum(float(r.get("supplied_usd") or 0.0) for r in rows)
    total_debt = sum(float(r.get("borrowed_usd") or 0.0) for r in rows)
    net_value = total_assets - total_debt
    rewards_24h = sum(float(r.get("rewards_usd_24h") or 0.0) for r in rows)

    by_protocol = defaultdict(lambda: {"assets_usd": 0.0, "debt_usd": 0.0, "net_value_usd": 0.0, "apy_supply": None, "apy_borrow": None, "assets": [], "native_amount": 0.0, "native_symbol": ""})
    for r in rows:
        key = f"{r.get('chain')}:{r.get('protocol')}"
        by_protocol[key]["assets_usd"] += float(r.get("supplied_usd") or 0.0)
        by_protocol[key]["debt_usd"] += float(r.get("borrowed_usd") or 0.0)
        by_protocol[key]["net_value_usd"] += float(r.get("net_value_usd") or 0.0)
        # Track APY (weighted average if multiple positions per protocol)
        supply_apy = r.get("apy_supply")
        if supply_apy and float(supply_apy) > 0:
            by_protocol[key]["apy_supply"] = float(supply_apy)
        borrow_apy = r.get("apy_borrow")
        if borrow_apy and float(borrow_apy) > 0:
            by_protocol[key]["apy_borrow"] = float(borrow_apy)
        if r.get("assets"):
            by_protocol[key]["assets"].extend(r["assets"])
        native_amount = float(r.get("native_amount") or 0.0)
        native_symbol = str(r.get("native_symbol") or "")
        if native_amount > 0:
            by_protocol[key]["native_amount"] += native_amount
        if native_symbol and not by_protocol[key]["native_symbol"]:
            by_protocol[key]["native_symbol"] = native_symbol

    now = datetime.now(timezone.utc)
    history = list(previous.get("snapshots") or previous.get("history") or [])
    base_24h = _find_baseline(history, now, timedelta(hours=24))
    base_7d = _find_baseline(history, now, timedelta(days=7))

    pnl_24h = (net_value - base_24h) if base_24h is not None else None
    pnl_7d = (net_value - base_7d) if base_7d is not None else None

    min_hf = thresholds.get("min_health_factor")
    max_drawdown_pct = thresholds.get("max_daily_drawdown_pct")
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
            risk_rows.append(
                {
                    "type": "health_factor",
                    "wallet": r.get("wallet"),
                    "protocol": r.get("protocol"),
                    "chain": r.get("chain"),
                    "health_factor": hf_val,
                    "threshold": float(min_hf),
                }
            )

    drawdown_pct_24h = None
    if base_24h and base_24h > 0:
        drawdown_pct_24h = ((base_24h - net_value) / base_24h) * 100.0
        if max_drawdown_pct is not None and drawdown_pct_24h > float(max_drawdown_pct):
            risk_rows.append(
                {
                    "type": "daily_drawdown",
                    "drawdown_pct": drawdown_pct_24h,
                    "threshold": float(max_drawdown_pct),
                    "baseline_24h_usd": base_24h,
                    "current_net_value_usd": net_value,
                }
            )

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
        "drawdown_24h_pct": drawdown_pct_24h,
        "notes": {
            "pnl_24h": "insufficient history" if pnl_24h is None else "ok",
            "pnl_7d": "insufficient history" if pnl_7d is None else "ok",
            "baseline_24h": "missing" if base_24h is None else "ok",
            "baseline_7d": "missing" if base_7d is None else "ok",
        },
    }
