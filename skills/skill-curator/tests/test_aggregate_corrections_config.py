import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "aggregate_corrections.py"
DEFAULT_POLICY = {
    "min_signal_count": 3,
    "min_distinct_tasks": 2,
    "max_batch_skills": 2,
    "cooldown_days": 7,
    "require_verified": True,
}


class AggregateCorrectionsConfigTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.output_dir = self.directory / "result"
        self.input = self.directory / "corrections.jsonl"
        signals = [
            {
                "id": f"signal-{index}",
                "skill": "project-matching",
                "rule_key": "scope",
                "task_id": f"task-{index % 2}",
                "summary": "筛选记录",
                "verified": True,
            }
            for index in range(3)
        ]
        self.input.write_text("".join(json.dumps(signal) + "\n" for signal in signals), encoding="utf-8")

    def write_config(self, path, threshold):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"evolution:\n  correction_batch:\n    min_signal_count: {threshold}\n",
            encoding="utf-8",
        )
        return path

    def aggregate(self, *options):
        result = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "--input", str(self.input),
             "--output-dir", str(self.output_dir), *options],
            capture_output=True, text=True, encoding="utf-8", cwd=self.directory, env={},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads((self.output_dir / "evolution-batch.json").read_text(encoding="utf-8"))

    def test_reads_bundled_defaults_without_environment_or_config_argument(self):
        result = self.aggregate()
        self.assertEqual(result["policy"], DEFAULT_POLICY)
        self.assertTrue(result["ready"])

    def test_work_root_config_overrides_packaged_values(self):
        self.write_config(self.directory / "config" / "common.yaml", 4)
        result = self.aggregate("--root", str(self.directory))
        self.assertEqual(result["policy"], {**DEFAULT_POLICY, "min_signal_count": 4})
        self.assertFalse(result["ready"])

    def test_explicit_user_config_takes_precedence(self):
        self.write_config(self.directory / "config" / "common.yaml", 4)
        config = self.write_config(self.directory / "user.yaml", 5)
        result = self.aggregate("--root", str(self.directory), "--config", str(config))
        self.assertEqual(result["policy"], {**DEFAULT_POLICY, "min_signal_count": 5})
        self.assertFalse(result["ready"])
