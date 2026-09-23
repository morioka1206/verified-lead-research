import csv
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skill" / "verifying-sales-leads" / "scripts"


class CliIntegrationTests(unittest.TestCase):
    def test_prepare_finalize_and_evaluate_flow(self):
        with TemporaryDirectory() as directory:
            work = Path(directory)
            campaign = {
                "id": "fixture",
                "product": {"name": "抹茶", "keywords": ["matcha"]},
                "market": {"name": "アメリカ", "keywords": ["United States"]},
                "objective": "find_importers",
                "buyer_types": [{"name": "輸入業者", "keywords": ["importer"]}],
                "excluded_types": [],
                "target_accepted": 1,
                "max_candidates": 2,
                "max_pages_per_company": 5,
            }
            candidates = [
                {"url": "https://example.com/", "discovery_query": "matcha importer", "discovery_source_url": "https://search.example/"},
                {"url": "https://www.example.com/about", "discovery_query": "duplicate"},
            ]
            page_url = "https://example.com/about"
            page_text = "We import Japanese matcha. We are a wholesale distributor. Based in the United States."
            crawl = [
                {
                    "candidate": candidates[0],
                    "canonical_url": "https://example.com/",
                    "final_url": page_url,
                    "site_status": "active",
                    "pages": [{"url": page_url, "text": page_text}],
                    "emails": [{"email": "sales@example.com", "source_url": page_url}],
                    "contact_forms": [],
                    "errors": [],
                    "checked_at": "2026-09-23T00:00:00+00:00",
                }
            ]
            assessment = [
                {
                    "candidate_url": "https://example.com/",
                    "company_name": "Example Imports",
                    "country": "アメリカ",
                    "company_type": "輸入業者・卸売業者",
                    "company_overview_ja": "日本茶を輸入する卸売会社。",
                    "recommendation": "accepted",
                    "claims": [
                        {
                            "type": "product",
                            "evidence_url": page_url,
                            "evidence_text_original": "We import Japanese matcha.",
                            "evidence_text_ja": "日本産抹茶を輸入している。",
                        },
                        {
                            "type": "buyer_role",
                            "evidence_url": page_url,
                            "evidence_text_original": "We are a wholesale distributor.",
                            "evidence_text_ja": "卸売流通業者である。",
                        },
                        {
                            "type": "target_market",
                            "evidence_url": page_url,
                            "evidence_text_original": "Based in the United States.",
                            "evidence_text_ja": "アメリカを拠点としている。",
                        },
                    ],
                    "uncertainties": [],
                    "rejection_reason": None,
                }
            ]

            paths = {
                "campaign": work / "campaign.json",
                "candidates": work / "candidates.json",
                "prepared": work / "prepared.json",
                "crawls": work / "crawls.json",
                "assessments": work / "assessments.json",
                "output": work / "output",
            }
            paths["campaign"].write_text(json.dumps(campaign), encoding="utf-8")
            paths["candidates"].write_text(json.dumps(candidates), encoding="utf-8")
            paths["crawls"].write_text(json.dumps(crawl), encoding="utf-8")
            paths["assessments"].write_text(json.dumps(assessment), encoding="utf-8")

            subprocess.run(
                [sys.executable, str(SCRIPTS / "prepare_candidates.py"), "--input", str(paths["candidates"]), "--output", str(paths["prepared"])],
                check=True,
                capture_output=True,
                text=True,
            )
            prepared = json.loads(paths["prepared"].read_text(encoding="utf-8"))
            self.assertEqual(len(prepared), 1)

            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "finalize_run.py"),
                    "--campaign",
                    str(paths["campaign"]),
                    "--crawls",
                    str(paths["crawls"]),
                    "--assessments",
                    str(paths["assessments"]),
                    "--output-dir",
                    str(paths["output"]),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            audit = json.loads((paths["output"] / "audit.json").read_text(encoding="utf-8"))
            self.assertEqual(audit[0]["verification_status"], "accepted")
            with (paths["output"] / "leads.csv").open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["会社名"], "Example Imports")


if __name__ == "__main__":
    unittest.main()
