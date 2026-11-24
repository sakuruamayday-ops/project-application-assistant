import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile

from docx import Document
from docx.oxml.ns import qn


SKILL = Path(__file__).resolve().parents[1]


class WordPreservationTests(unittest.TestCase):
    def run_tool(self, script, *args):
        run = subprocess.run([sys.executable, str(SKILL / "scripts" / script), *map(str, args)],
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr or run.stdout)
        return json.loads(run.stdout)

    def test_document_retains_unslotted_policy_short_condition_and_zero(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fixture = root / "facts.json"
            source = root / "实际资料.txt"
            source.write_text("现场记录：离线设备 0 台", encoding="utf-8")
            setup = {
                "project_id": "digitalization", "enterprise": "样例制造有限公司",
                "project_object": "数字化车间", "suggested_year": "2026",
                "deadline": "2026-10-10", "conclusion": "有条件申报",
                "conclusion_basis": "需补同口径现场运行材料", "primary_gap": "缺连续记录",
                "next_action": "保存最近六个月记录",
                "materials": [{"path": str(source), "anchors": ["离线设备 0 台"], "source_type": "customer-file"}],
                "policies": [{"title": "某市数字化车间认定管理办法",
                              "locator": "样例管理办法 正文第1页"}],
                "conditions": [{"match": "离线设备", "value": 0, "state": "已具备",
                                "source": "现场记录 第1页"}],
                "items": [{"item": "连续运行记录", "gap": "缺六个月", "action": "补导出记录", "priority": "高"}],
            }
            fixture.write_text(json.dumps(setup, ensure_ascii=False), encoding="utf-8")
            for report_type in ("preassessment", "feasibility"):
                with self.subTest(report_type=report_type):
                    master = self.run_tool("select_report_template.py", "--project-type", "digitalization",
                                           "--report-type", report_type, "--output-dir", root,
                                           "--enterprise", setup["enterprise"])
                    candidate = root / f"{report_type}.docx"
                    self.run_tool("fill_report_template.py", "--template", master.get("working_copy", master.get("output_path")),
                                  "--output", candidate, "--fixture", fixture, "--report-type", report_type,
                                  "--release-tag", "regression")
                    doc = Document(candidate)
                    with ZipFile(candidate) as archive:
                        self.assertNotIn(b"w:embed", archive.read("word/fontTable.xml"))
                        self.assertNotIn(b"w:embedTrueTypeFonts", archive.read("word/settings.xml"))
                        self.assertFalse(any(name.startswith("word/fonts/") for name in archive.namelist()))
                    defaults = doc.styles.element.xpath("./w:docDefaults/w:rPrDefault/w:rPr/w:rFonts")[0]
                    self.assertEqual(defaults.get(qn("w:eastAsia")), "宋体")
                    for node in doc.element.xpath(".//w:rFonts"):
                        self.assertEqual(node.get(qn("w:eastAsia")), "宋体")
                        self.assertEqual(node.get(qn("w:ascii")), "Times New Roman")
                        self.assertEqual(node.get(qn("w:hAnsi")), "Times New Roman")
                    rows = [[cell.text for cell in row.cells] for table in doc.tables for row in table.rows]
                    self.assertTrue(any(setup["policies"][0]["title"] in row and "样例管理办法 正文第1页" in row for row in rows))
                    self.assertTrue(any(row[0] == "离线设备" and row[1] == "0" for row in rows))
                    if report_type == "feasibility":
                        self.assertTrue(any({"优先级", "缺陷项", "差距", "补强动作"} <= set(row) for row in rows))
                        self.assertTrue(any("连续运行记录" in row and "补导出记录" in row for row in rows))


if __name__ == "__main__":
    unittest.main()
