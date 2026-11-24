from decimal import Decimal
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from docx import Document


SKILL = Path(__file__).resolve().parents[1]
REPORTS = SKILL.parent / "project-feasibility/scripts"


class InstituteReportTests(unittest.TestCase):
    def run_tool(self, command, *args):
        run = subprocess.run([sys.executable, str(REPORTS / command), *map(str, args)], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr or run.stdout)
        return json.loads(run.stdout)

    def test_management_rule_and_ledger_are_read_back_in_word(self):
        management = next((SKILL / "references/policies").glob("浙经信高新〔2025〕169号-*.pdf"))
        self.assertTrue(management.read_bytes().startswith(b"%PDF-"))
        rate = Decimal(230) / Decimal(4800)
        gap = Decimal(4800) * Decimal("0.05") - Decimal(230)
        self.assertEqual(f"{rate:.4%}", "4.7917%")
        self.assertEqual(gap, 10)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            ledger = root / "样例审计财务页.txt"
            ledger.write_text("2025年度营业收入4800万元\n研发费用230万元\n", encoding="utf-8")
            title = "浙经信高新〔2025〕169号 浙江省重点企业研究院、企业研究院建设与管理办法"
            input_data = {
                "project_id": "enterprise-rd-center", "enterprise": "样例制造有限公司",
                "project_object": "浙江省企业研究院", "suggested_year": "2026",
                "conclusion": "有条件申报",
                "conclusion_basis": "研发强度低于适用门槛", "primary_gap": "研发费用差10万元",
                "next_action": "核对研发辅助账与审计报告", "materials": [
                    {"path": str(ledger), "anchors": ["2025年度营业收入4800万元", "研发费用230万元"],
                     "source_type": "customer-file"}],
                "policies": [{"title": title, "locator": management.name + " 第（九）项第2款", "kind": "management"}],
                "conditions": [{"match": "研发投入", "value": f"{rate:.4%}", "state": "存在差距",
                                "source": "样例审计财务页", "gap": "差10万元",
                                "action": "核对研发费用归集", "priority": "高"}],
                "items": [{"item": "研发强度", "gap": "差10万元", "action": "核对研发费用归集", "priority": "高"}],
            }
            fixture = root / "case.json"
            fixture.write_text(json.dumps(input_data, ensure_ascii=False), encoding="utf-8")
            template = self.run_tool("select_report_template.py", "--project-type", "enterprise-rd-center",
                                     "--report-type", "feasibility", "--output-dir", root,
                                     "--enterprise", input_data["enterprise"])
            artifact = root / "研究院条件核对.docx"
            result = self.run_tool("fill_report_template.py", "--template", template["output_path"],
                                   "--output", artifact, "--fixture", fixture, "--report-type", "feasibility",
                                   "--release-tag", "regression")
            rows = [" | ".join(cell.text for cell in row.cells) for table in Document(artifact).tables for row in table.rows]
            self.assertEqual(result["status"], "pass")
            self.assertTrue(any(title in row and management.name in row for row in rows))
            self.assertTrue(any("4.7917%" in row and "差10万元" in row for row in rows))
            self.assertTrue(any("研发强度" in row and "核对研发费用归集" in row for row in rows))


if __name__ == "__main__":
    unittest.main()
