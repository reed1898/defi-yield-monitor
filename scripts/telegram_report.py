#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
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


def build_report(report: dict, summary: dict, sol_price: float | None) -> str:
    now_local = datetime.now(SH_TZ).strftime("%Y-%m-%d %H:%M:%S")
    protocols = report.get("protocol_breakdown") or {}
    kamino = protocols.get("solana:kamino", {})

    kamino_net_usd = float(kamino.get("net_value_usd") or 0.0)
    kamino_apy = kamino.get("apy_supply")
    kamino_sol_now = safe_div(kamino_net_usd, sol_price)
    kamino_sol_pnl = None if kamino_sol_now is None else (kamino_sol_now - KAMINO_BASELINE_SOL)
    kamino_sol_pnl_pct = None if kamino_sol_now is None else ((kamino_sol_now / KAMINO_BASELINE_SOL - 1) * 100)

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

    lines = [
        f"📘 DeFi 收益日报｜{now_local}（北京时间）",
        "",
        "💰 持仓对比表",
        "Kamino（SOL 本位）",
        f"- 当前净值：{fmt_usd(kamino_net_usd)}",
        f"- SOL 现价：{fmt_usd(sol_price) if sol_price is not None else 'N/A'}",
        f"- 当前折算：{fmt_sol(kamino_sol_now)}",
        f"- 对比投入 3,894 SOL：{fmt_sol(kamino_sol_pnl)} ({fmt_pct(kamino_sol_pnl_pct, with_sign=True)})",
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
        "📈 年化收益率",
        f"- 当前组合净值：{fmt_usd(report.get('net_value_usd'))}",
    ])

    for key, data in [("7d", summary.get("7d")), ("30d", summary.get("30d"))]:
        label = "7日" if key == "7d" else "30日"
        has = summary.get(f"has_{key}", False)
        if not has or not data:
            lines.append(f"- {label}：历史数据不足")
            continue
        lines.append(
            f"- {label}：PnL {fmt_usd(data.get('pnl'))} ({fmt_pct(data.get('pnl_pct'), with_sign=True)})｜年化 {fmt_pct(data.get('annualized_apy'))}"
        )

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
    print(build_report(report, summary, sol_price))


if __name__ == "__main__":
    main()
