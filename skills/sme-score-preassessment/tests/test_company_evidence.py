import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/preflight.py"


class CompanyEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.profile = {
            "enterprise_id": "SAMPLE-CO", "year": 2026,
            "financials": {
                "2024": {"revenue_wan": 3000, "rd_wan": 100, "locator": "样例审计报表2024"},
                "2025": {"revenue_wan": 3000, "rd_wan": 100, "main_revenue_wan": 2400,
                         "assets_wan": 500, "liabilities_wan": 400, "locator": "样例审计报表2025"},
            },
            "evidence": {key: {"met": True, "locator": f"样例证明材料 {key}"}
                         for key in ("designation", "market_duration", "intellectual_property",
                                     "market_position", "compliance")},
            "platform_evaluation": {"year": 2026, "enterprise_id": "SAMPLE-CO", "value": 50,
                                    "locator": "样例平台记录", "status": "verified-platform-score"},
        }

    def run_profile(self, level="省级专精特新中小企业", application="新申报"):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "company.json"
            path.write_text(json.dumps(self.profile, ensure_ascii=False), encoding="utf-8")
            checked = subprocess.run([sys.executable, str(SCRIPT), "--task-type", "quality-preassessment",
                                      "--project-level", level, "--application-type", application,
                                      "--input", str(path)], capture_output=True, text=True)
        self.assertEqual(checked.returncode, 0, checked.stderr or checked.stdout)
        report = json.loads(checked.stdout)
        self.assertEqual(report["input_status"], "received")
        return report["assessment"]

    def test_provincial_values_at_inclusive_limits(self):
        self.assertEqual(self.run_profile(), {"status": "checked", "items": []})

    def test_low_rd_and_wrong_enterprise_platform_receipt_list_defects(self):
        self.profile["financials"]["2024"]["rd_wan"] = 80
        self.profile["platform_evaluation"]["enterprise_id"] = "OTHER"
        result = self.run_profile()
        self.assertEqual(result["status"], "needs-evidence")
        self.assertEqual({row["item"] for row in result["items"]},
                         {"2024 年研发强度", "2024 年研发费用", "主管平台发展质量评价"})
        self.assertEqual(set(result["items"][0]), {"item", "gap", "action", "priority"})

    def test_national_new_application_reads_two_year_aggregate_and_growth(self):
        self.profile["platform_evaluation"]["value"] = 60
        self.profile["evidence"]["industry_chain"] = {"met": True, "locator": "样例产品定位表"}
        financials = self.profile["financials"]
        financials["2023"] = {"revenue_wan": 4500, "locator": "样例审计报表2023"}
        financials["2024"]["rd_wan"] = 600
        financials["2025"].update(revenue_wan=5000, main_revenue_wan=4500, rd_wan=600, liabilities_wan=375)
        self.assertEqual(self.run_profile("小巨人")["status"], "checked")
        financials["2024"]["rd_wan"] = 590
        self.assertEqual([row["item"] for row in self.run_profile("小巨人")["items"]], ["两年研发费用"])

    def test_national_review_keeps_management_checks_and_skips_growth(self):
        profile = self.profile
        profile["platform_evaluation"].update(year=2025, value=60)
        profile["evidence"]["industry_chain"] = {"met": True, "locator": "样例产品定位表"}
        profile["financials"]["2024"]["rd_wan"] = 600
        profile["financials"]["2025"].update(revenue_wan=5000, main_revenue_wan=4500, rd_wan=600, liabilities_wan=375)
        self.assertEqual(self.run_profile("小巨人", "复核"), {"status": "checked", "items": []})
        profile["review_group"] = "客户标记的专项情形"
        self.assertEqual(self.run_profile("小巨人", "复核")["status"], "review-transition")

    def test_financial_windows_roll_with_evaluation_year(self):
        self.profile["year"] = 2027
        data = self.profile["financials"]
        self.profile["financials"] = {"2025": data["2024"], "2026": data["2025"]}
        self.profile["platform_evaluation"]["year"] = 2027
        self.assertEqual(self.run_profile(), {"status": "checked", "items": []})


if __name__ == "__main__":
    unittest.main()
