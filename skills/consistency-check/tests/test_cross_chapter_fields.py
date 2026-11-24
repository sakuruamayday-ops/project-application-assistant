import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from cross_chapter_fields import field_findings, text_observations


class CrossChapterTests(unittest.TestCase):
    def test_same_year_compares_values_and_returns_both_sections(self):
        text = (
            "# 一、发展情况\nP007 2025年营收100万元\n"
            "# 二、财务摘要\nT02R03 2025年营业收入90万元\n"
            "T02R04 2024年营业收入80万元\n"
            "T02R05 2025年销售收入90万元"
        )
        findings = list(field_findings(text_observations(text, "表A")))
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["field"], "营业收入")
        self.assertEqual([(r["chapter"], r["position"]) for r in findings[0]["observations"]],
                         [("一、发展情况", "P007"), ("二、财务摘要", "T02R03")])

    def test_common_unit_compares_same_subject_and_scope_only(self):
        row = {"subject": "样本", "period": "2025", "scope": "单体", "field": "营业收入",
               "source": "A", "chapter": "财务摘要", "position": "B2", "value": "100", "unit": "万元"}
        aligned = {**row, "source": "B", "chapter": "利润表", "value": "1000000", "unit": "元"}
        other = {**row, "source": "C", "scope": "合并", "value": "20"}
        self.assertEqual(list(field_findings([row, aligned, other])), [])
