"""http:// candidates behind an HTTPS-only proxy (Claude Code cloud sessions); no live network."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/verifying-sales-leads/scripts'))
import leadlib

HTTPS_ONLY = {'https': 'http://proxy.invalid:3128'}
BOTH = {'https': 'http://proxy.invalid:3128', 'http': 'http://proxy.invalid:3128'}
PAGE = '<html><head><title>Neuland</title></head><body>' + 'Fleisch und Wurst aus Berlin. ' * 20 + '</body></html>'


def environment(proxies=HTTPS_ONLY, dns=False):
    return (
        patch.object(leadlib, 'getproxies', return_value=proxies),
        patch.object(leadlib, '_local_dns_resolves', return_value=dns),
    )


class HttpsUpgradeDecisionTests(unittest.TestCase):
    def check(self, url, proxies=HTTPS_ONLY, dns=False):
        a, b = environment(proxies, dns)
        with a, b:
            return leadlib.needs_https_upgrade(url)

    def test_upgrade_only_for_http_behind_https_only_proxy_without_dns(self):
        self.assertTrue(self.check('http://www.neuland-kluge.de/'))
        self.assertTrue(self.check('http://www.mago-wurst.de:80/produkte'))
        self.assertFalse(self.check('https://www.neuland-kluge.de/'))
        self.assertFalse(self.check('http://www.neuland-kluge.de/', proxies=BOTH))
        self.assertFalse(self.check('http://www.neuland-kluge.de/', proxies={}))
        self.assertFalse(self.check('http://www.neuland-kluge.de/', dns=True))
        self.assertFalse(self.check('http://127.0.0.1:8080/'))

    def test_upgraded_url_keeps_host_path_and_query(self):
        self.assertEqual(
            leadlib.https_upgrade_url('http://www.mendoza-berlin.de:80/speisen/karte?lang=de'),
            'https://www.mendoza-berlin.de/speisen/karte?lang=de',
        )


class HttpsUpgradeFetchTests(unittest.TestCase):
    def setUp(self):
        a, b = environment()
        a.start(), b.start()
        self.addCleanup(a.stop)
        self.addCleanup(b.stop)

    def test_static_fetch_uses_https_form(self):
        calls = []

        def static(url, **_kw):
            calls.append(url)
            return leadlib.FetchResult(PAGE, url, 'static', 200)

        with patch.object(leadlib, 'static_fetch', side_effect=static), \
                patch.object(leadlib, 'playwright_fetch') as browser:
            result, parsed = leadlib.fetch_page('http://www.neuland-kluge.de/')
        self.assertEqual(calls, ['https://www.neuland-kluge.de/'])
        self.assertEqual(result.final_url, 'https://www.neuland-kluge.de/')
        self.assertEqual(parsed['title'], 'Neuland')
        browser.assert_not_called()

    def test_browser_fallback_uses_https_form(self):
        def browser(url, **_kw):
            return leadlib.FetchResult(PAGE, url, 'playwright', 200)

        with patch.object(leadlib, 'static_fetch', side_effect=URLError('timed out')), \
                patch.object(leadlib, 'playwright_fetch', side_effect=browser) as rendered:
            result, _ = leadlib.fetch_page('http://www.mago-wurst.de/')
        rendered.assert_called_once()
        self.assertEqual(rendered.call_args.args[0], 'https://www.mago-wurst.de/')
        self.assertEqual(result.fetched_with, 'playwright')

    def test_http_only_site_gets_explicit_reason(self):
        cert = URLError('[SSL: CERTIFICATE_VERIFY_FAILED] self-signed certificate')
        with patch.object(leadlib, 'static_fetch', side_effect=cert), \
                patch.object(leadlib, 'playwright_fetch', side_effect=RuntimeError('Playwright fetch failed: net::ERR_CERT_AUTHORITY_INVALID')):
            with self.assertRaises(leadlib.HttpOnlyProxyError) as raised:
                leadlib.fetch_page('http://www.asado-steakhaus.de/')
        message = str(raised.exception)
        self.assertIn(leadlib.HTTP_ONLY_PROXY_REASON, message)
        self.assertIn('https://www.asado-steakhaus.de/', message)
        self.assertNotIn('ERR_NAME_NOT_RESOLVED', message)

    def test_access_denial_on_https_is_not_relabelled(self):
        denied = HTTPError('https://www.mago-wurst.de/', 403, 'Forbidden', {}, None)
        with patch.object(leadlib, 'static_fetch', side_effect=denied), \
                patch.object(leadlib, 'playwright_fetch') as browser:
            with self.assertRaises(HTTPError):
                leadlib.fetch_page('http://www.mago-wurst.de/')
        browser.assert_not_called()

    def test_reachable_https_errors_are_not_relabelled(self):
        cases = (
            (ValueError('Unsupported content type: application/pdf'), RuntimeError('Playwright fetch failed: Download is starting')),
            (HTTPError('https://www.mago-wurst.de/x', 500, 'Server Error', {}, None), RuntimeError('Playwright fetch failed: Timeout 20000ms exceeded')),
        )
        for static_error, browser_error in cases:
            with self.subTest(static=static_error), \
                    patch.object(leadlib, 'static_fetch', side_effect=static_error), \
                    patch.object(leadlib, 'playwright_fetch', side_effect=browser_error):
                with self.assertRaises(RuntimeError) as raised:
                    leadlib.fetch_page('http://www.mago-wurst.de/x')
                self.assertNotIsInstance(raised.exception, leadlib.HttpOnlyProxyError)
        with patch.object(leadlib, 'static_fetch', side_effect=ValueError('Unsupported content type: application/pdf')):
            with self.assertRaises(ValueError):
                leadlib.fetch_page('http://www.mendoza-berlin.de/flyer.pdf', browser_fallback=False)

    def test_robots_is_read_from_https_form(self):
        requested = []

        class Opener:
            def open(self, request, timeout):
                requested.append(request.full_url)
                raise URLError('offline')

        with patch.object(leadlib, 'validate_public_url', side_effect=lambda u, **_kw: u), \
                patch.object(leadlib, 'build_opener', return_value=Opener()):
            self.assertTrue(leadlib.robots_allows('http://www.neuland-kluge.de/kontakt'))
        self.assertEqual(requested, ['https://www.neuland-kluge.de/robots.txt'])


class HttpsUpgradeCrawlTests(unittest.TestCase):
    def crawl(self, start, static, browser):
        a, b = environment()
        with a, b, patch.object(leadlib, 'robots_allows', return_value=True), \
                patch.object(leadlib, 'static_fetch', side_effect=static), \
                patch.object(leadlib, 'playwright_fetch', side_effect=browser):
            return leadlib.crawl_company({'url': start}, delay_seconds=0)

    def test_http_candidate_and_followed_http_links_are_crawled_over_https(self):
        home = PAGE.replace('</body>', '<a href="http://www.neuland-kluge.de/kontakt">Kontakt</a></body>')
        pages = {'https://www.neuland-kluge.de/': home, 'https://www.neuland-kluge.de/kontakt': PAGE}

        def static(url, **_kw):
            if url not in pages:
                raise URLError('[Errno -2] Name or service not known')
            return leadlib.FetchResult(pages[url], url, 'static', 200)

        crawl = self.crawl('http://www.neuland-kluge.de/', static, RuntimeError('unused'))
        self.assertEqual(crawl['site_status'], 'active')
        self.assertEqual(crawl['final_url'], 'https://www.neuland-kluge.de/')
        self.assertEqual([p['url'] for p in crawl['pages']], list(pages))
        self.assertEqual(crawl['errors'], [])

    def test_http_only_candidate_stays_blocked_with_explicit_reason(self):
        crawl = self.crawl(
            'http://www.asado-steakhaus.de/',
            URLError('[SSL: CERTIFICATE_VERIFY_FAILED] self-signed certificate'),
            RuntimeError('Playwright fetch failed: net::ERR_CERT_AUTHORITY_INVALID'),
        )
        self.assertEqual(crawl['site_status'], 'blocked')
        self.assertEqual(crawl['pages'], [])
        [error] = crawl['errors']
        self.assertEqual(error['category'], 'http_only_proxy')
        self.assertIn(leadlib.HTTP_ONLY_PROXY_REASON, error['reason'])

    def test_unchanged_when_local_dns_works(self):
        calls = []

        def static(url, **_kw):
            calls.append(url)
            return leadlib.FetchResult(PAGE, url, 'static', 200)

        a, b = environment(dns=True)
        with a, b, patch.object(leadlib, 'static_fetch', side_effect=static):
            result, _ = leadlib.fetch_page('http://www.mendoza-berlin.de/')
        self.assertEqual(calls, ['http://www.mendoza-berlin.de/'])
        self.assertEqual(result.final_url, 'http://www.mendoza-berlin.de/')


if __name__ == '__main__':
    unittest.main()
