#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from adapters.aave import fetch_positions as fetch_aave_positions
from adapters.kamino import fetch_positions as fetch_kamino_positions
from adapters.spark import fetch_positions as fetch_spark_positions
from core.aggregate import aggregate_positions
from core.normalize import normalize_positions
from reports.daily import render_text_report
from reports.yield_summary import compute_yield_summary, render_yield_text
from storage.snapshots import load_previous_snapshot, save_snapshot


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DeFi yield monitor")
    parser.add_argument("--config", required=True, help="Path to config JSON")
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--text", action="store_true", help="Print text report output (default)")
    output.add_argument("--json", action="store_true", help="Print JSON output")
    output.add_argument("--yield-summary", action="store_true", dest="yield_summary", help="Print yield/earnings summary")
    return parser.parse_args()


def load_config(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def collect_positions(config: dict) -> list[dict]:
    rows: list[dict] = []
    enabled_names = {p.get("name") for p in config.get("protocols", [])}

    if "aave" in enabled_names:
        rows.extend(fetch_aave_positions(config))
    if "spark" in enabled_names or "spark_savings" in enabled_names:
        rows.extend(fetch_spark_positions(config))
    if "kamino" in enabled_names:
        rows.extend(fetch_kamino_positions(config))

    return rows


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    args = parse_args()
    config = load_config(args.config)

    raw_positions = collect_positions(config)
    positions = normalize_positions(raw_positions)

    snapshot_path = config.get("snapshot_path", "storage/snapshots.json")
    previous = load_previous_snapshot(snapshot_path)
    report = aggregate_positions(positions, previous=previous, thresholds=config.get("thresholds"))

    save_snapshot(snapshot_path, report, previous=previous)

    if args.json:
        print(json.dumps(report, ensure_ascii=True, indent=2))
    elif args.yield_summary:
        snapshots = list((previous or {}).get("snapshots", []))
        # Include the just-saved snapshot from this run
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
        print(render_yield_text(summary))
    else:
        print(render_text_report(report, thresholds=config.get("thresholds"), config=config))


if __name__ == "__main__":
    main()
