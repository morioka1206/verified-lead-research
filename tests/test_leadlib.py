from io import BytesIO
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skill" / "verifying-sales-leads" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import leadlib  # noqa: E402


HTML = """
<!doctype html>
<html>
  <head>
    <title>Example Tea Imports | Japanese Tea Distributor</title>
    <meta property="og:site_name" content="Example Tea Imports">
  </head>
  <body>
    <p>Example Tea Imports is a United States distributor of Japanese matcha for cafés and retailers.</p>
    <p>Email our wholesale team at sales@example.com.</p>
    <a href="/about">About</a>
    <a href="/products">Matcha products</a>
    <a href="/wholesale">Wholesale distribution</a>
    <a href="/contact">Contact us</a>
    <form action="/newsletter"><input name="email"><button>Subscribe</button></form>
    <script>ignore@example.net</script>
  </body>
</html>
"""


def public_resolver(*_args):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]


class LeadLibraryTests(unittest.TestCase):
    def test_parse_extracts_public_contact_data(self):
        parsed = leadlib.parse_site(HTML, "https://example.com/")
        self.assertEqual(parsed["company_name"], "Example Tea Imports")
        self.assertEqual(parsed["emails"], ["sales@example.com"])
        self.assertNotIn("ignore@example.net", parsed["emails"])
        self.assertFalse(parsed["has_form"])
        self.assertEqual(len(leadlib.priority_links(parsed["links"], "https://example.com/")), 4)

    def test_contact_form_is_not_confused_with_newsletter(self):
        html = """
        <form action="/newsletter"><input name="email"><button>Subscribe</button></form>
        <form action="/contact"><input name="company"><textarea name="message"></textarea></form>
        """
        self.assertTrue(leadlib.parse_site(html, "https://example.com/contact")["has_form"])
        newsletter = "<form action='/contact#contact_form'><input name='contact[email]'><button>Subscribe</button></form>"
        self.assertFalse(leadlib.parse_site(newsletter, "https://example.com/")["has_form"])

    def test_mailto_email_is_trimmed(self):
        parsed = leadlib.parse_site(
            "<a href='mailto:info@example.com%C2%A0'>Email</a>",
            "https://example.com/",
        )
        self.assertEqual(parsed["emails"], [])
        parsed = leadlib.parse_site(
            "<a href='mailto:info@example.com\u00a0'>Email</a>",
            "https://example.com/",
        )
        self.assertEqual(parsed["emails"], ["info@example.com"])

    def test_duplicate_email_keeps_one_source(self):
        page = {
            "url": "https://example.com/",
            "text": "Example wholesale matcha distributor in the United States.",
            "emails": ["sales@example.com"],
            "links": [],
            "has_form": False,
            "company_name": "Example",
            "title": "Example",
        }

        def fake_fetch(url, **_kwargs):
            parsed = dict(page, url=url)
            return leadlib.FetchResult("", url, "static", 200), parsed

        with patch.object(leadlib, "robots_allows", return_value=True), patch.object(
            leadlib, "fetch_page", side_effect=fake_fetch
        ), patch.object(leadlib, "priority_links", return_value=["https://example.com/about"]):
            crawl = leadlib.crawl_company(
                {"url": "https://example.com/"}, max_pages=2, delay_seconds=0
            )
        self.assertEqual(crawl["emails"], [{"email": "sales@example.com", "source_url": "https://example.com/"}])

    def test_private_urls_and_unsafe_schemes_are_rejected(self):
        for url in ("http://localhost/", "http://127.0.0.1/", "file:///etc/passwd"):
            with self.assertRaises(ValueError):
                leadlib.validate_public_url(url)
        safe = leadlib.validate_public_url("https://example.com", resolver=public_resolver)
        self.assertEqual(safe, "https://example.com/")

    def test_redirect_handler_rejects_private_destination(self):
        handler = leadlib.SafeRedirectHandler()
        with self.assertRaises(ValueError):
            handler.redirect_request(None, None, 302, "Found", {}, "http://127.0.0.1/private")

    def test_response_size_limit(self):
        self.assertEqual(leadlib.read_limited(BytesIO(b"1234"), 4), b"1234")
        with self.assertRaises(ValueError):
            leadlib.read_limited(BytesIO(b"12345"), 4)

    def test_robots_disallow(self):
        robots = "User-agent: *\nDisallow: /private\n"
        self.assertFalse(leadlib.robots_text_allows(robots, "https://example.com/private"))
        self.assertTrue(leadlib.robots_text_allows(robots, "https://example.com/public"))

    def test_crawler_stops_at_five_pages(self):
        parsed = leadlib.parse_site(HTML, "https://example.com/")

        def fake_fetch(url, **_kwargs):
            result = leadlib.FetchResult(HTML, url, "static", 200)
            return result, parsed

        with patch.object(leadlib, "robots_allows", return_value=True), patch.object(leadlib, "fetch_page", side_effect=fake_fetch):
            crawl = leadlib.crawl_company({"url": "https://example.com/"}, max_pages=5, delay_seconds=0)
        self.assertEqual(len(crawl["pages"]), 5)

    def test_negative_delay_is_rejected(self):
        with self.assertRaises(ValueError):
            leadlib.crawl_company(
                {"url": "https://example.com/"}, delay_seconds=-1
            )

    def test_all_three_claim_types_are_required(self):
        page = {
            "url": "https://example.com/about",
            "text": "We import Japanese matcha. We are a wholesale distributor. Based in California.",
        }
        crawl = {
            "candidate": {"url": "https://example.com/"},
            "canonical_url": "https://example.com/",
            "final_url": "https://example.com/about",
            "site_status": "active",
            "pages": [page],
            "emails": [],
            "contact_forms": [],
            "checked_at": "2026-09-23T00:00:00+00:00",
        }
        base_claims = [
            {
                "type": "product",
                "evidence_url": page["url"],
                "evidence_text_original": "We import Japanese matcha.",
                "evidence_text_ja": "日本産抹茶を輸入している。",
            },
            {
                "type": "buyer_role",
                "evidence_url": page["url"],
                "evidence_text_original": "We are a wholesale distributor.",
                "evidence_text_ja": "卸売流通業者である。",
            },
        ]
        assessment = {"company_name": "Example", "recommendation": "accepted", "claims": base_claims}
        self.assertEqual(leadlib.finalize_record(crawl, assessment)["verification_status"], "review")
        assessment["claims"] = base_claims + [
            {
                "type": "target_market",
                "evidence_url": page["url"],
                "evidence_text_original": "Based in California.",
                "evidence_text_ja": "カリフォルニアを拠点としている。",
            }
        ]
        self.assertEqual(leadlib.finalize_record(crawl, assessment)["verification_status"], "accepted")

    def test_invented_evidence_is_rejected(self):
        pages = [{"url": "https://example.com/", "text": "Real text only."}]
        claims, errors = leadlib.validate_claims(
            [
                {
                    "type": "product",
                    "evidence_url": "https://example.com/",
                    "evidence_text_original": "Invented sentence.",
                }
            ],
            pages,
        )
        self.assertEqual(claims, [])
        self.assertTrue(errors)

    def test_campaign_limits(self):
        campaign = {
            "id": "test",
            "product": {"name": "matcha", "keywords": ["matcha"]},
            "market": {"name": "US", "keywords": ["USA"]},
            "buyer_types": [{"name": "importer", "keywords": ["importer"]}],
            "target_accepted": 31,
            "max_candidates": 101,
            "max_pages_per_company": 6,
        }
        errors = leadlib.validate_campaign(campaign)
        self.assertEqual(len(errors), 3)


if __name__ == "__main__":
    unittest.main()
