#!/usr/bin/env python3
"""Merge the accepted companies of several runs into one deduplicated sales list.

Each run directory must contain the `audit.json` written by finalize_run.py or
manage_batches.py. Only records whose final `verification_status` is
`accepted` are merged; nothing is re-judged or upgraded. Companies are
deduplicated by company identity (`company_key` of the canonical URL): the first
run given wins, so list runs in priority order. A company that is accepted in one
run but review/rejected/blocked in another is still merged, and the conflict is
reported for a human look.

Writes `leads.xlsx`, `leads.csv`, `audit.json` (merged accepted records with a
`source_run` field), and `merge-summary.json` into --output-dir.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from export_review_workbook import write_sales_workbook
from finalize_run import CSV_COLUMNS, csv_row
from leadlib import canonicalize_url, company_key


def record_key(record: dict[str, Any]) -> str | None:
    url = record.get("canonical_url") or record.get("final_url")
    if not url:
        return None
    try:
        return company_key(canonicalize_url(url))
    except (TypeError, ValueError):
        return None


def merge(runs: list[tuple[str, list[dict[str, Any]]]]) -> dict[str, Any]:
    accepted: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    duplicates: list[dict[str, str]] = []
    status_by_key: dict[str, list[str]] = {}
    per_run: dict[str, dict[str, int]] = {}
    for run_name, records in runs:
        counts = per_run.setdefault(run_name, {"accepted": 0, "merged": 0, "duplicates": 0})
        for record in records:
            key = record_key(record)
            if key is None:
                continue
            status = record.get("verification_status") or "unknown"
            status_by_key.setdefault(key, []).append(f"{run_name}: {status}")
            if status != "accepted":
                continue
            counts["accepted"] += 1
            if key in accepted:
                counts["duplicates"] += 1
                duplicates.append({"company_key": key, "kept_from": accepted[key]["source_run"], "duplicate_in": run_name})
                continue
            merged = dict(record)
            merged["source_run"] = run_name
            accepted[key] = merged
            order.append(key)
            counts["merged"] += 1
    conflicts = [
        {"company_key": key, "statuses": statuses}
        for key, statuses in status_by_key.items()
        if key in accepted and any(not entry.endswith(": accepted") for entry in statuses)
    ]
    return {
        "records": [accepted[key] for key in order],
        "summary": {
            "runs": per_run,
            "merged_accepted": len(order),
            "duplicates_removed": len(duplicates),
            "duplicates": duplicates,
            "status_conflicts": conflicts,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-dir", action="append", required=True, type=Path, help="Run directory, repeatable, in priority order")
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    runs = []
    for run_dir in args.run_dir:
        audit = run_dir / "audit.json"
        payload = json.loads(audit.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            parser.error(f"{audit} must be a JSON array of records")
        runs.append((run_dir.name, payload))
    result = merge(runs)
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    (output / "audit.json").write_text(json.dumps(result["records"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "merge-summary.json").write_text(json.dumps(result["summary"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (output / "leads.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for record in result["records"]:
            writer.writerow(csv_row(record))
    write_sales_workbook(result["records"], output / "leads.xlsx")
    summary = result["summary"]
    print(json.dumps({
        "merged_accepted": summary["merged_accepted"],
        "duplicates_removed": summary["duplicates_removed"],
        "status_conflicts": len(summary["status_conflicts"]),
        "runs": summary["runs"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
