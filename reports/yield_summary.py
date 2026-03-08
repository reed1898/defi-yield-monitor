"""Calculate yield/earnings over time periods from historical snapshots."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _find_closest_snapshot(snapshots: list[dict], target: datetime, max_drift_hours: float = 24) -> dict | None:
    """Find the snapshot closest to target time, within max_drift_hours."""
    best = None
    best_diff = None
    for s in snapshots:
        ts = _parse_ts(s.get("timestamp"))
        if ts is None:
            continue
        diff = abs((ts - target).total_seconds())
        if best_diff is None or diff < best_diff:
            best = s
            best_diff = diff
    if best_diff is not None and best_diff <= max_drift_hours * 3600:
        return best
    return None


def compute_yield_summary(snapshots: list[dict], now: datetime | None = None) -> dict:
    """Compute yield summary for 7d and 30d periods.

    Returns:
        {
            "current": { ... latest snapshot ... },
            "7d": {
                "start_value": float, "end_value": float, "pnl": float,
                "pnl_pct": float, "annualized_apy": float,
                "protocols": { "ethereum:aave": { "start": ..., "end": ..., "pnl": ... }, ... }
            },
            "30d": { ... same structure ... },
            "has_7d": bool,
            "has_30d": bool,
        }
    """
    if now is None:
        now = datetime.now(timezone.utc)

    if not snapshots:
        return {"current": None, "has_7d": False, "has_30d": False}

    latest = snapshots[-1]
    result = {
        "current": latest,
        "has_7d": False,
        "has_30d": False,
    }

    for label, delta in [("7d", timedelta(days=7)), ("30d", timedelta(days=30))]:
        target = now - delta
        baseline = _find_closest_snapshot(snapshots, target)
        if baseline is None:
            result[label] = None
            continue

        start_value = baseline.get("net_value_usd", 0.0)
        end_value = latest.get("net_value_usd", 0.0)
        pnl = end_value - start_value
        pnl_pct = (pnl / start_value * 100) if start_value > 0 else 0.0

        # Annualized APY from actual returns
        days = delta.days
        if start_value > 0 and days > 0:
            daily_rate = (end_value / start_value) ** (1 / days) - 1
            annualized_apy = ((1 + daily_rate) ** 365 - 1) * 100
        else:
            annualized_apy = 0.0

        # Per-protocol breakdown
        start_protocols = baseline.get("protocols", {})
        end_protocols = latest.get("protocols", {})
        protocol_pnl = {}

        all_keys = set(list(start_protocols.keys()) + list(end_protocols.keys()))
        for key in all_keys:
            sp = start_protocols.get(key, {})
            ep = end_protocols.get(key, {})
            s_net = sp.get("net_value_usd", 0.0)
            e_net = ep.get("net_value_usd", 0.0)
            p = e_net - s_net
            pct = (p / s_net * 100) if s_net > 0 else 0.0
            protocol_pnl[key] = {
                "start_value": s_net,
                "end_value": e_net,
                "pnl": p,
                "pnl_pct": pct,
                "current_apy": ep.get("apy_supply"),
            }

        result[label] = {
            "start_ts": baseline.get("timestamp"),
            "end_ts": latest.get("timestamp"),
            "start_value": start_value,
            "end_value": end_value,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "annualized_apy": annualized_apy,
            "protocols": protocol_pnl,
        }
        result[f"has_{label}"] = True

    return result


def render_yield_text(summary: dict) -> str:
    """Render yield summary as text."""
    lines = ["📊 Yield Summary", ""]

    current = summary.get("current")
    if not current:
        return "No snapshot data available yet."

    lines.append(f"Current Net Value: ${current.get('net_value_usd', 0):,.2f}")

    # Current APY per protocol
    protocols = current.get("protocols", {})
    if protocols:
        lines.append("")
        lines.append("Current APY:")
        for key in sorted(protocols.keys()):
            data = protocols[key]
            apy = data.get("apy_supply")
            net = data.get("net_value_usd", 0)
            if apy and apy > 0:
                lines.append(f"  {key}: {apy * 100:.2f}% (${net:,.2f})")
            else:
                lines.append(f"  {key}: — (${net:,.2f})")

    for label, title in [("7d", "7-Day"), ("30d", "30-Day")]:
        data = summary.get(label)
        has_data = summary.get(f"has_{label}", False)
        lines.append("")
        if not has_data or data is None:
            lines.append(f"{title}: Insufficient data (need more snapshots)")
            continue

        lines.append(f"{title} Performance:")
        lines.append(f"  PnL: ${data['pnl']:+,.2f} ({data['pnl_pct']:+.2f}%)")
        lines.append(f"  Annualized: {data['annualized_apy']:.2f}%")
        lines.append(f"  Period: {data.get('start_ts', '?')} → {data.get('end_ts', '?')}")

        proto_pnl = data.get("protocols", {})
        if proto_pnl:
            lines.append("  By Protocol:")
            for key in sorted(proto_pnl.keys()):
                p = proto_pnl[key]
                if p["start_value"] > 0 or p["end_value"] > 0:
                    lines.append(f"    {key}: ${p['pnl']:+,.2f} ({p['pnl_pct']:+.2f}%)")

    return "\n".join(lines)
