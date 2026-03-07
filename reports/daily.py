from __future__ import annotations

from datetime import datetime


def _fmt_money(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"${value:,.2f}"


def render_text_report(report: dict, thresholds: dict | None = None) -> str:
    thresholds = thresholds or {}
    ts = report.get("generated_at") or datetime.utcnow().isoformat()
    pnl24 = report.get("pnl_24h_usd")
    pnl7 = report.get("pnl_7d_usd")

    notes = report.get("notes", {})
    drawdown = report.get("drawdown_24h_pct")
    drawdown_text = "N/A" if drawdown is None else f"{drawdown:.2f}%"

    lines = [
        "DeFi Yield Daily Report",
        f"Generated: {ts}",
        "",
        "Portfolio Overview",
        f"- Total Assets: {_fmt_money(report.get('total_assets_usd'))}",
        f"- Total Debt: {_fmt_money(report.get('total_debt_usd'))}",
        f"- Net Value: {_fmt_money(report.get('net_value_usd'))}",
        f"- 24h PnL: {_fmt_money(pnl24)} ({notes.get('pnl_24h', 'ok')})",
        f"- 7d PnL: {_fmt_money(pnl7)} ({notes.get('pnl_7d', 'ok')})",
        f"- 24h Drawdown: {drawdown_text} ({notes.get('baseline_24h', 'ok')})",
        f"- Rewards (24h): {_fmt_money(report.get('rewards_24h_usd'))}",
        "",
        "Protocol Breakdown",
    ]

    for name, data in sorted((report.get("protocol_breakdown") or {}).items()):
        lines.append(
            f"- {name}: assets {_fmt_money(data.get('assets_usd'))}, debt {_fmt_money(data.get('debt_usd'))}, net {_fmt_money(data.get('net_value_usd'))}"
        )

    risk_flags = report.get("risk_flags") or []
    lines.append("")
    lines.append("Risk Watch")
    if not risk_flags:
        lines.append("- No alerts triggered.")
    else:
        lines.append(f"- Health factor threshold: {thresholds.get('min_health_factor')}")
        lines.append(f"- Max daily drawdown threshold: {thresholds.get('max_daily_drawdown_pct')}%")
        for row in risk_flags:
            if row.get("type") == "health_factor":
                lines.append(
                    f"- ALERT health_factor {row.get('wallet')} {row.get('protocol')}@{row.get('chain')} hf={row.get('health_factor'):.4f} (< {row.get('threshold')})"
                )
            elif row.get("type") == "daily_drawdown":
                lines.append(
                    f"- ALERT daily_drawdown {row.get('drawdown_pct'):.2f}% (> {row.get('threshold')}%)"
                )
            else:
                lines.append(f"- ALERT {row}")

    return "\n".join(lines)
