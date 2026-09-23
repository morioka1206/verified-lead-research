#!/usr/bin/env python3
"""Normalize and deduplicate candidate company URLs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from leadlib import canonicalize_url, domain_key


def prepare(payload: Any, limit: int) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise ValueError("candidate input must be a JSON array")
    results = []
    seen_domains = set()
    for item in payload:
        candidate = {"url": item} if isinstance(item, str) else dict(item)
        url = canonicalize_url(candidate["url"])
        key = domain_key(url)
        if key in seen_domains:
            continue
        seen_domains.add(key)
        candidate["url"] = url
        results.append(candidate)
        if len(results) >= limit:
            break
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    results = prepare(payload, args.limit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"unique candidates: {len(results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
