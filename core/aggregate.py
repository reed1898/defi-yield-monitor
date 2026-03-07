"""Aggregate normalized protocol positions into a portfolio report."""

from __future__ import annotations

from collections import defaultdict


def aggregate_positions(rows: list[dict], previous: dict | None = None) -> dict:
    previous = previous or {}

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

    prev_net = float(previous.get("net_value_usd") or 0.0)

    return {
        "positions": rows,
        "total_assets_usd": total_assets,
        "total_debt_usd": total_debt,
        "net_value_usd": net_value,
        "pnl_24h_usd": net_value - prev_net if prev_net else 0.0,
        "pnl_7d_usd": 0.0,
        "rewards_24h_usd": rewards_24h,
        "protocol_breakdown": dict(by_protocol),
    }
