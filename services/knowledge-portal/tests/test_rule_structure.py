import json
from pathlib import Path

from app.rule_structure import audit_composite_rule_structure


PACK_DIR = (
    Path(__file__).resolve().parents[1]
    / "references"
    / "project-algorithm-packs"
)
SOURCE_DIR = (
    Path(__file__).resolve().parents[1]
    / "references"
    / "project-algorithm-rule-sources"
)


def test_composite_met_leaf_blocks_formal_decision():
    audit = audit_composite_rule_structure(
        {
            "fact_fields": [
                {"field": "revenue_or_investment_met", "value_type": "boolean"}
            ],
            "rule_cards": [
                {
                    "rule_id": "r1",
                    "field": "revenue_or_investment_met",
                    "operator": "truthy",
                    "source_quote": "营业收入达到要求或股权投资达到要求。",
                }
            ],
        }
    )

    assert audit["status"] == "blocked"
    assert audit["unresolved_count"] == 1
    assert audit["formal_decision_allowed"] is False


def test_native_all_any_and_declared_assessment_conclusion_are_allowed():
    audit = audit_composite_rule_structure(
        {
            "fact_fields": [
                {"field": "revenue", "value_type": "number"},
                {"field": "investment", "value_type": "number"},
                {
                    "field": "standard_assessment_met",
                    "value_type": "boolean",
                    "fact_semantics": "assessment-conclusion",
                },
            ],
            "rule_cards": [
                {
                    "rule_id": "route",
                    "logic": "any",
                    "children": [
                        {"rule_id": "revenue", "field": "revenue", "operator": "gte"},
                        {
                            "rule_id": "investment",
                            "field": "investment",
                            "operator": "gte",
                        },
                    ],
                },
                {
                    "rule_id": "assessment",
                    "field": "standard_assessment_met",
                    "operator": "truthy",
                    "source_quote": "按适用评价标准取得合格结论。",
                },
            ],
        }
    )

    assert audit["status"] == "passed"
    assert audit["formal_decision_allowed"] is True


def test_all_29_formal_packs_pass_composite_structure_gate():
    packs = sorted(PACK_DIR.glob("*.json"))

    assert len(packs) == 29
    blocked = {
        path.stem: audit
        for path in packs
        if not (
            audit := audit_composite_rule_structure(
                json.loads(path.read_text(encoding="utf-8"))
            )
        )["formal_decision_allowed"]
    }
    assert blocked == {}


def test_all_29_confirmed_sources_pass_before_pack_generation():
    sources = sorted(SOURCE_DIR.glob("*.json"))

    assert len(sources) == 29
    blocked = {
        path.stem: audit
        for path in sources
        if not (
            audit := audit_composite_rule_structure(
                json.loads(path.read_text(encoding="utf-8"))
            )
        )["formal_decision_allowed"]
    }
    assert blocked == {}
