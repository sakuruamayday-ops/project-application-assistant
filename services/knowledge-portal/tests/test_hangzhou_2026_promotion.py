import json
from copy import deepcopy
from pathlib import Path

from app.policy_thresholds import evaluate_threshold_track, validate_threshold_registry
from app.policy_transition_monitor import promote_verified_formal_candidate
from app.policy_transition import resolve_policy_transition

ROOT = Path(__file__).resolve().parents[1] / "references"


def test_live_hangzhou_registry_exposes_annual_source_and_retires_draft():
    result = resolve_policy_transition(
        load("four-city-rd-platform-policy-registry.json"),
        family_id="municipal-enterprise-rd-platform", city="杭州市",
        evaluation_mode="current-assessment")
    assert result["primary_policy_status"] == "current"
    assert result["prospective_policy"] is None
    assert result["applicable_years"] == [2026]
    assert result["verification_status"] == "user-supplied-reviewed"
    assert "转载" in result["source_role"]


def load(name):
    return json.loads((ROOT / name).read_text())


def setup():
    candidate = load("hangzhou-institute-promotion-20260909.json")
    policy = load("four-city-rd-platform-policy-registry.json")
    variant = policy["project_families"][1]["city_variants"][0]
    variant["prospective_policy"] = candidate["replaces_prospective_policy"]
    variant["prospective_policy_status"] = "draft"
    thresholds = load("four-city-rd-platform-threshold-packs.json")
    thresholds["city_variants"][0]["tracks"] = candidate["threshold_tracks"]
    return candidate, policy, thresholds


def test_source_exception_is_exact_and_explicit():
    c, p, t = setup()
    assert promote_verified_formal_candidate(p, t, c)["status"] == "rejected"
    assert promote_verified_formal_candidate(p, t, c, accepted_source_url=c["source_url"] + "x")["status"] == "rejected"
    result = promote_verified_formal_candidate(p, t, c, accepted_source_url=c["source_url"])
    assert result["status"] == "promoted"
    v = result["policy_registry"]["project_families"][1]["city_variants"][0]
    assert v["official_url"] is None
    assert v["verification_status"] == "user-supplied-reviewed"
    assert result["change_set"]["compile_project_ids"] == ["hangzhou-enterprise-institute"]
    incomplete = deepcopy(c)
    incomplete["threshold_tracks"][0]["execution_mode"] = "project-rule-layer"
    assert promote_verified_formal_candidate(p, t, incomplete, accepted_source_url=c["source_url"])["status"] == "rejected"


def basic_facts():
    return dict(hz26_registered_in_hangzhou=True, hz26_independent_legal_entity=True,
        hz26_management_systems=True, hz26_separate_rd_accounting=True,
        hz26_not_seriously_dishonest=True, hz26_valid_technology_sme=True,
        hz26_is_agriculture=False, hz26_is_software=True,
        hz26_rd_staff_previous_year=15, hz26_equipment_eligible_value=50,
        hz26_rd_site_area=100, hz26_rd_expense=100, hz26_rd_expense_ratio=0,
        hz26_ip_i_last3years=1, hz26_system_application_complete=True,
        hz26_authority_compliance_check_complete=True)


def test_basic_institute_boundaries_and_alternative_routes():
    c, p, t = setup()
    assert validate_threshold_registry(t) == []
    def evaluate(facts):
        return evaluate_threshold_track(t, city="杭州市", track_id=c["threshold_tracks"][0]["track_id"], facts=facts)
    facts = basic_facts()
    assert evaluate(facts)["conclusion"] == "eligible"
    facts["hz26_rd_staff_previous_year"] = 14
    assert evaluate(facts)["conclusion"] == "ineligible"
    facts.update(hz26_is_software=False, hz26_is_agriculture=True, hz26_rd_staff_previous_year=10)
    assert evaluate(facts)["conclusion"] == "eligible"
    facts["hz26_is_agriculture"] = False
    assert evaluate(facts)["conclusion"] == "ineligible"
    facts.update(hz26_equipment_eligible_value=100, hz26_rd_expense=0, hz26_rd_expense_ratio=3)
    assert evaluate(facts)["conclusion"] == "eligible"
    facts["hz26_ip_i_last3years"] = 0
    facts["hz26_ip_ii_last3years"] = 3
    assert evaluate(facts)["conclusion"] == "eligible"


def test_score_leaf_completeness_caps_and_agricultural_difference():
    c, p, t = setup()
    for track in c["threshold_tracks"][1:]:
        facts = basic_facts()
        facts["hz26_is_agriculture"] = "agriculture" in track["track_id"]
        facts["hz26_revenue"] = 100000
        facts["hz26_rd_expense"] = 10000
        facts["hz26_rd_expense_ratio"] = 6
        for g in track["score_groups"]:
            for leaf in g["leaves"]:
                if leaf["method"] == "reviewed":
                    facts[leaf["field"]] = leaf["max_score"]
                elif leaf["method"] == "band":
                    facts[leaf["field"]] = max(b["min"] for b in leaf["bands"])
                else:
                    facts[leaf["field"]] = 20
        def evaluate():
            return evaluate_threshold_track(t, city="杭州市", track_id=track["track_id"], facts=facts)
        result = evaluate()
        assert result["scoring"]["total_score"] == 110
        assert result["conclusion"] == "eligible"
        facts.pop("hz26_plan_reviewed_score")
        assert evaluate()["scoring"]["total_score"] is None
        assert evaluate()["conclusion"] == "conditional"
        facts["hz26_plan_reviewed_score"] = 6
        assert evaluate()["scoring"]["total_score"] is None
