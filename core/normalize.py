"""Normalization helpers for adapter outputs."""

from __future__ import annotations


REQUIRED_KEYS = {
    "chain",
    "protocol",
    "wallet",
    "supplied_usd",
    "borrowed_usd",
    "net_value_usd",
    "apy_supply",
    "apy_borrow",
    "health_factor",
    "rewards_usd_24h",
    "timestamp",
}


def normalize_positions(rows: list[dict]) -> list[dict]:
    normalized = []
    for row in rows:
        merged = {k: row.get(k) for k in REQUIRED_KEYS}
        merged.setdefault("supplied_usd", 0.0)
        merged.setdefault("borrowed_usd", 0.0)
        merged.setdefault("net_value_usd", merged["supplied_usd"] - merged["borrowed_usd"])
        merged.setdefault("apy_supply", 0.0)
        merged.setdefault("apy_borrow", 0.0)
        merged.setdefault("health_factor", None)
        merged.setdefault("rewards_usd_24h", 0.0)
        normalized.append(merged)
    return normalized
