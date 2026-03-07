from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

# SparkLend mainnet pool (from Spark app config, reproducible on-chain source).
SPARK_ETH_POOL = "0xC13e21B648A5Ee794902342038FF3aDAB66BE987"
# getUserAccountData(address)
GET_USER_ACCOUNT_DATA_SELECTOR = "bf92857c"
# Public RPC fallbacks; can be overridden in config.spark.rpc_endpoints.
DEFAULT_RPC_ENDPOINTS = [
    "https://eth.llamarpc.com",
    "https://ethereum-rpc.publicnode.com",
    "https://cloudflare-eth.com",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _is_evm_address(value: str) -> bool:
    return isinstance(value, str) and value.startswith("0x") and len(value) == 42


def _encode_get_user_account_data(wallet: str) -> str:
    wallet_hex = wallet.lower().replace("0x", "")
    return "0x" + GET_USER_ACCOUNT_DATA_SELECTOR + wallet_hex.rjust(64, "0")


def _decode_user_account_data(data: str) -> tuple[float, float, float] | None:
    if not isinstance(data, str) or not data.startswith("0x"):
        return None
    raw = data[2:]
    if len(raw) < 64 * 6:
        return None

    words = [int(raw[i : i + 64], 16) for i in range(0, 64 * 6, 64)]
    total_collateral_base = words[0] / 1e8
    total_debt_base = words[1] / 1e8
    health_factor_raw = words[5]
    health_factor = (health_factor_raw / 1e18) if health_factor_raw > 0 else None
    return total_collateral_base, total_debt_base, health_factor


def _fetch_from_rpc(endpoint: str, wallet: str) -> tuple[float, float, float | None] | None:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_call",
        "params": [
            {
                "to": SPARK_ETH_POOL,
                "data": _encode_get_user_account_data(wallet),
            },
            "latest",
        ],
    }
    resp = requests.post(endpoint, json=payload, timeout=20)
    resp.raise_for_status()
    body = resp.json()
    if body.get("error"):
        raise RuntimeError(body["error"])

    decoded = _decode_user_account_data(body.get("result"))
    if decoded is None:
        raise ValueError("unexpected eth_call result shape")

    supplied, borrowed, hf = decoded
    return supplied, borrowed, hf


def fetch_positions(config: dict) -> list[dict]:
    wallets = config.get("wallets", {}).get("evm", [])
    if not wallets:
        return []

    spark_cfg = config.get("spark") or {}
    rpc_endpoints = spark_cfg.get("rpc_endpoints") or DEFAULT_RPC_ENDPOINTS

    rows: list[dict] = []
    for wallet in wallets:
        if not _is_evm_address(wallet):
            logging.warning("spark adapter: skip invalid evm wallet format: %s", wallet)
            continue

        loaded = False
        for endpoint in rpc_endpoints:
            try:
                result = _fetch_from_rpc(endpoint, wallet)
                if result is None:
                    continue
                supplied, borrowed, health_factor = result
                rows.append(
                    {
                        "chain": "ethereum",
                        "protocol": "spark",
                        "wallet": wallet,
                        "supplied_usd": supplied,
                        "borrowed_usd": borrowed,
                        "net_value_usd": supplied - borrowed,
                        "apy_supply": 0.0,
                        "apy_borrow": 0.0,
                        "health_factor": health_factor,
                        "rewards_usd_24h": 0.0,
                        "timestamp": _now_iso(),
                    }
                )
                loaded = True
                break
            except Exception as exc:
                logging.warning("spark adapter rpc failed for %s via %s: %s", wallet, endpoint, exc)

        if not loaded:
            logging.warning("spark adapter: all rpc endpoints failed for wallet %s (degraded)", wallet)

    return rows
