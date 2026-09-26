#!/usr/bin/env python3
"""Calculate the spot-check result for a completed review CSV or Excel workbook."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


ALLOWED = {"正しい", "間違い"}


def load_rows(path: Path) -> list[dict[str, str]]:
    if path.suffix.lower() == ".xlsx":
        from openpyxl import load_workbook

        sheet = load_workbook(path, read_only=True, data_only=False)["確認リスト"]
        return [
            {
                "会社名": str(row[3].value or ""),
                "human_verdict": str(row[1].value or ""),
                "human_notes": str(row[2].value or ""),
            }
            for row in sheet.iter_rows(min_row=7)
            if row[3].value
        ]
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def evaluate(path: Path, expected: int = 10, threshold: float = 0.9) -> dict[str, object]:
    rows = load_rows(path)
    if len(rows) != expected:
        raise ValueError(f"Expected {expected} accepted rows, found {len(rows)}")
    unresolved = [index + 2 for index, row in enumerate(rows) if row.get("human_verdict") not in ALLOWED]
    if unresolved:
        raise ValueError(f"Resolve human_verdict before evaluation; data rows: {unresolved}")
    correct = sum(row["human_verdict"] == "正しい" for row in rows)
    precision = correct / len(rows)
    passed = precision >= threshold
    return {
        "reviewed": len(rows),
        "correct": correct,
        "incorrect": len(rows) - correct,
        "spot_check_rate": precision,
        "required_spot_check_rate": threshold,
        "precision": precision,
        "required_precision": threshold,
        "passed": passed,
        "next_action": "quick_check_complete" if passed else "expand_to_20_or_full_review",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_path", type=Path)
    parser.add_argument("--expected", type=int, default=10)
    parser.add_argument("--threshold", type=float, default=0.9)
    args = parser.parse_args()
    result = evaluate(args.review_path, args.expected, args.threshold)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
