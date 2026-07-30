import json
from pathlib import Path

from app.policy_thresholds import (
    evaluate_threshold_track,
    threshold_track_catalog,
    validate_threshold_registry,
)


PORTAL_DIR = Path(__file__).resolve().parents[1]
REGISTRY_PATH = (
    PORTAL_DIR
    / "references"
    / "four-city-rd-platform-threshold-packs.json"
)


def load_registry():
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def complete_scoring_facts():
    return {
        "annual_revenue_yi": 10,
        "annual_revenue_wan": 100000,
        "annual_rd_expense_ratio": 10,
        "annual_rd_expense_wan": 10000,
        "class_i_ip_count_last_3_years": 20,
        "class_ii_ip_count_last_3_years": 30,
        "research_equipment_original_value_wan": 10000,
        "concentrated_rd_site_area_sqm": 10000,
        "annual_rd_staff_count": 100,
        "annual_rd_staff_ratio": 50,
        "qualified_rd_staff_ratio": 90,
        "ip_advanced_review_score": 5,
        "high_level_talent_review_score": 5,
        "industry_academia_review_score": 10,
        "local_support_review_score": 5,
        "management_system_review_score": 5,
        "construction_plan_review_score": 5,
        "bonus_technology_projects_score": 5,
        "bonus_technology_awards_score": 5,
        "bonus_standards_score": 5,
        "bonus_industry_professor_score": 5,
        "bonus_high_level_talent_score": 5,
        "compliance_clear_from_previous_year": True,
        "enterprise_is_agricultural": False,
        "enterprise_industry_type": "制造业",
        "has_high_tech_enterprise_status": True,
        "has_municipal_or_above_technology_sme_status": False,
        "has_gazelle_star_status": False,
        "has_little_giant_status": False,
        "has_manufacturing_single_champion_status": False,
        "has_independent_legal_person_status": True,
    }


def test_four_city_threshold_registry_is_valid_and_has_six_tracks():
    registry = load_registry()

    assert validate_threshold_registry(registry) == []
    assert sum(
        len(item["tracks"]) for item in registry["city_variants"]
    ) == 6
    assert len(threshold_track_catalog(registry, "宁波市")) == 2
    assert len(threshold_track_catalog(registry, "绍兴市")) == 1
    assert len(threshold_track_catalog(registry, "金华市")) == 1


def test_ningbo_two_score_attachments_are_independently_executable():
    registry = load_registry()
    facts = complete_scoring_facts()

    key = evaluate_threshold_track(
        registry,
        city="宁波市",
        track_id="ningbo-key-enterprise-institute",
        facts=facts,
    )
    center = evaluate_threshold_track(
        registry,
        city="宁波市",
        track_id="ningbo-enterprise-technology-rd-center",
        facts=facts,
    )

    assert key["conclusion"] == "eligible"
    assert center["conclusion"] == "eligible"
    assert key["scoring"]["total_score"] == 110
    assert center["scoring"]["total_score"] == 110
    assert len(key["source_documents"]) == 3
    assert len(center["source_documents"]) == 3


def test_shaoxing_score_attachment_is_leaf_scored_and_missing_review_is_exposed():
    registry = load_registry()
    facts = complete_scoring_facts()
    facts.pop("industry_academia_review_score")

    result = evaluate_threshold_track(
        registry,
        city="绍兴市",
        track_id="shaoxing-enterprise-rd-center",
        facts=facts,
    )

    assert result["conclusion"] == "conditional"
    assert result["scoring"]["status"] == "pending"
    assert "industry_academia_review_score" in result["scoring"][
        "missing_fields"
    ]
    assert result["scoring"]["total_score"] is None


def test_jinhua_filing_measure_has_no_fabricated_score_and_requires_materials():
    registry = load_registry()
    facts = {
        "registered_in_jinhua_years": 2,
        "has_high_tech_enterprise_status": True,
        "has_above_scale_enterprise_status": False,
        "has_technology_sme_status": False,
        "is_university": False,
        "is_research_institute": False,
        "is_medical_institution": False,
        "research_and_financial_systems_sound": True,
        "has_experiment_and_pilot_conditions": True,
        "has_relatively_concentrated_rd_site": True,
        "has_autonomous_intellectual_property": True,
        "full_time_technology_staff_count": 6,
        "full_time_technology_staff_ratio": 10,
        "compliance_clear_last_year": True,
        "filing_application_form_complete": True,
        "construction_plan_complete": False,
        "research_and_financial_system_documents_complete": True,
    }

    result = evaluate_threshold_track(
        registry,
        city="金华市",
        track_id="jinhua-science-technology-rd-center",
        facts=facts,
    )

    assert result["scoring"]["enabled"] is False
    assert result["scoring"]["total_score"] is None
    assert result["conclusion"] == "conditional"
    assert result["submission"]["status"] == "pending"


def test_hangzhou_tracks_delegate_to_existing_policy_time_rule_layers():
    result = evaluate_threshold_track(
        load_registry(),
        city="杭州市",
        track_id="hangzhou-prospective-enterprise-institute",
        facts={},
    )

    assert result["status"] == "delegated"
    assert result["formal_conclusion_allowed"] is False
    assert result["rule_layer_id"] == (
        "hangzhou-enterprise-institute-2026-consultation"
    )
