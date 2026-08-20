from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


PREPARE = load_module(
    "prepare_codex_client_harness",
    ROOT / "scripts" / "prepare_codex_client_harness.py",
)


class CodexClientHarnessTests(unittest.TestCase):
    def test_matrix_covers_exact_suite_order_and_four_phases(self):
        suite = json.loads((ROOT / "skills/suite-manifest.json").read_text(encoding="utf-8"))
        matrix = json.loads(
            (ROOT / "tests/codex-client-skill-matrix.json").read_text(encoding="utf-8")
        )
        cases = PREPARE.validate_matrix(matrix, suite["skills"])
        expected_count = len(suite["skills"])
        self.assertEqual(len(cases), expected_count)
        self.assertEqual(sum(4 for _ in cases), expected_count * 4)
        for case in cases:
            prompt = PREPARE.effective_prompt("implicit", case["implicit_prompt"])
            self.assertNotIn(case["skill"], prompt)
            self.assertIn("不读取其他工作区文件", prompt)
        by_skill = {case["skill"]: case for case in cases}
        self.assertEqual(
            by_skill["deep-clarification"]["implicit_expected_behavior"],
            "not_triggered",
        )
        self.assertEqual(
            by_skill["project-rule-manager"]["negative_expected_behavior"],
            "refused_in_scope",
        )
        self.assertEqual(
            by_skill["project-rule-manager"]["negative_expected_skill"],
            "project-rule-manager",
        )
        self.assertNotIn(
            "https://",
            by_skill["web-task-operator"]["functional_prompt"],
        )

    def test_prepare_creates_project_snapshot_and_compression_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            options = type(
                "Options",
                (),
                {
                    "skills_root": str(ROOT / "skills"),
                    "project_root": str(root),
                    "matrix": str(ROOT / "tests/codex-client-skill-matrix.json"),
                    "run_id": "test-run",
                    "replace": False,
                    "materialization": "copy",
                },
            )()
            manifest = PREPARE.prepare(options)
            expected_count = len(
                json.loads((ROOT / "skills/suite-manifest.json").read_text(encoding="utf-8"))["skills"]
            )
            self.assertEqual(manifest["skill_count"], expected_count)
            self.assertEqual(manifest["expected_receipt_count"], expected_count * 4)
            self.assertTrue(manifest["description_budget"]["compression_risk"])
            self.assertEqual(manifest["skill_materialization"], "copy")
            self.assertTrue(
                all(
                    item["tree_sha256"] == item["materialized_tree_sha256"]
                    for item in manifest["skills"]
                )
            )
            self.assertEqual(len(list((root / ".agents/skills").iterdir())), expected_count)
            self.assertTrue(
                all(
                    item.is_dir() and not item.is_symlink()
                    for item in (root / ".agents/skills").iterdir()
                )
            )
            self.assertEqual(
                len(list((root / ".codex-client-harness/runs/test-run/cases").glob("*.json"))),
                expected_count,
            )
            first_case = json.loads(
                next(
                    (root / ".codex-client-harness/runs/test-run/cases").glob("*.json")
                ).read_text(encoding="utf-8")
            )
            artifact_dir = Path(first_case["functional_artifact_dir"])
            self.assertTrue(artifact_dir.is_dir())
            self.assertIn(str(artifact_dir), first_case["effective_prompt"]["functional"])
            self.assertIn(
                "GONGCHUANG_SKILL_DATA_DIR",
                first_case["effective_prompt"]["functional"],
            )
            web_case_path = next(
                (root / ".codex-client-harness/runs/test-run/cases").glob("*-web-task-operator.json")
            )
            web_case = json.loads(web_case_path.read_text(encoding="utf-8"))
            fixture_path = Path(web_case["functional_fixture_path"])
            self.assertTrue(fixture_path.is_file())
            self.assertIn(str(fixture_path), web_case["effective_prompt"]["functional"])
            self.assertNotIn("https://", web_case["effective_prompt"]["functional"])


if __name__ == "__main__":
    unittest.main()
