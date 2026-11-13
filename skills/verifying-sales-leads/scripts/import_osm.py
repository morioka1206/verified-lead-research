#!/usr/bin/env python3
"""Import bulk candidate websites from OpenStreetMap via the Overpass API.

OpenStreetMap is a discovery source only. A candidate imported here has the
same status as a web-search hit: its official website must still be crawled and
assessed with on-site evidence before it can be accepted.

Each output item records the Overpass query and the OSM element URL as its
discovery provenance. Websites that are social profiles, link hubs, review
sites, marketplaces, or shared hosting tenants are skipped, because their
host does not identify one company.

Use --preset for common buyer types (see PRESETS), for example
--preset steak-restaurant --preset butcher. Values of list-valued keys such as
cuisine ("japanese;sushi") are matched as list items.

Example:
  python import_osm.py --tag amenity=cafe --tag shop=tea --area US-OR --area US-WA \
      --output runs/<run>/discovery-osm-cafe.json --exclude-candidates runs/<run>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable

from leadlib import canonicalize_url, company_key

DEFAULT_ENDPOINT = "https://overpass-api.de/api/interpreter"
# Public mirror tried when the main server refuses or times out (seen from cloud sessions).
FALLBACK_ENDPOINTS = ("https://maps.mail.ru/osm/tools/overpass/api/interpreter",)
USER_AGENT = "verified-lead-research/1.0 (OSM candidate import)"

US_STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN",
    "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH",
    "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT",
    "VT", "VA", "WA", "WV", "WI", "WY",
]

# Hosts that do not identify a single company's own website.
SKIP_HOST_SUFFIXES = (
    "facebook.com", "instagram.com", "twitter.com", "x.com", "tiktok.com", "youtube.com",
    "linkedin.com", "pinterest.com", "linktr.ee", "linkin.bio", "beacons.ai", "bio.site",
    "yelp.com", "tripadvisor.com", "google.com", "goo.gl", "g.page", "maps.app.goo.gl",
    "foursquare.com", "opentable.com", "resy.com", "doordash.com", "ubereats.com",
    "grubhub.com", "seamless.com", "postmates.com", "toasttab.com", "order.online",
    "squareup.com", "square.site", "clover.com", "chownow.com", "menufy.com", "slicelife.com",
    "amazon.com", "etsy.com", "faire.com", "ebay.com", "wixsite.com", "weebly.com",
    "godaddysites.com", "blogspot.com", "wordpress.com", "business.site", "carrd.co",
    "myshopify.com", "sites.google.com", "wikipedia.org", "openstreetmap.org",
)


# Keys whose OSM values are semicolon-separated lists ("japanese;sushi"), so an
# exact match would miss most places. They are matched as list items instead.
LIST_VALUED_KEYS = {"cuisine"}
SAFE_VALUE = re.compile(r"^[A-Za-z0-9_:.-]+$")

# Named tag groups for common buyer types. Values follow OSM's documented tags.
PRESETS: dict[str, list[str]] = {
    "butcher": ["shop=butcher"],
    "deli": ["shop=deli"],
    "department-store": ["shop=department_store"],
    "steak-restaurant": ["cuisine=steak_house", "cuisine=argentinian", "cuisine=brazilian", "cuisine=barbecue"],
    "japanese-restaurant": ["cuisine=japanese", "cuisine=teppanyaki"],
    "cafe": ["amenity=cafe"],
    "tea-coffee-shop": ["shop=tea", "shop=coffee"],
    "bakery": ["shop=bakery", "shop=pastry"],
    "supermarket": ["shop=supermarket"],
}


def tag_selector(key: str, value: str) -> str:
    if key in LIST_VALUED_KEYS:
        # Values are limited to SAFE_VALUE; only "." is special in the regex. A
        # backslash would be consumed by Overpass string escaping, so use a class.
        return f'["{key}"~"(^|;) *{value.replace(".", "[.]")} *(;|$)"]'
    return f'["{key}"="{value}"]'


def build_query(tags: list[tuple[str, str]], area: str, timeout: int) -> str:
    selectors = "".join(
        f'nwr{tag_selector(key, value)}["website"](area.a);\n'
        f'nwr{tag_selector(key, value)}["contact:website"](area.a);\n'
        for key, value in tags
    )
    return (
        f"[out:json][timeout:{timeout}];\n"
        f'area["ISO3166-2"="{area}"][admin_level=4]->.a;\n'
        f"(\n{selectors});\nout tags;\n"
    )


def fetch_with_fallback(query: str, endpoints: list[str], timeout: int, pause: float = 0.0) -> dict[str, Any]:
    """Try each endpoint in order, pausing before each fallback; raise the last error if all fail."""
    last: Exception | None = None
    for position, endpoint in enumerate(endpoints):
        if position and pause:
            time.sleep(pause)
        try:
            return fetch_overpass(query, endpoint, timeout)
        except Exception as exc:  # try the next mirror
            last = exc
            print(f"  {endpoint} failed: {str(exc)[:120]}", file=sys.stderr)
    raise last or RuntimeError("no Overpass endpoint configured")


def fetch_overpass(query: str, endpoint: str, timeout: int) -> dict[str, Any]:
    data = urllib.parse.urlencode({"data": query}).encode("utf-8")
    request = urllib.request.Request(endpoint, data=data, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout + 30) as response:
        return json.loads(response.read().decode("utf-8"))


def host_is_skipped(url: str) -> bool:
    host = urllib.parse.urlsplit(url).hostname or ""
    host = host.lower().removeprefix("www.")
    if host.endswith((".edu", ".gov", ".mil")):
        return True  # campus and government cafeterias are not company websites
    return any(host == suffix or host.endswith("." + suffix) for suffix in SKIP_HOST_SUFFIXES)


def normalize_website(raw: str) -> str | None:
    value = raw.strip().split(";")[0].strip()
    if not value:
        return None
    if "://" not in value:
        value = "https://" + value
    try:
        url = canonicalize_url(value)
    except (TypeError, ValueError):
        return None
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname or "." not in parts.hostname or " " in parts.hostname:
        return None
    if host_is_skipped(url):
        return None
    # Use the company homepage; a store-locator page is not the company identity.
    return f"{parts.scheme}://{parts.hostname}/"


def matched_tags(tags: dict[str, str], wanted: list[tuple[str, str]]) -> list[str]:
    found = []
    for key, value in wanted:
        present = tags.get(key, "")
        items = [item.strip() for item in present.split(";")] if key in LIST_VALUED_KEYS else [present]
        if value in items:
            found.append(f"{key}={value}")
    return found


def elements_to_candidates(
    elements: Iterable[dict[str, Any]], area: str, tag_label: str, wanted: list[tuple[str, str]] | None = None
) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for element in elements:
        tags = element.get("tags") or {}
        raw = tags.get("website") or tags.get("contact:website")
        if not raw:
            continue
        url = normalize_website(raw)
        if url is None:
            continue
        key = company_key(url)
        osm_url = f"https://www.openstreetmap.org/{element.get('type')}/{element.get('id')}"
        matched = matched_tags(tags, wanted or [])
        if key in by_key:
            by_key[key]["osm_locations"] += 1
            for tag in matched:
                if tag not in by_key[key]["osm_matched_tags"]:
                    by_key[key]["osm_matched_tags"].append(tag)
            continue
        address = ", ".join(
            part for part in (tags.get("addr:city"), tags.get("addr:state")) if part
        )
        by_key[key] = {
            "url": url,
            "discovery_query": f"OpenStreetMap Overpass: {tag_label} with website in {area}",
            "search_result_source_url": osm_url,
            "company_name_hint": tags.get("name") or tags.get("brand") or "",
            "osm_brand": tags.get("brand") or "",
            "osm_address_hint": address,
            "osm_locations": 1,
            "osm_matched_tags": matched,
        }
    return list(by_key.values())


def load_excluded_keys(paths: list[Path]) -> set[str]:
    """Collect company keys already present in run ledgers or candidate files."""

    keys: set[str] = set()
    for path in paths:
        files: list[Path] = []
        if path.is_dir():
            database = path / "research.sqlite3"
            if database.exists():
                connection = sqlite3.connect(database)
                for (url,) in connection.execute("SELECT url FROM candidates"):
                    keys.add(company_key(url))
                connection.close()
            files.extend(sorted(path.glob("candidates.json")))
            files.extend(sorted(path.glob("discovery*.json")))
        elif path.exists():
            files.append(path)
        for file in files:
            try:
                payload = json.loads(file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            for item in payload if isinstance(payload, list) else []:
                url = item if isinstance(item, str) else (item or {}).get("url")
                if not url:
                    continue
                try:
                    keys.add(company_key(canonicalize_url(url)))
                except (TypeError, ValueError):
                    continue
    return keys


def parse_tags(values: list[str]) -> list[tuple[str, str]]:
    tags = []
    for value in values:
        if "=" not in value:
            raise ValueError(f"tag must be key=value: {value}")
        key, tag_value = value.split("=", 1)
        if not key or not tag_value or '"' in value or "\\" in value:
            raise ValueError(f"invalid tag: {value}")
        if key in LIST_VALUED_KEYS and not SAFE_VALUE.match(tag_value):
            raise ValueError(f"invalid {key} value: {tag_value}")
        tags.append((key, tag_value))
    return tags


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tag", action="append", default=[], help="OSM tag key=value, repeatable")
    parser.add_argument("--preset", action="append", default=[], choices=sorted(PRESETS),
                        help="named tag group for a buyer type; repeatable, combinable with --tag")
    parser.add_argument("--area", action="append", help="ISO3166-2 area such as US-CA; repeatable")
    parser.add_argument("--all-us-states", action="store_true", help="Query every US state and DC")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--exclude-candidates", action="append", type=Path, default=[],
                        help="Run directory or candidate JSON whose companies are skipped; repeatable")
    parser.add_argument("--max-locations", type=int, default=0,
                        help="Skip websites shared by more than this many OSM places (0 = keep chains)")
    parser.add_argument("--limit", type=int, default=0, help="Stop after this many new candidates (0 = no limit)")
    parser.add_argument("--endpoint", action="append",
                        help="Overpass endpoint; repeat to set the fallback order (default: main server, then a public mirror)")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--pause", type=float, default=5.0, help="Seconds between Overpass requests")
    parser.add_argument("--raw-dir", type=Path, help="Save raw Overpass responses here for audit")
    args = parser.parse_args()

    tag_values = [tag for preset in args.preset for tag in PRESETS[preset]] + list(args.tag)
    if not tag_values:
        parser.error("give --tag or --preset")
    tags = list(dict.fromkeys(parse_tags(tag_values)))
    areas = [f"US-{state}" for state in US_STATES] if args.all_us_states else (args.area or [])
    if not areas:
        parser.error("give --area or --all-us-states")
    tag_label = " | ".join(f"{k}={v}" for k, v in tags)
    excluded = load_excluded_keys(args.exclude_candidates)

    results: list[dict[str, Any]] = []
    seen = set(excluded)
    failures = []
    endpoints = args.endpoint or [DEFAULT_ENDPOINT, *FALLBACK_ENDPOINTS]
    if args.output.exists():
        previous = json.loads(args.output.read_text(encoding="utf-8"))
        results.extend(previous)
        seen.update(company_key(item["url"]) for item in previous)
    # Areas already fetched for this exact tag set are skipped on a rerun, so a
    # rerun only retries the areas that failed.
    progress_path = args.output.with_name(args.output.name + ".areas.json")
    progress = json.loads(progress_path.read_text(encoding="utf-8")) if progress_path.exists() else {}
    done_areas = set(progress.get(tag_label, []))
    pending = [area for area in areas if area not in done_areas]
    if len(pending) < len(areas):
        print(f"skipping {len(areas) - len(pending)} area(s) already fetched for these tags", file=sys.stderr)
    for index, area in enumerate(pending):
        if args.limit and len(results) >= args.limit:
            break
        if index:
            time.sleep(args.pause)
        query = build_query(tags, area, args.timeout)
        try:
            payload = fetch_with_fallback(query, endpoints, args.timeout, args.pause)
        except Exception as exc:  # network errors are reported, not fatal
            failures.append({"area": area, "error": str(exc)[:200]})
            print(f"[{area}] failed: {exc}", file=sys.stderr)
            continue
        if args.raw_dir:
            args.raw_dir.mkdir(parents=True, exist_ok=True)
            tag_hash = hashlib.sha256(tag_label.encode("utf-8")).hexdigest()[:8]
            (args.raw_dir / f"overpass-{area}-{tag_hash}.json").write_text(json.dumps(payload), encoding="utf-8")
        new = 0
        for candidate in elements_to_candidates(payload.get("elements", []), area, tag_label, tags):
            if args.max_locations and candidate["osm_locations"] > args.max_locations:
                continue
            key = company_key(candidate["url"])
            if key in seen:
                continue
            seen.add(key)
            results.append(candidate)
            new += 1
            if args.limit and len(results) >= args.limit:
                break
        print(f"[{area}] elements={len(payload.get('elements', []))} new={new} total={len(results)}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        if not (args.limit and len(results) >= args.limit):  # a limit can cut an area short
            done_areas.add(area)
            progress[tag_label] = sorted(done_areas)
            progress_path.write_text(json.dumps(progress, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"candidates": len(results), "areas": len(areas), "failures": failures}, ensure_ascii=False))
    return 0 if not pending or len(failures) < len(pending) else 1


if __name__ == "__main__":
    raise SystemExit(main())
