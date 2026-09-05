import json
import hashlib
import importlib.util
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

    def query(self, db, *options):
        result = subprocess.run(
            [sys.executable, str(ENGINE), "--db", str(db), "query", *options],
            check=True, capture_output=True, text=True,
        )
        return [json.loads(line) for line in result.stdout.splitlines()]

    def test_source_id_year_status_and_history_survive_raw_import(self):
        initial = [
            {"id": "Q1", "version": 1, "year": 2025, "title": "测试设备政策", "status": "active", "source": "GC-QA fixture 1"},
            {"id": "Q2", "version": 1, "year": 2026, "title": "测试研发政策", "status": "active", "source": "GC-QA fixture 2"},
        ]
        update = [
            {"id": "Q1", "version": 2, "year": 2026, "title": "测试设备政策更新", "status": "active", "source": "GC-QA fixture 3"},
            {"id": "Q2", "version": 2, "year": 2026, "title": "测试研发政策", "status": "inactive", "source": "GC-QA fixture 4"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db, input_path = root / "index.sqlite3", root / "records.json"
            command = [sys.executable, str(ENGINE), "--db", str(db), "ingest", "--input", str(input_path), "--source", "synthetic"]
            input_path.write_text(json.dumps(initial + [initial[0]]), encoding="utf-8")
            first = self.run_json(command)
            self.assertEqual((first["inserted"], first["unchanged"], first["failed"]), (2, 1, 0))
            self.assertEqual([row["source_record_id"] for row in self.query(db, "--year", "2026")], ["Q2"])
            input_path.write_text(json.dumps(update), encoding="utf-8")
            second = self.run_json(command)
            self.assertEqual((second["inserted"], second["updated"], second["failed"]), (0, 2, 0))
            self.assertEqual([row["source_record_id"] for row in self.query(db, "--year", "2026")], ["Q1"])
            rows = {row["source_record_id"]: row for row in self.query(db, "--year", "2026", "--include-inactive")}
            self.assertEqual(set(rows), {"Q1", "Q2"})
            self.assertEqual(rows["Q1"]["publish_date"], "")
            self.assertEqual(rows["Q1"]["source_version"], "2")
            self.assertEqual(rows["Q1"]["source"], "synthetic")
            self.assertEqual(rows["Q1"]["article_source"], "GC-QA fixture 3")
            self.assertEqual((rows["Q2"]["application_status"], rows["Q2"]["active"]), ("inactive", 0))
            repeated = self.run_json(command)
            self.assertEqual(repeated["unchanged"], 2)
            self.assertEqual(len(self.query(db, "--year", "2026")), 1)
            with closing(sqlite3.connect(db)) as connection:
                versions = [json.loads(row[0]) for row in connection.execute("SELECT canonical_json FROM record_versions ORDER BY id")]
            self.assertEqual(len(versions), 4)
            self.assertEqual(versions[0]["year"], "2025")
            self.assertEqual(versions[0]["article_source"], "GC-QA fixture 1")
            self.assertEqual(versions[1]["active"], 1)
            self.assertEqual(versions[3]["active"], 0)

    def test_distinct_source_ids_and_collection_sources_are_not_merged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db, input_path = root / "index.sqlite3", root / "records.json"
            records = [{"id": identity, "title": "同名记录", "year": 2026} for identity in (0, "Q2")]
            input_path.write_text(json.dumps(records), encoding="utf-8")
            command = [sys.executable, str(ENGINE), "--db", str(db), "ingest", "--input", str(input_path)]
            for source in ("source-a", "source-b"):
                self.assertEqual(self.run_json(command + ["--source", source])["inserted"], 2)
            self.assertEqual(len(self.query(db, "--include-inactive")), 4)
            # 无源 ID 的旧格式也不能把不同来源的同名记录合并。
            input_path.write_text(json.dumps([{"title": "旧格式同名记录", "publish_date": "2026-07-13"}]), encoding="utf-8")
            for source in ("source-a", "source-b"):
                self.assertEqual(self.run_json(command + ["--source", source])["inserted"], 1)
            self.assertEqual(len(self.query(db, "--year", "2026")), 6)

    def test_new_empty_fields_keep_existing_record_digest(self):
        spec = importlib.util.spec_from_file_location("index_engine", ENGINE)
        engine = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(engine)
        record = engine.canonicalize(self.sample_records()[0], "aiqice", "local")
        original = {key: value for key, value in record.items() if key not in {"authorization_scope", "source_record_id", "year", "source_version", "active"}}
        digest = hashlib.sha256(json.dumps(original, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        self.assertEqual(engine.record_hash(record), digest)

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
