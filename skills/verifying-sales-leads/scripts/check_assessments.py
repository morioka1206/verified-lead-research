#!/usr/bin/env python3
"""Dry-run the acceptance gate on draft AI assessments before completing a batch.

For each assessment, apply the same deterministic checks as finalize/complete-batch
(evidence excerpt present on its source page, every exclusion checked, blocked
sites) and report every company whose AI recommendation would be changed. Fix the
reported excerpts or URLs and run again; nothing is written to the ledger.

Exit status is 0 when every `accepted` recommendation survives the gate, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from leadlib import finalize_record


def check(campaign: dict[str, Any], crawls: list[dict[str, Any]], assessments: list[dict[str, Any]]) -> dict[str, Any]:
    by_url = {(c.get("candidate") or {}).get("url"): c for c in crawls}
    problems: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    seen: set[str] = set()
    for item in assessments:
        url = item.get("candidate_url")
        if url in seen:
            problems.append({"candidate_url": url, "problem": "duplicate assessment"})
            continue
        seen.add(url)
        crawl = by_url.get(url)
        if crawl is None:
            problems.append({"candidate_url": url, "problem": "candidate_url is not in the crawl file"})
            continue
        record = finalize_record(crawl, item, campaign)
        status = record["verification_status"]
        counts[status] = counts.get(status, 0) + 1
        if item.get("recommendation") == "accepted" and status != "accepted":
            problems.append({
                "candidate_url": url,
                "company_name": item.get("company_name"),
                "problem": f"accepted recommendation becomes {status}",
                "details": [u for u in record["uncertainties"] if u not in (item.get("uncertainties") or [])],
            })
    return {"assessments": len(assessments), "final_status_counts": counts, "problems": problems}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--crawls", required=True, type=Path)
    parser.add_argument("--assessments", required=True, type=Path)
    args = parser.parse_args()
    result = check(
        json.loads(args.campaign.read_text(encoding="utf-8")),
        json.loads(args.crawls.read_text(encoding="utf-8")),
        json.loads(args.assessments.read_text(encoding="utf-8")),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not result["problems"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
