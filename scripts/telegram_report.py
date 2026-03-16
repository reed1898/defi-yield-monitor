#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from main import collect_positions, load_config
from core.aggregate import aggregate_positions
from core.normalize import normalize_positions
from reports.yield_summary import compute_yield_summary
from storage.snapshots import load_previous_snapshot, save_snapshot

COINGECKO_SOL_URL = "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd"
SH_TZ = ZoneInfo("Asia/Shanghai")
KAMINO_BASELINE_SOL = 3894.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Chinese Telegram DeFi daily report")
    parser.add_argument("--config", required=True, help="Path to config JSON")
    return parser.parse_args()


def fetch_sol_price_usd() -> float | None:
    try:
        resp = requests.get(COINGECKO_SOL_URL, timeout=20)
        resp.raise_for_status()
        data = resp.json() or {}
        return float(data.get("solana", {}).get("usd"))
    except Exception:
        return None


def fmt_usd(value: float | None) -> str:
    if value is None:
        return "N/A"
    sign = "+" if value > 0 else ""
    return f"{sign}${value:,.2f}"


def fmt_pct(value: float | None, digits: int = 2, with_sign: bool = False) -> str:
    if value is None:
        return "N/A"
    sign = "+" if with_sign and value > 0 else ""
    return f"{sign}{value:.{digits}f}%"


def fmt_sol(value: float | None) -> str:
    if value is None:
        return "N/A"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:,.2f} SOL"


def safe_div(a: float | None, b: float | None) -> float | None:
    if a is None or b in (None, 0):
        return None
    return a / b


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _stable_value_from_snapshot(snap: dict) -> float:
    protocols = snap.get("protocols") or {}
    total = 0.0
    for key in ["ethereum:aave", "ethereum:spark_savings", "ethereum:spark", "bsc:aave", "base:aave", "base:spark", "base:spark_savings"]:
        total += float((protocols.get(key) or {}).get("net_value_usd") or 0.0)
    return total


def compute_today_summary(snapshots: list[dict], stable_only: bool = False) -> dict | None:
    if not snapshots:
        return None
    latest = snapshots[-1]
    latest_ts = parse_ts(latest.get("timestamp"))
    if latest_ts is None:
        return None

    latest_local = latest_ts.astimezone(SH_TZ)
    day_start_local = datetime.combine(latest_local.date(), time.min, tzinfo=SH_TZ)

    baseline = None
    for snap in snapshots:
        ts = parse_ts(snap.get("timestamp"))
        if ts is None:
            continue
        if ts.astimezone(SH_TZ) >= day_start_local:
            baseline = snap
            break

    if baseline is None:
        return None

    if stable_only:
        start_value = _stable_value_from_snapshot(baseline)
        end_value = _stable_value_from_snapshot(latest)
    else:
        start_value = float(baseline.get("net_value_usd") or 0.0)
        end_value = float(latest.get("net_value_usd") or 0.0)
    pnl = end_value - start_value
    pnl_pct = (pnl / start_value * 100) if start_value > 0 else 0.0
    return {
        "start_ts": baseline.get("timestamp"),
        "end_ts": latest.get("timestamp"),
        "start_value": start_value,
        "end_value": end_value,
        "pnl": pnl,
        "pnl_pct": pnl_pct,
    }


def _find_position_entry(entries: list[dict], protocol: str, chain: str | None = None) -> dict | None:
    for entry in entries:
        if entry.get("protocol") != protocol:
            continue
        if chain is not None and entry.get("chain") != chain:
            continue
        return entry
    return None


def compute_period_summary_for_stables(snapshots: list[dict], days: int) -> dict | None:
    if not snapshots:
        return None
    latest = snapshots[-1]
    latest_ts = parse_ts(latest.get("timestamp"))
    if latest_ts is None:
        return None
    target = latest_ts.timestamp() - days * 86400

    baseline = None
    best_diff = None
    for snap in snapshots:
        ts = parse_ts(snap.get("timestamp"))
        if ts is None:
            continue
        diff = abs(ts.timestamp() - target)
        if best_diff is None or diff < best_diff:
            baseline = snap
            best_diff = diff
    if baseline is None or best_diff is None or best_diff > 86400:
        return None

    start_value = _stable_value_from_snapshot(baseline)
    end_value = _stable_value_from_snapshot(latest)
    pnl = end_value - start_value
    pnl_pct = (pnl / start_value * 100) if start_value > 0 else 0.0
    return {
        "start_ts": baseline.get("timestamp"),
        "end_ts": latest.get("timestamp"),
        "start_value": start_value,
        "end_value": end_value,
        "pnl": pnl,
        "pnl_pct": pnl_pct,
    }


def compute_cost_basis_summary(config: dict, report: dict, sol_price: float | None) -> dict:
    entries = list((config.get("cost_basis") or {}).get("positions") or [])

    aave_entry = _find_position_entry(entries, "aave", "ethereum") or _find_position_entry(entries, "aave")
    spark_entry = _find_position_entry(entries, "spark_savings", "base") or _find_position_entry(entries, "spark_savings")
    kamino_entry = _find_position_entry(entries, "kamino", "solana") or _find_position_entry(entries, "kamino")

    aave_initial = float((aave_entry or {}).get("initial_amount") or 0.0)
    aave_adjustment = float((aave_entry or {}).get("amount") or 0.0)
    for entry in entries:
        if entry is aave_entry:
            continue
        if entry.get("protocol") == "aave":
            aave_adjustment += float(entry.get("amount") or 0.0)
    aave_basis = aave_initial + aave_adjustment

    spark_basis = float((spark_entry or {}).get("initial_amount") or 0.0)
    kamino_basis_sol = float((kamino_entry or {}).get("initial_amount") or KAMINO_BASELINE_SOL)
    protocols = report.get("protocol_breakdown") or {}
    aave_net = float((protocols.get("ethereum:aave") or {}).get("net_value_usd") or 0.0)
    spark_net = float((protocols.get("ethereum:spark_savings") or {}).get("net_value_usd") or 0.0)
    kamino_net = float((protocols.get("solana:kamino") or {}).get("net_value_usd") or 0.0)

    kamino_now_sol = float((protocols.get("solana:kamino") or {}).get("native_amount") or 0.0) or None

    stable_basis_usd = aave_basis + spark_basis
    stable_net_usd = aave_net + spark_net
    stable_profit_usd = stable_net_usd - stable_basis_usd
    stable_profit_pct = (stable_profit_usd / stable_basis_usd * 100) if stable_basis_usd > 0 else None

    kamino_profit_sol = None if kamino_now_sol is None else kamino_now_sol - kamino_basis_sol
    kamino_profit_pct = (kamino_profit_sol / kamino_basis_sol * 100) if kamino_basis_sol not in (None, 0) and kamino_profit_sol is not None else None

    return {
        "aave_basis_usd": aave_basis,
        "spark_basis_usd": spark_basis,
        "stable_basis_usd": stable_basis_usd,
        "stable_net_usd": stable_net_usd,
        "stable_profit_usd": stable_profit_usd,
        "stable_profit_pct": stable_profit_pct,
        "kamino_basis_sol": kamino_basis_sol,
        "kamino_net_usd": kamino_net,
        "kamino_now_sol": kamino_now_sol,
        "kamino_profit_sol": kamino_profit_sol,
        "kamino_profit_pct": kamino_profit_pct,
    }


def build_report(report: dict, summary: dict, sol_price: float | None, snapshots: list[dict], config: dict) -> str:
    now_local = datetime.now(SH_TZ).strftime("%Y-%m-%d %H:%M:%S")
    protocols = report.get("protocol_breakdown") or {}
    kamino = protocols.get("solana:kamino", {})

    kamino_net_usd = float(kamino.get("net_value_usd") or 0.0)

    aave = protocols.get("ethereum:aave", {})
    spark = protocols.get("ethereum:spark", {})
    spark_savings = protocols.get("ethereum:spark_savings", {})
    bsc_aave = protocols.get("bsc:aave", {})
    stablecoin_rows = [
        ("Aave ETH", aave),
        ("Aave BSC", bsc_aave),
        ("Spark", spark),
        ("Spark Savings", spark_savings),
    ]

    today = compute_today_summary(snapshots)
    today_stable = compute_today_summary(snapshots, stable_only=True)
    basis = compute_cost_basis_summary(config, report, sol_price)

    data_7d = compute_period_summary_for_stables(snapshots, 7)
    data_30d = compute_period_summary_for_stables(snapshots, 30)
    pnl_24h = today_stable.get("pnl") if today_stable else None
    pnl_24h_pct = today_stable.get("pnl_pct") if today_stable else None

    lines = [
        f"📘 DeFi 收益日报｜{now_local}（北京时间）",
        "",
        "📊 USD 本位（稳定币）",
        f"- 总投入：{fmt_usd(basis.get('stable_basis_usd'))}",
        f"- 当前净值：{fmt_usd(basis.get('stable_net_usd'))}",
        f"- 总收益：{fmt_usd(basis.get('stable_profit_usd'))}",
        f"- 累计收益率：{fmt_pct(basis.get('stable_profit_pct'), with_sign=True)}",
        f"- 每日收益（24h）：{fmt_usd(pnl_24h)} ({fmt_pct(pnl_24h_pct, with_sign=True)})",
        f"- 每周收益（7d）：{fmt_usd((data_7d or {}).get('pnl'))} ({fmt_pct((data_7d or {}).get('pnl_pct'), with_sign=True)})" if data_7d else "- 每周收益（7d）：历史数据不足",
        f"- 每月收入（30d）：{fmt_usd((data_30d or {}).get('pnl'))} ({fmt_pct((data_30d or {}).get('pnl_pct'), with_sign=True)})" if data_30d else "- 每月收入（30d）：历史数据不足",
        "",
        "🧮 SOL 本位（Kamino）",
        f"- 初始投入：{fmt_sol(basis.get('kamino_basis_sol'))}",
        f"- 当前净值：{fmt_sol(basis.get('kamino_now_sol'))}",
        f"- 总收益：{fmt_sol(basis.get('kamino_profit_sol'))}",
        f"- 累计收益率：{fmt_pct(basis.get('kamino_profit_pct'), with_sign=True)}",
        f"- 当前美元估值：{fmt_usd(kamino_net_usd)}",
        "",
        "稳定币仓位（USD 本位）",
    ]

    has_stable = False
    for label, data in stablecoin_rows:
        net = float(data.get("net_value_usd") or 0.0)
        if net == 0:
            continue
        has_stable = True
        apy = data.get("apy_supply")
        lines.append(f"- {label}：净值 {fmt_usd(net)}｜当前 APY {fmt_pct((apy or 0) * 100 if apy is not None else None)}")
    if not has_stable:
        lines.append("- 暂无稳定币仓位数据")

    lines.extend([
        "",
        "📅 当日收益（北京时间 00:00 起）",
    ])
    if not today:
        lines.append("- 历史数据不足")
    else:
        lines.append(f"- PnL {fmt_usd(today.get('pnl'))} ({fmt_pct(today.get('pnl_pct'), with_sign=True)})")

    lines.extend([
        "",
        "🪙 SOL 价格",
        f"- CoinGecko：{fmt_usd(sol_price) if sol_price is not None else '获取失败'}",
        "",
        "⚠️ 风险提示",
    ])

    risk_flags = report.get("risk_flags") or []
    if not risk_flags:
        lines.append("- 当前未触发阈值告警")
    else:
        for row in risk_flags:
            if row.get("type") == "health_factor":
                lines.append(
                    f"- 健康因子告警：{row.get('protocol')} @ {row.get('chain')}，HF={row.get('health_factor'):.4f}，阈值 {row.get('threshold')}"
                )
            elif row.get("type") == "daily_drawdown":
                lines.append(
                    f"- 24h 回撤告警：{row.get('drawdown_pct'):.2f}% ＞ {row.get('threshold')}%"
                )
            else:
                lines.append(f"- 其他告警：{json.dumps(row, ensure_ascii=False)}")

    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    raw_positions = collect_positions(config)
    positions = normalize_positions(raw_positions)

    snapshot_path = config.get("snapshot_path", "storage/snapshots.json")
    previous = load_previous_snapshot(snapshot_path)
    report = aggregate_positions(positions, previous=previous, thresholds=config.get("thresholds"))
    save_snapshot(snapshot_path, report, previous=previous)

    snapshots = list((previous or {}).get("snapshots", []))
    snapshots.append({
        "timestamp": report.get("generated_at"),
        "net_value_usd": report.get("net_value_usd", 0.0),
        "total_assets_usd": report.get("total_assets_usd", 0.0),
        "total_debt_usd": report.get("total_debt_usd", 0.0),
        "protocols": {k: {
            "assets_usd": v.get("assets_usd", 0.0),
            "debt_usd": v.get("debt_usd", 0.0),
            "net_value_usd": v.get("net_value_usd", 0.0),
            "apy_supply": v.get("apy_supply"),
            "apy_borrow": v.get("apy_borrow"),
        } for k, v in (report.get("protocol_breakdown") or {}).items()},
    })
    summary = compute_yield_summary(snapshots)
    sol_price = fetch_sol_price_usd()
    print(build_report(report, summary, sol_price, snapshots, config))


if __name__ == "__main__":
    main()
