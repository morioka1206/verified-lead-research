#!/usr/bin/env python3
"""Flag accepted records whose evidence or exclusion checks look weak (read-only).

This is a precision audit for runs that are already in a ledger. It never changes
a status; it lists accepted records that a human or assessor agent should re-check,
with the reason for each flag:

* product_quote_navigation  – product excerpt looks like a page title or nav string
* product_quote_thin        – product excerpt has no product keyword plus another word
* market_quote_no_marker    – market excerpt has no US state, ZIP, or US marker
* boilerplate_exclusions    – the same exclusion reason text is reused by many records
* franchise_signal          – crawled pages mention franchising/ownership opportunities
* closure_signal            – crawled pages mention a permanent closure or not-yet-open

Pass the run directory; crawls are read from batches/*/crawls.json.
"""

from __future__ import annotations

from leadlib import product_evidence_keywords

import argparse
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from prescreen import US_MARKET_PATTERNS

NAV_MARKERS = (" | ", "Skip to", "Open Menu", "Close Menu", "Toggle menu", "Log in", "Cart")
FRANCHISE_RE = re.compile(r"\bfranchis(e|ing|ee)\b|\bown a (franchise|location|store)\b", re.IGNORECASE)
CLOSURE_RE = re.compile(
    r"permanently closed|we have closed|has closed its doors|closed for good|(café|cafe|shop|store) has closed|opening soon|grand opening soon|now hiring for our opening",
    re.IGNORECASE,
)
BOILERPLATE_MIN = 10
US_STATE_NAMES = [
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado", "Connecticut", "Delaware", "Florida",
    "Georgia", "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana", "Maine",
    "Maryland", "Massachusetts", "Michigan", "Minnesota", "Mississippi", "Missouri", "Montana", "Nebraska",
    "Nevada", "New Hampshire", "New Jersey", "New Mexico", "New York", "North Carolina", "North Dakota", "Ohio",
    "Oklahoma", "Oregon", "Pennsylvania", "Rhode Island", "South Carolina", "South Dakota", "Tennessee", "Texas",
    "Utah", "Vermont", "Virginia", "Washington", "West Virginia", "Wisconsin", "Wyoming", "District of Columbia",
]


def load_records(run_dir: Path) -> list[dict[str, Any]]:
    connection = sqlite3.connect(run_dir / "research.sqlite3")
    rows = [json.loads(row[0]) for row in connection.execute("SELECT record_json FROM records")]
    connection.close()
    return rows


def load_pages(run_dir: Path) -> dict[str, list[dict[str, Any]]]:
    pages: dict[str, list[dict[str, Any]]] = {}
    for crawl_file in sorted(run_dir.glob("batches/*/crawls.json")):
        for crawl in json.loads(crawl_file.read_text(encoding="utf-8")):
            key = crawl.get("canonical_url") or (crawl.get("candidate") or {}).get("url")
            pages[key] = crawl.get("pages") or []
    return pages


def audit(campaign: dict[str, Any], records: list[dict[str, Any]], pages: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    keywords = [k.lower() for k in product_evidence_keywords(campaign)]
    market = re.compile("|".join(US_MARKET_PATTERNS + [rf"\b{re.escape(n)}\b" for n in US_STATE_NAMES] + [r"\bUS\b", r"\b[A-Za-z]{2}\.?,?\s+\d{5}\b"] + [re.escape(k) for k in (campaign.get("market") or {}).get("keywords") or [] if k]))
    accepted = [r for r in records if r.get("verification_status") == "accepted"]
    reason_counts = Counter(
        check.get("reason_ja") for r in accepted for check in r.get("exclusion_checks") or [] if check.get("reason_ja")
    )
    flagged = []
    for record in accepted:
        flags = []
        claims = {c.get("type"): c.get("evidence_text_original") or "" for c in record.get("claims") or []}
        product = claims.get("product", "")
        if any(marker in product for marker in NAV_MARKERS):
            flags.append("product_quote_navigation")
        lowered = product.lower()
        if not any(k in lowered for k in keywords) or len(product.split()) < 2:
            flags.append("product_quote_thin")
        if not market.search(claims.get("target_market", "")):
            flags.append("market_quote_no_marker")
        reasons = [c.get("reason_ja") for c in record.get("exclusion_checks") or []]
        if reasons and all(reason_counts.get(reason, 0) >= BOILERPLATE_MIN for reason in reasons):
            flags.append("boilerplate_exclusions")
        text = " ".join(p.get("text") or "" for p in pages.get(record.get("canonical_url"), []))
        if FRANCHISE_RE.search(text):
            flags.append("franchise_signal")
        if CLOSURE_RE.search(text):
            flags.append("closure_signal")
        if flags:
            flagged.append({
                "company_name": record.get("company_name"),
                "canonical_url": record.get("canonical_url"),
                "flags": flags,
                "product_quote": product,
                "market_quote": claims.get("target_market", ""),
            })
    return flagged


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    campaign = json.loads((args.run_dir / "campaign.json").read_text(encoding="utf-8"))
    records = load_records(args.run_dir)
    flagged = audit(campaign, records, load_pages(args.run_dir))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(flagged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    counts = Counter(flag for item in flagged for flag in item["flags"])
    substantive = sum(any(f != "boilerplate_exclusions" for f in item["flags"]) for item in flagged)
    accepted = sum(r.get("verification_status") == "accepted" for r in records)
    print(json.dumps({"accepted": accepted, "flagged": len(flagged), "substantive": substantive, "flag_counts": dict(counts)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
