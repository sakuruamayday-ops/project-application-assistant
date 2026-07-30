import json
from copy import deepcopy
from pathlib import Path

from app.policy_thresholds import validate_threshold_registry
from app.policy_transition import (
    resolve_policy_transition,
    validate_four_city_policy_registry,
)


PORTAL_DIR = Path(__file__).resolve().parents[1]
REGISTRY_PATH = (
    PORTAL_DIR
    / "references"
    / "four-city-rd-platform-policy-registry.json"
)
THRESHOLD_PATH = (
    PORTAL_DIR
    / "references"
    / "four-city-rd-platform-threshold-packs.json"
)


def load_registry():
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def test_four_city_two_family_policy_registry_is_closed():
    registry = load_registry()

    assert validate_four_city_policy_registry(registry) == []
    assert len(registry["cities"]) == 4
    assert all(
        len(family["city_variants"]) == 4
        for family in registry["project_families"]
    )
    rd_family = next(
        family
        for family in registry["project_families"]
        if family["family_id"] == "municipal-enterprise-rd-platform"
    )
    assert rd_family["family_name"] == "市级研发中心（四市属地版）"


def test_rd_platform_routes_only_reference_registered_threshold_tracks():
    registry = load_registry()
    thresholds = json.loads(THRESHOLD_PATH.read_text(encoding="utf-8"))
    assert validate_threshold_registry(thresholds) == []
    track_ids = {
        str(track["track_id"])
        for city in thresholds["city_variants"]
        for track in city["tracks"]
    }
    rd_family = next(
        item
        for item in registry["project_families"]
        if item["family_id"] == "municipal-enterprise-rd-platform"
    )

    assert all(
        set(variant["threshold_track_ids"]) <= track_ids
        for variant in rd_family["city_variants"]
    )


def test_hangzhou_consultation_draft_controls_future_preparation_not_formal_fact():
    registry = load_registry()

    future = resolve_policy_transition(
        registry,
        family_id="municipal-enterprise-rd-platform",
        city="杭州市",
        evaluation_mode="future-preparation",
    )
    current = resolve_policy_transition(
        registry,
        family_id="municipal-enterprise-rd-platform",
        city="杭州市",
        evaluation_mode="current-assessment",
    )

    assert future["primary_policy_status"] == "draft"
    assert "杭州市重点企业研究院" in future["primary_policy"]
    assert future["formal_conclusion_allowed"] is False
    assert "征求意见稿尚未正式生效" in future["mandatory_disclosures"]
    assert current["primary_policy_status"] == "current-until-repealed"
    assert "杭州市企业高新技术研究开发中心管理办法" in current[
        "primary_policy"
    ]
    assert current["formal_conclusion_allowed"] is True


def test_hangzhou_verified_replacement_draft_controls_current_year_pre_application():
    selected = resolve_policy_transition(
        load_registry(),
        family_id="municipal-enterprise-rd-platform",
        city="杭州市",
        evaluation_mode="current-year-preparation",
    )

    assert selected["primary_policy_status"] == "draft"
    assert selected["draft_used_as_preparation_baseline"] is True
    assert selected["output_label"] == "当年申报前准备（征求意见稿）"
    assert selected["formal_conclusion_allowed"] is False
    assert "征求意见稿尚未正式生效" in selected["mandatory_disclosures"]


def test_hangzhou_historical_replay_never_uses_consultation_draft():
    selected = resolve_policy_transition(
        load_registry(),
        family_id="municipal-enterprise-rd-platform",
        city="杭州市",
        evaluation_mode="historical-fact",
    )

    assert selected["primary_policy_status"] == "current-until-repealed"
    assert selected["draft_used_as_preparation_baseline"] is False
    assert selected["old_policy_role"] == "historical-time-point-only"
    assert "征求意见稿" not in selected["primary_policy"]
    assert selected["formal_conclusion_allowed"] is False
    assert selected["output_label"] == "历史时点规则待核验"
    assert "历史回放必须核验目标年度当时有效文件及有效期" in (
        selected["mandatory_disclosures"]
    )


def test_unverified_or_non_replacement_draft_cannot_replace_preparation_baseline():
    registry = deepcopy(load_registry())
    variant = registry["project_families"][1]["city_variants"][0]
    variant.pop("prospective_archive_sha256")
    variant["prospective_verification_status"] = "unverified"
    variant.pop("replacement_signal")
    variant.pop("replaces_formal_policy")

    assert any(
        "已核验来源或明确替代关系" in error
        for error in validate_four_city_policy_registry(registry)
    )
    selected = resolve_policy_transition(
        registry,
        family_id="municipal-enterprise-rd-platform",
        city="杭州市",
        evaluation_mode="current-year-preparation",
    )
    assert selected["draft_used_as_preparation_baseline"] is False
    assert selected["primary_policy_status"] == "current-until-repealed"


def test_non_hex_archive_marker_does_not_count_as_verified_draft():
    registry = deepcopy(load_registry())
    variant = registry["project_families"][1]["city_variants"][0]
    variant["prospective_url"] = "https://example.com/draft"
    variant["prospective_archive_sha256"] = "z" * 64

    assert any(
        "已核验来源或明确替代关系" in error
        for error in validate_four_city_policy_registry(registry)
    )


def test_ningbo_technology_center_routes_to_provincial_instead_of_other_city_rule():
    selected = resolve_policy_transition(
        load_registry(),
        family_id="municipal-enterprise-technology-center",
        city="宁波市",
        evaluation_mode="current-assessment",
    )

    assert selected["route_status"] == "redirect-to-provincial"
    assert selected["canonical_name"] == "浙江省企业技术中心（宁波推荐）"
    assert selected["formal_conclusion_allowed"] is True


def test_shaoxing_rd_platform_uses_2026_revision_not_superseded_2019_rule():
    selected = resolve_policy_transition(
        load_registry(),
        family_id="municipal-enterprise-rd-platform",
        city="绍兴市",
        evaluation_mode="current-assessment",
    )

    assert selected["primary_policy_status"] == "current"
    assert "2026年修订" in selected["primary_policy"]
    assert "2019" not in selected["primary_policy"]
    assert selected["formal_conclusion_allowed"] is True


def test_jinhua_rd_platform_uses_2024_formal_filing_measure():
    selected = resolve_policy_transition(
        load_registry(),
        family_id="municipal-enterprise-rd-platform",
        city="金华市",
        evaluation_mode="current-assessment",
    )

    assert selected["primary_policy_status"] == "current"
    assert "金市科〔2024〕47号" in selected["primary_policy"]
    assert selected["route_status"] == "active-municipal-filing"
