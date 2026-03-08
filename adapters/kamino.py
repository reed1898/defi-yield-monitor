from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

KAMINO_BASE = "https://api.kamino.finance"
# Kamino API can be slow; use a generous timeout.
KAMINO_TIMEOUT = 60

# Kamino on-chain values use 60-bit scaled fixed-point representation.
SF_DIVISOR = 2**60

# Placeholder reserve address means empty slot.
EMPTY_RESERVE = "11111111111111111111111111111111"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sf_to_float(value) -> float:
    """Convert a Kamino scaled-fixed-point string/int to a float USD value."""
    try:
        return int(value) / SF_DIVISOR
    except (TypeError, ValueError):
        return 0.0


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


def _resolve_health_factor(state: dict) -> float | None:
    """Try multiple paths to extract a health factor."""
    # Direct high-level fields (some API versions may include these)
    hf = _extract_optional_float(
        state,
        [
            "healthFactor",
            "riskMetrics.healthFactor",
            "stats.healthFactor",
        ],
    )
    if hf is not None:
        return hf

    # Compute from deposited vs borrowed if both are non-zero.
    deposited = _sf_to_float(state.get("depositedValueSf", "0"))
    borrowed = _sf_to_float(state.get("borrowedValueSf", "0"))
    if borrowed > 0 and deposited > 0:
        # Simplified: HF ≈ deposited / borrowed (ignoring LTV weights)
        return deposited / borrowed

    return None


def parse_obligation(obligation: dict, wallet: str) -> dict | None:
    """Parse a Kamino obligation object.

    The API returns raw on-chain data.  The obligation wrapper has:
      - obligationAddress: str
      - state: { depositedValueSf, borrowedValueSf, deposits: [...], borrows: [...], ... }

    Values ending in "Sf" are 60-bit scaled fixed-point (divide by 2^60 for USD).
    """
    state = obligation.get("state", obligation)  # fallback: obligation itself is the state

    # --- Try scaled fixed-point fields first (raw on-chain format) ---
    deposited_sf = state.get("depositedValueSf")
    borrowed_sf = state.get("borrowedValueSf")

    if deposited_sf is not None or borrowed_sf is not None:
        supplied = _sf_to_float(deposited_sf or "0")
        borrowed = _sf_to_float(borrowed_sf or "0")
    else:
        # Fallback: try pre-computed USD fields (in case Kamino changes API)
        supplied = _extract_float(
            state,
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
            state,
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

    # Count active deposits and borrows for debugging
    active_deposits = []
    for dep in state.get("deposits", []):
        if isinstance(dep, dict) and dep.get("depositReserve") != EMPTY_RESERVE:
            mv = _sf_to_float(dep.get("marketValueSf", "0"))
            if mv > 0:
                active_deposits.append({
                    "reserve": dep["depositReserve"],
                    "amount_raw": dep.get("depositedAmount", "0"),
                    "market_value_usd": mv,
                })

    active_borrows = []
    for bor in state.get("borrows", []):
        if isinstance(bor, dict) and bor.get("borrowReserve") != EMPTY_RESERVE:
            mv = _sf_to_float(bor.get("marketValueSf", "0"))
            if mv > 0:
                active_borrows.append({
                    "reserve": bor["borrowReserve"],
                    "market_value_usd": mv,
                })

    return {
        "chain": "solana",
        "protocol": "kamino",
        "wallet": wallet,
        "obligation": obligation.get("obligationAddress", ""),
        "supplied_usd": supplied,
        "borrowed_usd": borrowed,
        "net_value_usd": supplied - borrowed,
        "apy_supply": _extract_float(state, ["supplyApy", "depositApy", "apySupply", "rates.supplyApy"]),
        "apy_borrow": _extract_float(state, ["borrowApy", "apyBorrow", "rates.borrowApy"]),
        "health_factor": _resolve_health_factor(state),
        "rewards_usd_24h": _extract_float(state, ["rewardsUsd24h", "rewardUsd24h", "rewards.usd24h"]),
        "deposits_detail": active_deposits,
        "borrows_detail": active_borrows,
        "timestamp": _now_iso(),
    }


def _fetch_reserve_metrics(market: str) -> dict[str, dict]:
    """Fetch reserve-level metrics (APY, TVL, etc.) for a given market.

    Returns a dict keyed by reserve address with supplyApy, borrowApy, etc.
    """
    try:
        url = f"{KAMINO_BASE}/kamino-market/{market}/reserves/metrics"
        resp = requests.get(url, timeout=KAMINO_TIMEOUT)
        if resp.status_code != 200:
            return {}
        reserves = resp.json() or []
        if not isinstance(reserves, list):
            return {}
        result = {}
        for r in reserves:
            addr = r.get("reserve", "")
            if addr:
                result[addr] = {
                    "symbol": r.get("liquidityToken", ""),
                    "supply_apy": _safe_float(r.get("supplyApy")),
                    "borrow_apy": _safe_float(r.get("borrowApy")),
                    "total_supply_usd": _safe_float(r.get("totalSupplyUsd")),
                    "total_borrow_usd": _safe_float(r.get("totalBorrowUsd")),
                    "max_ltv": _safe_float(r.get("maxLtv")),
                }
        return result
    except Exception as exc:
        logging.warning("kamino: failed to fetch reserve metrics for market %s: %s", market[:12], exc)
        return {}


def _safe_float(value) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _enrich_with_reserve_metrics(row: dict, reserve_metrics: dict[str, dict]) -> None:
    """Enrich a position row with APY data from reserve metrics."""
    deposits = row.get("deposits_detail", [])
    if not deposits:
        return

    # Weighted average APY across deposit reserves
    total_value = 0.0
    weighted_apy = 0.0
    symbols = []

    for dep in deposits:
        reserve_addr = dep.get("reserve", "")
        mv = dep.get("market_value_usd", 0.0)
        metrics = reserve_metrics.get(reserve_addr, {})
        apy = metrics.get("supply_apy", 0.0)
        symbol = metrics.get("symbol", "")

        if symbol:
            symbols.append(symbol)
        if mv > 0 and apy > 0:
            weighted_apy += mv * apy
            total_value += mv

    if total_value > 0:
        row["apy_supply"] = weighted_apy / total_value
    if symbols:
        row["assets"] = symbols

    # Same for borrows
    borrows = row.get("borrows_detail", [])
    total_borrow_value = 0.0
    weighted_borrow_apy = 0.0

    for bor in borrows:
        reserve_addr = bor.get("reserve", "")
        mv = bor.get("market_value_usd", 0.0)
        metrics = reserve_metrics.get(reserve_addr, {})
        apy = metrics.get("borrow_apy", 0.0)

        if mv > 0 and apy > 0:
            weighted_borrow_apy += mv * apy
            total_borrow_value += mv

    if total_borrow_value > 0:
        row["apy_borrow"] = weighted_borrow_apy / total_borrow_value


def fetch_positions(config: dict) -> list[dict]:
    wallets = config.get("wallets", {}).get("solana", [])
    if not wallets:
        return []

    rows: list[dict] = []
    try:
        markets_resp = requests.get(f"{KAMINO_BASE}/v2/kamino-market", timeout=KAMINO_TIMEOUT)
        markets_resp.raise_for_status()
        markets = markets_resp.json() or []
    except Exception as exc:
        logging.warning("kamino adapter failed to load markets: %s", exc)
        return []

    market_keys = [m.get("lendingMarket") for m in markets if m.get("lendingMarket")]
    logging.info("kamino: checking %d markets for %d wallets", len(market_keys), len(wallets))

    for wallet in wallets:
        for market in market_keys:
            try:
                url = f"{KAMINO_BASE}/kamino-market/{market}/users/{wallet}/obligations"
                resp = requests.get(url, timeout=KAMINO_TIMEOUT)
                if resp.status_code != 200:
                    continue
                obligations = resp.json() or []
                if not isinstance(obligations, list):
                    logging.warning("kamino obligations malformed for wallet=%s market=%s", wallet, market)
                    continue
            except Exception as exc:
                logging.warning("kamino obligations fetch failed (%s, %s): %s", wallet, market, exc)
                continue

            if not obligations:
                continue

            # Fetch reserve metrics for APY enrichment (only when we have obligations)
            reserve_metrics = _fetch_reserve_metrics(market)

            for obligation in obligations:
                if not isinstance(obligation, dict):
                    continue
                row = parse_obligation(obligation, wallet)
                if row:
                    _enrich_with_reserve_metrics(row, reserve_metrics)
                    logging.info(
                        "kamino: found position in market %s: $%.2f supplied, APY=%.2f%%",
                        market[:12], row["supplied_usd"], row.get("apy_supply", 0) * 100,
                    )
                    rows.append(row)

    logging.info("kamino: total %d positions found", len(rows))
    return rows
