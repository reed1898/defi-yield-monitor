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
from storage.snapshots import load_previous_snapshot, save_snapshot


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DeFi yield monitor")
    parser.add_argument("--config", required=True, help="Path to config JSON")
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    return parser.parse_args()


def load_config(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def collect_positions(config: dict) -> list[dict]:
    rows: list[dict] = []
    enabled = {(p.get("name"), p.get("chain")) for p in config.get("protocols", [])}

    if ("aave", "eth") in enabled or ("aave", "bsc") in enabled:
        rows.extend(fetch_aave_positions(config))
    if ("spark", "eth") in enabled:
        rows.extend(fetch_spark_positions(config))
    if ("kamino", "solana") in enabled:
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
    else:
        print(render_text_report(report, thresholds=config.get("thresholds")))


if __name__ == "__main__":
    main()
