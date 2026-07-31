import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from app.project_decision import (
    select_project_algorithm_rules,
    validate_project_algorithm_pack,
)


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "manage_project_algorithm_packs.py"
)
SPEC = importlib.util.spec_from_file_location(
    "manage_project_algorithm_packs",
    SCRIPT_PATH,
)
assert SPEC and SPEC.loader
MANAGER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MANAGER)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_sync_creates_one_routing_pack_per_unique_project(tmp_path):
    rules_path = tmp_path / "rules.json"
    pack_dir = tmp_path / "packs"
    write_json(
        rules_path,
        {
            "rules": [
                {
                    "id": "technology-sme",
                    "aliases": ["科小"],
                    "targets": ["浙江省科技型中小企业", "国家科技型中小企业"],
                },
                {
                    "id": "little-giant",
                    "aliases": ["小巨人"],
                    "targets": ["专精特新小巨人"],
                },
            ]
        },
    )

    result = MANAGER.sync_packs(
        rules_path=rules_path,
        pack_dir=pack_dir,
        write=True,
    )

    packs = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in pack_dir.glob("*.json")
    ]
    assert result["high_frequency_projects"] == 3
    assert result["covered_after"] == 3
    assert {pack["project_name"] for pack in packs} == {
        "浙江省科技型中小企业",
        "国家科技型中小企业",
        "专精特新小巨人",
    }
    assert all(pack["coverage_status"] == "routing-only" for pack in packs)
    assert all(pack["source_retrieval_rule_ids"] for pack in packs)
    assert all(not validate_project_algorithm_pack(pack) for pack in packs)


def test_generate_requires_audited_current_rules_and_builds_gold_cases(tmp_path):
    input_path = tmp_path / "confirmed.json"
    output_path = tmp_path / "packs" / "test-project.json"
    fact_contract = tmp_path / "facts.json"
    write_json(
        fact_contract,
        {
            "fields": [
                {
                    "field": "annual_revenue",
                    "label": "年度营业收入",
                    "aliases": ["营业收入"],
                    "value_type": "number",
                    "unit": "万元",
                }
            ]
        },
    )
    write_json(
        input_path,
        {
            "project_id": "test-project",
            "project_name": "测试项目",
            "version": "2026.1",
            "aliases": ["测试"],
            "policy_status": "current",
            "approved_by": "测试审核人",
            "approved_at": "2026-07-27 12:00:00",
            "source_url": "https://example.gov.cn/policy",
            "rules": [
                {
                    "rule_id": "revenue-minimum",
                    "type": "hard-threshold",
                    "field": "annual_revenue",
                    "operator": "gte",
                    "expected": 1000,
                    "unit": "万元",
                    "source": "测试政策",
                    "source_quote": "年度营业收入不低于一千万元。",
                }
            ],
        },
    )

    result = MANAGER.generate_from_confirmed_rules(
        input_path=input_path,
        output_path=output_path,
        fact_contract_path=fact_contract,
    )
    pack = json.loads(output_path.read_text(encoding="utf-8"))

    assert result["rules"] == 1
    assert pack["coverage_status"] == "rules-confirmed"
    assert pack["rule_cards"][0]["review_status"] == "confirmed"
    assert pack["rule_layers"][0]["layer_type"] == "stable"
    assert pack["rule_layers"][0]["label"] == "稳定管理办法"
    assert [case["expected_conclusion"] for case in pack["gold_cases"]] == [
        "eligible",
        "conditional",
        "ineligible",
    ]
    assert not validate_project_algorithm_pack(pack)


def test_generate_preserves_rd_family_name_and_jurisdiction_source_contract(
    tmp_path,
):
    portal_dir = Path(__file__).resolve().parents[1]
    sources = portal_dir / "references" / "project-algorithm-rule-sources"
    fact_contract = portal_dir / "references" / "lifecycle-fact-contract.json"

    rd_output = tmp_path / "hangzhou-enterprise-institute.json"
    MANAGER.generate_from_confirmed_rules(
        input_path=sources / "hangzhou-enterprise-institute.json",
        output_path=rd_output,
        fact_contract_path=fact_contract,
    )
    rd_pack = json.loads(rd_output.read_text(encoding="utf-8"))
    assert rd_pack["project_name"] == "市级研发中心（四市属地版）"
    assert "杭州市企业研究院" in rd_pack["aliases"]
    prospective = next(
        layer
        for layer in rd_pack["rule_layers"]
        if layer["layer_type"] == "prospective"
    )
    assert prospective["replacement_signal"] == "explicit-replacement"
    assert prospective["replaces_policy_title"].startswith(
        "《杭州市企业高新技术研究开发中心管理办法》"
    )

    green_output = tmp_path / "green-factory-1.json"
    MANAGER.generate_from_confirmed_rules(
        input_path=sources / "green-factory-1.json",
        output_path=green_output,
        fact_contract_path=fact_contract,
    )
    green_pack = json.loads(green_output.read_text(encoding="utf-8"))
    assert green_pack["jurisdiction_source_contract"][
        "required_for_formal_decision"
    ] is True
    assert green_pack["rule_layers"][0]["source_scope_level"] == "province"
    selected = select_project_algorithm_rules(
        green_pack,
        {
            "evaluation_mode": "current-assessment",
            "city": "杭州市",
            "jurisdiction": "滨江区",
        },
    )
    assert selected["policy_time"]["status"] == "allowed"
    assert selected["selected_layers"] == [
        "green-factory-1-hangzhou-district-route"
    ]
    assert len(selected["rules"]) == 6
    assert {
        rule["_policy_source_scope_level"]
        for rule in selected["rules"]
    } == {"city"}


def test_generate_builds_stable_annual_and_jurisdiction_layers(tmp_path):
    input_path = tmp_path / "confirmed.json"
    output_path = tmp_path / "packs" / "test-project.json"
    fact_contract = tmp_path / "facts.json"
    write_json(
        fact_contract,
        {
            "fields": [
                {
                    "field": "status",
                    "label": "状态",
                    "aliases": ["状态"],
                    "value_type": "boolean",
                }
            ]
        },
    )
    write_json(
        input_path,
        {
            "project_id": "test-project",
            "project_name": "测试项目",
            "policy_status": "current",
            "approved_by": "审核人",
            "approved_at": "2026-07-27 12:00:00",
            "source_url": "https://example.gov.cn/method",
            "rules": [
                {
                    "rule_id": "status-rule",
                    "type": "hard-threshold",
                    "field": "status",
                    "operator": "truthy",
                    "expected": True,
                    "source": "稳定管理办法",
                    "source_quote": "企业状态应符合要求。",
                }
            ],
            "annual_overlays": [
                {
                    "overlay_id": "annual-2026",
                    "year": 2026,
                    "policy_status": "current",
                    "approved_by": "年度审核人",
                    "approved_at": "2026-07-27 13:00:00",
                    "source_url": "https://example.gov.cn/2026-notice",
                    "rules": [
                        {
                            "rule_id": "status-rule",
                            "type": "hard-threshold",
                            "field": "status",
                            "operator": "equals",
                            "expected": "年度有效",
                            "source": "2026年度通知",
                            "source_quote": "本年度状态应为年度有效。",
                        }
                    ],
                }
            ],
            "jurisdiction_overlays": [
                {
                    "overlay_id": "zhejiang-cover",
                    "regions": ["浙江省"],
                    "policy_status": "current",
                    "approved_by": "属地审核人",
                    "approved_at": "2026-07-27 14:00:00",
                    "source_url": "https://example.gov.cn/zhejiang",
                    "rules": [
                        {
                            "rule_id": "local-rule",
                            "type": "submission",
                            "field": "status",
                            "operator": "exists",
                            "expected": True,
                            "source": "浙江实施细则",
                            "source_quote": "应完成属地提交。",
                        }
                    ],
                }
            ],
        },
    )

    MANAGER.generate_from_confirmed_rules(
        input_path=input_path,
        output_path=output_path,
        fact_contract_path=fact_contract,
    )
    pack = json.loads(output_path.read_text(encoding="utf-8"))

    assert [layer["layer_type"] for layer in pack["rule_layers"]] == [
        "stable",
        "annual",
        "jurisdiction",
    ]
    assert pack["rule_layers"][1]["applicability"]["years"] == ["2026"]
    assert pack["rule_layers"][2]["applicability"]["regions"] == ["浙江省"]
    assert not validate_project_algorithm_pack(pack)


def test_generate_preserves_stable_application_type_branch(tmp_path):
    input_path = tmp_path / "confirmed.json"
    output_path = tmp_path / "packs" / "test-project.json"
    fact_contract = tmp_path / "facts.json"
    write_json(
        fact_contract,
        {
            "fields": [
                {
                    "field": "status",
                    "label": "状态",
                    "aliases": ["状态"],
                    "value_type": "boolean",
                }
            ]
        },
    )
    write_json(
        input_path,
        {
            "project_id": "test-project",
            "project_name": "测试项目",
            "policy_status": "current",
            "approved_by": "审核人",
            "approved_at": "2026-07-29 12:00:00",
            "source_url": "https://example.gov.cn/method",
            "stable_applicability": {
                "application_types": ["recognition"],
            },
            "rules": [
                {
                    "rule_id": "status-rule",
                    "type": "hard-threshold",
                    "field": "status",
                    "operator": "truthy",
                    "expected": True,
                    "source": "稳定管理办法",
                    "source_quote": "新认定状态应符合要求。",
                }
            ],
        },
    )

    MANAGER.generate_from_confirmed_rules(
        input_path=input_path,
        output_path=output_path,
        fact_contract_path=fact_contract,
    )
    pack = json.loads(output_path.read_text(encoding="utf-8"))

    assert pack["rule_layers"][0]["applicability"] == {
        "application_types": ["recognition"]
    }
    assert not validate_project_algorithm_pack(pack)


def test_generate_allows_confirmed_historical_annual_replay_layer(tmp_path):
    input_path = tmp_path / "confirmed.json"
    output_path = tmp_path / "packs" / "test-project.json"
    fact_contract = tmp_path / "facts.json"
    write_json(
        fact_contract,
        {
            "fields": [
                {
                    "field": "status",
                    "label": "状态",
                    "aliases": ["状态"],
                    "value_type": "boolean",
                }
            ]
        },
    )
    write_json(
        input_path,
        {
            "project_id": "test-project",
            "project_name": "测试项目",
            "policy_status": "current",
            "approved_by": "审核人",
            "approved_at": "2026-07-30 00:00:00",
            "source_url": "https://example.gov.cn/method",
            "rules": [
                {
                    "rule_id": "status-rule",
                    "type": "hard-threshold",
                    "field": "status",
                    "operator": "truthy",
                    "expected": True,
                    "source": "稳定管理办法",
                    "source_quote": "状态应符合要求。",
                }
            ],
            "annual_overlays": [
                {
                    "overlay_id": "annual-2025",
                    "year": 2025,
                    "policy_status": "historical_reference",
                    "approved_by": "审核人",
                    "approved_at": "2026-07-30 00:00:00",
                    "source_url": "https://example.gov.cn/2025-notice",
                    "rules": [
                        {
                            "rule_id": "status-rule",
                            "type": "hard-threshold",
                            "field": "status",
                            "operator": "falsy",
                            "expected": False,
                            "source": "2025年度通知",
                            "source_quote": "2025年度状态不得为真。",
                        }
                    ],
                }
            ],
        },
    )

    MANAGER.generate_from_confirmed_rules(
        input_path=input_path,
        output_path=output_path,
        fact_contract_path=fact_contract,
    )
    pack = json.loads(output_path.read_text(encoding="utf-8"))

    assert (
        pack["rule_layers"][1]["rules"][0]["policy_status"]
        == "historical_reference"
    )
    assert not validate_project_algorithm_pack(pack)


def test_generate_rejects_historical_policy(tmp_path):
    input_path = tmp_path / "historical.json"
    output_path = tmp_path / "pack.json"
    fact_contract = tmp_path / "facts.json"
    write_json(fact_contract, {"fields": []})
    write_json(
        input_path,
        {
            "project_id": "historical-project",
            "project_name": "历史项目",
            "policy_status": "historical",
            "approved_by": "审核人",
            "approved_at": "2026-07-27 12:00:00",
            "source_url": "https://example.gov.cn/history",
            "rules": [{"rule_id": "r1"}],
        },
    )

    try:
        MANAGER.generate_from_confirmed_rules(
            input_path=input_path,
            output_path=output_path,
            fact_contract_path=fact_contract,
        )
    except ValueError as error:
        assert "仅允许从current政策" in str(error)
    else:
        raise AssertionError("历史政策不得生成正式算法包")


def test_generate_rejects_unclassified_composite_met_leaf(tmp_path):
    input_path = tmp_path / "composite.json"
    output_path = tmp_path / "pack.json"
    fact_contract = tmp_path / "facts.json"
    write_json(
        fact_contract,
        {
            "fields": [
                {
                    "field": "revenue_or_investment_met",
                    "label": "收入或投资达标",
                    "value_type": "boolean",
                }
            ]
        },
    )
    write_json(
        input_path,
        {
            "project_id": "composite-project",
            "project_name": "复合规则项目",
            "policy_status": "current",
            "approved_by": "审核人",
            "approved_at": "2026-07-30 12:00:00",
            "source_url": "https://example.gov.cn/current",
            "fact_fields": [
                {
                    "field": "revenue_or_investment_met",
                    "label": "收入或投资达标",
                    "value_type": "boolean",
                }
            ],
            "rules": [
                {
                    "rule_id": "composite-rule",
                    "field": "revenue_or_investment_met",
                    "operator": "truthy",
                    "expected": True,
                    "source_quote": "营业收入达标或投资达到规定条件。",
                }
            ],
        },
    )

    try:
        MANAGER.generate_from_confirmed_rules(
            input_path=input_path,
            output_path=output_path,
            fact_contract_path=fact_contract,
        )
    except ValueError as error:
        assert "未分类综合布尔叶子" in str(error)
    else:
        raise AssertionError("未分类复合规则不得生成正式算法包")


def test_generate_all_rebuilds_each_confirmed_source(tmp_path):
    sources_dir = tmp_path / "sources"
    packs_dir = tmp_path / "packs"
    fact_contract = tmp_path / "facts.json"
    write_json(
        fact_contract,
        {
            "fields": [
                {
                    "field": "status",
                    "label": "状态",
                    "aliases": ["状态"],
                    "value_type": "boolean",
                }
            ]
        },
    )
    for index in (1, 2):
        write_json(
            sources_dir / f"project-{index}.json",
            {
                "project_id": f"project-{index}",
                "project_name": f"项目{index}",
                "policy_status": "current",
                "approved_by": "审核人",
                "approved_at": "2026-07-27 12:00:00",
                "source_url": "https://example.gov.cn/policy",
                "rules": [
                    {
                        "rule_id": f"rule-{index}",
                        "type": "hard-threshold",
                        "field": "status",
                        "operator": "truthy",
                        "expected": True,
                        "source": "现行政策",
                        "source_quote": "状态应符合要求。",
                    }
                ],
            },
        )

    result = MANAGER.generate_all_confirmed_rules(
        sources_dir=sources_dir,
        packs_dir=packs_dir,
        fact_contract_path=fact_contract,
    )

    assert result["generated_packs"] == 2
    assert len(list(packs_dir.glob("*.json"))) == 2
    assert result["coverage"] == {
        "total": 2,
        "rules_confirmed": 2,
        "routing_only": 0,
        "routing_only_projects": [],
    }


def test_priority_queue_orders_routing_packs_by_real_usage(tmp_path):
    database_path = tmp_path / "portal.sqlite3"
    packs_dir = tmp_path / "packs"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE api_usage(
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                project_rule_id TEXT NOT NULL DEFAULT '',
                counts_toward_usage INTEGER NOT NULL DEFAULT 1,
                called_at TEXT NOT NULL
            );
            INSERT INTO api_usage(user_id,project_rule_id,called_at)
            VALUES
              (1,'project-a','2099-01-01T00:00:00+00:00'),
              (2,'project-a','2099-01-01T00:00:00+00:00'),
              (1,'project-b','2099-01-01T00:00:00+00:00');
            """
        )
    for project_id, project_name in (
        ("project-a", "项目甲"),
        ("project-b", "项目乙"),
    ):
        write_json(
            packs_dir / f"{project_id}.json",
            {
                "project_id": project_id,
                "project_name": project_name,
                "coverage_status": "routing-only",
                "source_retrieval_rule_ids": [project_id],
            },
        )

    result = MANAGER.project_priority_queue(
        database_path=database_path,
        packs_dir=packs_dir,
        days=7,
    )

    assert [item["project_name"] for item in result["queue"]] == ["项目甲", "项目乙"]
    assert result["queue"][0]["usage"] == 2
    assert result["queue"][0]["users"] == 2
    assert result["queue"][0]["rank"] == 1


def test_release_validator_blocks_missing_high_frequency_pack(tmp_path):
    rules_path = tmp_path / "rules.json"
    pack_dir = tmp_path / "packs"
    fact_contract = tmp_path / "facts.json"
    write_json(
        rules_path,
        {
            "rules": [
                {
                    "id": "required-project",
                    "aliases": ["必测"],
                    "targets": ["必须覆盖的项目"],
                }
            ]
        },
    )
    write_json(fact_contract, {"fields": []})
    pack_dir.mkdir()

    result = subprocess.run(
        [
            sys.executable,
            str(
                Path(__file__).resolve().parents[1]
                / "scripts"
                / "validate_project_algorithm_packs.py"
            ),
            "--packs-dir",
            str(pack_dir),
            "--fact-contract",
            str(fact_contract),
            "--retrieval-rules",
            str(rules_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    report = json.loads(result.stdout)

    assert result.returncode == 2
    assert report["coverage"] == "incomplete"
    assert report["missing_projects"] == ["必须覆盖的项目"]


def test_release_validator_accepts_renamed_project_through_registered_alias(tmp_path):
    rules_path = tmp_path / "rules.json"
    pack_dir = tmp_path / "packs"
    fact_contract = tmp_path / "facts.json"
    write_json(
        rules_path,
        {
            "rules": [
                {
                    "id": "renamed-project",
                    "aliases": [],
                    "targets": ["旧项目名称"],
                }
            ]
        },
    )
    write_json(fact_contract, {"fields": []})
    pack_dir.mkdir()
    write_json(
        pack_dir / "renamed-project.json",
        {
            "schema_version": 1,
            "project_id": "renamed-project",
            "project_name": "新项目族名称",
            "version": "1.0",
            "coverage_status": "routing-only",
            "aliases": ["旧项目名称"],
            "source_retrieval_rule_ids": ["renamed-project"],
            "fact_fields": [],
            "rule_cards": [],
            "gold_cases": [
                {
                    "case_id": "rules-pending",
                    "facts": [],
                    "confirm_rule_ids": [],
                    "expected_conclusion": "undetermined",
                }
            ],
        },
    )

    result = subprocess.run(
        [
            sys.executable,
            str(
                Path(__file__).resolve().parents[1]
                / "scripts"
                / "validate_project_algorithm_packs.py"
            ),
            "--packs-dir",
            str(pack_dir),
            "--fact-contract",
            str(fact_contract),
            "--retrieval-rules",
            str(rules_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    report = json.loads(result.stdout)

    assert result.returncode == 0
    assert report["coverage"] == "100%"
    assert report["missing_projects"] == []


def test_production_deployment_includes_algorithm_references_and_rollback():
    deploy_script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "deploy_production.sh"
    ).read_text(encoding="utf-8")

    assert "app references templates static" in deploy_script
    assert "scripts/manage_project_algorithm_packs.py" in deploy_script
    assert "scripts/validate_project_algorithm_packs.py" in deploy_script
    assert "jiaotang-kb-release-slots" in deploy_script
    assert "runtime / 'previous'" in deploy_script
    assert "runtime / 'current'" in deploy_script
    assert "应用current已指回previous" in deploy_script
    assert "历史部署备份" in deploy_script
