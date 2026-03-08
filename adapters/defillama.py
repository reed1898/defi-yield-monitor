"""Fetch APY data from DefiLlama yields API as a supplementary data source."""

from __future__ import annotations

import logging

import requests

DEFILLAMA_YIELDS_URL = "https://yields.llama.fi/pools"
DEFILLAMA_TIMEOUT = 20


def fetch_apy_map() -> dict[str, dict]:
    """Fetch APY data and return a lookup dict keyed by (project, chain, symbol).

    Returns dict like:
        {
            "spark-savings:Ethereum:USDC": {"apy": 4.0, "tvl_usd": 376635699},
            "sparklend:Ethereum:USDS": {"apy": 4.03, "tvl_usd": 553036594},
            ...
        }
    """
    try:
        resp = requests.get(DEFILLAMA_YIELDS_URL, timeout=DEFILLAMA_TIMEOUT)
        resp.raise_for_status()
        pools = resp.json().get("data", [])
    except Exception as exc:
        logging.warning("defillama: failed to fetch yields: %s", exc)
        return {}

    result = {}
    for pool in pools:
        project = (pool.get("project") or "").lower()
        chain = pool.get("chain", "")
        symbol = (pool.get("symbol") or "").upper()
        apy = pool.get("apy")
        tvl = pool.get("tvlUsd", 0)

        if apy is None:
            continue

        key = f"{project}:{chain}:{symbol}"
        result[key] = {
            "apy": float(apy),
            "tvl_usd": float(tvl or 0),
            "pool_id": pool.get("pool", ""),
        }

    return result


def get_spark_savings_apy(apy_map: dict, symbol: str = "USDC", chain: str = "Ethereum") -> float:
    """Get Spark Savings APY for a given symbol."""
    key = f"spark-savings:{chain}:{symbol.upper()}"
    entry = apy_map.get(key)
    if entry:
        return entry["apy"] / 100.0  # Convert percentage to decimal
    return 0.0


def get_aave_apy(apy_map: dict, symbol: str, chain: str = "Ethereum") -> float:
    """Get Aave v3 APY for a given symbol."""
    key = f"aave-v3:{chain}:{symbol.upper()}"
    entry = apy_map.get(key)
    if entry:
        return entry["apy"] / 100.0
    return 0.0
