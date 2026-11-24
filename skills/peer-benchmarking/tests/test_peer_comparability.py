import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from classify_peers import classify


class PeerComparabilityTests(unittest.TestCase):
    target = {"project": "省级专精特新", "batch": "2026复核"}
    comparable = {**target, "product_relation": "same", "product_source": "产品说明第1页",
                  "recognition_source": "认定名单第2行"}

    def test_requires_all_three_comparability_factors(self):
        rows = [self.comparable, {**self.comparable, "project": "小巨人"},
                {**self.comparable, "batch": "2023认定"},
                {**self.comparable, "recognition_source": ""},
                {**self.comparable, "product_source": ""}]
        self.assertEqual([r["decision"] for r in classify(self.target, rows)],
                         ["include", "background", "background", "needs-evidence", "needs-evidence"])

    def test_recognition_stage_is_kept_in_the_primary_group(self):
        formal, proposed, no_evidence = classify(self.target, [
            {**self.comparable, "recognition_stage": "正式认定"},
            {**self.comparable, "recognition_stage": "拟认定"},
            {**self.comparable, "recognition_stage": "拟认定", "recognition_source": ""},
        ])
        self.assertEqual((formal["decision"], formal["group"], formal["group_label"]),
                         ("include", "直接组", "正式认定"))
        self.assertEqual((proposed["decision"], proposed["group"], proposed["group_label"]),
                         ("include", "拟认定/公示", "拟认定"))
        self.assertEqual(proposed["recognition_stage"], "拟认定")
        self.assertEqual(no_evidence["decision"], "needs-evidence")

    def test_frozen_bakery_scope_from_application(self):
        rows = [
            {"product_relation": "broader", "product_source": "B01 T01R68",
             "product": "综合冷冻烘焙业务，含麻薯和挞皮"},
            {"product_relation": "different", "product_source": "B01 T01R92",
             "product": "即烤冷冻蛋挞成品"},
        ]
        results = classify(self.target, rows)
        self.assertEqual([(r["product_source"], r["decision"]) for r in results],
                         [("B01 T01R68", "background"), ("B01 T01R92", "exclude")])
