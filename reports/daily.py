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

    lines = [
        "DeFi Yield Daily Report",
        f"Generated: {ts}",
        "",
        "Portfolio Overview",
        f"- Total Assets: {_fmt_money(report.get('total_assets_usd'))}",
        f"- Total Debt: {_fmt_money(report.get('total_debt_usd'))}",
        f"- Net Value: {_fmt_money(report.get('net_value_usd'))}",
        f"- 24h PnL: {_fmt_money(pnl24)} ({report.get('notes', {}).get('pnl_24h', 'ok')})",
        f"- 7d PnL: {_fmt_money(pnl7)} ({report.get('notes', {}).get('pnl_7d', 'ok')})",
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
        lines.append("- No health-factor alerts triggered.")
    else:
        min_hf = thresholds.get("min_health_factor")
        lines.append(f"- Health factor threshold: {min_hf}")
        for row in risk_flags:
            lines.append(
                f"- ALERT {row.get('wallet')} {row.get('protocol')}@{row.get('chain')} hf={row.get('health_factor')}"
            )

    return "\n".join(lines)
