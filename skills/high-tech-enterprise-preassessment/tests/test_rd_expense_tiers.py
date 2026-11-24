import json
import unittest
from decimal import Decimal
from operator import ge, gt, le, lt
from pathlib import Path


POLICY = Path(__file__).resolve().parents[1] / "references" / "policy-baseline-2026.json"
COMPARISONS = {"gt": gt, "gte": ge, "lt": lt, "lte": le}


class RDExpenseTierTest(unittest.TestCase):
    def assert_tier(self, revenue, expected_tier, expected_ratio):
        policy = json.loads(POLICY.read_text(encoding="utf-8"), parse_float=Decimal)
        rule = next(item for item in policy["conditions"] if item["rule_id"] == "hnte-rd-expense-ratio")
        matches = []
        for number, tier in enumerate(rule["tiers"], 1):
            comparisons = []
            for bound in ("revenue_lower", "revenue_upper"):
                if bound not in tier:
                    continue
                operator = tier.get(f"{bound}_operator")
                self.assertIn(operator, COMPARISONS, f"第 {number} 档缺有效比较符 {bound}_operator")
                comparisons.append(COMPARISONS[operator](Decimal(revenue), tier[bound]))
            if all(comparisons):
                matches.append((number, tier["ratio"]))
        self.assertEqual(matches, [(expected_tier, Decimal(expected_ratio))])

    def test_4999_99_hits_first_tier(self):
        self.assert_tier("4999.99", 1, "0.05")

    def test_5000_hits_first_tier(self):
        self.assert_tier("5000", 1, "0.05")

    def test_5000_01_hits_second_tier(self):
        self.assert_tier("5000.01", 2, "0.04")

    def test_19999_99_hits_second_tier(self):
        self.assert_tier("19999.99", 2, "0.04")

    def test_20000_hits_second_tier(self):
        self.assert_tier("20000", 2, "0.04")

    def test_20000_01_hits_third_tier(self):
        self.assert_tier("20000.01", 3, "0.03")
