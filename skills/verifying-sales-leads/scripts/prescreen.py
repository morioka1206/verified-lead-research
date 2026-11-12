#!/usr/bin/env python3
"""Deterministic pre-screen between crawling and AI assessment.

`screen` reads a batch's crawl output and splits it in two:

* Companies with no usable page, or whose usable pages never mention any
  campaign product keyword, receive an automatic `review` assessment. The
  pre-screen can only route a company to review; it never accepts one.
* Every other company is listed for AI assessment, with short keyword-in-context
  snippets (product, buyer role, market) to speed up reading. Snippets are hints,
  not evidence: the AI still copies exact excerpts from the crawl pages.

`split` divides the `for_ai` list into parts so several assessor agents (for
example a cheaper model per part) can work in parallel; each part keeps the
crawl `index`, which assessors use in their decisions.

`merge` combines the automatic assessments with the AI's assessments into one
file covering every crawled company, ready for finalize/complete-batch.
"""

from __future__ import annotations

from leadlib import product_evidence_keywords

import argparse
import json
import re
from pathlib import Path
from typing import Any

US_MARKET_PATTERNS = [
    r"\b(?:AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY)\s+\d{5}\b",
    r"\bUnited States\b",
    r"\bU\.S\.A?\.?\b",
    r"\bUSA\b",
]
AUTO_NOTE = "自動ふるい分け："


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def usable_pages(record: dict[str, Any]) -> list[dict[str, Any]]:
    pages = []
    for page in record.get("pages") or []:
        if str(page.get("status_code")) != "200":
            continue
        if page.get("content_quality") == "unresolved":
            continue
        if not (page.get("text") or "").strip():
            continue
        pages.append(page)
    return pages


def keyword_regex(keywords: list[str]) -> re.Pattern[str] | None:
    terms = sorted({k.strip() for k in keywords if k and k.strip()}, key=len, reverse=True)
    if not terms:
        return None
    return re.compile("|".join(re.escape(term) for term in terms), re.IGNORECASE)


def snippets(pages: list[dict[str, Any]], pattern: re.Pattern[str] | None, limit: int, width: int) -> list[str]:
    if pattern is None:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for page in pages:
        text = page["text"]
        for match in pattern.finditer(text):
            start = max(0, match.start() - width)
            snippet = " ".join(text[start: match.end() + width].split())
            if snippet in seen:
                continue
            seen.add(snippet)
            found.append(f"{page['url']} …{snippet}…")
            if len(found) >= limit:
                return found
            break  # one hit per page keeps snippets diverse
    return found


def auto_review(record: dict[str, Any], campaign: dict[str, Any], reason: str) -> dict[str, Any]:
    candidate = record.get("candidate") or {}
    pages = record.get("pages") or []
    name = candidate.get("company_name_hint") or next(
        (page.get("company_name_hint") for page in pages if page.get("company_name_hint")), ""
    )
    return {
        "candidate_url": candidate.get("url"),
        "company_name": name or candidate.get("url", ""),
        "country": (campaign.get("market") or {}).get("name", ""),
        "company_type": "—",
        "company_overview_ja": "—",
        "recommendation": "review",
        "claims": [],
        "exclusion_checks": [
            {"type": excluded, "result": "unclear", "reason_ja": AUTO_NOTE + "AI判定の対象外のため未確認。"}
            for excluded in campaign.get("excluded_types") or []
        ],
        "uncertainties": [AUTO_NOTE + reason],
        "rejection_reason": None,
        "assessed_by": "prescreen",
    }


def screen(campaign: dict[str, Any], crawls: list[dict[str, Any]], snippet_limit: int = 3, width: int = 90) -> dict[str, Any]:
    product = keyword_regex(product_evidence_keywords(campaign))
    if product is None:
        raise ValueError("campaign.product.keywords is required for pre-screening")
    role_keywords = [kw for buyer in campaign.get("buyer_types") or [] for kw in buyer.get("keywords") or []]
    role_keywords += ["wholesale", "distributor", "importer", "private label", "our story", "about us"]
    role = keyword_regex(role_keywords)
    market_keywords = (campaign.get("market") or {}).get("keywords") or []
    market = re.compile("|".join(US_MARKET_PATTERNS + [re.escape(k) for k in market_keywords if k]))

    auto: list[dict[str, Any]] = []
    for_ai: list[dict[str, Any]] = []
    for index, record in enumerate(crawls):
        url = (record.get("candidate") or {}).get("url")
        pages = usable_pages(record)
        if record.get("site_status") != "active" or not pages:
            errors = "; ".join(
                e if isinstance(e, str) else str(e.get("error") or e.get("message") or e)
                for e in record.get("errors") or []
            )[:160]
            auto.append(auto_review(record, campaign, f"有効なページを取得できず証拠なし（{errors or record.get('site_status')}）。"))
            continue
        product_hits = snippets(pages, product, snippet_limit, width)
        if not product_hits:
            auto.append(auto_review(record, campaign, "取得した公式ページに商材キーワードの記載がなく、商材の証拠がない。"))
            continue
        for_ai.append({
            "index": index,
            "candidate_url": url,
            "company_name_hint": (record.get("candidate") or {}).get("company_name_hint")
            or next((p.get("company_name_hint") for p in pages if p.get("company_name_hint")), ""),
            "emails": record.get("emails") or [],
            "product_snippets": product_hits,
            "role_snippets": snippets(pages, role, snippet_limit, width),
            "market_snippets": snippets(pages, market, snippet_limit, width),
        })
    return {
        "crawled": len(crawls),
        "auto_review": len(auto),
        "needs_ai_assessment": len(for_ai),
        "for_ai": for_ai,
        "auto_assessments": auto,
    }


def merge(crawls: list[dict[str, Any]], prescreen: dict[str, Any], ai: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_url: dict[str, dict[str, Any]] = {}
    for item in prescreen.get("auto_assessments") or []:
        by_url[item["candidate_url"]] = item
    expected_ai = {item["candidate_url"] for item in prescreen.get("for_ai") or []}
    for item in ai:
        url = item.get("candidate_url")
        if url in by_url and by_url[url].get("assessed_by") == "prescreen" and url not in expected_ai:
            # An AI may look at an auto-reviewed company; it may keep or lower it, never raise it.
            if item.get("recommendation") == "accepted":
                raise ValueError(f"pre-screened review cannot be accepted by merge: {url}")
        by_url[url] = item
    merged = []
    missing = []
    for record in crawls:
        url = (record.get("candidate") or {}).get("url")
        if url not in by_url:
            missing.append(url)
            continue
        merged.append(by_url[url])
    if missing:
        raise ValueError(f"{len(missing)} crawled companies have no assessment: {missing[:5]}")
    return merged


def split(prescreen: dict[str, Any], parts: int) -> list[list[dict[str, Any]]]:
    if parts < 1:
        raise ValueError("--parts must be at least 1")
    items = list(prescreen.get("for_ai") or [])
    if not items:
        return []
    parts = min(parts, len(items))
    size, extra = divmod(len(items), parts)
    chunks, start = [], 0
    for k in range(parts):
        end = start + size + (1 if k < extra else 0)
        chunks.append(items[start:end])
        start = end
    return chunks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("screen")
    s.add_argument("--campaign", required=True, type=Path)
    s.add_argument("--crawls", required=True, type=Path)
    s.add_argument("--output", required=True, type=Path)
    m = sub.add_parser("merge")
    m.add_argument("--crawls", required=True, type=Path)
    m.add_argument("--prescreen", required=True, type=Path)
    m.add_argument("--assessments", required=True, type=Path, help="AI assessments for the for_ai companies")
    m.add_argument("--output", required=True, type=Path)
    p = sub.add_parser("split")
    p.add_argument("--prescreen", required=True, type=Path)
    p.add_argument("--parts", required=True, type=int)
    p.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    if args.command == "split":
        chunks = split(read_json(args.prescreen), args.parts)
        files = []
        for k, chunk in enumerate(chunks, 1):
            path = args.output_dir / f"for-ai-part{k}.json"
            write_json(path, chunk)
            files.append({"file": str(path), "indices": [item["index"] for item in chunk]})
        print(json.dumps({"parts": files}, ensure_ascii=False))
        return 0
    if args.command == "screen":
        result = screen(read_json(args.campaign), read_json(args.crawls))
        write_json(args.output, result)
        print(json.dumps({k: result[k] for k in ("crawled", "auto_review", "needs_ai_assessment")}, ensure_ascii=False))
        return 0
    merged = merge(read_json(args.crawls), read_json(args.prescreen), read_json(args.assessments))
    write_json(args.output, merged)
    print(json.dumps({"assessments": len(merged)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
