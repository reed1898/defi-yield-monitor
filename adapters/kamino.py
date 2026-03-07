from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

KAMINO_BASE = "https://api.kamino.finance"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _get_nested(obj: dict, path: str):
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
        if cur is None:
            return None
    return cur


def _extract_float(obj: dict, paths: list[str]) -> float:
    for path in paths:
        value = _get_nested(obj, path)
        if value is None:
            continue
        try:
            return float(value)
        except Exception:
            continue
    return 0.0


def _extract_optional_float(obj: dict, paths: list[str]) -> float | None:
    for path in paths:
        value = _get_nested(obj, path)
        if value is None:
            continue
        try:
            return float(value)
        except Exception:
            continue
    return None


def _resolve_health_factor(obligation: dict) -> float | None:
    hf = _extract_optional_float(
        obligation,
        [
            "healthFactor",
            "riskMetrics.healthFactor",
            "stats.healthFactor",
        ],
    )
    if hf is not None:
        return hf

    # Fallback for responses that only provide LTV-like values.
    ltv = _extract_optional_float(
        obligation,
        [
            "loanToValue",
            "currentLtv",
            "riskMetrics.loanToValue",
            "riskMetrics.currentLtv",
        ],
    )
    if ltv is None or ltv <= 0:
        return None
    if ltv > 1:
        ltv = ltv / 100.0
    if ltv <= 0 or ltv >= 1:
        return None
    return 1.0 / ltv


def parse_obligation(obligation: dict, wallet: str) -> dict | None:
    supplied = _extract_float(
        obligation,
        [
            "totalSupplyUsd",
            "depositedValueUsd",
            "depositsUsd",
            "totalDepositsUsd",
            "totals.depositsUsd",
            "position.supplyUsd",
        ],
    )
    borrowed = _extract_float(
        obligation,
        [
            "totalBorrowUsd",
            "borrowedValueUsd",
            "borrowsUsd",
            "totalBorrowsUsd",
            "totals.borrowsUsd",
            "position.borrowUsd",
        ],
    )
    if supplied == 0.0 and borrowed == 0.0:
        return None

    return {
        "chain": "solana",
        "protocol": "kamino",
        "wallet": wallet,
        "supplied_usd": supplied,
        "borrowed_usd": borrowed,
        "net_value_usd": supplied - borrowed,
        "apy_supply": _extract_float(obligation, ["supplyApy", "depositApy", "apySupply", "rates.supplyApy"]),
        "apy_borrow": _extract_float(obligation, ["borrowApy", "apyBorrow", "rates.borrowApy"]),
        "health_factor": _resolve_health_factor(obligation),
        "rewards_usd_24h": _extract_float(obligation, ["rewardsUsd24h", "rewardUsd24h", "rewards.usd24h"]),
        "timestamp": _now_iso(),
    }


def fetch_positions(config: dict) -> list[dict]:
    wallets = config.get("wallets", {}).get("solana", [])
    if not wallets:
        return []

    rows: list[dict] = []
    try:
        markets_resp = requests.get(f"{KAMINO_BASE}/v2/kamino-market", timeout=20)
        markets_resp.raise_for_status()
        markets = markets_resp.json() or []
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
                if not isinstance(obligations, list):
                    logging.warning("kamino obligations malformed for wallet=%s market=%s", wallet, market)
                    continue
            except Exception as exc:
                logging.warning("kamino obligations fetch failed (%s, %s): %s", wallet, market, exc)
                continue

            for obligation in obligations:
                if not isinstance(obligation, dict):
                    continue
                row = parse_obligation(obligation, wallet)
                if row:
                    rows.append(row)

    return rows
