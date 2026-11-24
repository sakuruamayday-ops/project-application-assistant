import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/validate_green_factory_ledger.py"


class LedgerScopeTests(unittest.TestCase):
    def ledger(self, scope, recommendation):
        return {
            "policy": {
                "region": "样例地区", "level": "样例层级", "target_year": 2026,
                "guide_title": "台账校验用导则", "guide_version": "合成用例", "verified_on": "2026-11-20",
                "status": "current", "evaluation_mode": "current_application", "ledger_scope": scope,
                "core_max_score": 1.6, "bonus_max_score": 0, "recommendation_threshold": 1,
            },
            "factory": {"organization_boundary": "样例工厂", "production_boundary": "样例产线",
                        "reporting_period": "2025", "allowed_denominator_units": ["吨"]},
            "evidence": [{"id": "E1", "attachment_ref": "工厂台账 第2页", "title": "现场核验记录",
                          "status": "verified", "supports": ["B1", "M1"]}],
            "basic_requirements": [{"id": "B1", "status": "pass", "evidence_ids": ["E1"]}],
            "score_rows": [{"id": "M1", "section": "core", "category": "能源管理", "requirement_type": "mandatory",
                            "status": "pass", "max_raw_score": 2, "claimed_raw_score": 2, "weight": 0.8,
                            "claimed_weighted_score": 1.6, "evidence_ids": ["E1"], "metric_ids": []}],
            "metrics": [],
            "summary": {"basic_requirements_met": True, "core_score": 1.6, "bonus_score": 0,
                        "total_score": 1.6, "recommendation": recommendation},
        }

    def check(self, scope, recommendation, code, *, with_values=True):
        ledger = self.ledger(scope, recommendation)
        if not with_values:
            for field in ("core_max_score", "bonus_max_score", "recommendation_threshold"):
                del ledger["policy"][field]
            for field in ("max_raw_score", "claimed_raw_score", "weight", "claimed_weighted_score"):
                del ledger["score_rows"][0][field]
            for field in ("core_score", "bonus_score", "total_score"):
                del ledger["summary"][field]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "ledger.json"
            path.write_text(json.dumps(ledger), encoding="utf-8")
            command = [sys.executable, str(SCRIPT), str(path)]
            if scope == "complete":
                rules = {key: ledger["policy"][key] for key in ("region", "level", "target_year", "guide_version")}
                rules["source_ref"] = "【MOCK】样例导则核对件"
                rules["criteria"] = {"M1": {"name": "能源管理", "section": "core", "max_raw_score": 2, "weight": 0.8}}
                rule_path = Path(folder) / "rules.json"
                rule_path.write_text(json.dumps(rules), encoding="utf-8")
                command.extend(["--rules", str(rule_path)])
            run = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(run.returncode, code, run.stderr or run.stdout)
        return json.loads(run.stdout)

    def test_complete_and_partial_ledgers_diverge_on_recommendation(self):
        complete = self.check("complete", "recommendable", 0)
        self.assertTrue(complete["mandatory_requirements_met"])
        partial = self.check("partial", "recommendable", 2)
        self.assertIn("推荐判断需覆盖当期全部评价条款", partial["errors"])
        self.assertTrue(any(item["item"] == "评价条款覆盖" for item in partial["items"]))
        self.assertTrue(all(item["item"] != "当期推荐线" for item in partial["items"]))
        self.assertEqual(self.check("partial", "conditional", 0)["status"], "pass")

    def test_partial_accepts_evidence_without_legacy_values(self):
        result = self.check("partial", "conditional", 0, with_values=False)
        self.assertEqual(result["errors"], [])
        self.assertTrue(any(item["item"] == "M1 能源管理" for item in result["items"]))
        self.assertEqual(self.check("complete", "recommendable", 2, with_values=False)["status"], "fail")


if __name__ == "__main__":
    unittest.main()
