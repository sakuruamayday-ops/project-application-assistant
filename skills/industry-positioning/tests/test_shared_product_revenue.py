import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SKILL = Path(__file__).resolve().parents[1]
SCRIPT = SKILL / "scripts/technical_product_revenue_matrix.py"


class SharedProductRevenueTests(unittest.TestCase):
    def test_two_technical_versions_keep_one_sourced_terminal_sale(self):
        data = json.loads((SKILL / "assets/enterprise-technical-product-revenue-matrix.template.json").read_text())
        data["company"].update(name="样例设备企业", as_of_date="2026-11-20")
        tech = data["technologies"][0]
        tech.update(public_name="稳定成形工艺", technical_goal="提高一致性", public_route="受控工艺路线")
        tech["sources"][0].update(document="设备工艺表", locator="第1页")
        second = copy.deepcopy(tech)
        second.update(id="tech-002", internal_version="V2", public_name="改进成形工艺")
        data["technologies"].append(second)
        product = data["products"][0]
        product["name"] = "同一终端装置"
        product["sources"][0].update(document="产品清单", locator="表1")
        first_link = data["technology_product_links"][0]
        first_link["source"].update(document="工艺装配表", locator="表2")
        first_link["performance_contributions"][0].update(metric="成形一致性", value="符合出厂内控")
        data["technology_product_links"].append({**copy.deepcopy(first_link), "technology_id": "tech-002"})
        data["commercialization"][0].update(year="2025", amount="128.50")
        data["commercialization"][0]["source"].update(document="样例销售台账", locator="终端装置 D5")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "master.json"
            source.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            cmd = [sys.executable, str(SCRIPT), "build", "--input", str(source),
                   "--output-dir", str(root / "report"), "--projects", "provincial_sme,small_giant"]
            run = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr or run.stdout)
            for project in ("provincial_sme", "small_giant"):
                with self.subTest(project=project):
                    view = json.loads((root / f"report/project_views/{project}.json").read_text())
                    candidates = view["product_subject_candidates"]
                    self.assertEqual(len(candidates), 1)
                    item, = candidates
                    self.assertEqual(len(item["linked_technologies"]), 2)
                    self.assertEqual(len(item["commercialization"]), 1)
                    self.assertEqual(item["commercialization"][0]["amount"], "128.50")
                    self.assertEqual(item["commercialization"][0]["source"]["locator"], "终端装置 D5")


if __name__ == "__main__":
    unittest.main()
