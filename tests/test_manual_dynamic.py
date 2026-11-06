"""Exercise the published manual's nested navigation in a real browser."""
import os
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ManualNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise unittest.SkipTest('Playwright is not installed')
        os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(ROOT / '.playwright-browsers'))
        cls.runtime = sync_playwright().start()
        try:
            cls.browser = cls.runtime.chromium.launch()
        except Exception:
            cls.runtime.stop()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.runtime.stop()

    def setUp(self):
        self.context = self.browser.new_context()
        self.page = self.context.new_page()
        self.page.set_default_timeout(3000)

    def tearDown(self):
        self.context.close()

    def open_manual(self, fragment='install'):
        self.page.goto((ROOT / 'GUIDE.html').as_uri() + '#' + fragment)

    def test_app_and_os_choices_are_independent(self):
        self.open_manual()
        self.assertTrue(self.page.locator('#install-claude').is_visible())
        self.assertFalse(self.page.locator('#install-codex').is_visible())
        self.page.locator('#win-tab').click()
        self.page.locator('#codex-tab').click()
        self.assertFalse(self.page.locator('#install-claude').is_visible())
        self.assertTrue(self.page.locator('#codex-mac-panel').is_visible())
        self.page.locator('#codex-win-tab').click()
        self.page.locator('#claude-tab').click()
        self.assertTrue(self.page.locator('#win-panel').is_visible())
        self.assertFalse(self.page.locator('#mac-panel').is_visible())
        self.page.locator('#claude-tab').press('ArrowRight')
        self.assertTrue(self.page.locator('#codex-win-panel').is_visible())
        self.assertEqual(self.page.locator('#codex-tab').get_attribute('aria-selected'), 'true')

    def test_direct_links_reveal_hidden_app_and_os_panels(self):
        self.open_manual('codex-win-panel')
        self.assertTrue(self.page.locator('#codex-win-panel').is_visible())
        self.assertFalse(self.page.locator('#install-claude').is_visible())
        self.page.locator('.header-links a[href="#install-claude"]').click()
        self.page.locator('#install-claude').wait_for(state='visible')
        self.page.locator('.header-links a[href="#install-codex"]').click()
        self.page.locator('#codex-win-panel').wait_for(state='visible')
        self.assertTrue(self.page.locator('#codex-win-panel').is_visible())
        self.page.reload()
        self.assertTrue(self.page.locator('#install-codex').is_visible())

    def test_phone_width_can_switch_apps_and_os_without_page_overflow(self):
        self.page.set_viewport_size({'width': 390, 'height': 844})
        self.open_manual()
        self.page.locator('#codex-tab').click()
        self.page.locator('#codex-win-tab').click()
        self.assertTrue(self.page.locator('#codex-win-panel').is_visible())
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), 390)

    def test_all_instructions_remain_readable_without_js_and_in_print(self):
        no_js = self.browser.new_context(java_script_enabled=False)
        try:
            page = no_js.new_page()
            page.goto((ROOT / 'GUIDE.html').as_uri())
            for panel in ('install-claude', 'install-codex', 'mac-panel', 'win-panel',
                          'codex-mac-panel', 'codex-win-panel'):
                self.assertTrue(page.locator('#' + panel).is_visible(), panel)
        finally:
            no_js.close()
        self.open_manual()
        self.page.emulate_media(media='print')
        for panel in ('install-claude', 'install-codex', 'mac-panel', 'win-panel',
                      'codex-mac-panel', 'codex-win-panel'):
            self.assertTrue(self.page.locator('#' + panel).is_visible(), panel)
        self.assertTrue(self.page.locator('#codex-win-panel .platform-title').is_visible())


if __name__ == '__main__':
    unittest.main()
