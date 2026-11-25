import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from async_search_checkpoint import DEFAULT_REGISTRY, registry_location
from build_search_plan import build_plan, run_async_search_unit


class AsyncSearchCheckpointTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.registry = self.root / "registry.json"
        self.checkpoint = self.root / "checkpoint.json"
        self.plan = build_plan({"case_id": "case-1", "features": ["轴承"]})
        self.unit_id = self.plan["search_units"][0]["unit_id"]
        self.provider = Mock()
        self.provider.name = "fixture-provider"
        self.provider.submit.side_effect = ["task-1", "task-2"]
        self.provider.get_status.return_value = "running"

    def run_search(self, **kwargs):
        options = {"registry_path": self.registry, **kwargs}
        return run_async_search_unit(
            self.plan, self.unit_id, self.provider, self.checkpoint, **options,
        )

    def tasks(self):
        return json.loads(self.registry.read_text(encoding="utf-8"))["tasks"]

    def save_first_page(self, task_id, checkpoint, progress):
        self.assertEqual((task_id, checkpoint, progress), ("task-1", self.checkpoint, 0))
        checkpoint.write_text('["doc-1"]', encoding="utf-8")
        yield 1
        raise TimeoutError("download interrupted")

    def test_submission_immediately_persists_all_five_fields(self):
        query = "轴承\n检索"
        record = self.run_search(query=query)
        saved, = self.tasks()
        expected = {
            "provider": "fixture-provider",
            "remote_task_id": "task-1",
            "query_sha256": hashlib.sha256('"轴承\\u000a检索"'.encode("utf-8")).hexdigest(),
            "checkpoint_path": str(self.checkpoint),
            "progress": 0,
        }
        self.assertEqual({key: saved[key] for key in expected}, expected)
        self.assertEqual(saved, record)
        self.assertEqual(saved["status"], "submitted")
        self.provider.submit.assert_called_once_with(query)
        self.provider.get_status.assert_not_called()
        self.assertNotIn("轴承", self.registry.read_text(encoding="utf-8"))

    def test_timeout_resumes_original_task_and_continues_saved_progress(self):
        first = self.run_search()
        self.provider.resume.side_effect = self.save_first_page
        interrupted = self.run_search()
        self.assertEqual((interrupted["status"], interrupted["progress"]), ("unknown", 1))

        def finish(task_id, checkpoint, progress):
            self.assertEqual((task_id, checkpoint, progress), ("task-1", self.checkpoint, 1))
            results = json.loads(checkpoint.read_text(encoding="utf-8"))
            self.assertEqual(results, ["doc-1"])
            checkpoint.write_text(json.dumps(results + ["doc-2"]), encoding="utf-8")
            yield 2

        self.provider.reset_mock()
        self.provider.get_status.return_value = "completed"
        self.provider.resume.side_effect = finish
        resumed = self.run_search()
        self.assertEqual(
            self.provider.mock_calls,
            [call.get_status("task-1"), call.resume("task-1", self.checkpoint, 1)],
        )
        self.assertEqual(resumed["record_id"], first["record_id"])
        self.assertEqual((resumed["status"], self.tasks()[0]["progress"]), ("completed", 2))
        self.assertEqual(json.loads(self.checkpoint.read_text()), ["doc-1", "doc-2"])

    def test_unknown_status_preserves_results_and_creates_no_task_file(self):
        self.run_search()
        self.provider.resume.side_effect = self.save_first_page
        self.run_search()
        filenames = set(self.root.iterdir())
        saved_checkpoint = self.checkpoint.read_bytes()
        self.provider.get_status.return_value = "unrecognized-provider-status"
        self.provider.resume.reset_mock()

        record = self.run_search(retry_authorized=True)

        self.assertEqual(record["status"], "unknown")
        self.assertEqual(record["progress"], 1)
        self.assertEqual(self.checkpoint.read_bytes(), saved_checkpoint)
        self.assertEqual(set(self.root.iterdir()), filenames)
        self.assertEqual(len(self.tasks()), 1)
        self.provider.resume.assert_not_called()
        self.provider.submit.assert_called_once()

    def test_status_lookup_timeout_also_preserves_original_task(self):
        original = self.run_search()
        self.provider.get_status.side_effect = TimeoutError("status endpoint timed out")
        result = self.run_search(retry_authorized=True)
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["record_id"], original["record_id"])
        self.assertEqual(len(self.tasks()), 1)
        self.provider.get_status.assert_called_once_with("task-1")
        self.provider.submit.assert_called_once()

    def test_confirmed_failure_retries_only_after_authorization_and_links_attempts(self):
        original = self.run_search()
        self.provider.resume.side_effect = self.save_first_page
        self.run_search()
        self.provider.get_status.return_value = "failed"
        failed = self.run_search()
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(len(self.tasks()), 1)
        self.provider.submit.assert_called_once()

        new = self.run_search(retry_authorized=True)
        self.assertEqual(new["remote_task_id"], "task-2")
        self.assertEqual(new["retry_of"], original["record_id"])
        self.assertNotEqual(new["checkpoint_path"], original["checkpoint_path"])
        self.assertEqual(new["progress"], 0)
        self.assertEqual(self.tasks()[0]["progress"], 1)
        self.assertEqual(self.checkpoint.read_text(), '["doc-1"]')
        self.assertEqual(self.tasks(), [failed, new])

    def test_confirmed_missing_task_can_retry_with_authorization(self):
        original = self.run_search()
        self.provider.get_status.return_value = "not_found"
        new = self.run_search(retry_authorized=True)
        self.assertEqual(self.tasks()[0]["status"], "not_found")
        self.assertEqual(new["retry_of"], original["record_id"])
        self.assertEqual(new["remote_task_id"], "task-2")

    def test_lost_submission_receipt_is_not_replayed(self):
        self.provider.submit.side_effect = TimeoutError("response lost")
        first = self.run_search()
        self.assertIsNone(first["remote_task_id"])
        self.assertEqual(first["status"], "unknown")
        self.assertEqual(self.run_search(retry_authorized=True), first)
        self.assertEqual(self.tasks(), [first])
        self.provider.submit.assert_called_once()
        self.provider.get_status.assert_not_called()

    def test_configured_registry_and_skill_directory_default(self):
        with patch.dict(os.environ, {"PATENT_ROUTER_ASYNC_REGISTRY": str(self.registry)}):
            record = self.run_search(registry_path=None)
        self.assertEqual(self.tasks(), [record])
        with patch.dict(os.environ, clear=True):
            self.assertEqual(registry_location(None), DEFAULT_REGISTRY)
        self.assertEqual(DEFAULT_REGISTRY, SCRIPTS.parent / "local-overrides" / ".async-search-tasks.json")

    def test_overlapping_calls_cannot_create_a_second_remote_task(self):
        def submit(query):
            with self.assertRaises(OSError):
                self.run_search(query=query)
            return "task-1"

        self.provider.submit.side_effect = submit
        result = self.run_search()
        self.assertEqual(self.tasks(), [result])
        self.provider.submit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
