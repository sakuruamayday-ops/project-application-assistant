import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "skills/first-run-configuration/scripts/manage_preferences.py"
)
SPEC = importlib.util.spec_from_file_location("manage_preferences", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class PreferenceTests(unittest.TestCase):
    def test_three_way_merge_combines_independent_changes(self):
        base = {"output": {"tone": "professional"}, "region": {"city": "杭州"}}
        local = {"output": {"tone": "concise"}, "region": {"city": "杭州"}}
        remote = {"output": {"tone": "professional"}, "region": {"city": "宁波"}}
        merged, conflicts = MODULE.merge_three_way(base, local, remote)
        self.assertEqual(conflicts, [])
        self.assertEqual(merged["output"]["tone"], "concise")
        self.assertEqual(merged["region"]["city"], "宁波")

    def test_three_way_merge_reports_same_field_conflict(self):
        merged, conflicts = MODULE.merge_three_way(
            {"output": {"tone": "professional"}},
            {"output": {"tone": "concise"}},
            {"output": {"tone": "formal"}},
        )
        self.assertEqual(merged["output"]["tone"], "concise")
        self.assertEqual(conflicts[0]["path"], "output.tone")

    def test_local_file_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preferences.json"
            MODULE.write_local(path, {"preferences": {}})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
