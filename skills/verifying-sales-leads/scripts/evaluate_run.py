#!/usr/bin/env python3
"""Calculate human-reviewed precision for a completed leads CSV."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


ALLOWED = {"正しい", "間違い"}


def evaluate(path: Path, expected: int = 50, threshold: float = 0.9) -> dict[str, object]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != expected:
        raise ValueError(f"Expected {expected} accepted rows, found {len(rows)}")
    unresolved = [index + 2 for index, row in enumerate(rows) if row.get("human_verdict") not in ALLOWED]
    if unresolved:
        raise ValueError(f"Resolve human_verdict before evaluation; CSV rows: {unresolved}")
    correct = sum(row["human_verdict"] == "正しい" for row in rows)
    precision = correct / len(rows)
    return {
        "reviewed": len(rows),
        "correct": correct,
        "incorrect": len(rows) - correct,
        "precision": precision,
        "required_precision": threshold,
        "passed": precision >= threshold,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--expected", type=int, default=50)
    parser.add_argument("--threshold", type=float, default=0.9)
    args = parser.parse_args()
    result = evaluate(args.csv_path, args.expected, args.threshold)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
