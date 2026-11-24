import contextlib
import importlib.util
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ENGINE = Path(__file__).resolve().parents[1] / "scripts" / "index_engine.py"
SPEC = importlib.util.spec_from_file_location("index_engine", ENGINE)
engine = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(engine)
COLLECTION_DATE = "2026-11-18"


class IndexDeliveryTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name) / "index"
        self.db = self.root / "policy-index.sqlite3"
        self.input = Path(scratch.name) / "input.json"
        self.ingest_args = (
            "ingest", "--input", str(self.input), "--source", "test-source",
            "--collection-date", COLLECTION_DATE, "--authorization-scope", "本地测试",
            "--region", "浙江省",
        )
        self.record = {"id": "source-7", "title": "测试申报通知", "region": "浙江省", "page_number": 1}
        self.write_input([self.record])

    def write_input(self, records):
        self.input.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")

    def run_cli(self, *args, use_default_db=False):
        db_args = [] if use_default_db else ["--db", str(self.db)]
        return subprocess.run(
            [sys.executable, "-B", str(ENGINE), *db_args, *args],
            env={**os.environ, "PROJECT_APPLICATION_ASSISTANT_INDEX_ROOT": str(self.root)},
            capture_output=True, encoding="utf-8", check=False,
        )

    def cli_result(self, *args, use_default_db=False):
        process = self.run_cli(*args, use_default_db=use_default_db)
        self.assertEqual(process.returncode, 0, process.stderr)
        return json.loads(process.stdout)

    def assert_ingest_failure(self, *messages):
        output = io.StringIO()
        errors = io.StringIO()
        argv = [str(ENGINE), "--db", str(self.db), *self.ingest_args]
        with patch.object(sys, "argv", argv), contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            exit_code = engine.main() or 0
        self.assertNotEqual(exit_code, 0)
        self.assertEqual(output.getvalue(), "")
        error = json.loads(errors.getvalue())["error"]
        for message in messages:
            self.assertIn(message, error)
        status = self.cli_result("status")
        self.assertEqual(status["records"], 1)
        self.assertEqual(status["last_run"]["status"], "failed")
        self.assertEqual(status["last_run"]["inserted_count"], 1)
        self.assertEqual(status["last_run"]["error_summary"], error)
        self.assertIsNone(status["last_success_date"])
        with contextlib.closing(sqlite3.connect(self.db)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM collection_checkpoints").fetchone()[0], 0)

    def read_reports(self, result):
        paths = {
            key: self.root / "reports" / f"{result['run_id']}_{key}.json"
            for key in ("batch_history", "delivery_checklist")
        }
        self.assertEqual(result["reports"], {key: str(path) for key, path in paths.items()})
        return [json.loads(path.read_text(encoding="utf-8")) for path in paths.values()]

    def test_success_with_both_reports_and_batch_counts(self):
        unchanged = {"id": "source-8", "title": "原样政策", "official_url": "https://example.invalid/source-8"}
        self.write_input([self.record, unchanged])
        seed = self.cli_result(*self.ingest_args, use_default_db=True)
        changed = dict(self.record, title="更新的申报通知", official_url="https://example.invalid/source-7")
        self.write_input([changed, unchanged, {"id": "source-9", "title": "新增通知"}])
        result = self.cli_result(*self.ingest_args, use_default_db=True)
        self.assertEqual(result["status"], "success")
        self.assertNotEqual(result["run_id"], seed["run_id"])
        history, checklist = self.read_reports(result)
        self.assertEqual(history["run_id"], result["run_id"])
        self.assertEqual(history["collection_date"], COLLECTION_DATE)
        self.assertEqual(history["source"], "test-source")
        expected_counts = {"inserted": 1, "updated": 1, "unchanged": 1, "failed": 0, "missing_official": 1}
        self.assertEqual({key: history[key] for key in expected_counts}, expected_counts)
        self.assertEqual(checklist["run_id"], result["run_id"])
        self.assertEqual({key: item["status"] for key, item in checklist["items"].items()}, {
            "字段完整性": "已取得", "分页覆盖": "部分取得", "去重": "已取得",
            "来源链接": "部分取得", "授权范围": "部分取得",
        })
        for item in checklist["items"].values():
            self.assertTrue(Path(item["evidence"]).is_file())
            self.assertTrue(item["detail"])

    def test_index_write_without_reports_fails_and_can_be_retried(self):
        with patch.object(engine, "write_delivery_reports"):
            self.assert_ingest_failure("缺少批次履历", "缺少交付检查表")
        retry = self.cli_result(*self.ingest_args)
        self.assertEqual(retry["status"], "success")
        self.assertEqual(retry["inserted"], 0)
        self.assertEqual(retry["unchanged"], 1)
        self.read_reports(retry)
        self.assertEqual(self.cli_result("status")["last_success_date"], COLLECTION_DATE)

    def test_missing_checklist_fails_even_with_batch_history(self):
        def write_history_only(paths, batch, checklist):
            path = paths["batch_history"]
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(batch), encoding="utf-8")

        with patch.object(engine, "write_delivery_reports", side_effect=write_history_only):
            self.assert_ingest_failure("缺少交付检查表")

    def test_batch_history_missing_count_fails(self):
        write_reports = engine.write_delivery_reports

        def write_incomplete_history(paths, batch, checklist):
            history = dict(batch)
            del history["missing_official"]
            write_reports(paths, history, checklist)

        with patch.object(engine, "write_delivery_reports", side_effect=write_incomplete_history):
            self.assert_ingest_failure("批次履历缺少字段 missing_official")

    def test_checklist_missing_evidence_fails(self):
        write_reports = engine.write_delivery_reports

        def write_incomplete_checklist(paths, batch, checklist):
            del checklist["items"]["去重"]["evidence"]
            write_reports(paths, batch, checklist)

        with patch.object(engine, "write_delivery_reports", side_effect=write_incomplete_checklist):
            self.assert_ingest_failure("交付检查表 去重 缺少字段 evidence")

    def test_report_directory_write_error_returns_nonzero(self):
        self.root.mkdir()
        (self.root / "reports").touch()
        result = self.run_cli(*self.ingest_args)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("无法创建批次履历和交付检查表目录", json.loads(result.stderr)["error"])
        self.assertEqual(self.cli_result("status")["last_run"]["status"], "failed")

    def test_query_status_and_export_work_without_reports(self):
        with patch.object(engine, "write_delivery_reports"):
            self.assert_ingest_failure("缺少批次履历", "缺少交付检查表")
        record = self.cli_result("query", "--region", "浙江省", "--keyword", "申报")
        self.assertEqual(record["source_record_id"], self.record["id"])
        exported = self.root / "records.jsonl"
        result = self.cli_result("export", "--format", "jsonl", "--output", str(exported))
        self.assertEqual(result["records"], 1)
        self.assertEqual(json.loads(exported.read_text(encoding="utf-8"))["id"], record["id"])

    def test_partial_ingest_retains_counts_and_emits_reports(self):
        self.write_input([self.record, {"id": "broken-record"}])
        result = self.cli_result(*self.ingest_args)
        self.assertEqual(result["status"], "partial")
        history, checklist = self.read_reports(result)
        self.assertEqual(history["inserted"], 1)
        self.assertEqual(history["failed"], 1)
        self.assertEqual(checklist["items"]["字段完整性"]["status"], "部分取得")
        self.assertEqual(checklist["items"]["来源链接"]["status"], "未取得")
        self.assertIsNone(self.cli_result("status")["last_success_date"])
