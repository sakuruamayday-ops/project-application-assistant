import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/validate_industrialization_assessment.py"
DIMENSIONS = ("innovation", "maturity", "intellectual_property", "testing",
              "user_application", "transaction", "industrialization")


class IndustrializationTests(unittest.TestCase):
    def setUp(self):
        self.document = {
            "project_context": {"product": "示例精密装备", "region": "浙江省", "year": 2026,
                                "policy_status": "current", "policy_locator": "首台（套）通知 第一节"},
            "primary_project": "首台（套）装备", "classification_basis": "整机合同",
            "maturity_stage": "首单销售", "conclusion": "eligible",
            "evidence": {name: {"status": "verified", "source_locator": f"证据包 第{index + 1}页"}
                         for index, name in enumerate(DIMENSIONS)},
            "alternative_projects": [], "exclusion_risks": [], "next_actions": ["备齐申报附件"],
        }

    def run_document(self, code):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "result.json"
            path.write_text(json.dumps(self.document, ensure_ascii=False), encoding="utf-8")
            run = subprocess.run([sys.executable, str(SCRIPT), str(path)], capture_output=True, text=True)
        self.assertEqual(run.returncode, code, run.stderr or run.stdout)
        return json.loads(run.stdout)

    def test_each_dimension_has_a_source_and_main_flow_passes(self):
        self.assertEqual(self.run_document(0)["items"], [])

    def test_verified_label_without_source_cannot_pass_qualification(self):
        for entry in self.document["evidence"].values():
            entry.pop("source_locator")
        report = self.run_document(2)
        self.assertEqual(len(report["items"]), 7)
        self.assertEqual(set(report["items"][0]), {"item", "gap", "action", "priority"})
        self.document["conclusion"] = "candidate"
        self.assertEqual(self.run_document(0)["status"], "pass")

    def test_old_policy_and_unsupported_exclusion_fail(self):
        self.document["project_context"]["policy_status"] = "historical"
        self.document["evidence"]["testing"] = {"status": "not-applicable"}
        report = self.run_document(2)
        self.assertEqual({row["item"] for row in report["items"]},
                         {"project_context.policy_locator", "evidence.testing"})


if __name__ == "__main__":
    unittest.main()
