import argparse
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "verifying-sales-leads" / "scripts"))

import search_web  # noqa: E402


class Response:
    def __init__(self, payload):
        self.body = json.dumps(payload).encode("utf-8")

    def read(self, _limit):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class SearchWebTests(unittest.TestCase):
    def test_request_carries_country_language_and_key(self):
        seen = {}

        class Opener:
            def open(self, request, timeout):
                seen["url"] = request.full_url
                seen["key"] = request.get_header("X-subscription-token")
                return Response({"web": {"results": [
                    {"url": "https://metzgerei.example.de/", "title": "Metzgerei", "description": "Dry Aged"},
                    {"url": "https://www.gelbeseiten.de/x", "title": "Liste"},
                    {"url": "mailto:x@example.de"},
                ]}})

        results = search_web.brave_search("Metzgerei München", country="DE", lang="de", count=20, offset=0,
                                          key="k123", timeout=5, opener_factory=Opener)
        self.assertIn("country=DE", seen["url"])
        self.assertIn("search_lang=de", seen["url"])
        self.assertEqual(seen["key"], "k123")
        self.assertEqual([r["url"] for r in results], ["https://metzgerei.example.de/", "https://www.gelbeseiten.de/x"])
        self.assertEqual([r["directory_like"] for r in results], [False, True])
        self.assertEqual(results[0]["rank"], 1)

    def test_key_comes_from_env_or_proxy_placeholder(self):
        with patch.dict(search_web.os.environ, {"BRAVE_SEARCH_API_KEY": "abc"}):
            self.assertEqual(search_web.api_key(), "abc")
        with patch.dict(search_web.os.environ, {}, clear=True):
            with patch.object(search_web, "https_only_proxy", return_value=True):
                self.assertEqual(search_web.api_key(), search_web.PROXY_PLACEHOLDER)
            with patch.object(search_web, "https_only_proxy", return_value=False):
                with self.assertRaises(SystemExit):
                    search_web.api_key()

    def test_run_stops_on_rejected_key_and_records_errors(self):
        calls = []

        def fake(query, **_kw):
            calls.append(query)
            if query == "bad":
                raise HTTPError("u", 401, "Unauthorized", {}, None)
            return [{"rank": 1, "url": "https://a.example.de/", "title": "", "description": "", "directory_like": False}]

        with TemporaryDirectory() as tmp:
            queries = Path(tmp) / "q.txt"
            queries.write_text("ok\nbad\nnever\n", encoding="utf-8")
            args = argparse.Namespace(query=None, queries_file=queries, country="DE", lang="de", count=20,
                                      pages=1, pause=0, timeout=5)
            with patch.object(search_web, "api_key", return_value="k"):
                out = search_web.run(args, search=fake)
        self.assertEqual(calls, ["ok", "bad"])
        self.assertIn("API key rejected", out["stopped"])
        self.assertEqual(out["queries"][1]["error"], "HTTP 401")


if __name__ == "__main__":
    unittest.main()
