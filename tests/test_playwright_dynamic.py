import os
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skill" / "verifying-sales-leads" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import leadlib  # noqa: E402


class PlaywrightTests(unittest.TestCase):
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
                    browser = playwright.chromium.launch(headless=True)
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
