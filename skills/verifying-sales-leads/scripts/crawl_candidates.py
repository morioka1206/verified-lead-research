#!/usr/bin/env python3
"""Retrieve up to five relevant pages for each candidate company."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from leadlib import (
    DEFAULT_LINK_GROUP_ORDER,
    HOSPITALITY_LINK_GROUP_ORDER,
    crawl_company,
    validate_campaign,
)


def page_priorities(campaign: dict[str, Any]) -> tuple[str, ...]:
    objective = str(campaign.get("objective") or "").lower()
    buyer_parts: list[str] = []
    for item in campaign.get("buyer_types") or []:
        if not isinstance(item, dict):
            continue
        buyer_parts.append(str(item.get("name") or ""))
        buyer_parts.extend(str(value) for value in item.get("keywords") or [])
    buyer_text = " ".join(buyer_parts).lower()
    if "hospitality" in objective or any(
        hint in buyer_text
        for hint in ("cafe", "café", "coffee shop", "restaurant", "カフェ", "レストラン")
    ):
        return HOSPITALITY_LINK_GROUP_ORDER
    return DEFAULT_LINK_GROUP_ORDER


def write_checkpoint(path: Path, results: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def load_checkpoint(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("existing crawl output must be a JSON array")
    by_url: dict[str, dict[str, Any]] = {}
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("existing crawl output entries must be objects")
        candidate_url = (item.get("candidate") or {}).get("url")
        if candidate_url:
            by_url[candidate_url] = item
    return by_url


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--candidates", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--restart", action="store_true", help="ignore and replace an existing checkpoint")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between pages for one company")
    args = parser.parse_args()
    campaign = json.loads(args.campaign.read_text(encoding="utf-8"))
    campaign_errors = validate_campaign(campaign)
    if campaign_errors:
        raise ValueError("; ".join(campaign_errors))
    candidates = json.loads(args.candidates.read_text(encoding="utf-8"))
    candidates = candidates[: int(campaign.get("max_candidates", 100))]
    max_pages = min(int(campaign.get("max_pages_per_company", 5)), 5)
    priority_groups = page_priorities(campaign)
    checkpoint = {} if args.restart else load_checkpoint(args.output)
    candidate_urls = {candidate.get("url") for candidate in candidates}
    results_by_url = {
        url: result for url, result in checkpoint.items() if url in candidate_urls
    }
    write_checkpoint(
        args.output,
        [
            results_by_url[candidate["url"]]
            for candidate in candidates
            if candidate.get("url") in results_by_url
        ],
    )
    for index, candidate in enumerate(candidates, start=1):
        if candidate.get("url") in results_by_url:
            result = results_by_url[candidate["url"]]
            print(f"[{index}/{len(candidates)}] {candidate['url']} -> {result['site_status']} (checkpoint)")
            continue
        result = crawl_company(
            candidate,
            max_pages=max_pages,
            timeout=args.timeout,
            browser_fallback=not args.no_browser,
            delay_seconds=args.delay,
            priority_groups=priority_groups,
        )
        results_by_url[candidate["url"]] = result
        write_checkpoint(
            args.output,
            [
                results_by_url[item["url"]]
                for item in candidates
                if item.get("url") in results_by_url
            ],
        )
        print(f"[{index}/{len(candidates)}] {candidate['url']} -> {result['site_status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
