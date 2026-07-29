from __future__ import annotations

import json
from pathlib import Path

from app.project_decision import select_project_algorithm_rules
from app.rule_ir import compile_rule_ir


PORTAL_DIR = Path(__file__).resolve().parents[1]
PACK_DIR = PORTAL_DIR / "references" / "project-algorithm-packs"
LIFECYCLE_PATH = PORTAL_DIR / "references" / "enterprise-lifecycle-rules.json"


def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_pack(project_id: str) -> dict[str, object]:
    return load_json(PACK_DIR / f"{project_id}.json")


def selected_rule_map(
    project_id: str,
    *,
    year: int,
    application_type: str,
    region: str = "",
) -> dict[str, dict[str, object]]:
    selected = select_project_algorithm_rules(
        load_pack(project_id),
        {
            "year": year,
            "application_type": application_type,
            "region": region,
        },
    )
    return {
        str(rule["rule_id"]): rule
        for rule in selected["rules"]
        if isinstance(rule, dict)
    }


def test_little_giant_2026_recognition_and_review_use_separate_standards():
    recognition = selected_rule_map(
        "little-giant",
        year=2026,
        application_type="recognition",
    )
    review = selected_rule_map(
        "little-giant",
        year=2026,
        application_type="review",
    )

    assert recognition["little-giant-revenue"]["expected"] == 5000
    assert "little-giant-2026-relationship-exclusion" in recognition
    assert "little-giant-review-main-business-ratio" not in recognition

    assert review["little-giant-review-main-business-ratio"]["expected"] == 70
    assert review["little-giant-review-liability-ratio"]["expected"] == 70
    assert "little-giant-revenue" not in review
    assert "little-giant-revenue-cagr" not in review
    assert "little-giant-quality-score" not in review


def test_missing_application_type_keeps_backward_compatible_recognition_branch():
    selected = select_project_algorithm_rules(
        load_pack("little-giant"),
        {},
    )
    rule_ids = {
        str(rule["rule_id"])
        for rule in selected["rules"]
        if isinstance(rule, dict)
    }

    assert "little-giant-specialized-sme-status" in rule_ids
    assert "little-giant-review-main-business-ratio" not in rule_ids


def test_single_champion_keeps_four_hundred_million_revenue_as_hard_gate():
    rules = selected_rule_map(
        "manufacturing-single-champion-2",
        year=2026,
        application_type="recognition",
    )

    assert rules["single-champion-revenue"]["field"] == (
        "three_year_average_main_business_revenue"
    )
    assert rules["single-champion-revenue"]["operator"] == "gte"
    assert rules["single-champion-revenue"]["expected"] == 40000
    assert rules["single-champion-revenue"]["unit"] == "万元"


def test_green_factory_2025_uses_self_evaluation_and_dynamic_exit_rule():
    recognition = selected_rule_map(
        "green-factory-4",
        year=2025,
        application_type="recognition",
    )
    dynamic = selected_rule_map(
        "green-factory-4",
        year=2025,
        application_type="annual-evaluation",
    )

    assert recognition["national-green-factory-report"]["field"] == (
        "green_self_evaluation_evidence_available"
    )
    assert dynamic["national-green-factory-bottom-five-exit"]["field"] == (
        "green_factory_three_year_bottom_five_percent"
    )


def test_research_institute_platform_is_not_a_hard_gate_and_archive_is_pinned():
    expected_sha256 = (
        "b6b766c57e82ff71faa83301c3acf194a7f8a8c14063a4ae7b1a389e2abb28f9"
    )
    for project_id, platform_rule_id, annual_rule_id in (
        (
            "zhejiang-enterprise-institute",
            "zj-institute-platform",
            "zhejiang-enterprise-institute-2026-data-cutoff",
        ),
        (
            "zhejiang-key-enterprise-institute",
            "zj-key-institute-platform",
            "zhejiang-key-enterprise-institute-2026-data-cutoff",
        ),
    ):
        rules = selected_rule_map(
            project_id,
            year=2026,
            application_type="recognition",
            region="浙江省",
        )
        assert rules[platform_rule_id]["type"] == "competitive"
        assert rules[annual_rule_id]["source_archive_sha256"] == expected_sha256


def test_compiled_ir_resolves_all_confirmed_lifecycle_aliases():
    project_ids = (
        "national-high-tech-enterprise",
        "zhejiang-specialized-sme",
        "little-giant",
        "green-factory-4",
        "zhejiang-enterprise-institute",
        "zhejiang-key-enterprise-institute",
    )
    packs = [load_pack(project_id) for project_id in project_ids]
    lifecycle = load_json(LIFECYCLE_PATH)

    compiled = compile_rule_ir(packs, lifecycle, {"fields": []})

    for project_id in project_ids:
        assert compiled["projects"][project_id]["lifecycle_rule"] is not None
    key_institute = compiled["projects"]["zhejiang-key-enterprise-institute"][
        "lifecycle_rule"
    ]
    assert key_institute["construction_years"] == 3
    assert key_institute["performance_cycle_years"] == 3
    assert key_institute["rectification_years"] == 1
