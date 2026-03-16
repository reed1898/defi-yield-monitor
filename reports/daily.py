from __future__ import annotations

from datetime import datetime


STABLE_UNITS = {"USD", "USDT", "USDC", "USDS", "DAI", "USDE"}


def _fmt_money(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"${value:,.2f}"


def _fmt_units(value: float | None, symbol: str | None = None) -> str:
    if value is None:
        return "N/A"
    suffix = f" {symbol}" if symbol else ""
    return f"{value:,.4f}{suffix}"


def _build_cost_basis_map(config: dict | None) -> tuple[dict[str, dict], dict[str, list[dict]]]:
    if not config:
        return {}, {}

    positions = ((config.get("cost_basis") or {}).get("positions") or [])
    by_key: dict[str, dict] = {}
    by_protocol: dict[str, list[dict]] = {}

    for row in positions:
        protocol = str(row.get("protocol") or "").lower()
        chain = str(row.get("chain") or "").lower()
        unit = row.get("unit") or row.get("token") or ""
        key = f"{chain}:{protocol}"
        amount = row.get("amount")
        if amount is None:
            amount = row.get("initial_amount")
        try:
            amount_value = float(amount or 0.0)
        except Exception:
            amount_value = 0.0

        entry = by_key.setdefault(
            key,
            {"amount": 0.0, "unit": unit, "protocol": protocol, "chain": chain},
        )
        entry["amount"] += amount_value
        if not entry.get("unit") and unit:
            entry["unit"] = unit

    for entry in by_key.values():
        by_protocol.setdefault(entry["protocol"], []).append(entry)

    return by_key, by_protocol


def _match_cost_basis(name: str, config: dict | None) -> dict:
    by_key, by_protocol = _build_cost_basis_map(config)
    if name in by_key:
        return by_key[name]

    protocol = name.split(":", 1)[1] if ":" in name else name
    candidates = by_protocol.get(protocol, [])
    if len(candidates) == 1:
        return candidates[0]
    return {}


def _infer_current_units(data: dict, baseline: dict) -> tuple[float | None, str | None]:
    native_amount = data.get("native_amount")
    native_symbol = data.get("native_symbol")
    if native_amount and native_symbol:
        return float(native_amount), native_symbol

    unit = str(baseline.get("unit") or "")
    if unit.upper() in STABLE_UNITS:
        return float(data.get("assets_usd") or data.get("net_value_usd") or 0.0), unit

    return None, unit or None


def render_text_report(report: dict, thresholds: dict | None = None, config: dict | None = None) -> str:
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
        apy_parts = []
        supply_apy = data.get("apy_supply")
        borrow_apy = data.get("apy_borrow")
        if supply_apy:
            apy_parts.append(f"supply APY {supply_apy * 100:.2f}%")
        if borrow_apy:
            apy_parts.append(f"borrow APY {borrow_apy * 100:.2f}%")
        apy_str = f", {', '.join(apy_parts)}" if apy_parts else ""
        assets_list = data.get("assets", [])
        assets_str = f" [{', '.join(assets_list)}]" if assets_list else ""
        lines.append(
            f"- {name}: assets {_fmt_money(data.get('assets_usd'))}, debt {_fmt_money(data.get('debt_usd'))}, net {_fmt_money(data.get('net_value_usd'))}{apy_str}{assets_str}"
        )

        baseline = _match_cost_basis(name, config)
        current_units, current_symbol = _infer_current_units(data, baseline)
        baseline_amount = baseline.get("amount")
        baseline_unit = baseline.get("unit") or current_symbol

        if current_units is not None and current_symbol:
            lines.append(f"  current units: {_fmt_units(current_units, current_symbol)}")
        if baseline and baseline_amount is not None and baseline_unit:
            lines.append(f"  baseline units: {_fmt_units(float(baseline_amount), baseline_unit)}")
            if current_units is not None:
                pnl_units = current_units - float(baseline_amount)
                pnl_pct = (pnl_units / float(baseline_amount) * 100.0) if float(baseline_amount) else 0.0
                lines.append(f"  cumulative units pnl: {_fmt_units(pnl_units, current_symbol or baseline_unit)} ({pnl_pct:+.2f}%)")

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
