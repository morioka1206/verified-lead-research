#!/usr/bin/env python3
"""Deterministic helpers for evidence-backed company research."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from http.client import HTTPException
import html
import ipaddress
import os
from pathlib import Path
import re
import socket
import time
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.robotparser import RobotFileParser


USER_AGENT = "VerifiedLeadResearch/1.0"
MAX_HTML_BYTES = 2_000_000
MAX_ROBOTS_BYTES = 256_000
EMAIL_RE = re.compile(r"(?i)\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b")
HIDDEN_TAGS = {"script", "style", "noscript", "svg", "template"}
CONTACT_HINTS = (
    "contact",
    "inquiry",
    "enquiry",
    "お問い合わせ",
    "聯絡",
    "联系",
    "kontakt",
    "contato",
    "contacto",
    "contatti",
)
FORM_CONTEXT_HINTS = (
    "inquiry",
    "enquiry",
    "お問い合わせ",
    "聯絡",
    "联系",
    "application",
    "company",
    "message",
    "contact[body]",
)
LINK_GROUP_HINTS = {
    "about": ("about", "company", "who-we-are", "会社概要", "企業情報"),
    "menu": (
        "menu",
        "drink",
        "beverage",
        "food-tea",
        "food & tea",
        "メニュー",
    ),
    "locations": (
        "location",
        "/cafes",
        "our cafes",
        "visit-us",
        "visit us",
        "find-us",
        "find us",
        "store-locator",
        "店舗",
    ),
    "products": ("product", "catalog", "matcha", "tea", "商品", "製品"),
    "distribution": (
        "wholesale",
        "distributor",
        "distribution",
        "import",
        "foodservice",
        "trade",
        "卸",
        "流通",
        "輸入",
    ),
    "contact": CONTACT_HINTS,
}
DEFAULT_LINK_GROUP_ORDER = ("about", "products", "distribution", "contact")
HOSPITALITY_LINK_GROUP_ORDER = ("about", "menu", "locations", "contact")
REQUIRED_CLAIM_TYPES = {"product", "buyer_role", "target_market"}
EXCLUSION_CHECK_RESULTS = {"not_matched", "matched", "unclear"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def validate_campaign(campaign: Any) -> list[str]:
    if not isinstance(campaign, dict):
        return ["campaign must be an object"]
    errors = []
    product = campaign.get("product") or {}
    market = campaign.get("market") or {}
    if not campaign.get("id"):
        errors.append("id is required")
    if not product.get("name"):
        errors.append("product.name is required")
    if not product.get("keywords"):
        errors.append("product.keywords must not be empty")
    if not market.get("name"):
        errors.append("market.name is required")
    if not market.get("keywords"):
        errors.append("market.keywords must not be empty")
    if not campaign.get("buyer_types"):
        errors.append("buyer_types must not be empty")
    research_mode = campaign.get("research_mode", "standard")
    if research_mode not in {"standard", "batch"}:
        errors.append("research_mode must be standard or batch")
    maximums = {
        "standard": {"target_accepted": 50, "max_candidates": 100},
        "batch": {"target_accepted": 1000, "max_candidates": 5000},
    }.get(research_mode, {"target_accepted": 50, "max_candidates": 100})
    for field, default, maximum in (
        ("target_accepted", 50, maximums["target_accepted"]),
        ("max_candidates", 100, maximums["max_candidates"]),
        ("max_pages_per_company", 5, 5),
    ):
        value = campaign.get(field, default)
        if not isinstance(value, int) or not 1 <= value <= maximum:
            errors.append(f"{field} must be an integer from 1 to {maximum}")
    target = campaign.get("target_accepted", 50)
    maximum_candidates = campaign.get("max_candidates", 100)
    if isinstance(target, int) and isinstance(maximum_candidates, int) and maximum_candidates < target:
        errors.append("max_candidates must be greater than or equal to target_accepted")
    if research_mode == "batch":
        batch_size = campaign.get("batch_size", 50)
        if not isinstance(batch_size, int) or not 1 <= batch_size <= 100:
            errors.append("batch_size must be an integer from 1 to 100")
    return errors


def canonicalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    scheme = parsed.scheme.lower() or "https"
    if not parsed.netloc and parsed.path:
        parsed = urlparse(f"{scheme}://{parsed.path}")
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not hostname:
        raise ValueError("URL has no hostname")
    port = parsed.port
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    netloc = hostname if port is None or default_port else f"{hostname}:{port}"
    path = quote(parsed.path or "/", safe="/%:@-._~!$&'()*+,;=")
    query = quote(parsed.query, safe="/%?:@-._~!$&'()*+,;=")
    return urlunparse((scheme, netloc, path, "", query, ""))


def domain_key(url: str) -> str:
    hostname = (urlparse(canonicalize_url(url)).hostname or "").lower()
    return hostname[4:] if hostname.startswith("www.") else hostname


def same_site(left: str, right: str) -> bool:
    left_host = domain_key(left)
    right_host = domain_key(right)
    return left_host == right_host or left_host.endswith(f".{right_host}") or right_host.endswith(f".{left_host}")


def validate_public_url(
    url: str,
    *,
    allow_private: bool = False,
    resolver: Callable[..., Any] = socket.getaddrinfo,
) -> str:
    canonical = canonicalize_url(url)
    parsed = urlparse(canonical)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http and https URLs are allowed")
    if parsed.username or parsed.password:
        raise ValueError("URLs containing credentials are not allowed")
    if parsed.port not in {None, 80, 443} and not allow_private:
        raise ValueError("Only ports 80 and 443 are allowed")
    hostname = parsed.hostname or ""
    if hostname.lower() == "localhost" and not allow_private:
        raise ValueError("Local addresses are not allowed")
    try:
        addresses = {item[4][0] for item in resolver(hostname, parsed.port or (443 if parsed.scheme == "https" else 80))}
    except socket.gaierror as exc:
        raise ValueError(f"Hostname could not be resolved: {exc}") from exc
    if not addresses:
        raise ValueError("Hostname did not resolve to an address")
    if not allow_private:
        for address in addresses:
            if not ipaddress.ip_address(address).is_global:
                raise ValueError("Private or non-global addresses are not allowed")
    return canonical


class SafeRedirectHandler(HTTPRedirectHandler):
    def __init__(self, *, allow_private: bool = False) -> None:
        super().__init__()
        self.allow_private = allow_private

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        validate_public_url(newurl, allow_private=self.allow_private)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def read_limited(response: Any, limit: int) -> bytes:
    body = response.read(limit + 1)
    if len(body) > limit:
        raise ValueError(f"Response exceeded the {limit}-byte limit")
    return body


@dataclass
class FetchResult:
    html: str
    final_url: str
    fetched_with: str
    status_code: int | None


def static_fetch(url: str, *, timeout: float = 15.0, allow_private: bool = False) -> FetchResult:
    safe_url = validate_public_url(url, allow_private=allow_private)
    opener = build_opener(SafeRedirectHandler(allow_private=allow_private))
    request = Request(safe_url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.1"})
    with opener.open(request, timeout=timeout) as response:
        final_url = validate_public_url(response.geturl(), allow_private=allow_private)
        content_type = response.headers.get_content_type()
        if content_type not in {"text/html", "application/xhtml+xml"}:
            raise ValueError(f"Unsupported content type: {content_type}")
        body = read_limited(response, MAX_HTML_BYTES)
        charset = response.headers.get_content_charset() or "utf-8"
        return FetchResult(body.decode(charset, errors="replace"), final_url, "static", response.getcode())


def robots_text_allows(robots_text: str, target_url: str) -> bool:
    parser = RobotFileParser()
    parser.set_url(urljoin(target_url, "/robots.txt"))
    parser.parse(robots_text.splitlines())
    return parser.can_fetch(USER_AGENT, target_url)


def robots_allows(url: str, *, timeout: float = 10.0, allow_private: bool = False) -> bool:
    parsed = urlparse(validate_public_url(url, allow_private=allow_private))
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        opener = build_opener(SafeRedirectHandler(allow_private=allow_private))
        request = Request(robots_url, headers={"User-Agent": USER_AGENT, "Accept": "text/plain,*/*;q=0.1"})
        with opener.open(request, timeout=timeout) as response:
            body = read_limited(response, MAX_ROBOTS_BYTES)
            charset = response.headers.get_content_charset() or "utf-8"
    except HTTPError as exc:
        return exc.code not in {401, 403}
    except (HTTPException, URLError, OSError, ValueError):
        return True
    return robots_text_allows(body.decode(charset, errors="replace"), url)


class SiteHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.text_blocks: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.mailto: list[str] = []
        self.site_name: str | None = None
        self.form_count = 0
        self.contact_form_count = 0
        self._in_title = False
        self._hidden_depth = 0
        self._anchor_href: str | None = None
        self._anchor_text: list[str] = []
        self._form_depth = 0
        self._form_signals: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        values = {key.lower(): value or "" for key, value in attrs}
        if tag in HIDDEN_TAGS:
            self._hidden_depth += 1
            return
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            prop = (values.get("property") or values.get("name") or "").lower()
            if prop == "og:site_name" and values.get("content"):
                self.site_name = normalize_text(values["content"])
        elif tag == "a":
            self._anchor_href = values.get("href")
            self._anchor_text = []
            if self._anchor_href and self._anchor_href.lower().startswith("mailto:"):
                self.mailto.append(self._anchor_href[7:].split("?", 1)[0])
        elif tag == "form":
            self.form_count += 1
            self._form_depth += 1
            self._form_signals = [" ".join(f"{key}={value}" for key, value in values.items())]
        elif self._form_depth and tag in {"input", "textarea", "select", "button", "label"}:
            attributes = " ".join(f"{key}={value}" for key, value in values.items())
            self._form_signals.append(f"{tag} {attributes}")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in HIDDEN_TAGS:
            if self._hidden_depth:
                self._hidden_depth -= 1
            return
        if tag == "title":
            self._in_title = False
        elif tag == "a" and self._anchor_href is not None:
            self.links.append((self._anchor_href, normalize_text(" ".join(self._anchor_text))))
            self._anchor_href = None
            self._anchor_text = []
        elif tag == "form" and self._form_depth:
            signals = normalize_text(" ".join(self._form_signals)).lower()
            if "textarea" in signals and any(hint in signals for hint in FORM_CONTEXT_HINTS):
                self.contact_form_count += 1
            self._form_depth -= 1
            self._form_signals = []

    def handle_data(self, data: str) -> None:
        value = normalize_text(data)
        if not value:
            return
        if self._in_title:
            self.title_parts.append(value)
        if self._hidden_depth:
            return
        self.text_blocks.append(value)
        if self._form_depth:
            self._form_signals.append(value)
        if self._anchor_href is not None:
            self._anchor_text.append(value)


def parse_site(html_text: str, base_url: str) -> dict[str, Any]:
    parser = SiteHTMLParser()
    parser.feed(html_text)
    text = normalize_text(" ".join(parser.text_blocks))
    title = normalize_text(" ".join(parser.title_parts))
    company_name = parser.site_name or re.split(r"\s+[|–—]\s+|\s+-\s+", title, maxsplit=1)[0] or None
    emails = {email.strip().lower() for email in parser.mailto if EMAIL_RE.fullmatch(email.strip())}
    emails.update(match.lower() for match in EMAIL_RE.findall(text))

    links = []
    for href, anchor_text in parser.links:
        if not href or href.lower().startswith(("#", "javascript:", "tel:", "mailto:")):
            continue
        absolute = urljoin(base_url, href).split("#", 1)[0]
        if urlparse(absolute).scheme not in {"http", "https"}:
            continue
        links.append({"url": absolute, "text": anchor_text})
    return {
        "company_name": company_name,
        "title": title,
        "text": text,
        "text_blocks": parser.text_blocks,
        "emails": sorted(emails),
        "links": links,
        "has_form": parser.contact_form_count > 0,
    }


def looks_like_js_shell(parsed: dict[str, Any]) -> bool:
    text = parsed.get("text", "").lower()
    return len(text) < 200 or "enable javascript" in text or "javascript is required" in text


def _browser_request_allowed(url: str, *, allow_private: bool, cache: dict[str, bool]) -> bool:
    parsed = urlparse(url)
    origin = f"{parsed.scheme.lower()}://{(parsed.hostname or '').lower()}:{parsed.port or ''}"
    if origin in cache:
        return cache[origin]
    try:
        validate_public_url(url, allow_private=allow_private)
        cache[origin] = True
    except ValueError:
        cache[origin] = False
    return cache[origin]


def playwright_fetch(url: str, *, timeout: float = 20.0, allow_private: bool = False) -> FetchResult:
    safe_url = validate_public_url(url, allow_private=allow_private)
    project_dir = Path(__file__).resolve().parents[3]
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(project_dir / ".playwright-browsers"))
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright is not installed; run scripts/bootstrap.py") from exc

    cache: dict[str, bool] = {}
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(user_agent=USER_AGENT)
            page = context.new_page()

            def route_request(route: Any) -> None:
                if _browser_request_allowed(route.request.url, allow_private=allow_private, cache=cache):
                    route.continue_()
                else:
                    route.abort()

            page.route("**/*", route_request)
            response = page.goto(safe_url, wait_until="domcontentloaded", timeout=int(timeout * 1000))
            page.wait_for_timeout(750)
            final_url = validate_public_url(page.url, allow_private=allow_private)
            content = page.content()
            status = response.status if response else None
            browser.close()
    except Exception as exc:
        raise RuntimeError(f"Playwright fetch failed: {exc}") from exc
    if len(content.encode("utf-8")) > MAX_HTML_BYTES:
        raise ValueError(f"Rendered response exceeded the {MAX_HTML_BYTES}-byte limit")
    return FetchResult(content, final_url, "playwright", status)


def fetch_page(
    url: str,
    *,
    timeout: float = 15.0,
    browser_fallback: bool = True,
    allow_private: bool = False,
) -> tuple[FetchResult, dict[str, Any]]:
    static_error: Exception | None = None
    try:
        result = static_fetch(url, timeout=timeout, allow_private=allow_private)
        parsed = parse_site(result.html, result.final_url)
        if not browser_fallback or not looks_like_js_shell(parsed):
            return result, parsed
    except HTTPError as exc:
        if exc.code in {401, 403, 429}:
            raise
        static_error = exc
    except (HTTPException, URLError, OSError, ValueError) as exc:
        static_error = exc

    if not browser_fallback:
        if static_error:
            raise static_error
        raise RuntimeError("Static page did not contain enough visible text")
    result = playwright_fetch(url, timeout=max(timeout, 20.0), allow_private=allow_private)
    return result, parse_site(result.html, result.final_url)


def _link_group(link: dict[str, str]) -> str | None:
    haystack = f"{urlparse(link['url']).path} {link.get('text', '')}".lower()
    for group, hints in LINK_GROUP_HINTS.items():
        if any(hint in haystack for hint in hints):
            return group
    return None


def _link_group_score(group: str, link: dict[str, str]) -> int:
    haystack = f"{urlparse(link['url']).path} {link.get('text', '')}".lower()
    if group != "menu":
        return 0
    score = 0
    if any(
        hint in haystack
        for hint in ("drink", "beverage", "coffee", "tea", "matcha", "non-coffee")
    ):
        score += 10
    if "menu" in haystack:
        score += 2
    if any(hint in haystack for hint in ("brunch", "lunch", "dinner", "food")):
        score -= 3
    return score


def priority_links(
    links: Iterable[dict[str, str]],
    base_url: str,
    group_order: Iterable[str] = DEFAULT_LINK_GROUP_ORDER,
) -> list[str]:
    grouped: dict[str, tuple[int, str]] = {}
    for link in links:
        url = link["url"]
        if not same_site(url, base_url):
            continue
        group = _link_group(link)
        if not group:
            continue
        score = _link_group_score(group, link)
        current = grouped.get(group)
        if current is None or score > current[0]:
            grouped[group] = (score, url)
    return [grouped[group][1] for group in group_order if group in grouped]


def crawl_company(
    candidate: dict[str, Any],
    *,
    max_pages: int = 5,
    timeout: float = 15.0,
    browser_fallback: bool = True,
    allow_private: bool = False,
    delay_seconds: float = 1.0,
    priority_groups: Iterable[str] = DEFAULT_LINK_GROUP_ORDER,
) -> dict[str, Any]:
    if delay_seconds < 0:
        raise ValueError("delay_seconds must not be negative")
    start_url = candidate["url"]
    queue = [canonicalize_url(start_url)]
    seen: set[str] = set()
    pages: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    external_contact_urls: list[str] = []

    while queue and len(pages) < max_pages:
        requested_url = queue.pop(0)
        if requested_url in seen:
            continue
        seen.add(requested_url)
        if pages and delay_seconds:
            time.sleep(delay_seconds)
        try:
            if not robots_allows(requested_url, timeout=min(timeout, 10.0), allow_private=allow_private):
                errors.append({"url": requested_url, "reason": "robots.txt disallows this crawler"})
                continue
            fetched, parsed = fetch_page(
                requested_url,
                timeout=timeout,
                browser_fallback=browser_fallback,
                allow_private=allow_private,
            )
        except (HTTPException, HTTPError, URLError, OSError, ValueError, RuntimeError) as exc:
            errors.append({"url": requested_url, "reason": str(exc)})
            continue

        page = {
            "url": fetched.final_url,
            "title": parsed["title"],
            "company_name_hint": parsed["company_name"],
            "text": parsed["text"],
            "emails": parsed["emails"],
            "has_form": parsed["has_form"],
            "fetched_with": fetched.fetched_with,
            "status_code": fetched.status_code,
            "checked_at": utc_now(),
        }
        pages.append(page)

        for link in parsed["links"]:
            if same_site(link["url"], fetched.final_url):
                continue
            haystack = f"{link['url']} {link.get('text', '')}".lower()
            if any(hint in haystack for hint in CONTACT_HINTS):
                external_contact_urls.append(link["url"])
        for link in priority_links(
            parsed["links"], fetched.final_url, group_order=priority_groups
        ):
            canonical = canonicalize_url(link)
            if canonical not in seen and canonical not in queue:
                queue.append(canonical)

    emails = []
    seen_emails: set[str] = set()
    contact_forms = []
    for page in pages:
        for email in page["emails"]:
            if email in seen_emails:
                continue
            seen_emails.add(email)
            item = {"email": email, "source_url": page["url"]}
            emails.append(item)
        if page["has_form"]:
            contact_forms.append({"url": page["url"], "verification": "form_found"})
    for url in dict.fromkeys(external_contact_urls):
        contact_forms.append({"url": url, "verification": "linked_from_official_site"})

    first_page = pages[0] if pages else None
    return {
        "candidate": candidate,
        "canonical_url": (
            f"{urlparse(first_page['url']).scheme}://{urlparse(first_page['url']).netloc}/" if first_page else canonicalize_url(start_url)
        ),
        "final_url": first_page["url"] if first_page else None,
        "site_status": "active" if pages else "blocked",
        "pages": pages,
        "emails": emails,
        "contact_forms": contact_forms,
        "errors": errors,
        "checked_at": utc_now(),
    }


def evidence_exists(claim: dict[str, Any], pages: list[dict[str, Any]]) -> bool:
    source_url = claim.get("evidence_url")
    evidence = normalize_text(str(claim.get("evidence_text_original") or ""))
    if not source_url or not evidence:
        return False
    for page in pages:
        if page.get("url") == source_url and evidence in normalize_text(page.get("text", "")):
            return True
    return False


def validate_claims(claims: Any, pages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(claims, list):
        return [], ["claims must be a list"]
    valid = []
    errors = []
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            errors.append(f"claim {index} is not an object")
            continue
        claim_type = claim.get("type")
        if claim_type not in REQUIRED_CLAIM_TYPES:
            errors.append(f"claim {index} has an invalid type")
            continue
        if not evidence_exists(claim, pages):
            errors.append(f"claim {index} evidence was not found in its source page")
            continue
        valid.append(claim)
    return valid, errors


def validate_exclusion_checks(
    checks: Any,
    campaign: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    excluded_types = [
        str(item).strip()
        for item in (campaign or {}).get("excluded_types", [])
        if str(item).strip()
    ]
    if not excluded_types:
        return list(checks) if isinstance(checks, list) else [], []
    if not isinstance(checks, list):
        return [], ["Excluded-type checks are missing"]

    valid: list[dict[str, Any]] = []
    errors: list[str] = []
    by_type: dict[str, dict[str, Any]] = {}
    for index, check in enumerate(checks):
        if not isinstance(check, dict):
            errors.append(f"exclusion check {index} is not an object")
            continue
        excluded_type = str(check.get("type") or "").strip()
        result = check.get("result")
        if excluded_type not in excluded_types:
            errors.append(f"exclusion check {index} does not match a campaign exclusion")
            continue
        if excluded_type in by_type:
            errors.append(f"duplicate exclusion check: {excluded_type}")
            continue
        if result not in EXCLUSION_CHECK_RESULTS:
            errors.append(f"exclusion check {index} has an invalid result")
            continue
        normalized = dict(check)
        normalized["type"] = excluded_type
        by_type[excluded_type] = normalized
        valid.append(normalized)

    for excluded_type in excluded_types:
        if excluded_type not in by_type:
            errors.append(f"Missing excluded-type check: {excluded_type}")
    return valid, errors


def finalize_record(
    crawl: dict[str, Any],
    assessment: dict[str, Any],
    campaign: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pages = crawl.get("pages") or []
    valid_claims, claim_errors = validate_claims(assessment.get("claims"), pages)
    exclusion_checks, exclusion_errors = validate_exclusion_checks(
        assessment.get("exclusion_checks"), campaign
    )
    claim_types = {claim["type"] for claim in valid_claims}
    recommendation = assessment.get("recommendation", "review")
    matched_exclusions = [
        check["type"] for check in exclusion_checks if check.get("result") == "matched"
    ]
    unclear_exclusions = [
        check["type"] for check in exclusion_checks if check.get("result") == "unclear"
    ]
    exclusions_clear = not exclusion_errors and not matched_exclusions and not unclear_exclusions

    if crawl.get("site_status") == "blocked":
        status = "blocked"
        reason = "The official website could not be retrieved"
    elif recommendation == "rejected":
        status = "rejected"
        reason = assessment.get("rejection_reason") or "The company did not meet the campaign requirements"
    elif matched_exclusions:
        status = "rejected"
        reason = "Matched excluded company type: " + ", ".join(matched_exclusions)
    elif (
        recommendation == "accepted"
        and REQUIRED_CLAIM_TYPES.issubset(claim_types)
        and exclusions_clear
    ):
        status = "accepted"
        reason = None
    else:
        status = "review"
        reason = None

    company_name = assessment.get("company_name")
    if not company_name and pages:
        company_name = pages[0].get("company_name_hint")
    uncertainties = list(assessment.get("uncertainties") or [])
    uncertainties.extend(claim_errors)
    uncertainties.extend(exclusion_errors)
    uncertainties.extend(f"Excluded type is unclear: {item}" for item in unclear_exclusions)
    missing = sorted(REQUIRED_CLAIM_TYPES - claim_types)
    if status == "review" and missing:
        uncertainties.append(f"Missing verified evidence: {', '.join(missing)}")

    return {
        "company_name": company_name,
        "canonical_url": crawl.get("canonical_url"),
        "final_url": crawl.get("final_url"),
        "country": assessment.get("country"),
        "company_type": assessment.get("company_type"),
        "company_overview_ja": assessment.get("company_overview_ja"),
        "emails": crawl.get("emails") or [],
        "contact_forms": crawl.get("contact_forms") or [],
        "assessment_recommendation": recommendation,
        "verification_status": status,
        "claims": valid_claims,
        "exclusion_checks": exclusion_checks,
        "uncertainties": list(dict.fromkeys(uncertainties)),
        "rejection_reason": reason,
        "checked_at": crawl.get("checked_at") or utc_now(),
        "discovery": {
            "query": (crawl.get("candidate") or {}).get("discovery_query"),
            "source_url": (crawl.get("candidate") or {}).get("discovery_source_url"),
        },
    }
