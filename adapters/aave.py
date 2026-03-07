from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

AAVE_GQL = "https://api.v3.aave.com/graphql"
AAVE_CHAIN_IDS = {"eth": 1, "bsc": 56}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def fetch_positions(config: dict) -> list[dict]:
    wallets = config.get("wallets", {}).get("evm", [])
    chains = [p.get("chain") for p in config.get("protocols", []) if p.get("name") == "aave"]
    chain_ids = [AAVE_CHAIN_IDS[c] for c in chains if c in AAVE_CHAIN_IDS]
    if not wallets or not chain_ids:
        return []

    query = (
        "query($chainIds:[Int!]!, $user:EvmAddress){"
        "markets(request:{chainIds:$chainIds,user:$user}){"
        "name chain{chainId name} "
        "userState{totalCollateralBase totalDebtBase netWorth healthFactor netAPY{value} userDebtAPY{value}}"
        "}}"
    )

    rows: list[dict] = []
    for wallet in wallets:
        try:
            resp = requests.post(
                AAVE_GQL,
                json={"query": query, "variables": {"chainIds": chain_ids, "user": wallet}},
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logging.warning("aave adapter request failed for %s: %s", wallet, exc)
            continue

        if data.get("errors"):
            logging.warning("aave adapter graphql errors for %s: %s", wallet, data.get("errors"))
            continue

        markets = (data.get("data") or {}).get("markets", [])
        for market in markets:
            state = market.get("userState") or {}
            supplied = float(state.get("totalCollateralBase") or 0.0)
            borrowed = float(state.get("totalDebtBase") or 0.0)
            if supplied == 0.0 and borrowed == 0.0:
                continue
            rows.append(
                {
                    "chain": (market.get("chain") or {}).get("name", "unknown").lower(),
                    "protocol": "aave",
                    "wallet": wallet,
                    "supplied_usd": supplied,
                    "borrowed_usd": borrowed,
                    "net_value_usd": float(state.get("netWorth") or supplied - borrowed),
                    "apy_supply": float((state.get("netAPY") or {}).get("value") or 0.0) * 100.0,
                    "apy_borrow": float((state.get("userDebtAPY") or {}).get("value") or 0.0) * 100.0,
                    "health_factor": state.get("healthFactor"),
                    "rewards_usd_24h": 0.0,
                    "timestamp": _now_iso(),
                }
            )
    return rows
