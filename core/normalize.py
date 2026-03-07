from __future__ import annotations

REQUIRED_KEYS = [
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
]


def normalize_positions(rows: list[dict]) -> list[dict]:
    normalized: list[dict] = []
    for row in rows:
        item = {k: row.get(k) for k in REQUIRED_KEYS}
        item["chain"] = str(item.get("chain") or "unknown").lower()
        item["protocol"] = str(item.get("protocol") or "unknown").lower()
        item["wallet"] = str(item.get("wallet") or "")
        item["supplied_usd"] = float(item.get("supplied_usd") or 0.0)
        item["borrowed_usd"] = float(item.get("borrowed_usd") or 0.0)
        item["net_value_usd"] = float(item.get("net_value_usd") or (item["supplied_usd"] - item["borrowed_usd"]))
        item["apy_supply"] = float(item.get("apy_supply") or 0.0)
        item["apy_borrow"] = float(item.get("apy_borrow") or 0.0)
        item["health_factor"] = item.get("health_factor")
        item["rewards_usd_24h"] = float(item.get("rewards_usd_24h") or 0.0)
        item["timestamp"] = item.get("timestamp")
        normalized.append(item)
    return normalized
