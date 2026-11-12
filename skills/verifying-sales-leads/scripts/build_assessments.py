#!/usr/bin/env python3
"""Build schema-valid ai-assessments.json from compact AI decisions, with guardrails.

The assessor writes a short decisions file instead of hand-building the schema.
Each decision (JSON array item) looks like:

  {"index": 3,                       # position in crawls.json (or "candidate_url")
   "company_name": "Example Cafe", "company_type": "カフェ", "overview_ja": "…",
   "recommendation": "accepted",     # accepted | review | rejected
   "claims": [
     {"type": "product", "quote": "Matcha Latte $5.50", "ja": "抹茶ラテを提供。", "url": "https://…/menu"},
     {"type": "buyer_role", "quote": "…", "ja": "…"},
     {"type": "target_market", "quote": "Austin, TX 78701", "ja": "…"}],
   "exclusions": [["not_matched", "米国の住所があり日本の親会社の記載なし。"], …],  # one per campaign exclusion, in order
   "uncertainties": ["…"], "rejection_reason": null}

Guardrails (the build fails, listing every problem, instead of writing output):
* every campaign exclusion needs an explicit result and a company-specific reason;
  no defaults are filled in, and a reason reused verbatim by many companies is rejected
* a claim's quote must appear on its page; without "url" it must appear on exactly
  one crawled page, otherwise the assessor must name the page
* for `accepted`: all three claim types are required
* advisory warnings (not errors): a thin or title-like product quote, or a market quote
  without a state/ZIP/US marker. The campaign's product_evidence and judgment_rules,
  decided with the user, define what is acceptable; this tool must not be stricter

check_assessments.py remains the independent verifier after this build.
"""

from __future__ import annotations

from leadlib import product_evidence_keywords

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from audit_accepted import NAV_MARKERS, US_STATE_NAMES
from leadlib import normalize_text
from prescreen import US_MARKET_PATTERNS, usable_pages

CLAIM_TYPES = ("product", "buyer_role", "target_market")
STATE_CODES = (
    "al ak az ar ca co ct de dc fl ga hi id il in ia ks ky la me md ma mi mn ms mo mt ne nv nh nj nm ny "
    "nc nd oh ok or pa ri sc sd tn tx ut vt va wa wv wi wy"
).split()
PRICE_RE = re.compile(r"\$\s?\d|\d+\.\d{2}")


def looks_like_navigation(quote: str) -> bool:
    """A title/nav string, but allow pipe-separated menu lines that carry a price."""
    hard = [m for m in NAV_MARKERS if m != " | "]
    if any(m in quote for m in hard):
        return True
    return " | " in quote and not PRICE_RE.search(quote)
RESULTS = {"not_matched", "matched", "unclear"}
MAX_REASON_REUSE = 5


def market_regex(campaign: dict[str, Any]) -> re.Pattern[str]:
    patterns = US_MARKET_PATTERNS + [rf"\b{re.escape(n)}\b" for n in US_STATE_NAMES]
    patterns += [r"\bUS\b", r"\b[A-Za-z]{2}\.?,?\s+\d{5}\b"]
    patterns += [r"(?i:,\s*(?:" + "|".join(STATE_CODES) + r")\b)"]
    patterns += [re.escape(k) for k in (campaign.get("market") or {}).get("keywords") or [] if k]
    return re.compile("|".join(patterns))


def find_pages(crawl: dict[str, Any], quote: str) -> list[str]:
    needle = normalize_text(quote)
    return [p["url"] for p in usable_pages(crawl) if needle and needle in normalize_text(p.get("text") or "")]


def build(campaign: dict[str, Any], crawls: list[dict[str, Any]], decisions: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    excluded = [str(x).strip() for x in campaign.get("excluded_types") or [] if str(x).strip()]
    keywords = [k.lower() for k in product_evidence_keywords(campaign)]
    market = market_regex(campaign)
    country = (campaign.get("market") or {}).get("name", "")
    by_url = {(c.get("candidate") or {}).get("url"): c for c in crawls}
    reason_use = Counter(
        str(item[1]).strip() for d in decisions for item in d.get("exclusions") or [] if isinstance(item, (list, tuple)) and len(item) == 2
    )
    out: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for n, d in enumerate(decisions):
        if "index" in d:
            if not isinstance(d["index"], int) or not 0 <= d["index"] < len(crawls):
                errors.append(f"decision {n}: index out of range")
                continue
            crawl = crawls[d["index"]]
        else:
            crawl = by_url.get(d.get("candidate_url"))
            if crawl is None:
                errors.append(f"decision {n}: unknown candidate_url")
                continue
        url = (crawl.get("candidate") or {}).get("url")
        label = f"{d.get('company_name') or url}"
        if url in seen:
            errors.append(f"{label}: duplicate decision")
            continue
        seen.add(url)
        rec = d.get("recommendation")
        if rec not in {"accepted", "review", "rejected"}:
            errors.append(f"{label}: invalid recommendation")
            continue

        exclusions = d.get("exclusions") or []
        checks = []
        if len(exclusions) != len(excluded):
            errors.append(f"{label}: needs exactly {len(excluded)} exclusions (one per campaign exclusion, in order)")
        else:
            for kind, item in zip(excluded, exclusions):
                if not isinstance(item, (list, tuple)) or len(item) != 2 or item[0] not in RESULTS:
                    errors.append(f"{label}: exclusion '{kind}' must be [result, reason]")
                    continue
                reason = str(item[1]).strip()
                if len(reason) < 8:
                    errors.append(f"{label}: exclusion '{kind}' needs a specific reason")
                elif reason_use[reason] > MAX_REASON_REUSE:
                    errors.append(f"{label}: exclusion reason for '{kind}' is reused by {reason_use[reason]} companies; write a company-specific reason")
                checks.append({"type": kind, "result": item[0], "reason_ja": reason})

        claims = []
        types = Counter()
        for c in d.get("claims") or []:
            ctype, quote = c.get("type"), str(c.get("quote") or "").strip()
            if ctype not in CLAIM_TYPES or not quote:
                errors.append(f"{label}: claim needs a valid type and quote")
                continue
            types[ctype] += 1
            pages = find_pages(crawl, quote)
            source = c.get("url")
            if source:
                if source not in pages:
                    errors.append(f"{label}: {ctype} quote not found on {source}")
                    continue
            elif len(pages) == 1:
                source = pages[0]
            elif not pages:
                errors.append(f"{label}: {ctype} quote not found on any usable page: {quote[:60]!r}")
                continue
            else:
                errors.append(f"{label}: {ctype} quote appears on {len(pages)} pages; add \"url\" to choose the page")
                continue
            if rec == "accepted":
                # Advisory only: the campaign's product_evidence / judgment_rules decide acceptance, not this tool.
                if ctype == "product":
                    lowered = quote.lower()
                    if looks_like_navigation(quote) or not any(k in lowered for k in keywords) or len(quote.split()) < 3:
                        warnings.append(f"{label}: product quote looks thin or like a title/nav string; check it fits product_evidence: {quote[:60]!r}")
                if ctype == "target_market" and not market.search(quote):
                    warnings.append(f"{label}: target_market quote has no state/ZIP/US marker; fine if judgment_rules accept a place name: {quote[:60]!r}")
            claims.append({"type": ctype, "evidence_url": source, "evidence_text_original": quote, "evidence_text_ja": c.get("ja") or ""})
        if rec == "accepted":
            missing = [t for t in CLAIM_TYPES if not types[t]]
            if missing:
                errors.append(f"{label}: accepted needs claims of type {', '.join(missing)}")
        out.append({
            "candidate_url": url,
            "company_name": d.get("company_name") or "",
            "country": d.get("country") or country,
            "company_type": d.get("company_type") or "—",
            "company_overview_ja": d.get("overview_ja") or "—",
            "recommendation": rec,
            "claims": claims,
            "exclusion_checks": checks,
            "uncertainties": list(d.get("uncertainties") or []),
            "rejection_reason": d.get("rejection_reason"),
        })
    build.last_warnings = warnings  # type: ignore[attr-defined]
    return out, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--crawls", required=True, type=Path)
    parser.add_argument("--decisions", required=True, type=Path, action="append",
                        help="decisions JSON array; repeat to combine parts written by parallel assessors")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    assessments, errors = build(
        json.loads(args.campaign.read_text(encoding="utf-8")),
        json.loads(args.crawls.read_text(encoding="utf-8")),
        [d for path in args.decisions for d in json.loads(path.read_text(encoding="utf-8"))],
    )
    if errors:
        print(json.dumps({"written": False, "errors": errors}, ensure_ascii=False, indent=2))
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(assessments, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    counts = Counter(a["recommendation"] for a in assessments)
    print(json.dumps({"written": True, "assessments": len(assessments), "recommendations": dict(counts),
                      "warnings": getattr(build, "last_warnings", [])}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
