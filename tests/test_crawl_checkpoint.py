import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "verifying-sales-leads" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import crawl_candidates  # noqa: E402


class CrawlCheckpointTests(unittest.TestCase):
    def test_cafe_campaign_uses_hospitality_page_priorities(self):
        campaign = {
            "objective": "find_hospitality_buyers",
            "buyer_types": [{"name": "カフェ", "keywords": ["cafe"]}],
        }
        self.assertEqual(
            crawl_candidates.page_priorities(campaign),
            crawl_candidates.HOSPITALITY_LINK_GROUP_ORDER,
        )

    def fixture(self, work):
        campaign = {
            "id": "checkpoint-test",
            "product": {"name": "抹茶", "keywords": ["matcha"]},
            "market": {"name": "アメリカ", "keywords": ["United States"]},
            "buyer_types": [{"name": "カフェ", "keywords": ["cafe"]}],
            "target_accepted": 1,
            "max_candidates": 2,
            "max_pages_per_company": 5,
        }
        candidates = [
            {"url": "https://example1.com/"},
            {"url": "https://example2.com/"},
        ]
        campaign_path = work / "campaign.json"
        candidates_path = work / "candidates.json"
        output_path = work / "crawls.json"
        campaign_path.write_text(json.dumps(campaign), encoding="utf-8")
        candidates_path.write_text(json.dumps(candidates), encoding="utf-8")
        arguments = [
            "crawl_candidates.py",
            "--campaign",
            str(campaign_path),
            "--candidates",
            str(candidates_path),
            "--output",
            str(output_path),
        ]
        return candidates, output_path, arguments

    def test_completed_company_survives_interruption(self):
        with TemporaryDirectory() as directory:
            work = Path(directory)
            candidates, output_path, arguments = self.fixture(work)
            first_result = {
                "candidate": candidates[0],
                "canonical_url": candidates[0]["url"],
                "site_status": "active",
                "pages": [],
            }
            with patch.object(sys, "argv", arguments), patch.object(
                crawl_candidates,
                "crawl_company",
                side_effect=[first_result, KeyboardInterrupt()],
            ):
                with self.assertRaises(KeyboardInterrupt):
                    crawl_candidates.main()

            saved = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(saved, [first_result])

    def test_rerun_resumes_after_completed_company(self):
        with TemporaryDirectory() as directory:
            work = Path(directory)
            candidates, output_path, arguments = self.fixture(work)
            first_result = {
                "candidate": candidates[0],
                "canonical_url": candidates[0]["url"],
                "site_status": "active",
                "pages": [],
            }
            second_result = {
                "candidate": candidates[1],
                "canonical_url": candidates[1]["url"],
                "site_status": "active",
                "pages": [],
            }
            output_path.write_text(json.dumps([first_result]), encoding="utf-8")
            with patch.object(sys, "argv", arguments), patch.object(
                crawl_candidates, "crawl_company", return_value=second_result
            ) as crawler:
                self.assertEqual(crawl_candidates.main(), 0)

            crawler.assert_called_once()
            saved = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(saved, [first_result, second_result])


if __name__ == "__main__":
    unittest.main()
