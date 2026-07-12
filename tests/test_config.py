import unittest
from pathlib import Path

from project_assistant.config import deep_merge, load_config, unresolved_environment


ROOT = Path(__file__).resolve().parents[1]


class ConfigTests(unittest.TestCase):
    def test_deep_merge_preserves_common_values(self):
        merged = deep_merge({"a": {"b": 1, "c": 2}}, {"a": {"b": 3}})
        self.assertEqual(merged, {"a": {"b": 3, "c": 2}})

    def test_load_all_platform_configs(self):
        for platform in ("codex", "claude-code", "hermes"):
            config = load_config(ROOT, platform)
            self.assertEqual(config["platform"], platform)
            self.assertEqual(config["product"]["name"], "项目申报助手")

    def test_unresolved_environment_is_reported(self):
        self.assertEqual(unresolved_environment({"path": "${MISSING_TEST_VARIABLE}"}), ["MISSING_TEST_VARIABLE"])


if __name__ == "__main__":
    unittest.main()

