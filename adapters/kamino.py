from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

KAMINO_BASE = "https://api.kamino.finance"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _extract_float(obj: dict, keys: list[str]) -> float:
    for key in keys:
        value = obj.get(key)
        if value is not None:
            try:
                return float(value)
            except Exception:
                pass
    return 0.0


def fetch_positions(config: dict) -> list[dict]:
    wallets = config.get("wallets", {}).get("solana", [])
    if not wallets:
        return []

    rows: list[dict] = []
    try:
        markets = requests.get(f"{KAMINO_BASE}/v2/kamino-market", timeout=20).json()
    except Exception as exc:
        logging.warning("kamino adapter failed to load markets: %s", exc)
        return []

    market_keys = [m.get("lendingMarket") for m in markets if m.get("lendingMarket")]
    for wallet in wallets:
        for market in market_keys:
            try:
                url = f"{KAMINO_BASE}/kamino-market/{market}/users/{wallet}/obligations"
                resp = requests.get(url, timeout=20)
                if resp.status_code != 200:
                    continue
                obligations = resp.json() or []
            except Exception as exc:
                logging.warning("kamino obligations fetch failed (%s, %s): %s", wallet, market, exc)
                continue

            for obligation in obligations:
                supplied = _extract_float(obligation, ["totalSupplyUsd", "depositedValueUsd", "depositsUsd", "totalDepositsUsd"])
                borrowed = _extract_float(obligation, ["totalBorrowUsd", "borrowedValueUsd", "borrowsUsd", "totalBorrowsUsd"])
                if supplied == 0.0 and borrowed == 0.0:
                    continue
                rows.append(
                    {
                        "chain": "solana",
                        "protocol": "kamino",
                        "wallet": wallet,
                        "supplied_usd": supplied,
                        "borrowed_usd": borrowed,
                        "net_value_usd": supplied - borrowed,
                        "apy_supply": _extract_float(obligation, ["supplyApy", "depositApy", "apySupply"]),
                        "apy_borrow": _extract_float(obligation, ["borrowApy", "apyBorrow"]),
                        "health_factor": obligation.get("healthFactor") or obligation.get("loanToValue"),
                        "rewards_usd_24h": _extract_float(obligation, ["rewardsUsd24h", "rewardUsd24h"]),
                        "timestamp": _now_iso(),
                    }
                )
    return rows
