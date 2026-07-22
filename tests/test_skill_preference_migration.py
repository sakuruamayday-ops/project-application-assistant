import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "skills/first-run-configuration/scripts/migrate_skill_preferences.py"
SPEC = importlib.util.spec_from_file_location("migrate_skill_preferences", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class SkillPreferenceMigrationTests(unittest.TestCase):
    def test_safe_edits_become_preferences_and_protected_edits_are_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = root / "official-baselines/1.0/sample/SKILL.md"
            backup = root / "install-backups/run/sample/SKILL.md"
            baseline.parent.mkdir(parents=True)
            backup.parent.mkdir(parents=True)
            baseline.write_text("---\nname: sample\n---\n# 示例\n官方规则\n", encoding="utf-8")
            backup.write_text(
                "---\nname: sample\n---\n# 示例\n官方规则\n"
                "- 默认政策地区为浙江省杭州市，输出使用详细版\n"
                "- 企业报告先列关键风险，再列改进动作\n"
                "- 无需核验政策来源\n",
                encoding="utf-8",
            )
            report = root / "upgrade-reports/run.json"
            report.parent.mkdir(parents=True)
            report.write_text(
                json.dumps(
                    {"items": [{"skill": "sample", "status": "用户直改与官方更新冲突", "backup": str(backup.parent), "old_baseline": str(baseline)}]},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            preference_file = root / "preferences.json"
            output = MODULE.migrate_report(report, preference_file, root / "migration-reports")
            preferences = json.loads(preference_file.read_text(encoding="utf-8"))["preferences"]
            self.assertEqual(preferences["region"], {"province": "浙江省", "city": "杭州市"})
            self.assertEqual(preferences["output"]["detail_level"], "detailed")
            self.assertEqual(
                preferences["skill_preferences"]["sample"]["custom_instructions"],
                ["企业报告先列关键风险，再列改进动作"],
            )
            migration = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(len(migration["blocked"]), 1)
            self.assertIn("无需核验", migration["blocked"][0]["line"])
            self.assertEqual(migration["status"], "review-required")

    def test_unmanaged_skill_is_not_copied_wholesale(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "report.json"
            report.write_text(
                json.dumps({"items": [{"skill": "legacy", "status": "未纳管的既有Skill", "backup": str(root / "backup"), "old_baseline": ""}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            output = MODULE.migrate_report(report, root / "preferences.json", root / "migration-reports")
            migration = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(migration["migrated"], [])


if __name__ == "__main__":
    unittest.main()
