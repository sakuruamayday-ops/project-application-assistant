import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/validate_ip_inventory.py"


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.entry = {"id": "SAMPLE-01", "type": "发明专利", "title": "样例权利",
                      "owner": "样例企业", "status": "granted-active", "cutoff_date": "2026-11-20",
                      "acquisition": "自主研发", "product_link": "样例产品模块", "usable_as_granted": True}

    def validate(self, *rows, code=0):
        return self.validate_content(json.dumps(rows, ensure_ascii=False), code=code)

    def validate_content(self, content, *, code):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "inventory.json"
            path.write_text(content, encoding="utf-8")
            run = subprocess.run([sys.executable, str(SCRIPT), str(path)], capture_output=True, text=True)
        self.assertEqual(run.returncode, code, run.stderr or run.stdout)
        return json.loads(run.stdout)

    def test_missing_inventory_rejects_empty_array_file_and_header_only(self):
        headers = "id,type,title,owner,status,cutoff_date,acquisition,product_link"
        cases = ("[]", "", headers + "\n", json.dumps({"headers": headers.split(","), "rows": []}))
        for content in cases:
            with self.subTest(content=content):
                report = self.validate_content(content, code=2)
                self.assertEqual(report["status"], "fail")
                self.assertIn("未提供知识产权清单", report["errors"][0])

    def test_valid_and_pending_are_classified_separately(self):
        pending = {**self.entry, "id": "SAMPLE-02", "status": "pending", "usable_as_granted": False}
        self.assertEqual(self.validate(self.entry, pending)["items"], [])

    def test_invalid_owner_date_and_status_are_each_reported(self):
        broken = {**self.entry, "status": "expired", "owner": "", "cutoff_date": "2026-02-30"}
        report = self.validate(broken, code=2)
        self.assertEqual({row["item"].rsplit(" / ", 1)[-1] for row in report["items"]},
                         {"owner", "cutoff_date", "status"})
        self.assertEqual(set(report["items"][0]), {"item", "gap", "action", "priority"})

    def test_legacy_granted_needs_confirmed_effectiveness(self):
        record = {**self.entry, "status": "granted"}
        self.assertEqual(self.validate(record, code=2)["status"], "fail")
        record["effective"] = True
        self.assertEqual(self.validate(record)["status"], "pass")


if __name__ == "__main__":
    unittest.main()
