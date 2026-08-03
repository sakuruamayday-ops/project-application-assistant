from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/three_first_analysis_gold.jsonl"
sys.path.insert(0, str(ROOT / "services/knowledge-portal"))

from app.three_first_routing import plan_three_first_analysis


def subset(actual, expected):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and subset(actual[key], value)
            for key, value in expected.items()
        )
    return actual == expected


def test_three_first_gold_cases():
    cases = [
        json.loads(line)
        for line in FIXTURE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(cases) >= 18
    for case in cases:
        result = plan_three_first_analysis(case["query"], **case.get("inputs", {}))
        expected = {
            key: value
            for key, value in case["expected"].items()
            if key != "clarification_contains"
        }
        assert subset(result, expected), case["id"]
        clarification = case["expected"].get("clarification_contains")
        if clarification:
            assert clarification in result["clarifications"], case["id"]


def test_three_first_combination_keeps_all_projects_and_regions():
    result = plan_three_first_analysis(
        "列出浙江省和江苏省智能水表相关的首台套和首版次产品及企业",
        product_name="智能水表",
        regions=["浙江省", "江苏省"],
    )
    assert result["project_types"] == ["首台套", "首版次"]
    assert result["project_names"] == [
        "浙江省制造业首台（套）装备",
        "浙江省首版次软件产品",
    ]
    assert result["regions"] == ["浙江省", "江苏省"]
    assert result["routes"]["public_list_search"] is True
