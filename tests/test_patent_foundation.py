import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class PatentRouterCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.repository = Path(__file__).resolve().parents[1]

    def test_normalize_patent_records(self):
        script = self.repository / "skills/patent-router/scripts/normalize_patent_records.py"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.jsonl"
            target = root / "output.jsonl"
            source.write_text(
                json.dumps({"publication_number": "CN 123-A", "applicants_original": "测试 公司"}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            subprocess.run(["python3", str(script), str(source), str(target)], check=True)
            record = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(record["publication_number"], "CN123A")
            self.assertEqual(record["applicants_original"][0]["normalized"], "测试公司")
            self.assertEqual(record["legal_status"], "无法确认")

    def test_build_search_plan(self):
        script = self.repository / "skills/patent-router/scripts/build_search_plan.py"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.json"
            target = root / "output.json"
            source.write_text(json.dumps({"purpose": "稳定性", "features": ["多层共挤"]}, ensure_ascii=False), encoding="utf-8")
            subprocess.run(["python3", str(script), str(source), str(target)], check=True)
            plan = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(plan["purpose"], "稳定性")
            self.assertEqual(plan["features"][0]["feature"], "多层共挤")

    def test_patent_connector_imports_and_searches(self):
        script = self.repository / "skills/patent-router/scripts/patent_index.py"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "patents.jsonl"
            source.write_text(json.dumps({
                "publication_number": "CN112345678A",
                "application_number": "CN202011234567.8",
                "title": "一种多层共挤容器",
                "legal_status": "审中",
                "status_sources": [{"level": "第三方数据库", "checked_at": "2026-07-13"}],
            }, ensure_ascii=False) + "\n", encoding="utf-8")
            database = root / "patents.sqlite3"
            imported = subprocess.run([sys.executable, str(script), "--db", str(database), "import", "--input", str(source)], check=True, capture_output=True, text=True)
            self.assertEqual(json.loads(imported.stdout)["inserted"], 1)
            connection = sqlite3.connect(database)
            row = connection.execute("SELECT document_kind, legal_status FROM patents").fetchone()
            connection.close()
            self.assertEqual(row, ("A", "审中"))


if __name__ == "__main__":
    unittest.main()
