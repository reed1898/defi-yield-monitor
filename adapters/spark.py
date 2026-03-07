from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

# Spark public API is not consistently documented. We try known endpoints and degrade safely.
SPARK_CANDIDATE_ENDPOINTS = [
    "https://api-v2.spark.fi/api/v1/spark/positions/{wallet}",
    "https://api-v2.spark.fi/api/v1/spark/lend/{wallet}",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def fetch_positions(config: dict) -> list[dict]:
    wallets = config.get("wallets", {}).get("evm", [])
    if not wallets:
        return []

    rows: list[dict] = []
    for wallet in wallets:
        loaded = False
        for endpoint in SPARK_CANDIDATE_ENDPOINTS:
            url = endpoint.format(wallet=wallet)
            try:
                resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
                if resp.status_code != 200:
                    continue
                payload = resp.json()
                supplied = float(payload.get("supplied_usd") or payload.get("totalCollateralBase") or 0.0)
                borrowed = float(payload.get("borrowed_usd") or payload.get("totalDebtBase") or 0.0)
                rows.append(
                    {
                        "chain": "ethereum",
                        "protocol": "spark",
                        "wallet": wallet,
                        "supplied_usd": supplied,
                        "borrowed_usd": borrowed,
                        "net_value_usd": float(payload.get("net_value_usd") or supplied - borrowed),
                        "apy_supply": float(payload.get("apy_supply") or 0.0),
                        "apy_borrow": float(payload.get("apy_borrow") or 0.0),
                        "health_factor": payload.get("health_factor"),
                        "rewards_usd_24h": float(payload.get("rewards_usd_24h") or 0.0),
                        "timestamp": _now_iso(),
                    }
                )
                loaded = True
                break
            except Exception as exc:
                logging.warning("spark adapter error for %s (%s): %s", wallet, url, exc)
        if not loaded:
            logging.warning("spark adapter: no usable public endpoint for wallet %s (degraded)", wallet)
    return rows
