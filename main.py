#!/usr/bin/env python3
"""Entry point for DeFi yield monitoring.

Current version provides project skeleton and mockable adapter pipeline.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from core.aggregate import aggregate_positions
from core.normalize import normalize_positions
from storage.snapshots import load_previous_snapshot, save_snapshot


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DeFi yield monitor")
    parser.add_argument("--config", required=True, help="Path to config JSON")
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    return parser.parse_args()


def load_config(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def collect_positions(_config: dict) -> list[dict]:
    # Placeholder for protocol adapters. Adapters will return normalized position rows.
    return []


def main() -> None:
    args = parse_args()
    config = load_config(args.config)

    raw_positions = collect_positions(config)
    positions = normalize_positions(raw_positions)

    previous = load_previous_snapshot(config.get("snapshot_path", "storage/snapshots.json"))
    report = aggregate_positions(positions, previous)

    save_snapshot(config.get("snapshot_path", "storage/snapshots.json"), report)

    if args.json:
        print(json.dumps(report, ensure_ascii=True, indent=2))
    else:
        print("DeFi Yield Monitor")
        print(f"- Total assets: {report['total_assets_usd']:.2f} USD")
        print(f"- Total debt: {report['total_debt_usd']:.2f} USD")
        print(f"- Net value: {report['net_value_usd']:.2f} USD")


if __name__ == "__main__":
    main()
