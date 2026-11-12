#!/usr/bin/env python3
"""Country-targeted web search for candidate discovery (Brave Search API).

The client's built-in web search may be limited to one country. This script
queries the Brave Search API with an explicit country and language, so
discovery for, say, Germany returns German results.

Search is discovery only: every result is a lead to check, never evidence.
The output lists raw results; the scout picks official company sites from it
and the crawler and assessors still verify everything on the site itself.

API key: set BRAVE_SEARCH_API_KEY. In a Claude Code cloud session the key can
instead be saved as a network secret for api.search.brave.com (header
X-Subscription-Token); the proxy then injects it, and this script sends a
placeholder value.

Example:
  python search_web.py --country DE --lang de \
      --query "Metzgerei München Dry Aged" --query "Steakhaus Hamburg" \
      --output runs/<run>/search-001.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, build_opener

from leadlib import USER_AGENT, https_only_proxy

ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
KEY_ENV = "BRAVE_SEARCH_API_KEY"
PROXY_PLACEHOLDER = "injected-by-proxy"
MAX_RESPONSE_BYTES = 2_000_000

# Hosts whose pages describe other businesses (directories, reviews, maps,
# marketplaces, social media). Results on them are marked, not dropped, so the
# scout can still see which companies they mention.
DIRECTORY_HOST_SUFFIXES = (
    "facebook.com", "instagram.com", "tiktok.com", "youtube.com", "linkedin.com", "pinterest.com",
    "x.com", "twitter.com", "google.com", "yelp.com", "yelp.de", "tripadvisor.com", "tripadvisor.de",
    "opentable.com", "opentable.de", "quandoo.de", "thefork.de", "wanderlog.com", "foursquare.com",
    "speisekarte.de", "speisekarte.menu", "gelbeseiten.de", "dasoertliche.de", "dastelefonbuch.de",
    "golocal.de", "meinestadt.de", "werkenntdenbesten.de", "kennstdueinen.de", "11880.com",
    "cylex.de", "branchenbuch.meinestadt.de", "falstaff.com", "falstaff.de", "guide.michelin.com",
    "wolt.com", "lieferando.de", "ubereats.com", "amazon.de", "amazon.com", "ebay.de", "ebay.com",
    "etsy.com", "faire.com", "knuspr.de", "wikipedia.org", "rekki.com",
)


def is_directory_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == suffix or host.endswith("." + suffix) for suffix in DIRECTORY_HOST_SUFFIXES)


def api_key() -> str:
    key = os.environ.get(KEY_ENV, "").strip()
    if key:
        return key
    if https_only_proxy():
        # Cloud session: a network secret saved for the API host replaces this header.
        return PROXY_PLACEHOLDER
    raise SystemExit(f"{KEY_ENV} is not set. Get a Brave Search API key and export it first.")


def brave_search(
    query: str,
    *,
    country: str,
    lang: str,
    count: int,
    offset: int,
    key: str,
    timeout: float,
    opener_factory: Callable[[], Any] = build_opener,
) -> list[dict[str, Any]]:
    params = {"q": query, "country": country, "search_lang": lang, "count": count, "offset": offset,
              "result_filter": "web"}
    request = Request(
        f"{ENDPOINT}?{urlencode(params)}",
        headers={"Accept": "application/json", "X-Subscription-Token": key, "User-Agent": USER_AGENT},
    )
    with opener_factory().open(request, timeout=timeout) as response:
        body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("search response too large")
    payload = json.loads(body.decode("utf-8"))
    results = []
    for rank, item in enumerate((payload.get("web") or {}).get("results") or [], start=offset * count + 1):
        url = str(item.get("url") or "")
        if not url.startswith(("http://", "https://")):
            continue
        results.append({
            "rank": rank,
            "url": url,
            "title": str(item.get("title") or ""),
            "description": str(item.get("description") or ""),
            "directory_like": is_directory_host(url),
        })
    return results


def run(args: argparse.Namespace, search: Callable[..., list[dict[str, Any]]] = brave_search) -> dict[str, Any]:
    queries = list(args.query or [])
    if args.queries_file:
        queries += [line.strip() for line in args.queries_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not queries:
        raise SystemExit("give --query or --queries-file")
    key = api_key()
    out: dict[str, Any] = {"provider": "brave", "country": args.country, "lang": args.lang, "queries": []}
    for index, query in enumerate(queries):
        if index:
            time.sleep(args.pause)
        entry: dict[str, Any] = {"query": query, "results": []}
        try:
            for page in range(args.pages):
                entry["results"] += search(query, country=args.country, lang=args.lang, count=args.count,
                                           offset=page, key=key, timeout=args.timeout)
        except HTTPError as exc:
            entry["error"] = f"HTTP {exc.code}"
            if exc.code in {401, 403}:
                out["queries"].append(entry)
                out["stopped"] = "API key rejected; check the key or the saved network secret"
                break
        except (URLError, OSError, ValueError) as exc:
            entry["error"] = str(exc)[:200]
        out["queries"].append(entry)
        print(f"[{index + 1}/{len(queries)}] {query}: {len(entry['results'])} results"
              + (f" ({entry['error']})" if "error" in entry else ""), file=sys.stderr)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--query", action="append", help="search query; repeatable")
    parser.add_argument("--queries-file", type=Path, help="text file with one query per line")
    parser.add_argument("--country", required=True, help="two-letter country code, e.g. DE, FR, US")
    parser.add_argument("--lang", required=True, help="search language code, e.g. de, fr, en")
    parser.add_argument("--count", type=int, default=20, help="results per page (max 20)")
    parser.add_argument("--pages", type=int, default=1, help="result pages per query (max 10)")
    parser.add_argument("--pause", type=float, default=1.1, help="seconds between queries")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not 1 <= args.count <= 20 or not 1 <= args.pages <= 10:
        parser.error("--count must be 1-20 and --pages 1-10")
    args.country = args.country.upper()
    result = run(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    total = sum(len(q["results"]) for q in result["queries"])
    print(json.dumps({"queries": len(result["queries"]), "results": total,
                      "stopped": result.get("stopped")}, ensure_ascii=False))
    return 1 if result.get("stopped") else 0


if __name__ == "__main__":
    raise SystemExit(main())
