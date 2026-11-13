import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "verifying-sales-leads" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import leadlib  # noqa: E402


class PlaywrightTests(unittest.TestCase):
    def test_structured_address_shell_renders_actual_business_content(self):
        addresses = [{'@type': 'PostalAddress', 'streetAddress': f'{n} Main Street',
                      'addressLocality': 'Cambridge', 'addressRegion': 'MA',
                      'postalCode': '02139', 'addressCountry': 'US'} for n in range(5)]
        body = ('<html><body><div id="app"></div><script id="locations-json" type="application/ld+json">'
                + json.dumps(addresses) + '</script><script>'
                'document.getElementById("app").textContent = "We manufacture matcha cookies for wholesale customers.";'
                'document.getElementById("locations-json").remove();'
                '</script></body></html>')
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(body.encode())
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            result, parsed = leadlib.fetch_page(f'http://127.0.0.1:{server.server_port}/', allow_private=True)
            self.assertEqual(result.fetched_with, 'playwright')
            self.assertIn('We manufacture matcha cookies for wholesale customers.', parsed['text'])
            self.assertIn('[structured data address]', parsed['text'])
            self.assertNotIn('locations-json" type=', result.html)
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=3)

    def test_browser_does_not_load_automatic_child_frames_outside_crawl_budget(self):
        try:
            import playwright.sync_api
        except ImportError:
            self.skipTest('Playwright is not installed')
        requested=[]
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requested.append(self.path)
                body=('User-agent: *\nDisallow: /denied/\n'if self.path=='/robots.txt'else ''.join(f'<iframe src="/denied/{i}"></iframe>'for i in range(6))if self.path=='/'else'Denied frame')
                self.send_response(200)
                self.send_header('Content-Type','text/plain'if self.path=='/robots.txt'else'text/html')
                self.end_headers();self.wfile.write(body.encode())
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        try:
            c=leadlib.crawl_company({'url':f'http://127.0.0.1:{server.server_port}/'},max_pages=1,allow_private=True,delay_seconds=0)
            self.assertEqual(c['site_status'],'active')
            self.assertEqual([p for p in requested if p.startswith('/denied/')],[])
            self.assertEqual(len(c['pages']),1)
        finally:
            server.shutdown();server.server_close();worker.join(timeout=3)

    def test_javascript_content_is_rendered(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest("Playwright is not installed")
        os.environ.setdefault(
            "PLAYWRIGHT_BROWSERS_PATH", str(ROOT / ".playwright-browsers")
        )
        html = """<html><body><div id='app'></div><script>
        document.getElementById('app').textContent =
          'Rendered matcha distributor content';
        </script></body></html>"""
        with tempfile.TemporaryDirectory() as directory:
            page_path = Path(directory) / "dynamic.html"
            page_path.write_text(html, encoding="utf-8")
            try:
                with sync_playwright() as playwright:
                    browser = leadlib.launch_browser(playwright)
                    page = browser.new_page()
                    page.goto(page_path.as_uri(), wait_until="domcontentloaded")
                    rendered = page.content()
                    browser.close()
            except Exception as exc:
                if "MachPortRendezvousServer" in str(exc) and "Permission denied" in str(exc):
                    self.skipTest("The Codex macOS sandbox does not permit Chromium launch")
                raise
            parsed = leadlib.parse_site(rendered, page_path.as_uri())
            self.assertIn("Rendered matcha distributor content", parsed["text"])


if __name__ == "__main__":
    unittest.main()
