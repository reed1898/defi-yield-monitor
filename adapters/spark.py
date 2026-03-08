from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

# ---------------------------------------------------------------------------
# SparkLend pool addresses per chain (Aave v3 Pool interface).
# ---------------------------------------------------------------------------
SPARK_POOLS = {
    "eth": "0xC13e21B648A5Ee794902342038FF3aDAB66BE987",
    "base": "0xA238Dd80C259a72e81d7e4664a9801593F98d1c5",
}

# getUserAccountData(address) selector
GET_USER_ACCOUNT_DATA_SELECTOR = "bf92857c"

# ---------------------------------------------------------------------------
# Spark Savings vaults – ERC-4626 contracts.
# Each vault maps shares → underlying stablecoin.
# ---------------------------------------------------------------------------
SPARK_SAVINGS_VAULTS = {
    "eth": {
        "spUSDC": {
            "vault": "0x28B3a8fb53B741A8Fd78c0fb9A6B2393d896a43d",
            "underlying": "USDC",
            "decimals": 6,
        },
        "spUSDT": {
            "vault": "0xe2e7a17dFf93280dec073C995595155283e3C372",
            "underlying": "USDT",
            "decimals": 6,
        },
        "sUSDS": {
            "vault": "0xa3931d71877C0E7a3148CB7Eb4463524FEc27fbD",
            "underlying": "USDS",
            "decimals": 18,
        },
    },
}

# ERC-4626 / ERC-20 selectors
BALANCE_OF_SELECTOR = "70a08231"         # balanceOf(address)
CONVERT_TO_ASSETS_SELECTOR = "07a2d13a"  # convertToAssets(uint256)

# ---------------------------------------------------------------------------
# RPC endpoints
# ---------------------------------------------------------------------------
DEFAULT_RPC_ENDPOINTS = {
    "eth": [
        "https://eth.llamarpc.com",
        "https://ethereum-rpc.publicnode.com",
        "https://cloudflare-eth.com",
    ],
    "base": [
        "https://mainnet.base.org",
        "https://base-rpc.publicnode.com",
    ],
}
CHAIN_NAMES = {"eth": "ethereum", "base": "base"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _is_evm_address(value: str) -> bool:
    return isinstance(value, str) and value.startswith("0x") and len(value) == 42


def _get_rpc_endpoints(config: dict, chain: str) -> list[str]:
    spark_cfg = config.get("spark") or {}
    rpc_endpoints = spark_cfg.get("rpc_endpoints", {})
    if isinstance(rpc_endpoints, list):
        return rpc_endpoints if chain == "eth" else DEFAULT_RPC_ENDPOINTS.get(chain, [])
    elif isinstance(rpc_endpoints, dict):
        return rpc_endpoints.get(chain, DEFAULT_RPC_ENDPOINTS.get(chain, []))
    return DEFAULT_RPC_ENDPOINTS.get(chain, [])


def _eth_call(endpoint: str, to: str, data: str) -> str | None:
    """Execute a single eth_call and return the hex result, or None on error."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_call",
        "params": [{"to": to, "data": data}, "latest"],
    }
    resp = requests.post(endpoint, json=payload, timeout=20)
    resp.raise_for_status()
    body = resp.json()
    if body.get("error"):
        raise RuntimeError(body["error"])
    result = body.get("result")
    if not result or result == "0x":
        return None
    return result


def _pad_address(wallet: str) -> str:
    return wallet.lower().replace("0x", "").rjust(64, "0")


def _pad_uint256(value: int) -> str:
    return hex(value)[2:].rjust(64, "0")


# ---------------------------------------------------------------------------
# SparkLend (Aave v3 lending pool)
# ---------------------------------------------------------------------------
def _encode_get_user_account_data(wallet: str) -> str:
    return "0x" + GET_USER_ACCOUNT_DATA_SELECTOR + _pad_address(wallet)


def _decode_user_account_data(data: str) -> tuple[float, float, float | None] | None:
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


def _fetch_lend_positions(config: dict) -> list[dict]:
    """Fetch SparkLend (Aave v3 fork) positions."""
    wallets = config.get("wallets", {}).get("evm", [])
    if not wallets:
        return []

    enabled_chains = [
        p.get("chain") for p in config.get("protocols", []) if p.get("name") == "spark"
    ]

    rows: list[dict] = []
    for chain in enabled_chains:
        pool_addr = SPARK_POOLS.get(chain)
        if not pool_addr:
            logging.warning("spark adapter: no pool address for chain %s", chain)
            continue

        endpoints = _get_rpc_endpoints(config, chain)
        chain_name = CHAIN_NAMES.get(chain, chain)

        for wallet in wallets:
            if not _is_evm_address(wallet):
                logging.warning("spark adapter: skip invalid evm wallet: %s", wallet)
                continue

            loaded = False
            for endpoint in endpoints:
                try:
                    call_data = _encode_get_user_account_data(wallet)
                    result = _eth_call(endpoint, pool_addr, call_data)
                    if result is None:
                        continue
                    decoded = _decode_user_account_data(result)
                    if decoded is None:
                        raise ValueError("unexpected eth_call result shape")
                    supplied, borrowed, health_factor = decoded
                    if supplied == 0.0 and borrowed == 0.0:
                        loaded = True
                        break
                    rows.append(
                        {
                            "chain": chain_name,
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
                    logging.warning(
                        "spark lend rpc failed for %s on %s via %s: %s",
                        wallet, chain, endpoint, exc,
                    )
            if not loaded:
                logging.warning(
                    "spark lend: all rpc endpoints failed for %s on %s",
                    wallet, chain,
                )

    return rows


# ---------------------------------------------------------------------------
# Spark Savings (ERC-4626 vaults: spUSDC, spUSDT, sUSDS, …)
# ---------------------------------------------------------------------------
def _fetch_savings_positions(config: dict) -> list[dict]:
    """Fetch Spark Savings vault positions (ERC-4626)."""
    wallets = config.get("wallets", {}).get("evm", [])
    if not wallets:
        return []

    enabled_chains = [
        p.get("chain")
        for p in config.get("protocols", [])
        if p.get("name") == "spark_savings"
    ]

    rows: list[dict] = []
    for chain in enabled_chains:
        vaults = SPARK_SAVINGS_VAULTS.get(chain, {})
        if not vaults:
            logging.warning("spark savings: no vaults configured for chain %s", chain)
            continue

        endpoints = _get_rpc_endpoints(config, chain)
        chain_name = CHAIN_NAMES.get(chain, chain)

        for wallet in wallets:
            if not _is_evm_address(wallet):
                continue

            for vault_symbol, vault_info in vaults.items():
                vault_addr = vault_info["vault"]
                decimals = vault_info["decimals"]
                underlying = vault_info["underlying"]

                fetched = False
                for endpoint in endpoints:
                    try:
                        # 1. balanceOf(wallet) → shares
                        bal_data = "0x" + BALANCE_OF_SELECTOR + _pad_address(wallet)
                        bal_result = _eth_call(endpoint, vault_addr, bal_data)
                        if bal_result is None:
                            continue
                        shares_raw = int(bal_result, 16)
                        if shares_raw == 0:
                            fetched = True
                            break

                        shares_human = shares_raw / (10 ** decimals)

                        # 2. convertToAssets(shares) → underlying amount
                        conv_data = "0x" + CONVERT_TO_ASSETS_SELECTOR + _pad_uint256(shares_raw)
                        conv_result = _eth_call(endpoint, vault_addr, conv_data)
                        if conv_result is None:
                            # Fallback: use shares as value (rate ≈ 1)
                            assets_human = shares_human
                        else:
                            assets_human = int(conv_result, 16) / (10 ** decimals)

                        rows.append(
                            {
                                "chain": chain_name,
                                "protocol": "spark_savings",
                                "vault": vault_symbol,
                                "underlying": underlying,
                                "wallet": wallet,
                                "shares": round(shares_human, decimals),
                                "supplied_usd": round(assets_human, 2),
                                "borrowed_usd": 0.0,
                                "net_value_usd": round(assets_human, 2),
                                "apy_supply": 0.0,
                                "apy_borrow": 0.0,
                                "health_factor": None,
                                "rewards_usd_24h": 0.0,
                                "timestamp": _now_iso(),
                            }
                        )
                        fetched = True
                        break
                    except Exception as exc:
                        logging.warning(
                            "spark savings rpc failed for %s/%s on %s via %s: %s",
                            wallet, vault_symbol, chain, endpoint, exc,
                        )

                if not fetched:
                    logging.warning(
                        "spark savings: all endpoints failed for %s/%s on %s",
                        wallet, vault_symbol, chain,
                    )

    return rows


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def _enrich_savings_apy(rows: list[dict]) -> None:
    """Enrich Spark Savings positions with APY from DefiLlama."""
    try:
        from adapters.defillama import fetch_apy_map, get_spark_savings_apy
        apy_map = fetch_apy_map()
        if not apy_map:
            return
        for row in rows:
            if row.get("protocol") != "spark_savings":
                continue
            underlying = row.get("underlying", "USDC")
            apy = get_spark_savings_apy(apy_map, symbol=underlying)
            if apy > 0:
                row["apy_supply"] = apy
                logging.info("spark savings: %s APY = %.2f%%", underlying, apy * 100)
    except Exception as exc:
        logging.warning("spark savings: failed to enrich APY from DefiLlama: %s", exc)


def fetch_positions(config: dict) -> list[dict]:
    """Fetch all Spark positions (Lend + Savings)."""
    rows: list[dict] = []
    rows.extend(_fetch_lend_positions(config))
    rows.extend(_fetch_savings_positions(config))
    _enrich_savings_apy(rows)
    return rows
