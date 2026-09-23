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

    def test_finalize_combines_repeated_batch_files(self):
        with TemporaryDirectory() as directory:
            work = Path(directory)
            campaign = {
                "id": "batches",
                "product": {"name": "抹茶", "keywords": ["matcha"]},
                "market": {"name": "アメリカ", "keywords": ["United States"]},
                "objective": "find_wholesalers",
                "buyer_types": [{"name": "卸売業者", "keywords": ["wholesale"]}],
                "excluded_types": [],
                "target_accepted": 2,
                "max_candidates": 2,
                "max_pages_per_company": 5,
            }
            page_text = "Japanese matcha. Wholesale supplier. United States."
            crawl_batches = []
            assessment_batches = []
            for number in (1, 2):
                candidate_url = f"https://example{number}.com/"
                page_url = f"{candidate_url}about"
                crawl_batches.append(
                    [
                        {
                            "candidate": {"url": candidate_url},
                            "canonical_url": candidate_url,
                            "final_url": page_url,
                            "site_status": "active",
                            "pages": [{"url": page_url, "text": page_text}],
                            "emails": [],
                            "contact_forms": [],
                            "errors": [],
                            "checked_at": "2026-09-23T00:00:00+00:00",
                        }
                    ]
                )
                assessment_batches.append(
                    [
                        {
                            "candidate_url": candidate_url,
                            "company_name": f"Example {number}",
                            "recommendation": "accepted",
                            "claims": [
                                {"type": "product", "evidence_url": page_url, "evidence_text_original": "Japanese matcha."},
                                {"type": "buyer_role", "evidence_url": page_url, "evidence_text_original": "Wholesale supplier."},
                                {"type": "target_market", "evidence_url": page_url, "evidence_text_original": "United States."},
                            ],
                        }
                    ]
                )

            campaign_path = work / "campaign.json"
            campaign_path.write_text(json.dumps(campaign), encoding="utf-8")
            crawl_paths = [work / f"crawl-{number}.json" for number in (1, 2)]
            assessment_paths = [work / f"assessment-{number}.json" for number in (1, 2)]
            for path, value in zip(crawl_paths, crawl_batches):
                path.write_text(json.dumps(value), encoding="utf-8")
            for path, value in zip(assessment_paths, assessment_batches):
                path.write_text(json.dumps(value), encoding="utf-8")

            command = [
                sys.executable,
                str(SCRIPTS / "finalize_run.py"),
                "--campaign",
                str(campaign_path),
            ]
            for path in crawl_paths:
                command.extend(["--crawls", str(path)])
            for path in assessment_paths:
                command.extend(["--assessments", str(path)])
            command.extend(["--output-dir", str(work / "output")])
            subprocess.run(command, check=True, capture_output=True, text=True)

            summary = json.loads((work / "output" / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["candidates_checked"], 2)
            self.assertEqual(summary["accepted_exported"], 2)
            self.assertTrue(summary["target_met"])


if __name__ == "__main__":
    unittest.main()
