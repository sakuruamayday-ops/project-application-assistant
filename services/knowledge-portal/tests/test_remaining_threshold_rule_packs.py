from __future__ import annotations

import json
from pathlib import Path

from app.project_decision import select_project_algorithm_rules


PORTAL_DIR = Path(__file__).resolve().parents[1]
PACK_DIR = PORTAL_DIR / "references" / "project-algorithm-packs"
SOURCE_DIR = PORTAL_DIR / "references" / "project-algorithm-rule-sources"


def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def pack(project_id: str) -> dict[str, object]:
    return load_json(PACK_DIR / f"{project_id}.json")


def rule_map(
    project_id: str,
    *,
    year: int | None = None,
    application_type: str = "recognition",
) -> dict[str, dict[str, object]]:
    selected = select_project_algorithm_rules(
        pack(project_id),
        {
            "year": year or "",
            "application_type": application_type,
        },
    )
    return {
        str(rule["rule_id"]): rule
        for rule in selected["rules"]
        if isinstance(rule, dict)
    }


def test_all_twenty_nine_projects_have_auditable_formal_rule_sources():
    packs = [load_json(path) for path in sorted(PACK_DIR.glob("*.json"))]
    sources = [load_json(path) for path in sorted(SOURCE_DIR.glob("*.json"))]

    assert len(packs) == 29
    assert len(sources) == 29
    assert all(item["coverage_status"] == "rules-confirmed" for item in packs)
    assert {item["project_id"] for item in packs} == {
        item["project_id"] for item in sources
    }
    assert all(item["rules"] for item in sources)
    assert all(
        rule["source_quote"]
        for item in sources
        for rule in item["rules"]
    )


def test_hidden_champion_2026_thresholds_and_review_exception_are_separated():
    recognition = rule_map("zhejiang-hidden-champion", year=2026)
    review = rule_map(
        "zhejiang-hidden-champion",
        year=2026,
        application_type="review",
    )

    assert recognition["hidden-debt-ratio"]["expected"] == 75
    assert recognition["hidden-invention"]["expected"] == 4
    assert recognition["hidden-profit-growth"]["expected"] == 10
    assert "hidden-review-operation" not in recognition

    assert "hidden-profit-growth" not in review
    assert review["hidden-review-debt"]["expected"] == 75
    assert review["hidden-review-invention"]["expected"] == 4


def test_annual_only_2025_rules_do_not_leak_into_2026_current_decisions():
    assert rule_map("first-material-batch", year=2026) == {}
    assert rule_map("first-software-version", year=2026) == {}
    assert rule_map("zhejiang-manufacturing-quality", year=2026) == {}
    assert rule_map("first-material-batch", year=2025)
    assert rule_map("first-software-version", year=2025)
    assert rule_map("zhejiang-manufacturing-quality", year=2025)


def test_zhejiang_enterprise_technology_center_uses_native_branch_rules():
    rules = rule_map("zhejiang-enterprise-technology-center", year=2026)

    for rule_id, fact_field in (
        ("zj-tech-center-2", "zj_tech_center_revenue_value"),
        ("zj-tech-center-3", "zj_tech_center_equipment_value"),
        ("zj-tech-center-5", "zj_tech_center_staff_value"),
    ):
        rule = rules[rule_id]
        assert rule["logic"] == "any"
        assert len(rule["children"]) == 4
        assert any(
            child.get("field") == fact_field
            for branch in rule["children"]
            for child in branch["children"]
        )
    assert rules["zj-tech-center-4"]["field"] == (
        "zj_tech_center_applicable_rnd_ratio_assessment_passed"
    )


def test_key_provincial_specialized_sme_2026_hard_thresholds():
    rules = rule_map("zhejiang-key-specialized-sme", year=2026)

    assert rules["key-zj-sme-investment"]["expected"] == 1000
    assert rules["key-zj-sme-rnd-ratio"]["expected"] == 3
    assert rules["key-zj-sme-rnd-expense"]["expected"] == 300
    assert rules["key-zj-sme-ip"]["expected"] == 2
    assert rules["key-zj-sme-debt"]["expected"] == 100


def test_zhejiang_single_champion_uses_current_2025_method_and_2026_overlay():
    rules = rule_map("manufacturing-single-champion-1", year=2026)

    assert "zj-single-champion-3" in rules
    assert "zj-single-champion-4" in rules
    assert "zj-single-champion-2026-one-product" in rules
