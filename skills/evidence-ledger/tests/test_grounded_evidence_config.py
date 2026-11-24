import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import grounded_evidence
from grounded_evidence import DELIVERY_CONFIG_PATH, load_delivery_config


class GroundedEvidenceConfigTest(unittest.TestCase):
    def test_reads_report_registry_from_packaged_runtime(self):
        self.assertEqual(DELIVERY_CONFIG_PATH, SKILL_ROOT.parent / "_runtime" / "report-skill-registry.json")
        config = load_delivery_config()
        self.assertEqual(config["profiles"]["analysis-report"]["source_placement"], "end-section")
        self.assertEqual(config["profiles"]["analysis-report"]["source_title"], "数据来源")


class GroundedEvidenceConfigPathTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.runtime = root / "_runtime" / "report-skill-registry.json"
        self.legacy = root / "report-skill-registry.json"
        config_patch = patch.multiple(
            grounded_evidence, SKILLS_ROOT=root, DELIVERY_CONFIG_PATH=self.runtime,
        )
        config_patch.start()
        self.addCleanup(config_patch.stop)

    def write_config(self, path, profile):
        value = {"schema_version": 1, "profiles": {profile: {}}}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")
        return value

    def test_reads_runtime_registry(self):
        expected = self.write_config(self.runtime, "runtime")
        self.assertEqual(load_delivery_config(), expected)

    def test_falls_back_to_legacy_registry(self):
        expected = self.write_config(self.legacy, "legacy")
        self.assertEqual(load_delivery_config(), expected)

    def test_prefers_runtime_registry_when_both_exist(self):
        expected = self.write_config(self.runtime, "runtime")
        self.write_config(self.legacy, "legacy")
        self.assertEqual(load_delivery_config(), expected)

    def test_missing_registry_lists_both_paths(self):
        with self.assertRaises(FileNotFoundError) as error:
            load_delivery_config()
        self.assertIn(str(self.runtime), str(error.exception))
        self.assertIn(str(self.legacy), str(error.exception))
