import csv
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skill" / "verifying-sales-leads" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import evaluate_run  # noqa: E402
import finalize_run  # noqa: E402
import prepare_candidates  # noqa: E402


class OutputTests(unittest.TestCase):
    def test_candidate_domains_are_deduplicated(self):
        payload = ["https://example.com/a", "https://www.example.com/b", "https://other.example.org/"]
        results = prepare_candidates.prepare(payload, 100)
        self.assertEqual(len(results), 2)

    def test_csv_uses_japanese_and_json_keeps_original(self):
        record = {
            "company_name": "Example Imports",
            "canonical_url": "https://example.com/",
            "country": "アメリカ",
            "company_type": "輸入業者",
            "company_overview_ja": "日本茶の輸入会社。",
            "emails": [{"email": "sales@example.com", "source_url": "https://example.com/contact"}],
            "contact_forms": [{"url": "https://example.com/contact", "verification": "form_found"}],
            "verification_status": "accepted",
            "claims": [
                {
                    "type": "product",
                    "evidence_text_original": "We import matcha.",
                    "evidence_text_ja": "抹茶を輸入している。",
                }
            ],
            "checked_at": "2026-09-23T00:00:00+00:00",
        }
        row = finalize_run.csv_row(record)
        self.assertEqual(row["商材の証拠"], "抹茶を輸入している。")
        self.assertNotIn("We import matcha.", row.values())
        self.assertEqual(record["claims"][0]["evidence_text_original"], "We import matcha.")

    def test_precision_requires_all_thirty_labels(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "leads.csv"
            with path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["会社名", "human_verdict", "human_notes"])
                writer.writeheader()
                for index in range(30):
                    writer.writerow(
                        {
                            "会社名": f"Company {index}",
                            "human_verdict": "正しい" if index < 27 else "間違い",
                            "human_notes": "",
                        }
                    )
            result = evaluate_run.evaluate(path)
            self.assertEqual(result["correct"], 27)
            self.assertEqual(result["precision"], 0.9)
            self.assertTrue(result["passed"])

            with path.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            rows[0]["human_verdict"] = ""
            with path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)
            with self.assertRaises(ValueError):
                evaluate_run.evaluate(path)


if __name__ == "__main__":
    unittest.main()
