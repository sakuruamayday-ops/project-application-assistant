import importlib.util
import json
from pathlib import Path

from app.green_factory_policy import (
    EXPECTED_ADMINISTRATIVE_UNITS,
    expand_green_factory_context_regions,
    load_four_city_green_factory_registry,
    resolve_green_factory_registration,
    validate_four_city_green_factory_registry,
)
from app.project_decision import select_project_algorithm_rules


PORTAL_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PORTAL_DIR / "scripts" / "manage_project_algorithm_packs.py"
SPEC = importlib.util.spec_from_file_location(
    "green_factory_pack_manager",
    SCRIPT_PATH,
)
assert SPEC and SPEC.loader
MANAGER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MANAGER)


def generated_pack(tmp_path: Path, project_id: str) -> dict[str, object]:
    output = tmp_path / f"{project_id}.json"
    MANAGER.generate_from_confirmed_rules(
        input_path=(
            PORTAL_DIR
            / "references"
            / "project-algorithm-rule-sources"
            / f"{project_id}.json"
        ),
        output_path=output,
        fact_contract_path=(
            PORTAL_DIR / "references" / "lifecycle-fact-contract.json"
        ),
    )
    return json.loads(output.read_text(encoding="utf-8"))


def test_four_city_green_factory_registry_closes_all_38_units():
    registry = load_four_city_green_factory_registry()

    assert validate_four_city_green_factory_registry(registry) == []
    assert registry["coverage_summary"] == {
        "city_count": 4,
        "administrative_unit_count": 38,
        "district_recognition_units": 13,
        "district_three_star_units": 10,
        "municipal_redirect_units": 15,
        "unresolved_units": 0,
    }
    assert sum(
        len(units)
        for units in EXPECTED_ADMINISTRATIVE_UNITS.values()
    ) == 38


def test_each_registered_district_resolves_to_audited_formal_sources():
    registry = load_four_city_green_factory_registry()

    for city, districts in EXPECTED_ADMINISTRATIVE_UNITS.items():
        for district in districts:
            resolved = resolve_green_factory_registration(
                district,
                registry,
            )
            assert resolved["status"] == "resolved"
            assert resolved["city"] == city
            assert resolved["formal_sources"]
            assert all(
                source.get("official_url")
                or source.get("archive_sha256")
                for source in resolved["formal_sources"]
            )


def test_citywide_rules_expand_a_district_only_context_to_its_parent_city():
    assert expand_green_factory_context_regions(["滨江区"]) == [
        "滨江区",
        "杭州市",
    ]
    assert expand_green_factory_context_regions(["金东区"]) == [
        "金东区",
        "金华市",
    ]


def test_hangzhou_and_ningbo_district_routes_use_local_formal_rules(
    tmp_path,
):
    pack = generated_pack(tmp_path, "green-factory-1")

    for district, expected_layer in (
        ("滨江区", "green-factory-1-hangzhou-district-route"),
        ("鄞州区", "green-factory-1-ningbo-district-route"),
    ):
        selected = select_project_algorithm_rules(
            pack,
            {
                "evaluation_mode": "current-assessment",
                "jurisdiction": district,
            },
        )
        assert selected["policy_time"]["status"] == "allowed"
        assert selected["project_route"]["status"] == "direct"
        assert selected["selected_layers"] == [expected_layer]
        assert len(selected["rules"]) == 6
        assert {
            rule["_policy_source_scope_level"]
            for rule in selected["rules"]
        } == {"city"}


def test_shaoxing_and_jinhua_district_queries_redirect_to_municipal_project(
    tmp_path,
):
    pack = generated_pack(tmp_path, "green-factory-1")

    for district, city in (
        ("越城区", "绍兴市"),
        ("金东区", "金华市"),
    ):
        selected = select_project_algorithm_rules(
            pack,
            {
                "evaluation_mode": "current-assessment",
                "jurisdiction": district,
            },
        )
        assert selected["rules"] == []
        assert selected["policy_time"]["status"] == (
            "jurisdiction-project-redirect"
        )
        assert selected["policy_time"]["formal_conclusion_allowed"] is False
        assert selected["project_route"]["target_project_id"] == (
            "green-factory-2"
        )
        assert selected["project_route"]["source_scope_region"] == city


def test_municipal_pack_resolves_all_38_district_contexts_without_province(
    tmp_path,
):
    pack = generated_pack(tmp_path, "green-factory-2")

    for districts in EXPECTED_ADMINISTRATIVE_UNITS.values():
        for district in districts:
            selected = select_project_algorithm_rules(
                pack,
                {
                    "evaluation_mode": "current-assessment",
                    "jurisdiction": district,
                },
            )
            assert selected["policy_time"]["status"] == "allowed"
            assert len(selected["rules"]) == 6
            assert {
                rule["_policy_source_scope_level"]
                for rule in selected["rules"]
            } == {"city"}
