import csv
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "verifying-sales-leads" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import evaluate_run  # noqa: E402
import export_review_workbook  # noqa: E402
import finalize_run  # noqa: E402
import prepare_candidates  # noqa: E402


class OutputTests(unittest.TestCase):
    def accepted_record(self, index=0, company_type="カフェ", uncertainties=None):
        url = f"https://example{index}.com/"
        return {
            "company_name": f"Example Cafe {index}",
            "canonical_url": url,
            "country": "アメリカ",
            "company_type": company_type,
            "company_overview_ja": "抹茶ドリンクを提供するカフェ。",
            "emails": [{"email": f"hello{index}@example.com", "source_url": url}],
            "contact_forms": [],
            "verification_status": "accepted",
            "uncertainties": uncertainties or [],
            "claims": [
                {"type": "product", "evidence_url": url + "menu", "evidence_text_ja": "抹茶ラテを提供。"},
                {"type": "buyer_role", "evidence_url": url + "about", "evidence_text_ja": "カフェを運営。"},
                {"type": "target_market", "evidence_url": url + "locations", "evidence_text_ja": "米国に店舗がある。"},
            ],
            "checked_at": "2026-09-25T00:00:00+00:00",
        }

    def test_candidate_domains_are_deduplicated(self):
        payload = ["https://example.com/a", "https://www.example.com/b", "https://other.example.org/"]
        results = prepare_candidates.prepare(payload, 100)
        self.assertEqual(len(results), 2)

    def test_newer_recrawl_replaces_older_result(self):
        old = {
            "candidate": {"url": "https://example.com/"},
            "site_status": "blocked",
            "pages": [],
        }
        new = {
            "candidate": {"url": "https://example.com/"},
            "site_status": "active",
            "pages": [{"url": "https://example.com/", "text": "new"}],
        }
        results = finalize_run.deduplicate_crawls([old, new])
        self.assertEqual(results, [new])

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
                    "evidence_url": "https://example.com/about",
                    "evidence_text_original": "We import matcha.",
                    "evidence_text_ja": "抹茶を輸入している。",
                }
            ],
            "checked_at": "2026-09-23T00:00:00+00:00",
        }
        row = finalize_run.csv_row(record)
        self.assertEqual(row["商材の証拠"], "抹茶を輸入している。")
        self.assertEqual(row["商材の証拠URL"], "https://example.com/about")
        self.assertIn("会社の役割の証拠URL", row)
        self.assertIn("対象地域の証拠URL", row)
        self.assertNotIn("We import matcha.", row.values())
        self.assertEqual(record["claims"][0]["evidence_text_original"], "We import matcha.")

    def test_review_workbook_has_rows_filters_and_verdict_dropdown(self):
        record = self.accepted_record()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "leads.xlsx"
            export_review_workbook.write_review_workbook([record], path)
            workbook = export_review_workbook.load_workbook(path)
            self.assertEqual(workbook.sheetnames, ["確認リスト", "確認ガイド"])
            sheet = workbook["確認リスト"]
            self.assertEqual(sheet["D7"].value, "Example Cafe 0")
            self.assertEqual(sheet["E7"].hyperlink.target, "https://example0.com/")
            self.assertEqual(sheet.freeze_panes, "D7")
            self.assertEqual(len(sheet.data_validations.dataValidation), 1)
            self.assertIn("B7", str(sheet.data_validations.dataValidation[0].sqref))
            self.assertEqual(len(sheet.tables), 1)

    def test_sales_workbook_is_clean_and_has_no_review_columns(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "leads.xlsx"
            export_review_workbook.write_sales_workbook([self.accepted_record()], path)
            workbook = export_review_workbook.load_workbook(path)
            self.assertEqual(workbook.sheetnames, ["営業リスト"])
            sheet = workbook["営業リスト"]
            headers = [cell.value for cell in sheet[4]]
            self.assertNotIn("人の判定", headers)
            self.assertNotIn("確認メモ", headers)
            self.assertEqual(sheet["B5"].value, "Example Cafe 0")
            self.assertEqual(sheet["C5"].hyperlink.target, "https://example0.com/")
            self.assertEqual(sheet.freeze_panes, "B5")

    def test_quality_sample_is_deterministic_diverse_and_includes_difficult_records(self):
        records = [
            self.accepted_record(
                index,
                company_type=("カフェ", "レストラン", "小売店")[index % 3],
                uncertainties=["境界事例"] if index in (12, 17) else [],
            )
            for index in range(20)
        ]
        first = export_review_workbook.select_quality_sample(records, 10)
        second = export_review_workbook.select_quality_sample(records, 10)
        urls = [record["canonical_url"] for record in first]
        self.assertEqual(urls, [record["canonical_url"] for record in second])
        self.assertIn("https://example12.com/", urls)
        self.assertIn("https://example17.com/", urls)
        self.assertNotEqual(urls, [record["canonical_url"] for record in records[:10]])
        self.assertEqual(len({record["company_type"] for record in first}), 3)

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
            result = evaluate_run.evaluate(path, expected=30)
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
                evaluate_run.evaluate(path, expected=30)

    def test_precision_can_be_calculated_from_review_workbook(self):
        records = []
        labels = {}
        for index in range(2):
            url = f"https://example{index}.com/"
            records.append(
                {
                    "company_name": f"Example {index}",
                    "canonical_url": url,
                    "claims": [],
                    "emails": [],
                    "contact_forms": [],
                }
            )
            labels[url] = ("正しい" if index == 0 else "間違い", "")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "leads.xlsx"
            export_review_workbook.write_review_workbook(records, path, labels)
            result = evaluate_run.evaluate(path, expected=2, threshold=0.5)
            self.assertEqual(result["correct"], 1)
            self.assertEqual(result["precision"], 0.5)
            self.assertTrue(result["passed"])
            self.assertEqual(result["next_action"], "quick_check_complete")


if __name__ == "__main__":
    unittest.main()
