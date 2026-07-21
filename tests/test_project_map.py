import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "skills" / "project-matching" / "references" / "project-map.jsonl"
RULES_PATH = ROOT / "skills" / "project-matching" / "references" / "high-frequency-project-rules.jsonl"
CANONICAL_PATH = ROOT / "skills" / "project-matching" / "references" / "canonical-project-index.jsonl"
PROFILE_SCRIPT = ROOT / "skills" / "project-application-assistant" / "scripts" / "user_region_profile.py"
FILTER_SCRIPT = ROOT / "skills" / "project-matching" / "scripts" / "filter_project_map.py"


class ProjectMapTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = [
            json.loads(line)
            for line in MAP_PATH.read_text(encoding="utf-8").splitlines()
        ]

    def test_project_map_is_sanitized_and_unique(self):
        self.assertEqual(len(self.records), 959)
        self.assertEqual(len({record["title"] for record in self.records}), len(self.records))
        self.assertTrue(all("source" not in record for record in self.records))
        self.assertTrue(all("id" not in record for record in self.records))
        self.assertTrue(
            all(
                set(record)
                == {"title", "level", "authority", "category", "category_label", "regions", "primary_region"}
                for record in self.records
            )
        )

    def test_project_map_has_expected_levels(self):
        levels = {record["level"] for record in self.records}
        self.assertEqual(levels, {"国家级", "省级", "市级"})
        self.assertTrue(all(record["regions"] for record in self.records))
        self.assertTrue(all(record["regions"] == ["全国"] for record in self.records if record["level"] == "国家级"))
        self.assertTrue(all(record["primary_region"] == record["regions"][0] for record in self.records))

    def test_high_frequency_rules_use_current_special_rules(self):
        cards = [json.loads(line) for line in RULES_PATH.read_text(encoding="utf-8").splitlines()]
        current = {card["project_name"]: card for card in cards if card["rule_status"] == "current"}
        self.assertIn("专精特新中小企业", current)
        self.assertIn("专精特新小巨人企业", current)
        self.assertIn("浙江省企业研究院", current)
        self.assertIn("浙江省重点企业研究院", current)
        historical = [card for card in cards if card["rule_status"] == "historical-reference"]
        self.assertFalse(any(EXCLUDED_TERM in card["project_name"] for card in historical for EXCLUDED_TERM in ["专精特新", "小巨人", "研发中心", "企业研究院"]))

    def test_high_frequency_rules_are_traceable(self):
        cards = [json.loads(line) for line in RULES_PATH.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(cards), 308)
        self.assertTrue(all(card["official_verification_required"] for card in cards))
        self.assertTrue(all("source" not in card for card in cards))
        self.assertTrue(all("internal_id" not in card for card in cards))

    def test_high_frequency_rules_have_canonical_relationships(self):
        cards = [json.loads(line) for line in RULES_PATH.read_text(encoding="utf-8").splitlines()]
        canonical = {json.loads(line)["canonical_project_name"] for line in CANONICAL_PATH.read_text(encoding="utf-8").splitlines()}
        self.assertTrue(all(card["canonical_project_name"] in canonical for card in cards))
        self.assertTrue(all(card["canonical_relation"] in {"base-map", "high-frequency-extension"} for card in cards))
        self.assertTrue(all(card["condition_fields"] for card in cards))
        self.assertTrue(all(card["condition_schema_version"] == 1 for card in cards))
        first_set = next(card for card in cards if "浙江省】关于组织2025年度首台" in card["project_name"])
        self.assertFalse(first_set["canonical_project_name"].startswith("杭州市"))
        golden_boot = next(card for card in cards if "金靴奔跑" in card["project_name"])
        self.assertEqual(golden_boot["canonical_relation"], "high-frequency-extension")

    def test_region_profile_persists_hierarchy(self):
        with tempfile.TemporaryDirectory() as directory:
            environment = dict(os.environ)
            environment["PROJECT_APPLICATION_ASSISTANT_PROFILE"] = str(Path(directory) / "profile.json")
            subprocess.run([sys.executable, str(PROFILE_SCRIPT), "set", "浙江省杭州市余杭区"], check=True, capture_output=True, text=True, env=environment)
            result = subprocess.run([sys.executable, str(PROFILE_SCRIPT), "get"], check=True, capture_output=True, text=True, env=environment)
            profile = json.loads(result.stdout)
            self.assertEqual(profile["default_region"], "浙江省杭州市")
            self.assertEqual(profile["scope"], ["杭州市", "浙江省", "全国"])

    def test_region_filter_excludes_other_localities(self):
        result = subprocess.run(
            [sys.executable, str(FILTER_SCRIPT), str(CANONICAL_PATH), "--scope", "全国", "--limit", "2000"],
            check=True,
            capture_output=True,
            text=True,
        )
        records = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertTrue(records)
        self.assertTrue(all(record["primary_region"] == "全国" for record in records))
        local = subprocess.run(
            [
                sys.executable,
                str(FILTER_SCRIPT),
                str(CANONICAL_PATH),
                "--scope",
                "余杭区",
                "--scope",
                "杭州市",
                "--scope",
                "浙江省",
                "--scope",
                "全国",
                "--limit",
                "2000",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        local_records = [json.loads(line) for line in local.stdout.splitlines()]
        self.assertTrue(all(record["primary_region"] in {"余杭区", "杭州市", "浙江省", "全国"} for record in local_records))
        self.assertFalse(any(record["primary_region"] == "临平区" for record in local_records))


if __name__ == "__main__":
    unittest.main()
