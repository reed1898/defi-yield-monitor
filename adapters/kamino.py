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

    ltv = _extract_optional_float(
        state,
        [
            "currentLtv",
            "loanToValue",
            "riskMetrics.loanToValue",
            "riskMetrics.currentLtv",
        ],
    )
    if ltv is not None and ltv > 0:
        ltv_ratio = ltv / 100.0 if ltv > 1 else ltv
        if ltv_ratio > 0:
            return 1.0 / ltv_ratio

    deposited = _sf_to_float(state.get("depositedValueSf", "0"))
    borrowed = _sf_to_float(state.get("borrowedValueSf", "0"))
    if borrowed > 0 and deposited > 0:
        return deposited / borrowed

    return None


def _extract_native_amount(active_deposits: list[dict], reserve_metrics: dict[str, dict], supplied_usd: float | None = None) -> tuple[float | None, str | None]:
    if len(active_deposits) != 1:
        return None, None

    dep = active_deposits[0]
    reserve_addr = dep.get("reserve", "")
    metrics = reserve_metrics.get(reserve_addr, {})
    symbol = metrics.get("symbol") or None
    market_value_usd = float(supplied_usd or dep.get("market_value_usd") or 0.0)
    price_usd = float(metrics.get("price_usd") or 0.0)

    if market_value_usd > 0 and price_usd > 0:
        return market_value_usd / price_usd, symbol

    return None, symbol


def parse_obligation(obligation: dict, wallet: str) -> dict | None:
    """Parse a Kamino obligation object.

    The API returns raw on-chain data.  The obligation wrapper has:
      - obligationAddress: str
      - state: { depositedValueSf, borrowedValueSf, deposits: [...], borrows: [...], ... }

    Values ending in "Sf" are 60-bit scaled fixed-point (divide by 2^60 for USD).
    """
    state = obligation.get("state", obligation)  # fallback: obligation itself is the state

    supplied = _extract_float(
        obligation,
        [
            "refreshedStats.userTotalDeposit",
            "refreshedStats.userTotalCollateralDeposit",
        ],
    )
    borrowed = _extract_float(
        obligation,
        [
            "refreshedStats.userTotalBorrow",
            "refreshedStats.userTotalBorrowBorrowFactorAdjusted",
        ],
    )

    if supplied == 0.0 and borrowed == 0.0:
        deposited_sf = state.get("depositedValueSf")
        borrowed_sf = state.get("borrowedValueSf")

        if deposited_sf is not None or borrowed_sf is not None:
            supplied = _sf_to_float(deposited_sf or "0")
            borrowed = _sf_to_float(borrowed_sf or "0")
        else:
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
            amount_raw = dep.get("depositedAmount", "0")
            if mv > 0:
                active_deposits.append({
                    "reserve": dep["depositReserve"],
                    "amount_raw": amount_raw,
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


def _fetch_oracle_prices() -> dict[str, float]:
    try:
        resp = requests.get(f"{KAMINO_BASE}/oracles/prices", timeout=KAMINO_TIMEOUT)
        if resp.status_code != 200:
            return {}
        rows = resp.json() or []
        if not isinstance(rows, list):
            return {}
        out = {}
        for row in rows:
            mint = row.get("mint")
            if mint:
                out[mint] = _safe_float(row.get("price"))
        return out
    except Exception as exc:
        logging.warning("kamino: failed to fetch oracle prices: %s", exc)
        return {}


def _fetch_reserve_metrics(market: str, oracle_prices: dict[str, float] | None = None) -> dict[str, dict]:
    """Fetch reserve-level metrics (APY, TVL, etc.) for a given market."""
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
                mint = r.get("mintAddress") or r.get("liquidityMint") or r.get("liquidityTokenMint") or ""
                result[addr] = {
                    "symbol": r.get("symbol") or r.get("liquidityToken") or "",
                    "mint": mint,
                    "decimals": int(r.get("decimals") or 0),
                    "price_usd": _safe_float((oracle_prices or {}).get(mint)),
                    "supply_apy": _safe_float(r.get("supplyApy")),
                    "borrow_apy": _safe_float(r.get("borrowApy")),
                    "total_supply_usd": _safe_float(r.get("totalSupplyUsd")),
                    "total_borrow_usd": _safe_float(r.get("totalBorrowUsd")),
                    "total_supply_native": _safe_float(r.get("totalSupply")),
                    "total_borrow_native": _safe_float(r.get("totalBorrow")),
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

    native_amount, native_symbol = _extract_native_amount(deposits, reserve_metrics, supplied_usd=row.get("supplied_usd"))
    if native_amount is not None:
        row["native_amount"] = native_amount
    if native_symbol:
        row["native_symbol"] = native_symbol

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
    oracle_prices = _fetch_oracle_prices()
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

            reserve_metrics = _fetch_reserve_metrics(market, oracle_prices=oracle_prices)

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
