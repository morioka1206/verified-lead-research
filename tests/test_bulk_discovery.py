import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "verifying-sales-leads" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import import_osm  # noqa: E402
import prescreen  # noqa: E402


CAMPAIGN = {
    "product": {"name": "抹茶", "keywords": ["matcha", "Japanese green tea"]},
    "market": {"name": "アメリカ", "keywords": ["United States"]},
    "buyer_types": [{"name": "カフェ", "keywords": ["cafe"]}],
    "excluded_types": ["競合", "メディア"],
    "product_evidence": {"rule": "already_handles", "summary_ja": "抹茶の取扱いを証拠とする。"},
}


def page(url, text, status=200, quality="readable"):
    return {"url": url, "text": text, "status_code": status, "content_quality": quality}


def record(url, pages, status="active"):
    return {"candidate": {"url": url}, "site_status": status, "pages": pages, "errors": [], "emails": []}


class CampaignDefinitionTests(unittest.TestCase):
    def test_product_evidence_and_judgment_rules_are_validated(self):
        import leadlib
        base = {"id": "x", "product": {"name": "抹茶", "keywords": ["matcha"]}, "market": {"name": "米国", "keywords": ["US"]},
                "buyer_types": [{"name": "カフェ"}]}
        self.assertTrue(any("product_evidence is required" in e for e in leadlib.validate_campaign(base)))
        ok = dict(base, product_evidence={"rule": "can_use", "summary_ja": "使える業態", "prescreen_keywords": ["latte"]},
                  judgment_rules=["本部サイトのみ合格。"])
        self.assertEqual(leadlib.validate_campaign(ok), [])
        self.assertTrue(any("judgment_rules" in e for e in leadlib.validate_campaign(dict(ok, judgment_rules="x"))))
        self.assertIn("latte", leadlib.product_evidence_keywords(ok))


class OsmImportTests(unittest.TestCase):
    def test_normalize_skips_social_marketplace_and_campus_hosts(self):
        self.assertIsNone(import_osm.normalize_website("https://www.facebook.com/somecafe"))
        self.assertIsNone(import_osm.normalize_website("https://somecafe.square.site/"))
        self.assertIsNone(import_osm.normalize_website("https://dining.example.edu/"))
        self.assertIsNone(import_osm.normalize_website("not a url"))
        self.assertEqual(
            import_osm.normalize_website("www.Example-Cafe.com/locations/12; https://x.com/a"),
            "https://www.example-cafe.com/",
        )

    def test_elements_collapse_chain_locations_to_one_company(self):
        elements = [
            {"type": "node", "id": 1, "tags": {"name": "Bean A", "website": "https://bean.example/store/1"}},
            {"type": "node", "id": 2, "tags": {"name": "Bean B", "website": "https://www.bean.example/store/2"}},
            {"type": "way", "id": 3, "tags": {"name": "Leaf", "contact:website": "leaf.example"}},
            {"type": "node", "id": 4, "tags": {"name": "No site"}},
        ]
        result = import_osm.elements_to_candidates(elements, "US-RI", "amenity=cafe")
        self.assertEqual([c["url"] for c in result], ["https://bean.example/", "https://leaf.example/"])
        self.assertEqual(result[0]["osm_locations"], 2)
        self.assertEqual(result[0]["search_result_source_url"], "https://www.openstreetmap.org/node/1")
        self.assertIn("US-RI", result[0]["discovery_query"])

    def test_query_uses_state_area_and_website_tags(self):
        query = import_osm.build_query([("amenity", "cafe")], "US-CA", 60)
        self.assertIn('area["ISO3166-2"="US-CA"]', query)
        self.assertIn('nwr["amenity"="cafe"]["website"](area.a);', query)
        self.assertIn('["contact:website"]', query)
        with self.assertRaises(ValueError):
            import_osm.parse_tags(['amenity="cafe'])

    def test_excluded_keys_read_candidate_files(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "discovery-1.json"
            path.write_text(json.dumps([{"url": "https://www.known.example/about"}]), encoding="utf-8")
            keys = import_osm.load_excluded_keys([Path(tmp)])
        self.assertEqual(len(keys), 1)


class PrescreenTests(unittest.TestCase):
    def crawls(self):
        return [
            record("https://a.example/", [page("https://a.example/", "Ceremonial MATCHA cafe in Austin, TX 78701")]),
            record("https://b.example/", [page("https://b.example/", "Espresso and pastries only")]),
            record("https://c.example/", [], status="blocked"),
            record("https://d.example/", [page("https://d.example/", "matcha", status=404)]),
            record("https://e.example/", [page("https://e.example/", "matcha", quality="unresolved")]),
        ]

    def test_screen_routes_only_product_mentions_to_ai(self):
        result = prescreen.screen(CAMPAIGN, self.crawls())
        self.assertEqual([item["candidate_url"] for item in result["for_ai"]], ["https://a.example/"])
        self.assertEqual(result["auto_review"], 4)
        ai = result["for_ai"][0]
        self.assertTrue(ai["product_snippets"] and ai["market_snippets"])
        for auto in result["auto_assessments"]:
            self.assertEqual(auto["recommendation"], "review")
            self.assertEqual(auto["claims"], [])
            self.assertEqual([c["type"] for c in auto["exclusion_checks"]], CAMPAIGN["excluded_types"])
            self.assertTrue(all(c["result"] == "unclear" for c in auto["exclusion_checks"]))

    def test_merge_covers_every_crawl_in_order(self):
        crawls = self.crawls()
        result = prescreen.screen(CAMPAIGN, crawls)
        ai = [{"candidate_url": "https://a.example/", "recommendation": "accepted"}]
        merged = prescreen.merge(crawls, result, ai)
        self.assertEqual([m["candidate_url"] for m in merged], [c["candidate"]["url"] for c in crawls])
        with self.assertRaises(ValueError):
            prescreen.merge(crawls, result, [])

    def test_merge_never_upgrades_auto_review(self):
        crawls = self.crawls()
        result = prescreen.screen(CAMPAIGN, crawls)
        ai = [
            {"candidate_url": "https://a.example/", "recommendation": "accepted"},
            {"candidate_url": "https://b.example/", "recommendation": "accepted"},
        ]
        with self.assertRaises(ValueError):
            prescreen.merge(crawls, result, ai)


class MalformedLinkTests(unittest.TestCase):
    def test_same_site_rejects_link_with_phone_number_port(self):
        import leadlib
        self.assertFalse(leadlib.same_site("https://shop.example:+1.510.900.0449/", "https://shop.example/"))
        self.assertTrue(leadlib.same_site("https://www.shop.example/about", "https://shop.example/"))

    def test_html_parse_drops_malformed_links(self):
        import leadlib
        html = '<a href="http://shop.example:+1.510.900.0449/">call</a><a href="/about">About</a>'
        links = [link["url"] for link in leadlib.parse_site(html, "https://shop.example/")["links"]]
        self.assertEqual(links, ["https://shop.example/about"])


class CheckAssessmentTests(unittest.TestCase):
    def test_reports_accepted_record_with_missing_excerpt(self):
        import check_assessments
        crawl = record("https://a.example/", [page("https://a.example/", "Matcha latte at our cafe in Austin, TX 78701")])
        good = {
            "candidate_url": "https://a.example/", "recommendation": "accepted",
            "claims": [
                {"type": "product", "evidence_url": "https://a.example/", "evidence_text_original": "Matcha latte"},
                {"type": "buyer_role", "evidence_url": "https://a.example/", "evidence_text_original": "our cafe"},
                {"type": "target_market", "evidence_url": "https://a.example/", "evidence_text_original": "Austin, TX 78701"},
            ],
            "exclusion_checks": [{"type": t, "result": "not_matched"} for t in CAMPAIGN["excluded_types"]],
        }
        self.assertEqual(check_assessments.check(CAMPAIGN, [crawl], [good])["problems"], [])
        bad = json.loads(json.dumps(good))
        bad["claims"][0]["evidence_text_original"] = "Hojicha latte"
        problems = check_assessments.check(CAMPAIGN, [crawl], [bad])["problems"]
        self.assertEqual(len(problems), 1)
        self.assertIn("becomes review", problems[0]["problem"])


class MergeRunsTests(unittest.TestCase):
    def test_merge_dedupes_by_company_and_reports_conflicts(self):
        import merge_runs
        a = [{"canonical_url": "https://www.cafe.example/", "verification_status": "accepted"},
             {"canonical_url": "https://other.example/", "verification_status": "review"}]
        b = [{"canonical_url": "https://cafe.example/menu", "verification_status": "accepted"},
             {"canonical_url": "https://other.example/", "verification_status": "accepted"},
             {"canonical_url": "https://new.example/", "verification_status": "rejected"}]
        result = merge_runs.merge([("run-a", a), ("run-b", b)])
        self.assertEqual([r["source_run"] for r in result["records"]], ["run-a", "run-b"])
        self.assertEqual(result["summary"]["duplicates_removed"], 1)
        self.assertEqual(len(result["summary"]["status_conflicts"]), 1)


class AuditAcceptedTests(unittest.TestCase):
    def test_flags_weak_quotes_and_signals(self):
        import audit_accepted
        def rec(url, product, market):
            return {"verification_status": "accepted", "canonical_url": url, "company_name": url,
                    "claims": [{"type": "product", "evidence_text_original": product},
                               {"type": "target_market", "evidence_text_original": market}],
                    "exclusion_checks": [{"reason_ja": f"r-{url}"}]}
        records = [rec("https://a.example/", "Matcha Latte $5.50", "Austin, TX 78701"),
                   rec("https://b.example/", "Menu | Matcha", "Free shipping on US orders"),
                   rec("https://c.example/", "Matcha Latte", "downtown by the river")]
        pages = {"https://c.example/": [{"text": "Own a franchise today. Our cafe has closed."}]}
        flagged = {f["canonical_url"]: f["flags"] for f in audit_accepted.audit(CAMPAIGN, records, pages)}
        self.assertNotIn("https://a.example/", flagged)
        self.assertEqual(flagged["https://b.example/"], ["product_quote_navigation"])
        self.assertEqual(set(flagged["https://c.example/"]), {"market_quote_no_marker", "franchise_signal", "closure_signal"})


class BuildAssessmentsTests(unittest.TestCase):
    def crawls(self):
        return [record("https://a.example/", [
            page("https://a.example/", "Home | Cafe. Visit us at 1 Main St, Austin, TX 78701"),
            page("https://a.example/menu", "Drinks: Matcha Latte $5.50, ceremonial grade. Our cafe roasts daily."),
        ])]

    def decision(self, **over):
        d = {"index": 0, "company_name": "A Cafe", "recommendation": "accepted",
             "claims": [{"type": "product", "quote": "Matcha Latte $5.50", "ja": "抹茶ラテ"},
                        {"type": "buyer_role", "quote": "Our cafe roasts daily.", "ja": "カフェ"},
                        {"type": "target_market", "quote": "Austin, TX 78701", "ja": "テキサス"}],
             "exclusions": [["not_matched", "米国テキサスの独立系カフェ。"], ["not_matched", "メニューを掲載する店舗サイト。"]]}
        d.update(over)
        return d

    def test_builds_valid_assessment_and_locates_pages(self):
        import build_assessments
        out, errors = build_assessments.build(CAMPAIGN, self.crawls(), [self.decision()])
        self.assertEqual(errors, [])
        self.assertEqual({c["type"]: c["evidence_url"] for c in out[0]["claims"]}["product"], "https://a.example/menu")
        self.assertEqual([c["type"] for c in out[0]["exclusion_checks"]], CAMPAIGN["excluded_types"])

    def test_guardrails_reject_weak_accepts(self):
        import build_assessments
        bad = self.decision(claims=[{"type": "product", "quote": "Matcha", "ja": ""},
                                    {"type": "buyer_role", "quote": "Our cafe roasts daily.", "ja": ""},
                                    {"type": "target_market", "quote": "1 Main St", "ja": ""}],
                            exclusions=[["not_matched", "short"]])
        _, errors = build_assessments.build(CAMPAIGN, self.crawls(), [bad])
        joined = " ".join(errors)
        self.assertIn("too thin", joined)
        self.assertIn("no US state", joined)
        self.assertIn("needs exactly 2 exclusions", joined)

    def test_allows_priced_pipe_menu_and_lowercase_state(self):
        import build_assessments
        crawls = [record("https://p.example/", [page("https://p.example/", "Matcha Latte | $6.00 (12oz) | Chai. Our cafe on Magazine St, new orleans, la.")])]
        d = {"index": 0, "recommendation": "accepted",
             "claims": [{"type": "product", "quote": "Matcha Latte | $6.00 (12oz)"},
                        {"type": "buyer_role", "quote": "Our cafe on Magazine St"},
                        {"type": "target_market", "quote": "new orleans, la"}],
             "exclusions": [["not_matched", "ニューオーリンズの独立系カフェ。"], ["not_matched", "価格付きメニューのある店舗サイト。"]]}
        _, errors = build_assessments.build(CAMPAIGN, crawls, [d])
        self.assertEqual(errors, [])
        self.assertTrue(build_assessments.looks_like_navigation("Home | Menu | Contact"))

    def test_rejects_reused_boilerplate_reason(self):
        import build_assessments
        crawls = [record(f"https://c{i}.example/", [page(f"https://c{i}.example/", "Matcha Latte $5 at our cafe, Austin, TX 78701")]) for i in range(7)]
        decisions = [{"index": i, "recommendation": "review", "claims": [],
                      "exclusions": [["not_matched", "定型の理由文です。"], ["not_matched", f"店舗{i}の固有の理由。"]]} for i in range(7)]
        _, errors = build_assessments.build(CAMPAIGN, crawls, decisions)
        self.assertTrue(any("reused by 7" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
