#!/usr/bin/env python3
"""Deterministic helpers for evidence-backed company research."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from http.client import HTTPException
import html
import ipaddress
import json
import math
import os
from pathlib import Path
import posixpath
import re
import socket
import time
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlencode, urljoin, urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, getproxies
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
    "about": ("about", "company", "who-we-are", "会社概要", "企業情報", "会社案内", "会社情報", "企業概要", "profile", "outline", "gaiyou", "gaiyo", "kaisha"),
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
        "所在地", "事業所", "営業所", "拠点", "アクセス", "access", "office_list",
    ),
    "products": ("product", "catalog", "matcha", "tea", "商品", "製品", "事業内容", "事業紹介", "業務内容", "施工", "工事", "business", "works", "service"),
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
DEFAULT_LINK_GROUP_ORDER = ("about", "products", "distribution", "locations", "contact")
HOSPITALITY_LINK_GROUP_ORDER = ("about", "menu", "locations", "contact")
REQUIRED_CLAIM_TYPES = {"product", "buyer_role", "target_market"}
EXCLUSION_CHECK_RESULTS = {"not_matched", "matched", "unclear"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


_INVISIBLE_RE = re.compile("[\ue000-\uf8ff\u200b-\u200d\u2060\ufeff]")


def normalize_text(value: str) -> str:
    # Private-use icon glyphs and zero-width characters are invisible on the page; drop them before matching.
    return re.sub(r"\s+", " ", _INVISIBLE_RE.sub("", html.unescape(value))).strip()


PRODUCT_EVIDENCE_RULES = {"already_handles", "can_use"}


def product_evidence_keywords(campaign: dict[str, Any]) -> list[str]:
    """Words that count as product relevance: the product's own keywords, plus the
    buyer-fit words when the campaign accepts companies that can use the product."""
    keywords = list((campaign.get("product") or {}).get("keywords") or [])
    evidence = campaign.get("product_evidence") or {}
    if evidence.get("rule") == "can_use":
        keywords += list(evidence.get("prescreen_keywords") or [])
    return keywords


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
    evidence = campaign.get("product_evidence")
    if not isinstance(evidence, dict):
        errors.append("product_evidence is required: decide in the intake what counts as product evidence (see references/intake-interview.md)")
    else:
        if evidence.get("rule") not in PRODUCT_EVIDENCE_RULES:
            errors.append("product_evidence.rule must be one of: " + ", ".join(sorted(PRODUCT_EVIDENCE_RULES)))
        if not str(evidence.get("summary_ja") or "").strip():
            errors.append("product_evidence.summary_ja is required")
        if evidence.get("rule") == "can_use" and not evidence.get("prescreen_keywords"):
            errors.append("product_evidence.prescreen_keywords must not be empty when rule is can_use")
    rules = campaign.get("judgment_rules", [])
    if not isinstance(rules, list) or not all(isinstance(rule, str) and rule.strip() for rule in rules):
        errors.append("judgment_rules must be a list of non-empty sentences (answers to the intake checklist)")
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


def _shared_host(hostname: str) -> bool:
    return bool(re.fullmatch(r"(?:www\d*\.)?(?:nns\.ne\.jp|fruits\.jp)", hostname)) or hostname in {
        "r.goope.jp", "yamanashi-machitsukuri.jp", "www.yamanashi-machitsukuri.jp"
    }


def _tenant_path(url: str) -> str:
    parsed = urlparse(canonicalize_url(url))
    path = parsed.path
    # Normalize encoded parent segments before comparing company boundaries.
    for _ in range(4):
        decoded = unquote(path)
        if decoded == path:
            break
        path = decoded
    path = posixpath.normpath('/' + path.lstrip('/').replace('\\', '/'))
    parts = path.strip('/').split('/')
    if re.fullmatch(r"(?:www\d*\.)?(?:nns\.ne\.jp|fruits\.jp)", parsed.hostname or ''):
        if parts[0].startswith('~') and len(parts[0]) > 1:
            return '/' + parts[0]
        if len(parts) > 1 and parts[0] == 'ent' and parts[1]:
            return '/ent/' + parts[1]
        return ''
    return '/' + parts[0] if parts[0] else ''


def company_key(url: str) -> str:
    """Company identity for supported shared providers; ordinary sites stay host-based."""
    return domain_key(url) + (_tenant_path(url) if _shared_host(urlparse(canonicalize_url(url)).hostname or '') else '')


def company_root_url(url: str) -> str:
    parsed = urlparse(canonicalize_url(url))
    path = _tenant_path(url) if _shared_host(parsed.hostname or '') else ''
    return canonicalize_url(f'{parsed.scheme}://{parsed.netloc}{path}/')


def _link_is_valid(url: str) -> bool:
    """Drop malformed page links (for example a phone number where the port belongs)."""
    try:
        canonicalize_url(url)
    except (TypeError, ValueError):
        return False
    return True


def same_site(left: str, right: str) -> bool:
    try:
        left_raw = urlparse(canonicalize_url(left)).hostname or ''
        right_raw = urlparse(canonicalize_url(right)).hostname or ''
    except ValueError:
        # A malformed page link (for example a phone number in the port) is not same-site.
        return False
    if _shared_host(left_raw) or _shared_host(right_raw):
        # A provider homepage is not the root of every customer's company site.
        return bool(_tenant_path(left) and _tenant_path(right) and company_key(left) == company_key(right))
    left_host = domain_key(left)
    right_host = domain_key(right)
    return left_host == right_host or left_host.endswith(f".{right_host}") or right_host.endswith(f".{left_host}")


DOH_URL = "https://cloudflare-dns.com/dns-query"
MAX_DOH_BYTES = 64 * 1024
_DOH_CACHE: dict[str, frozenset[str]] = {}


def doh_resolve(hostname: str, *, timeout: float = 10.0) -> set[str]:
    """Resolve A/AAAA records with DNS-over-HTTPS through the configured proxy.

    Used only when local DNS is unavailable but an HTTPS proxy is configured,
    as in Claude Code cloud sessions. Callers still apply the public-address check.
    """
    key = hostname.lower().rstrip(".")
    if key in _DOH_CACHE:
        return set(_DOH_CACHE[key])
    addresses: set[str] = set()
    opener = build_opener()
    for record_type in ("A", "AAAA"):
        request = Request(
            f"{DOH_URL}?{urlencode({'name': key, 'type': record_type})}",
            headers={"Accept": "application/dns-json", "User-Agent": USER_AGENT},
        )
        try:
            with opener.open(request, timeout=timeout) as response:
                payload = json.loads(read_limited(response, MAX_DOH_BYTES).decode("utf-8"))
        except (HTTPException, URLError, OSError, ValueError):
            continue
        for answer in payload.get("Answer") or []:
            if not isinstance(answer, dict) or answer.get("type") not in {1, 28}:
                continue
            try:
                addresses.add(str(ipaddress.ip_address(str(answer.get("data", "")).strip())))
            except ValueError:
                continue
    _DOH_CACHE[key] = frozenset(addresses)
    return addresses


def _default_fallback_resolver(hostname: str) -> set[str]:
    if not getproxies().get("https"):
        return set()
    return doh_resolve(hostname)


def validate_public_url(
    url: str,
    *,
    allow_private: bool = False,
    resolver: Callable[..., Any] = socket.getaddrinfo,
    fallback_resolver: Callable[[str], set[str]] | None = _default_fallback_resolver,
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
        addresses = fallback_resolver(hostname) if fallback_resolver else set()
        if not addresses:
            raise ValueError(f"Hostname could not be resolved: {exc}") from exc
    if not addresses:
        raise ValueError("Hostname did not resolve to an address")
    if not allow_private:
        for address in addresses:
            if not ipaddress.ip_address(address).is_global:
                raise ValueError("Private or non-global addresses are not allowed")
    return canonical


HTTP_ONLY_PROXY_REASON = "http-only site cannot be reached through the HTTPS-only proxy"


class HttpOnlyProxyError(RuntimeError):
    """An http:// site has no working https:// form and no HTTP proxy can reach it."""


def _https_only_proxy() -> bool:
    proxies = getproxies()
    return bool(proxies.get("https")) and not proxies.get("http")


def _local_dns_resolves(hostname: str) -> bool:
    try:
        socket.getaddrinfo(hostname, 80)
    except socket.gaierror:
        return False
    return True


def https_upgrade_url(url: str) -> str:
    """Return the https:// form of an http:// URL with the same host and path."""
    parsed = urlparse(url)
    netloc = parsed.netloc
    if parsed.port == 80:
        netloc = netloc.rsplit(":", 1)[0]
    return urlunparse(parsed._replace(scheme="https", netloc=netloc))


def needs_https_upgrade(url: str) -> bool:
    """True when an http:// URL cannot be fetched directly but its https form may be.

    This is the Claude Code cloud session case: local DNS is unavailable and only an
    HTTPS proxy is configured, so a plain http:// request fails with a DNS error.
    Machines with working local DNS or an HTTP proxy keep the original URL.
    """
    parsed = urlparse(url)
    if parsed.scheme.lower() != "http" or parsed.port not in {None, 80}:
        return False
    if not _https_only_proxy():
        return False
    return not _local_dns_resolves(parsed.hostname or "")


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
        charset = response.headers.get_content_charset()
        if not charset:
            declaration = re.search(br'<meta\b[^>]*charset\s*=\s*[\"\x27\s]*([a-zA-Z0-9_-]+)', body[:8192], re.I)
            charset = declaration.group(1).decode('ascii') if declaration else 'utf-8'
        if charset.lower().replace('-', '_') in {'shift_jis', 'sjis', 'x_sjis'}:
            charset = 'cp932'
        try:
            decoded = body.decode(charset, errors='replace')
        except LookupError:
            decoded = body.decode('utf-8', errors='replace')
        return FetchResult(decoded, final_url, "static", response.getcode())


def robots_text_allows(robots_text: str, target_url: str) -> bool:
    parser = RobotFileParser()
    parser.set_url(urljoin(target_url, "/robots.txt"))
    parser.parse(robots_text.splitlines())
    return parser.can_fetch(USER_AGENT, target_url)


def robots_allows(url: str, *, timeout: float = 10.0, allow_private: bool = False) -> bool:
    if needs_https_upgrade(url):
        url = https_upgrade_url(url)
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
        self.frame_links: list[str] = []
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
        elif tag == 'img' and self._anchor_href is not None:
            self._anchor_text.append(values.get('alt', ''))
        elif tag in {'frame', 'iframe'} and values.get('src'):
            self.frame_links.append(values['src'])
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


def corrupt_text(text: str) -> bool:
    return text.count('\ufffd') > max(3, len(text) // 50)


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
        if urlparse(absolute).scheme not in {"http", "https"} or not _link_is_valid(absolute):
            continue
        links.append({"url": absolute, "text": anchor_text})
    for source in parser.frame_links:
        absolute = urljoin(base_url, source).split('#', 1)[0]
        if urlparse(absolute).scheme in {'http', 'https'} and _link_is_valid(absolute):
            links.append({'url': absolute, 'text': 'frame document', 'kind': 'frame'})
    return {
        "company_name": company_name,
        "title": title,
        "text": text,
        "text_blocks": parser.text_blocks,
        "emails": sorted(emails),
        "links": links,
        "has_form": parser.contact_form_count > 0,
        "content_quality": 'unresolved' if corrupt_text(text) else 'readable',
    }


def looks_like_js_shell(parsed: dict[str, Any]) -> bool:
    text = parsed.get("text", "").lower()
    return len(text) < 200 or "enable javascript" in text or "javascript is required" in text or corrupt_text(text)


class BrowserEnvironmentError(RuntimeError):
    """Browser runtime failed before a website could be checked."""


def launch_browser(playwright: Any, *, timeout: float = 20.0) -> Any:
    if not math.isfinite(timeout) or not 0.001 <= timeout <= 60:
        raise BrowserEnvironmentError('Browser timeout must be finite and between 0.001 and 60 seconds')
    channel = os.environ.get('VLR_BROWSER_CHANNEL', 'chromium')
    if channel not in {'chromium', 'headless-shell'}:
        raise BrowserEnvironmentError('VLR_BROWSER_CHANNEL must be chromium or headless-shell')
    options: dict[str, Any] = {'headless': True, 'timeout': int(timeout * 1000)}
    if channel == 'chromium':
        options['channel'] = 'chromium'
    try:
        return playwright.chromium.launch(**options)
    except Exception as exc:
        raise BrowserEnvironmentError(f'Browser launch failed ({channel}): {exc}') from exc


def browser_diagnostic(*, timeout: float = 20.0) -> dict[str, Any]:
    """Render a local JS fixture, never contact a prospect's website."""
    project_dir = Path(__file__).resolve().parents[3]
    os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(project_dir / '.playwright-browsers'))
    result: dict[str, Any] = {'checked_at': utc_now(), 'channel': os.environ.get('VLR_BROWSER_CHANNEL', 'chromium')}
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = launch_browser(playwright, timeout=timeout)
            try:
                page = browser.new_page()
                page.set_content('<html><body><script>document.body.textContent="VLR JS rendered";</script></body></html>', timeout=int(timeout * 1000))
                if page.inner_text('body', timeout=int(timeout * 1000)) != 'VLR JS rendered':
                    raise RuntimeError('JavaScript fixture was not rendered')
            finally:
                browser.close()
        result['status'] = 'ok'
    except Exception as exc:
        result.update(status='environment_error', error=str(exc))
    return result


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
        raise BrowserEnvironmentError("Playwright is not installed; run scripts/bootstrap.py") from exc

    cache: dict[str, bool] = {}
    phase = 'initialization'
    try:
        with sync_playwright() as playwright:
            browser = launch_browser(playwright, timeout=timeout)
            try:
                context = browser.new_context(user_agent=USER_AGENT)
                page = context.new_page()

                def route_request(route: Any) -> None:
                    # Child documents must pass the crawler's scope, robots and budget checks.
                    if route.request.is_navigation_request() and route.request.frame != page.main_frame:
                        route.abort()
                    elif _browser_request_allowed(route.request.url, allow_private=allow_private, cache=cache):
                        route.continue_()
                    else:
                        route.abort()

                page.route("**/*", route_request)
                phase = 'navigation'
                response = page.goto(safe_url, wait_until="domcontentloaded", timeout=int(timeout * 1000))
                page.wait_for_timeout(750)
                final_url = validate_public_url(page.url, allow_private=allow_private)
                content = page.content()
                status = response.status if response else None
            finally:
                browser.close()
    except BrowserEnvironmentError:
        raise
    except Exception as exc:
        if phase == 'initialization':
            raise BrowserEnvironmentError(f'Playwright runtime initialization failed: {exc}') from exc
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
    if not needs_https_upgrade(url):
        return _fetch_page_once(url, timeout=timeout, browser_fallback=browser_fallback, allow_private=allow_private)
    # Only HTTPS leaves this machine: try the same host and path over https (with
    # normal certificate verification) before giving up on an http:// site.
    upgraded = https_upgrade_url(url)
    try:
        return _fetch_page_once(upgraded, timeout=timeout, browser_fallback=browser_fallback, allow_private=allow_private)
    except (HTTPException, URLError, OSError, ValueError, RuntimeError) as exc:
        if not _connection_failure(exc):
            raise  # https answered (HTTP status, content type, size...): report it as is.
        raise HttpOnlyProxyError(f"{HTTP_ONLY_PROXY_REASON} ({upgraded} failed: {exc})") from exc


_BROWSER_CONNECTION_ERROR = re.compile(
    r"net::ERR_(NAME_NOT_RESOLVED|CONNECTION_\w+|CERT_\w+|SSL_\w+|BAD_SSL_\w+|TIMED_OUT|TUNNEL_\w+|ADDRESS_\w+|PROXY_\w+|EMPTY_RESPONSE)"
)


def _connection_failure(exc: Exception) -> bool:
    """True when no usable https connection was made (DNS, refused, reset, TLS)."""
    if isinstance(exc, (BrowserEnvironmentError, HTTPError, ValueError)):
        return False
    if isinstance(exc, RuntimeError):
        return bool(_BROWSER_CONNECTION_ERROR.search(str(exc)))
    return isinstance(exc, (HTTPException, URLError, OSError))


def _fetch_page_once(
    url: str,
    *,
    timeout: float,
    browser_fallback: bool,
    allow_private: bool,
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
    exclude_urls: Iterable[str] = (),
) -> list[str]:
    grouped: dict[str, tuple[int, str]] = {}
    frames: list[str] = []
    excluded = set(exclude_urls)
    for link in links:
        url = link["url"]
        if canonicalize_url(url) in excluded:
            continue
        if not same_site(url, base_url):
            continue
        if link.get('kind') == 'frame':
            if url not in frames:
                frames.append(url)
            continue
        group = _link_group(link)
        if not group:
            continue
        score = _link_group_score(group, link)
        current = grouped.get(group)
        if current is None or score > current[0]:
            grouped[group] = (score, url)
    return frames + [grouped[group][1] for group in group_order if group in grouped]


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
    if not isinstance(max_pages, int) or not 1 <= max_pages <= 5:
        raise ValueError('max_pages must be between 1 and 5')
    start_url = candidate["url"]
    queue = [canonicalize_url(start_url)]
    seen: set[str] = set()
    pages: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    external_contact_urls: list[str] = []
    attempts = 0
    link_groups: dict[str, str | None] = {}
    about_visits = 0
    effective_scope = company_root_url(start_url) if _shared_host(urlparse(start_url).hostname or '') else None

    priority_groups = tuple(priority_groups)
    while queue and attempts < max_pages:
        requested_url = queue.pop(0)
        if requested_url in seen:
            continue
        seen.add(requested_url)
        attempts += 1
        if link_groups.get(requested_url) == 'about':
            about_visits += 1
        if attempts > 1 and delay_seconds:
            time.sleep(delay_seconds)
        if effective_scope and not same_site(requested_url, effective_scope):
            errors.append({'url': requested_url, 'reason': 'Request left the company scope', 'category': 'company_scope'})
            continue
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
            category = 'browser_environment' if isinstance(exc, BrowserEnvironmentError) else 'http_only_proxy' if isinstance(exc, HttpOnlyProxyError) else 'retrieval'
            errors.append({"url": requested_url, "reason": str(exc), "category": category})
            continue

        if effective_scope and not same_site(effective_scope, fetched.final_url):
            errors.append({'url': requested_url, 'reason': 'Redirect left the company tenant scope', 'category': 'company_scope'})
            continue
        if effective_scope is None and fetched.status_code is not None and 200 <= fetched.status_code < 300:
            effective_scope = company_root_url(fetched.final_url)
        seen.add(canonicalize_url(fetched.final_url))
        if any(p['url'] == fetched.final_url for p in pages):
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
            "content_quality": parsed.get('content_quality', 'unresolved' if corrupt_text(parsed['text']) else 'readable'),
        }
        pages.append(page)
        if fetched.status_code is None or not 200 <= fetched.status_code < 300:
            errors.append({'url': fetched.final_url, 'reason': f'HTTP status {fetched.status_code}', 'category': 'http_status'})
            continue

        for link in parsed["links"]:
            if same_site(link["url"], fetched.final_url):
                continue
            if _shared_host(urlparse(fetched.final_url).hostname or '') and _shared_host(urlparse(link['url']).hostname or ''):
                continue  # A neighbouring tenant is not this company's external form.
            haystack = f"{link['url']} {link.get('text', '')}".lower()
            if any(hint in haystack for hint in CONTACT_HINTS):
                external_contact_urls.append(link["url"])
        for link in priority_links(
            parsed["links"], fetched.final_url, group_order=priority_groups, exclude_urls=seen
        ):
            canonical = canonicalize_url(link)
            if canonical not in seen and canonical not in queue:
                group = _link_group({'url': canonical, 'text': next((x.get('text','') for x in parsed['links'] if canonicalize_url(x['url']) == canonical), '')})
                link_groups[canonical] = group
                # Follow an index to its detail, then leave room for business/location evidence.
                if group == 'about' and about_visits < 2:
                    queue.insert(0, canonical)
                else:
                    queue.append(canonical)

    emails = []
    seen_emails: set[str] = set()
    contact_forms = []
    for page in pages:
        if page['status_code'] is None or not 200 <= page['status_code'] < 300:
            continue
        if page['content_quality'] != 'readable':
            continue
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

    first_page = next((p for p in pages if p['status_code'] is not None and 200 <= p['status_code'] < 300), None)
    return {
        "candidate": candidate,
        "canonical_url": (
            company_root_url(first_page['url']) if first_page else canonicalize_url(start_url)
        ),
        "final_url": first_page["url"] if first_page else None,
        "site_status": "active" if first_page else "blocked",
        "company_scope_url": effective_scope,
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
    if '\ufffd' in evidence:
        return False
    for page in pages:
        if page.get('content_quality') == 'unresolved' or corrupt_text(page.get('text', '')):
            continue
        status = page.get('status_code', 200)  # Legacy saved fixtures may not carry HTTP metadata.
        if isinstance(status, int) and 200 <= status < 300 and page.get("url") == source_url and evidence in normalize_text(page.get("text", "")):
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
    scope_url = crawl.get('company_scope_url') or crawl.get('canonical_url') or (crawl.get('candidate') or {}).get('url')
    if scope_url and (crawl.get('company_scope_url') or _shared_host(urlparse(scope_url).hostname or '')):
        pages = [p for p in pages if p.get('url') and same_site(p['url'], scope_url)]
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
    if any(p.get('content_quality') == 'unresolved' or corrupt_text(p.get('text', '')) for p in pages):
        uncertainties.append('Retrieved text has unresolved decoding corruption')
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
