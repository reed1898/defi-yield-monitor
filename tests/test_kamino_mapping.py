#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from adapters.kamino import parse_obligation


def main() -> int:
    fixture_path = Path(__file__).parent / "fixtures" / "kamino_obligation_variants.json"
    cases = json.loads(fixture_path.read_text(encoding="utf-8"))

    wallet = "So11111111111111111111111111111111111111112"
    for case in cases:
        row = parse_obligation(case["input"], wallet)
        if row is None:
            raise AssertionError(f"case {case['name']} unexpectedly parsed as None")

        exp = case["expected"]
        for key, expected_value in exp.items():
            got = row.get(key)
            if got is None:
                raise AssertionError(f"case {case['name']} missing {key}")
            if abs(float(got) - float(expected_value)) > 1e-6:
                raise AssertionError(f"case {case['name']} {key} mismatch: got={got}, expected={expected_value}")

    print(f"OK: {len(cases)} kamino mapping fixtures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
