#!/usr/bin/env python3
"""Validate AI assessments and export audit JSON, CSV, and clean sales Excel."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from leadlib import finalize_record, utc_now, validate_campaign


CSV_COLUMNS = [
    "会社名",
    "公式URL",
    "国・地域",
    "会社種別",
    "会社概要",
    "メール",
    "メール掲載URL",
    "問い合わせフォームURL",
    "判定",
    "商材の証拠",
    "商材の証拠URL",
    "会社の役割の証拠",
    "会社の役割の証拠URL",
    "対象地域の証拠",
    "対象地域の証拠URL",
    "確認日時",
    "human_verdict",
    "human_notes",
]


def claim_text(record: dict[str, Any], claim_type: str) -> str:
    return " / ".join(
        claim.get("evidence_text_ja") or claim.get("evidence_text_original", "")
        for claim in record["claims"]
        if claim.get("type") == claim_type
    )


def claim_urls(record: dict[str, Any], claim_type: str) -> str:
    return " / ".join(
        dict.fromkeys(
            claim.get("evidence_url", "")
            for claim in record["claims"]
            if claim.get("type") == claim_type and claim.get("evidence_url")
        )
    )


def csv_row(record: dict[str, Any]) -> dict[str, str]:
    return {
        "会社名": record.get("company_name") or "",
        "公式URL": record.get("canonical_url") or "",
        "国・地域": record.get("country") or "",
        "会社種別": record.get("company_type") or "",
        "会社概要": record.get("company_overview_ja") or "",
        "メール": " / ".join(item["email"] for item in record.get("emails") or []),
        "メール掲載URL": " / ".join(item["source_url"] for item in record.get("emails") or []),
        "問い合わせフォームURL": " / ".join(item["url"] for item in record.get("contact_forms") or []),
        "判定": record.get("verification_status") or "",
        "商材の証拠": claim_text(record, "product"),
        "商材の証拠URL": claim_urls(record, "product"),
        "会社の役割の証拠": claim_text(record, "buyer_role"),
        "会社の役割の証拠URL": claim_urls(record, "buyer_role"),
        "対象地域の証拠": claim_text(record, "target_market"),
        "対象地域の証拠URL": claim_urls(record, "target_market"),
        "確認日時": record.get("checked_at") or "",
        "human_verdict": "",
        "human_notes": "",
    }


def deduplicate_crawls(crawls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one crawl per candidate URL, preferring the newest supplied result."""
    ordered_urls: list[str] = []
    by_url: dict[str, dict[str, Any]] = {}
    anonymous: list[dict[str, Any]] = []
    for crawl in crawls:
        candidate_url = (crawl.get("candidate") or {}).get("url")
        if not candidate_url:
            anonymous.append(crawl)
            continue
        if candidate_url not in by_url:
            ordered_urls.append(candidate_url)
        by_url[candidate_url] = crawl
    return [by_url[url] for url in ordered_urls] + anonymous


def finalize(
    crawls: list[dict[str, Any]],
    assessments: list[dict[str, Any]],
    target: int,
    campaign: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    crawls = deduplicate_crawls(crawls)
    by_url = {item["candidate_url"]: item for item in assessments}
    records = []
    for crawl in crawls:
        candidate_url = (crawl.get("candidate") or {}).get("url")
        assessment = by_url.get(candidate_url, {"recommendation": "review", "claims": [], "uncertainties": ["AI assessment missing"]})
        records.append(finalize_record(crawl, assessment, campaign))
    accepted = [record for record in records if record["verification_status"] == "accepted"][:target]
    summary = {
        "generated_at": utc_now(),
        "candidates_checked": len(records),
        "accepted_available": sum(record["verification_status"] == "accepted" for record in records),
        "accepted_exported": len(accepted),
        "target_accepted": target,
        "target_met": len(accepted) == target,
        "status_counts": {
            status: sum(record["verification_status"] == status for record in records)
            for status in ("accepted", "review", "rejected", "blocked")
        },
    }
    return records, {"accepted": accepted, "summary": summary}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument(
        "--crawls",
        required=True,
        action="append",
        type=Path,
        help="crawl JSON file; repeat this option to combine research batches",
    )
    parser.add_argument(
        "--assessments",
        required=True,
        action="append",
        type=Path,
        help="assessment JSON file; repeat this option to combine research batches",
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    campaign = json.loads(args.campaign.read_text(encoding="utf-8"))
    campaign_errors = validate_campaign(campaign)
    if campaign_errors:
        raise ValueError("; ".join(campaign_errors))
    crawls = [
        item
        for path in args.crawls
        for item in json.loads(path.read_text(encoding="utf-8"))
    ]
    assessments = [
        item
        for path in args.assessments
        for item in json.loads(path.read_text(encoding="utf-8"))
    ]
    records, result = finalize(
        crawls,
        assessments,
        int(campaign.get("target_accepted", 50)),
        campaign,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "audit.json").write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "summary.json").write_text(json.dumps(result["summary"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (args.output_dir / "leads.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(csv_row(record) for record in result["accepted"])
    from export_review_workbook import write_sales_workbook

    write_sales_workbook(result["accepted"], args.output_dir / "leads.xlsx")
    print(json.dumps(result["summary"], ensure_ascii=False))
    return 0 if result["summary"]["target_met"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
