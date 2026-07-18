import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "skills" / "third-party-data-indexing" / "scripts" / "index_engine.py"
DAILY = ROOT / "skills" / "third-party-data-indexing" / "scripts" / "daily_update.py"


class DataIndexingTests(unittest.TestCase):
    def run_json(self, command):
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        return json.loads(result.stdout)

    def sample_records(self):
        return [
            {
                "title": "浙江省某项目申报通知",
                "region": "浙江省",
                "record_type": "申报通知",
                "publish_date": "2026-07-13",
                "issuer": "浙江省某厅",
                "detail_url": "https://www.aiqice.cn/policyDetail?id=1&indexId=2",
                "official_url": "https://example.gov.cn/policy/1",
                "eligibility_conditions": "企业注册地在浙江省，具有自主知识产权。",
            },
            {
                "title": "杭州市某项目公示",
                "region": "杭州市",
                "record_type": "公示",
                "publish_date": "2026-07-13",
                "issuer": "杭州市某局",
                "detail_url": "https://www.aiqice.cn/policyDetail?id=3&indexId=4",
                "beneficiary_companies": ["杭州示例科技有限公司"],
                "beneficiary_count": 1,
            },
        ]

    def test_sqlite_ingest_dedupe_version_and_export(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = root / "index.sqlite3"
            input_path = root / "records.jsonl"
            input_path.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in self.sample_records()) + "\n", encoding="utf-8")
            first = self.run_json([sys.executable, str(ENGINE), "--db", str(db), "ingest", "--input", str(input_path), "--collection-date", "2026-07-13"])
            self.assertEqual(first["inserted"], 2)
            second = self.run_json([sys.executable, str(ENGINE), "--db", str(db), "ingest", "--input", str(input_path), "--collection-date", "2026-07-13"])
            self.assertEqual(second["unchanged"], 2)
            records = self.sample_records()
            records[0]["application_status"] = "申报中"
            records[1]["official_url"] = "https://example.gov.cn/policy/2"
            input_path.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in records) + "\n", encoding="utf-8")
            third = self.run_json([sys.executable, str(ENGINE), "--db", str(db), "ingest", "--input", str(input_path), "--collection-date", "2026-07-13"])
            self.assertEqual(third["updated"], 2)
            with closing(sqlite3.connect(db)) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM records").fetchone()[0], 2)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM record_versions").fetchone()[0], 4)
                self.assertEqual(connection.execute("SELECT eligibility_conditions FROM records WHERE record_type='申报通知'").fetchone()[0], "企业注册地在浙江省，具有自主知识产权。")
                self.assertEqual(json.loads(connection.execute("SELECT beneficiary_companies_json FROM records WHERE record_type='公示'").fetchone()[0]), ["杭州示例科技有限公司"])
            export_dir = root / "markdown"
            exported = self.run_json([sys.executable, str(ENGINE), "--db", str(db), "export", "--format", "markdown", "--output", str(export_dir)])
            self.assertEqual(exported["records"], 2)
            self.assertEqual(len(list((export_dir / "项目").glob("*.md"))), 2)

    def test_daily_backfill_request_then_ingest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = self.run_json([sys.executable, str(DAILY), "--root", str(root), "--through", "2026-07-13", "--region", "浙江省"])
            self.assertEqual(first["status"], "browser_collection_required")
            self.assertTrue((root / "requests" / "aiqice-2026-07-13.json").exists())
            inbox = root / "inbox" / "aiqice-2026-07-13.jsonl"
            inbox.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in self.sample_records()) + "\n", encoding="utf-8")
            second = self.run_json([sys.executable, str(DAILY), "--root", str(root), "--through", "2026-07-13", "--region", "浙江省"])
            self.assertEqual(second["status"], "success")
            self.assertEqual(second["ingested"][0]["inserted"], 2)
            self.assertFalse((root / "requests" / "aiqice-2026-07-13.json").exists())

    def test_daily_requires_region_before_collection(self):
        with tempfile.TemporaryDirectory() as directory:
            environment = dict(os.environ)
            environment["HOME"] = directory
            process = subprocess.run(
                [sys.executable, str(DAILY), "--root", directory, "--through", "2026-07-13"],
                check=True,
                capture_output=True,
                text=True,
                env=environment,
            )
            result = json.loads(process.stdout)
            self.assertEqual(result["status"], "region_configuration_required")

if __name__ == "__main__":
    unittest.main()
