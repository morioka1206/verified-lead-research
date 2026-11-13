"""Reproductions of omissions found during the November cross-client review."""
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/verifying-sales-leads/scripts'))
import leadlib
import import_osm


class RetrievalRegressionTests(unittest.TestCase):
    def test_structured_addresses_do_not_hide_empty_javascript_shell(self):
        addresses = [{'@type': 'PostalAddress', 'streetAddress': f'{n} Main Street',
                      'addressLocality': 'Cambridge', 'addressRegion': 'MA',
                      'postalCode': '02139', 'addressCountry': 'US'} for n in range(5)]
        raw = '<div id="root"></div><script type="application/ld+json">' + json.dumps(addresses) + '</script>'
        rendered = '<p>Our bakery makes cookies and pastries for cafes.</p>'
        url = 'https://bakery.example/'
        with patch.object(leadlib, 'static_fetch', return_value=leadlib.FetchResult(raw, url, 'static', 200)), \
             patch.object(leadlib, 'playwright_fetch', return_value=leadlib.FetchResult(rendered, url, 'playwright', 200)):
            result, parsed = leadlib.fetch_page(url)
        self.assertEqual(result.fetched_with, 'playwright')
        self.assertIn('Our bakery makes cookies', parsed['text'])
        self.assertIn('[structured data address]', leadlib.parse_site(raw, url)['text'])

    def test_static_addresses_survive_hydration_only_at_same_successful_url(self):
        url = 'https://bakery.example/'
        raw = '<div id="app"></div><script type="application/ld+json">' + json.dumps([
            {'@type': 'PostalAddress', 'streetAddress': '123 Main Street',
             'addressLocality': 'Cambridge', 'addressRegion': 'MA', 'postalCode': '02139'}]) + '</script>'
        for final, static_status, browser_status, retain in [(url, 200, 200, True),
                ('https://other.example/', 200, 200, False),
                ('https://bakery.example/another-company', 200, 200, False),
                (url, 404, 200, False), (url, 200, 500, False)]:
            with self.subTest(final=final, static=static_status, browser=browser_status), \
                 patch.object(leadlib, 'static_fetch', return_value=leadlib.FetchResult(raw, url, 'static', static_status)), \
                 patch.object(leadlib, 'playwright_fetch', return_value=leadlib.FetchResult('<p>Wholesale bakery cookies</p>', final, 'playwright', browser_status)):
                _, parsed = leadlib.fetch_page(url)
            self.assertEqual('123 Main Street' in parsed['text'], retain)

    def test_static_addresses_are_not_duplicated_when_rendering_preserves_them(self):
        url = 'https://bakery.example/'
        raw = '<script type="application/ld+json">{"@type":"PostalAddress","streetAddress":"123 Main Street"}</script>'
        with patch.object(leadlib, 'static_fetch', return_value=leadlib.FetchResult(raw, url, 'static', 200)), \
             patch.object(leadlib, 'playwright_fetch', return_value=leadlib.FetchResult('<p>Wholesale bakery</p>' + raw, url, 'playwright', 200)):
            _, parsed = leadlib.fetch_page(url)
        self.assertEqual(parsed['text'].count('[structured data address] 123 Main Street'), 1)

    def test_readable_visible_page_still_uses_static_fetch(self):
        raw = '<p>' + 'We manufacture tea and bakery ingredients in our own facility. ' * 6 + '</p>'
        url = 'https://bakery.example/'
        with patch.object(leadlib, 'static_fetch', return_value=leadlib.FetchResult(raw, url, 'static', 200)), \
             patch.object(leadlib, 'playwright_fetch', side_effect=AssertionError('Unnecessary browser fetch')):
            result, _ = leadlib.fetch_page(url)
        self.assertEqual(result.fetched_with, 'static')

    def test_cookie_food_pages_remain_evidence_candidates(self):
        for path, label, order in [('/products/cookies/', 'Our products', leadlib.DEFAULT_LINK_GROUP_ORDER),
                                   ('/menu/', 'Menu - Coffee and Cookies', leadlib.HOSPITALITY_LINK_GROUP_ORDER),
                                   ('/cookies/', 'Cookies products', leadlib.DEFAULT_LINK_GROUP_ORDER)]:
            with self.subTest(path=path):
                url = 'https://bakery.example' + path
                self.assertEqual(leadlib.priority_links([{'url': url, 'text': label}],
                    'https://bakery.example/', group_order=order), [url])

    def test_cookie_policies_still_do_not_take_page_slots(self):
        for path, label in [('/cookie-policy/access/', 'Accessibility'),
                            ('/cookies', 'Cookie settings'), ('/about/cookie_notice', 'About cookies'),
                            ('/about/cookies', 'How we use cookies'),
                            ('/about/cookies/policy', 'Policy on cookies'),
                            ('/company/cookie-richtlinie', 'Cookie-Richtlinie')]:
            with self.subTest(path=path):
                self.assertEqual(leadlib.priority_links([{'url': 'https://bakery.example' + path, 'text': label}],
                    'https://bakery.example/'), [])


class DiscoveryRegressionTests(unittest.TestCase):
    def test_overpass_runtime_error_tries_mirror_instead_of_partial_data(self):
        replies = [{'elements': [{'id': 1}], 'remark': 'runtime error: Query timed out'}, {'elements': []}]
        with patch.object(import_osm, 'fetch_overpass', side_effect=replies):
            self.assertEqual(import_osm.fetch_with_fallback('q', ['main', 'mirror'], 10), {'elements': []})

    def test_overpass_failure_is_not_saved_as_completed_and_can_resume(self):
        with TemporaryDirectory() as folder:
            output = Path(folder) / 'discovery.json'
            argv = ['import_osm.py', '--preset', 'cafe', '--area', 'US-CA', '--pause', '0',
                    '--endpoint', 'test', '--output', str(output)]
            with patch.object(sys, 'argv', argv), patch.object(import_osm, 'fetch_overpass',
                return_value={'elements': [], 'remark': 'runtime error: Query timed out'}):
                self.assertEqual(import_osm.main(), 1)
            self.assertFalse(output.with_name(output.name + '.areas.json').exists())
            with patch.object(sys, 'argv', argv), patch.object(import_osm, 'fetch_overpass', return_value={'elements': []}):
                self.assertEqual(import_osm.main(), 0)
            self.assertEqual(json.loads(output.with_name(output.name + '.areas.json').read_text()),
                             {'amenity=cafe': ['US-CA']})

    def test_malformed_overpass_payload_does_not_masquerade_as_empty_region(self):
        for payload in ({}, {'elements': None}, {'elements': {}}, [], {'elements': [{}]},
                        {'elements': [None]}, {'elements': [{'id': 1, 'tags': 'invalid'}]}):
            with self.subTest(payload=payload), patch.object(import_osm, 'fetch_overpass', return_value=payload):
                with self.assertRaises(ValueError):
                    import_osm.fetch_with_fallback('q', ['main'], 10)

    def test_malformed_elements_try_mirror_and_later_areas_continue(self):
        with TemporaryDirectory() as folder:
            output = Path(folder) / 'discovery.json'
            argv = ['import_osm.py', '--preset', 'cafe', '--area', 'US-CA', '--area', 'US-NY',
                    '--pause', '0', '--endpoint', 'main', '--endpoint', 'mirror', '--output', str(output)]
            valid = {'elements': [{'type': 'node', 'id': 42, 'tags': {'website': 'https://cafe.example/'}}]}
            with patch.object(sys, 'argv', argv), patch.object(import_osm, 'fetch_overpass',
                    side_effect=[{'elements': [None]}, {'elements': []}, valid]):
                self.assertEqual(import_osm.main(), 0)
            self.assertEqual([row['url'] for row in json.loads(output.read_text())], ['https://cafe.example/'])
            self.assertEqual(json.loads(output.with_name(output.name + '.areas.json').read_text()),
                             {'amenity=cafe': ['US-CA', 'US-NY']})

    def test_osm_preserves_supported_shared_tenant_roots(self):
        for raw, wanted in [('https://r.goope.jp/cafe-a/menu', 'https://r.goope.jp/cafe-a/'),
                            ('https://www.nns.ne.jp/~cafe-a/about', 'https://www.nns.ne.jp/~cafe-a/'),
                            ('https://www.fruits.jp/ent/cafe-a/menu', 'https://www.fruits.jp/ent/cafe-a/'),
                            ('https://yamanashi-machitsukuri.jp/cafe-a/about', 'https://yamanashi-machitsukuri.jp/cafe-a/')]:
            with self.subTest(raw=raw):
                self.assertEqual(import_osm.normalize_website(raw), wanted)
        elements = [{'type': 'node', 'id': n, 'tags': {'website': f'https://r.goope.jp/cafe-{n}/menu'}} for n in (1, 2)]
        results = import_osm.elements_to_candidates(elements, 'JP-19', 'amenity=cafe')
        self.assertEqual([r['url'] for r in results], ['https://r.goope.jp/cafe-1/', 'https://r.goope.jp/cafe-2/'])

    def test_shared_provider_roots_and_unsupported_tenants_are_excluded(self):
        for raw in ('https://r.goope.jp/', 'https://www.nns.ne.jp/', 'https://www.fruits.jp/ent/',
                    'https://yamanashi-machitsukuri.jp/', 'https://sites.google.com/view/cafe/'):
            with self.subTest(raw=raw):
                self.assertIsNone(import_osm.normalize_website(raw))


if __name__ == '__main__':
    unittest.main()
