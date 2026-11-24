import json
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from validate_report_profile_delivery import _load_delivery_contract


class DeliveryContractPathTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.runtime = self.root / "skills" / "_runtime" / "delivery-contracts.json"
        self.legacy = self.root / "skills" / "delivery-contracts.json"

    def write_contract(self, path, profile_id):
        value = {"delivery_profiles": {profile_id: {}}}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")
        return value

    def test_reads_runtime_contract(self):
        expected = self.write_contract(self.runtime, "runtime")
        self.assertEqual(_load_delivery_contract(self.root), expected)

    def test_falls_back_to_legacy_contract(self):
        expected = self.write_contract(self.legacy, "legacy")
        self.assertEqual(_load_delivery_contract(self.root), expected)

    def test_prefers_runtime_contract_when_both_exist(self):
        expected = self.write_contract(self.runtime, "runtime")
        self.write_contract(self.legacy, "legacy")
        self.assertEqual(_load_delivery_contract(self.root), expected)

    def test_missing_contract_lists_both_paths(self):
        with self.assertRaises(FileNotFoundError) as error:
            _load_delivery_contract(self.root)
        self.assertIn(str(self.runtime), str(error.exception))
        self.assertIn(str(self.legacy), str(error.exception))
