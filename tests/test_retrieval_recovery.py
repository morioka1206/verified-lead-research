"""Regressions for observed website recovery failures; no live-site dependencies."""
from email.message import Message
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/verifying-sales-leads/scripts'))
import leadlib
import manage_batches
import prepare_candidates


class RetrievalRecoveryTests(unittest.TestCase):
    def crawl(self, pages, start='https://example.com/', **options):
        # Replace external network I/O only; real parsing, prioritization and gates run.
        def fetch(url, **kwargs):
            body, status = pages[url]
            return leadlib.FetchResult(body, url, 'static', status), leadlib.parse_site(body, url)
        with patch.object(leadlib, 'robots_allows', return_value=True), patch.object(leadlib, 'fetch_page', side_effect=fetch):
            return leadlib.crawl_company({'url': start}, delay_seconds=0, **options)

    def test_nested_company_details_are_not_crowded_out_by_contact(self):
        nav = '<a href="/outline">会社案内</a><a href="/products">製品</a><a href="/distribution">卸</a><a href="/contact">Contact</a>'
        pages = {
            'https://example.com/': (nav, 200),
            'https://example.com/outline': (nav+'<a href="/profile">企業概要と所在地</a>', 200),
            'https://example.com/profile': ('山梨県甲府市に本社。電気工事を施工する。', 200),
            'https://example.com/products': ('Products', 200),
            'https://example.com/distribution': ('Distribution', 200),
            'https://example.com/contact': ('Contact', 200),
        }
        c = self.crawl(pages)
        self.assertIn('https://example.com/profile', [p['url'] for p in c['pages']])
        self.assertLessEqual(len(c['pages']), 5)

    def test_company_history_does_not_crowd_out_business_page(self):
        nav='<a href="/company/">会社案内</a><a href="/business/">事業内容</a>'
        c=self.crawl({
            'https://example.com/':(nav,200),
            'https://example.com/company/':(nav+'<a href="/company/info">企業概要</a>',200),
            'https://example.com/company/info':('<p>山梨県の本社</p><a href="/company/history">沿革</a>',200),
            'https://example.com/company/history':('<a href="/company/philosophy">理念</a>',200),
            'https://example.com/company/philosophy':('理念',200),
            'https://example.com/business/':('設備工事を施工します',200),
        })
        self.assertIn('https://example.com/business/',[p['url']for p in c['pages']])

    def test_browser_launch_rejects_disabled_or_unbounded_timeout(self):
        class BrowserType:
            def launch(self,**kwargs):return object()
        class Playwright:
            chromium=BrowserType()
        for timeout in (0,0.0001,-1,float('inf'),float('nan'),3600):
            with self.subTest(timeout=timeout),self.assertRaises(leadlib.BrowserEnvironmentError):
                leadlib.launch_browser(Playwright(),timeout=timeout)

    def test_frame_and_image_alt_supply_observed_links(self):
        c = self.crawl({
            'https://example.com/': ('<frameset><frame src="/main.htm"></frameset>', 200),
            'https://example.com/main.htm': ('<a href="/details.htm"><img alt="会社概要" src="/button.gif"></a>', 200),
            'https://example.com/details.htm': ('会社名は例示工業。山梨県内で施工。', 200),
        })
        self.assertIn('https://example.com/details.htm', [p['url'] for p in c['pages']])

    def test_attempt_budget_includes_failed_pages(self):
        nav = ''.join(f'<a href="/{part}">{part}</a>' for part in ('about','products','distribution','locations','contact'))
        def fetch(url, **kwargs):
            if url == 'https://example.com/':
                return leadlib.FetchResult(nav, url, 'static', 200), leadlib.parse_site(nav, url)
            raise RuntimeError('unavailable')
        with patch.object(leadlib, 'robots_allows', return_value=True), patch.object(leadlib, 'fetch_page', side_effect=fetch) as requests:
            leadlib.crawl_company({'url':'https://example.com/'}, max_pages=5, delay_seconds=0, priority_groups=('about','products','distribution','locations','contact'))
        self.assertLessEqual(requests.call_count, 5)

    def test_http_to_https_redirect_does_not_consume_two_page_slots(self):
        def fetch(url, **kwargs):
            final=url.replace('http:', 'https:')
            number=int(final.rsplit('/',1)[-1]) if final.rsplit('/',1)[-1].isdigit() else 0
            body=f'<a href="/about/{number+1}">会社概要</a>'
            return leadlib.FetchResult(body,final,'static',200),leadlib.parse_site(body,final)
        with patch.object(leadlib,'robots_allows',return_value=True),patch.object(leadlib,'fetch_page',side_effect=fetch):
            c=leadlib.crawl_company({'url':'http://example.com/'},max_pages=5,delay_seconds=0)
        self.assertEqual(len(c['pages']),5)

    def test_browser_failure_is_marked_as_environment_problem(self):
        with patch.object(leadlib, 'robots_allows', return_value=True), patch.object(leadlib, 'fetch_page', side_effect=leadlib.BrowserEnvironmentError('could not launch')):
            c = leadlib.crawl_company({'url':'https://example.com/'}, delay_seconds=0)
        self.assertEqual(c['site_status'], 'blocked')
        self.assertEqual(c['errors'][0]['category'], 'browser_environment')

    def test_explicit_http_error_page_is_not_valid_evidence(self):
        page = {'url':'https://example.com/', 'text':'We do construction in Yamanashi.', 'status_code':500}
        claim = {'type':'product','evidence_url':page['url'],'evidence_text_original':page['text']}
        self.assertFalse(leadlib.evidence_exists(claim, [page]))

    def test_http_url_uses_https_behind_https_only_proxy(self):
        https_only = {'https': 'http://127.0.0.1:3128'}
        with patch.object(leadlib, 'getproxies', return_value=https_only), patch.object(leadlib, 'proxy_bypass', return_value=False):
            self.assertEqual(leadlib.proxy_reachable_url('http://shop.example/menu?a=1'), 'https://shop.example/menu?a=1')
            self.assertEqual(leadlib.proxy_reachable_url('http://shop.example:80/'), 'https://shop.example/')
            self.assertEqual(leadlib.proxy_reachable_url('https://shop.example/'), 'https://shop.example/')
        with patch.object(leadlib, 'getproxies', return_value=https_only), patch.object(leadlib, 'proxy_bypass', return_value=True):
            self.assertEqual(leadlib.proxy_reachable_url('http://127.0.0.1:8000/'), 'http://127.0.0.1:8000/')
        for proxies in ({}, {'https': 'http://p:1', 'http': 'http://p:1'}):
            with patch.object(leadlib, 'getproxies', return_value=proxies):
                self.assertEqual(leadlib.proxy_reachable_url('http://shop.example/'), 'http://shop.example/')

        calls = []
        def fake_fetch(url, **_kw):
            calls.append(url)
            return leadlib.FetchResult('<p>ok</p>', url, 'static', 200), {'text': 'ok'}
        with patch.object(leadlib, 'getproxies', return_value=https_only), patch.object(leadlib, 'proxy_bypass', return_value=False), patch.object(leadlib, '_fetch_page', side_effect=fake_fetch):
            result, _ = leadlib.fetch_page('http://shop.example/')
        self.assertEqual(calls, ['https://shop.example/'])
        self.assertEqual(result.final_url, 'https://shop.example/')

    def test_http_only_site_gets_explicit_reason(self):
        def broken(url, **_kw):
            raise OSError('certificate verify failed: self-signed certificate')
        with patch.object(leadlib, 'getproxies', return_value={'https': 'http://127.0.0.1:3128'}), patch.object(leadlib, 'proxy_bypass', return_value=False), patch.object(leadlib, '_fetch_page', side_effect=broken):
            with self.assertRaises(leadlib.HttpOnlySiteError) as ctx:
                leadlib.fetch_page('http://shop.example/')
        self.assertIn('HTTPS-only proxy', str(ctx.exception))
        def denied(url, **_kw):
            raise leadlib.HTTPError(url, 403, 'Forbidden', {}, None)
        with patch.object(leadlib, 'getproxies', return_value={'https': 'http://127.0.0.1:3128'}), patch.object(leadlib, 'proxy_bypass', return_value=False), patch.object(leadlib, '_fetch_page', side_effect=denied):
            with self.assertRaises(leadlib.HTTPError):
                leadlib.fetch_page('http://shop.example/')

    def test_http_error_crawl_is_not_active(self):
        c = self.crawl({'https://example.com/': ('Service unavailable', 500)})
        self.assertEqual(c['site_status'], 'blocked')

    def test_shift_jis_meta_is_used_without_http_charset(self):
        body = '<meta charset="shift_jis"><p>山梨県甲府市の設備工事会社</p>'.encode('cp932')
        headers = Message(); headers['Content-Type']='text/html'
        class Response(BytesIO):
            def geturl(self): return 'https://example.com/'
            def getcode(self): return 200
        response=Response(body); response.headers=headers
        class Opener:
            def open(self, *args, **kwargs): return response
        with patch.object(leadlib, 'validate_public_url', side_effect=lambda u,**kw:u), patch.object(leadlib, 'build_opener', return_value=Opener()):
            result=leadlib.static_fetch('https://example.com/')
        self.assertIn('山梨県甲府市', result.html)

    def test_preparation_keeps_shared_host_tenants_separate(self):
        result=prepare_candidates.prepare([
            'https://www2.nns.ne.jp/~alpha/index.html',
            'https://www2.nns.ne.jp/~beta/company.htm',
            'https://www2.nns.ne.jp/~alpha/company.htm',
        ], 100)
        self.assertEqual(len(result), 2)

    def test_shared_host_neighbour_is_not_same_company(self):
        self.assertFalse(leadlib.same_site('https://www2.nns.ne.jp/~alpha/', 'https://www2.nns.ne.jp/~beta/'))
        self.assertTrue(leadlib.same_site('https://www2.nns.ne.jp/~alpha/company.htm', 'https://www2.nns.ne.jp/~alpha/'))
        self.assertFalse(leadlib.same_site('https://r.goope.jp/alpha/', 'https://r.goope.jp/alpha-two/'))

    def test_shared_site_canonical_url_preserves_tenant(self):
        url='https://www2.nns.ne.jp/~alpha/index.html'
        c=self.crawl({url: ('Alpha company', 200)}, start=url)
        self.assertEqual(c['canonical_url'], 'https://www2.nns.ne.jp/~alpha/')

    def test_shared_host_redirect_does_not_collect_neighbour_evidence(self):
        start='https://www2.nns.ne.jp/~alpha/'
        final='https://www2.nns.ne.jp/~beta/'
        parsed=leadlib.parse_site('<p>Beta 山梨県の施工会社</p><a href="mailto:beta@example.com">メール</a>', final)
        with patch.object(leadlib, 'robots_allows', return_value=True), patch.object(leadlib, 'fetch_page', return_value=(leadlib.FetchResult('',final,'static',200),parsed)):
            c=leadlib.crawl_company({'url':start},delay_seconds=0)
        self.assertEqual(c['site_status'],'blocked')
        self.assertEqual(c['emails'],[])
        self.assertEqual(c['pages'],[])

    def test_shared_neighbour_contact_is_not_an_external_official_form(self):
        start='https://www2.nns.ne.jp/~alpha/'
        c=self.crawl({start:('<a href="/~beta/contact">Contact</a><p>Alpha company</p>',200)},start=start)
        self.assertEqual(c['contact_forms'],[])

    def test_shared_neighbour_quotes_cannot_satisfy_acceptance(self):
        start='https://r.goope.jp/alpha/'
        other='https://r.goope.jp/beta/'
        text='Manufacturing. Supplier. Yamanashi.'
        crawl={'candidate':{'url':start},'canonical_url':start,'site_status':'active','pages':[{'url':other,'text':text,'status_code':200}]}
        assessment={'recommendation':'accepted','claims':[{'type':kind,'evidence_url':other,'evidence_text_original':text}for kind in ('product','buyer_role','target_market')]}
        self.assertNotEqual(leadlib.finalize_record(crawl,assessment)['verification_status'],'accepted')

    def test_custom_domain_redirect_into_shared_host_keeps_effective_scope(self):
        start='https://alpha.example/'
        alpha='https://r.goope.jp/alpha/'
        beta='https://r.goope.jp/beta/'
        def fetch(url,**kwargs):
            final,body=(alpha,'<a href="/alpha/about">About</a>')if url==start else(beta,'Beta construction in Yamanashi. beta@example.com')
            return leadlib.FetchResult(body,final,'static',200),leadlib.parse_site(body,final)
        with patch.object(leadlib,'robots_allows',return_value=True),patch.object(leadlib,'fetch_page',side_effect=fetch):
            c=leadlib.crawl_company({'url':start},delay_seconds=0)
        self.assertEqual([p['url']for p in c['pages']],[alpha])
        self.assertEqual(c['emails'],[])
        # Also guard legacy crawls that have the effective canonical URL but no scope field.
        legacy={'candidate':{'url':start},'canonical_url':alpha,'site_status':'active','pages':[{'url':beta,'text':'Beta work','status_code':200}]}
        a={'recommendation':'accepted','claims':[{'type':k,'evidence_url':beta,'evidence_text_original':'Beta work'}for k in ('product','buyer_role','target_market')]}
        self.assertNotEqual(leadlib.finalize_record(legacy,a)['verification_status'],'accepted')

    def test_multiple_observed_frames_do_not_drop_main_content(self):
        c=self.crawl({
            'https://example.com/':('<frameset><frame src="/banner.html"><frame src="/main.html"></frameset>',200),
            'https://example.com/banner.html':('Banner',200),
            'https://example.com/main.html':('山梨の施工会社の本文',200),
        })
        self.assertIn('https://example.com/main.html',[p['url']for p in c['pages']])

    def test_driver_start_failure_is_an_environment_failure(self):
        class Driver:
            def __enter__(self):raise OSError('Playwright Node driver cannot start')
            def __exit__(self,*args):pass
        with patch.object(leadlib,'validate_public_url',side_effect=lambda u,**kw:u),patch('playwright.sync_api.sync_playwright',return_value=Driver()):
            with self.assertRaises(leadlib.BrowserEnvironmentError):
                leadlib.playwright_fetch('https://example.com/')

    def test_unrecovered_corrupt_text_cannot_be_evidence(self):
        url='https://example.com/'
        text='\ufffd'*300
        c=self.crawl({url:(text,200)})
        a={'recommendation':'accepted','claims':[{'type':k,'evidence_url':url,'evidence_text_original':text[:30]}for k in ('product','buyer_role','target_market')]}
        self.assertNotEqual(leadlib.finalize_record(c,a)['verification_status'],'accepted')
        self.assertEqual(c['pages'][0]['content_quality'],'unresolved')

    def test_browser_returning_corrupt_text_remains_unresolved(self):
        url='https://example.com/'
        bad=leadlib.FetchResult('\ufffd'*300,url,'static',200)
        with patch.object(leadlib,'static_fetch',return_value=bad),patch.object(leadlib,'playwright_fetch',return_value=bad):
            result,parsed=leadlib.fetch_page(url)
        self.assertEqual(parsed['content_quality'],'unresolved')
        claim={'evidence_url':url,'evidence_text_original':'\ufffd'*30}
        self.assertFalse(leadlib.evidence_exists(claim,[{'url':url,'text':parsed['text'],'status_code':200}]))

    def test_missing_browser_package_is_an_environment_failure(self):
        with patch.object(leadlib,'validate_public_url',side_effect=lambda url,**kw:url), patch.dict(sys.modules,{'playwright.sync_api':None}):
            with self.assertRaises(leadlib.BrowserEnvironmentError):
                leadlib.playwright_fetch('https://example.com/')

    def test_encoded_parent_path_cannot_cross_shared_tenant(self):
        self.assertFalse(leadlib.same_site('https://www2.nns.ne.jp/~alpha/%2e%2e/~beta/', 'https://www2.nns.ne.jp/~alpha/'))

    def test_browser_diagnostic_reports_environment_failure_without_site_claim(self):
        with patch.object(leadlib, 'launch_browser', create=True, side_effect=RuntimeError('launch failed')):
            result=leadlib.browser_diagnostic(timeout=2)
        self.assertEqual(result['status'],'environment_error')
        self.assertNotIn('site_status',result)

    def test_legacy_database_keys_do_not_allow_duplicate_tenant(self):
        with TemporaryDirectory() as directory:
            root=Path(directory)
            db=sqlite3.connect(root/'research.sqlite3')
            db.execute('CREATE TABLE candidates (domain TEXT PRIMARY KEY,url TEXT,payload_json TEXT,status TEXT,added_at TEXT)')
            old='https://www2.nns.ne.jp/~alpha/'
            db.execute('INSERT INTO candidates VALUES (?,?,?,?,?)',('www2.nns.ne.jp',old,json.dumps({'url':old}),'queued','old'))
            db.commit();db.close()
            inp=root/'candidates.json'
            inp.write_text(json.dumps([old+'about.htm','https://www2.nns.ne.jp/~beta/']))
            r=manage_batches.add_candidates(root, inp)
            self.assertEqual((r['added'],r['duplicates_skipped']), (1,1))
            db=sqlite3.connect(root/'research.sqlite3')
            self.assertEqual(db.execute('SELECT url FROM candidates WHERE domain=?',('www2.nns.ne.jp',)).fetchone()[0], old)
            db.close()


if __name__=='__main__': unittest.main()
