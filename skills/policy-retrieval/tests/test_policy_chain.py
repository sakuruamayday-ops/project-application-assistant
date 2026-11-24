import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SKILL = Path(__file__).resolve().parents[1]
SOURCE = SKILL.parent / "sme-score-preassessment/references/policies"


class PolicyChainTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "record.json"
        self.original = next(SOURCE.glob("工信部企业〔2026〕2号-*.pdf"))
        self.payload = {"project": "专精特新小巨人", "region": "全国", "documents": {
            "management": {"title": "优质中小企业梯度培育管理办法", "issuer": "工业和信息化部",
                           "region": "全国", "status": "current", "number": "工信部企业〔2026〕2号",
                           "official_url": "https://www.miit.gov.cn/zwgk/zcwj/wjfb/tz/art/2026/art_5546b1a622ea4d73bd2ca395b73bd4eb.html",
                           "body": str(self.original),
                           "number_source": str(next(SOURCE.glob("工信部企业〔2026〕2号-*.md")))},
        }}

    def run_chain(self, code):
        self.path.write_text(json.dumps(self.payload, ensure_ascii=False), encoding="utf-8")
        run = subprocess.run([sys.executable, str(SKILL / "scripts/validate_policy_chain.py"), str(self.path)],
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, code, run.stderr or run.stdout)
        return json.loads(run.stdout)

    def test_management_original_is_sufficient(self):
        report = self.run_chain(0)
        self.assertEqual(report["items"], [])
        self.assertEqual(Path(report["documents"]["management"]["body"]), self.original)

    def test_missing_attachment_number_and_official_host(self):
        management = self.payload["documents"]["management"]
        management.pop("number")
        management["official_url"] = "https://www.miit.gov.cn.example.invalid/"
        management["attachments_expected"] = 1
        management["attachments"] = [{"title": "管理办法附表", "path": "缺件.pdf"}]
        report = self.run_chain(2)
        self.assertEqual({row["item"] for row in report["items"]}, {"管理办法", "管理办法附件 1"})
        self.assertTrue(all({"item", "gap", "action", "priority"} == set(row) for row in report["items"]))


if __name__ == "__main__":
    unittest.main()
