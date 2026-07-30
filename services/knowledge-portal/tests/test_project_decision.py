import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.project_decision import (
    activate_confirmed_policy_rules,
    audit_delivery_quality,
    build_enterprise_fact_ledger,
    build_growth_path,
    build_lifecycle_decision,
    build_project_decision,
    compile_policy_rule_candidates,
    convert_host_extractions_to_materials,
    evaluate_policy_evidence,
    evaluate_project_feasibility,
    evaluate_requirement,
    extract_enterprise_fact_candidates,
    parse_deadline_candidates,
    select_project_algorithm_rules,
    validate_project_algorithm_pack,
)
from app.policy_time import enrich_policy_time_context


RULES = [
    {
        "id": "technology-sme",
        "aliases": ["科小"],
        "targets": ["浙江省科技型中小企业", "国家科技型中小企业"],
        "selection_required": True,
        "selection_prompt": "请选择浙江省科技型中小企业，还是国家科技型中小企业。",
        "selectors": {
            "浙江": "浙江省科技型中小企业",
            "国家": "国家科技型中小企业",
        },
    },
    {
        "id": "little-giant",
        "aliases": ["小巨人"],
        "targets": ["专精特新小巨人"],
    },
]

PROJECT_RECORDS = [
    {
        "canonical_project_name": "专精特新小巨人",
        "aliases": ["国家专精特新小巨人"],
    },
    {
        "canonical_project_name": "浙江省科技型中小企业",
        "aliases": ["浙江科小"],
    },
    {
        "canonical_project_name": "国家科技型中小企业",
        "aliases": ["国科小"],
    },
]

ALIASES = {
    "小巨人": ["专精特新小巨人"],
    "科小": ["浙江省科技型中小企业", "国家科技型中小企业"],
}


def load_fact_contract() -> list[dict[str, object]]:
    path = (
        Path(__file__).resolve().parents[1]
        / "references"
        / "lifecycle-fact-contract.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))["fields"]


def build(query: str) -> dict[str, object]:
    return build_project_decision(
        query,
        rules=RULES,
        project_records=PROJECT_RECORDS,
        configured_aliases=ALIASES,
    )


def test_decision_maps_year_to_batch_and_builds_multi_path_variants():
    decision = build("2024年浙江省小巨人名单")

    assert decision["year"] == 2024
    assert decision["batch"] == "第六批"
    assert decision["targets"] == ["专精特新小巨人"]
    assert decision["preflight"]["status"] == "ready"
    assert decision["preflight"]["can_start_substantive_work"] is True
    assert decision["list_intent"] is True
    assert decision["retrieval_policy"]["current_policy_only"] is False
    assert any("第六批" in variant for variant in decision["variants"])
    assert any("公示名单" in variant for variant in decision["variants"])


def test_decision_requires_clarification_for_ambiguous_project_alias():
    decision = build("科小申报条件")

    assert decision["clarification"] == (
        "请选择浙江省科技型中小企业，还是国家科技型中小企业。"
    )
    assert decision["targets"] == [
        "浙江省科技型中小企业",
        "国家科技型中小企业",
    ]
    assert decision["preflight"]["status"] == "needs-user-input"
    assert decision["preflight"]["can_start_substantive_work"] is False
    assert decision["preflight"]["blocking_question"] == decision["clarification"]


def test_current_policy_decision_blocks_stale_validity_states():
    decision = build("小巨人申报条件")

    assert decision["retrieval_policy"]["current_policy_only"] is True
    assert decision["retrieval_policy"]["minimum_sme_policy_year"] == 2026
    assert set(decision["retrieval_policy"]["excluded_validity_statuses"]) == {
        "historical_reference",
        "superseded",
        "invalid",
    }


def test_evidence_gate_blocks_stale_and_reviews_draft_or_unverified_content():
    stale = evaluate_policy_evidence({"validity_status": "superseded"})
    draft = evaluate_policy_evidence(
        {
            "validity_status": "draft",
            "official_source_detected": True,
        }
    )
    unverified = evaluate_policy_evidence({"validity_status": "active_candidate"})
    verified = evaluate_policy_evidence(
        {
            "validity_status": "revised",
            "official_source_detected": True,
        }
    )

    assert stale["status"] == "blocked"
    assert draft["status"] == "needs_review"
    assert unverified["status"] == "needs_review"
    assert verified["status"] == "allowed"


def test_deadline_algorithm_distinguishes_enterprise_and_authority_dates():
    now = datetime(2026, 7, 27, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    candidates = parse_deadline_candidates(
        "企业网上申报截止时间为2026年8月5日17:00，"
        "主管部门报送截止时间为2026年8月10日17:00。",
        policy_year=2026,
        now=now,
    )

    priorities = {deadline.day: priority for deadline, _, priority in candidates}
    assert priorities[5] == 0
    assert priorities[10] == 2


def test_lifecycle_gold_standard_cases_are_mechanically_derived():
    path = (
        Path(__file__).resolve().parents[1]
        / "references"
        / "lifecycle-decision-gold-standard.jsonl"
    )
    cases = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    for case in cases:
        result = build_lifecycle_decision(
            case["query"],
            rules=RULES,
            project_records=PROJECT_RECORDS,
            configured_aliases=ALIASES,
            enterprise_facts=case["facts"],
            project_context=case["project_context"],
            requirements=case["requirements"],
        )
        assert result["feasibility"]["overall_conclusion"] == case[
            "expected_conclusion"
        ], case["case_id"]
        assert result["scoring"]["enabled"] is False


def test_fact_ledger_preserves_conflicts_instead_of_silently_choosing_value():
    ledger = build_enterprise_fact_ledger(
        [
            {
                "id": "audit",
                "field": "revenue",
                "value": 5000,
                "evidence_state": "verified",
            },
            {
                "id": "tax",
                "field": "revenue",
                "value": 4800,
                "evidence_state": "verified",
            },
        ]
    )

    assert ledger["resolved"]["revenue"]["evidence_state"] == "conflicting"
    assert ledger["resolved"]["revenue"]["value"] is None
    assert ledger["conflicts"][0]["fact_ids"] == ["audit", "tax"]


def test_growth_path_respects_prerequisites_and_non_quantitative_conclusions():
    path = build_growth_path(
        [
            {
                "project_id": "specialized-sme",
                "project_name": "专精特新中小企业",
                "sequence": 1,
                "overall_conclusion": "conditional",
                "evidence_gaps": [{"field": "revenue"}],
            },
            {
                "project_id": "little-giant",
                "project_name": "专精特新小巨人",
                "sequence": 2,
                "overall_conclusion": "eligible",
                "prerequisite_projects": ["specialized-sme"],
            },
        ]
    )

    assert path[0]["stage"] == "prepare"
    assert path[1]["stage"] == "later"
    assert path[1]["unmet_prerequisites"] == ["specialized-sme"]


def test_delivery_quality_blocks_missing_sections_and_cross_section_conflicts():
    feasibility = evaluate_project_feasibility(
        project_context={
            "project_name": "测试项目",
            "policy_status": "current",
        },
        requirements=[
            {
                "rule_id": "r1",
                "type": "hard-threshold",
                "field": "status",
                "operator": "equals",
                "expected": "正常",
                "source": "现行办法",
            }
        ],
        fact_ledger=build_enterprise_fact_ledger(
            [
                {
                    "field": "status",
                    "value": "正常",
                    "evidence_state": "verified",
                }
            ]
        ),
    )
    quality = audit_delivery_quality(
        {
            "required_sections": ["企业简介", "项目可行性"],
            "sections": {"企业简介": "正文"},
            "consistency_groups": [
                {"name": "主导产品", "values": ["产品A", "产品B"]}
            ],
            "unresolved_claims": 1,
        },
        feasibility=feasibility,
    )

    assert quality["status"] == "blocked"
    assert "缺少必填章节：项目可行性" in quality["blocking_issues"]
    assert "跨章节口径冲突：主导产品" in quality["blocking_issues"]
    assert "仍有1项事实断言未绑定证据" in quality["blocking_issues"]


def test_policy_and_material_compiler_gold_standard():
    path = (
        Path(__file__).resolve().parents[1]
        / "references"
        / "lifecycle-compiler-gold-standard.jsonl"
    )
    cases = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    fact_contract = load_fact_contract()

    for case in cases:
        expected = case["expected"]
        if case["kind"] == "policy":
            candidates = compile_policy_rule_candidates(
                case["text"],
                source="现行政策原文",
                policy_status="current",
                fact_contract=fact_contract,
            )
            candidate = next(
                item for item in candidates if item["field"] == expected["field"]
            )
            assert candidate["operator"] == expected["operator"], case["case_id"]
            assert candidate["expected"] == expected["value"], case["case_id"]
            assert candidate["unit"] == expected["unit"], case["case_id"]
            assert candidate["review_status"] == "candidate"
        else:
            extraction = extract_enterprise_fact_candidates(
                [case["material"]],
                fact_contract=fact_contract,
            )
            fact = next(
                item
                for item in extraction["facts"]
                if item["field"] == expected["field"]
            )
            assert fact["value"] == expected["value"], case["case_id"]
            assert fact["evidence_state"] == expected["evidence_state"], case["case_id"]


def test_unconfirmed_policy_candidate_never_enters_hard_gate():
    candidates = compile_policy_rule_candidates(
        "企业上年度营业收入不低于5000万元。",
        source="现行政策原文",
        policy_status="current",
        fact_contract=load_fact_contract(),
    )

    unconfirmed = activate_confirmed_policy_rules(candidates, {})
    confirmed = activate_confirmed_policy_rules(
        candidates,
        {candidates[0]["rule_id"]: "confirmed"},
    )

    assert unconfirmed["active_rules"] == []
    assert len(confirmed["active_rules"]) == 1


def test_lifecycle_compiler_activates_only_confirmed_rule():
    fact_contract = load_fact_contract()
    policy_text = "企业上年度营业收入不低于5000万元。"
    candidates = compile_policy_rule_candidates(
        policy_text,
        source="现行政策原文",
        policy_status="current",
        fact_contract=fact_contract,
    )
    rule_id = candidates[0]["rule_id"]
    result = build_lifecycle_decision(
        "企业能否申报测试项目",
        rules=RULES,
        project_records=PROJECT_RECORDS,
        configured_aliases=ALIASES,
        enterprise_facts=[],
        project_context={
            "project_id": "test-project",
            "project_name": "测试项目",
            "policy_status": "current",
        },
        requirements=[],
        enterprise_materials=[
            {
                "document_type": "audit_report",
                "source": "2025年度审计报告",
                "period": "2025",
                "verified": True,
                "fields": {"营业收入": "6000万元"},
            }
        ],
        fact_contract=fact_contract,
        policy_text=policy_text,
        policy_source="现行政策原文",
        policy_status="current",
        rule_confirmations={rule_id: "confirmed"},
    )

    assert result["policy_rule_compilation"]["active_rules"][0]["rule_id"] == rule_id
    assert result["feasibility"]["overall_conclusion"] == "eligible"


def test_host_pdf_word_excel_extractions_share_one_material_adapter():
    conversion = convert_host_extractions_to_materials(
        [
            {
                "format": "pdf",
                "file_name": "审计报告.pdf",
                "document_type": "audit_report",
                "pages": [{"text": "营业收入：5000万元"}],
            },
            {
                "format": "docx",
                "file_name": "申请书.docx",
                "document_type": "application_form",
                "paragraphs": ["研发费用占比：3%"],
            },
            {
                "format": "xlsx",
                "file_name": "财务底稿.xlsx",
                "document_type": "financial_statement",
                "verified": True,
                "worksheets": [
                    {
                        "name": "主要指标",
                        "rows": [
                            ["营业收入", "6000万元"],
                            {"字段": "研发费用", "数值": "400万元"},
                        ],
                    }
                ],
            },
        ]
    )

    assert len(conversion["materials"]) == 3
    assert "营业收入：5000万元" in conversion["materials"][0]["text"]
    assert "研发费用占比：3%" in conversion["materials"][1]["text"]
    assert conversion["materials"][2]["fields"] == {
        "营业收入": "6000万元",
        "研发费用": "400万元",
    }


def test_project_algorithm_pack_contract_forbids_new_api_or_mcp_entry():
    valid_pack = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "references"
            / "project-algorithm-packs"
            / "little-giant.json"
        ).read_text(encoding="utf-8")
    )
    assert validate_project_algorithm_pack(valid_pack) == []

    invalid_pack = {**valid_pack, "mcp_url": "https://example.invalid/mcp"}
    assert any(
        "禁止的入口字段" in error
        for error in validate_project_algorithm_pack(invalid_pack)
    )


def test_three_layer_algorithm_selects_and_overrides_by_context():
    pack = {
        "rule_cards": [],
        "rule_layers": [
            {
                "layer_id": "stable-management",
                "layer_type": "stable",
                "applicability": {},
                "rules": [{"rule_id": "shared", "source": "稳定管理办法"}],
            },
            {
                "layer_id": "annual-2026",
                "layer_type": "annual",
                "applicability": {"years": ["2026"]},
                "rules": [{"rule_id": "shared", "source": "2026年度通知"}],
            },
            {
                "layer_id": "zhejiang-cover",
                "layer_type": "jurisdiction",
                "applicability": {"regions": ["浙江省"]},
                "rules": [{"rule_id": "local", "source": "浙江属地细则"}],
            },
        ],
    }

    selected = select_project_algorithm_rules(
        pack,
        {"year": 2026, "province": "浙江省", "city": "杭州市"},
    )
    rules = {rule["rule_id"]: rule for rule in selected["rules"]}

    assert selected["selected_layers"] == [
        "stable-management",
        "annual-2026",
        "zhejiang-cover",
    ]
    assert rules["shared"]["source"] == "2026年度通知"
    assert rules["local"]["source"] == "浙江属地细则"


def test_three_layer_algorithm_ignores_nonmatching_overlays():
    pack = {
        "rule_cards": [],
        "rule_layers": [
            {
                "layer_id": "stable-management",
                "layer_type": "stable",
                "applicability": {},
                "rules": [{"rule_id": "stable"}],
            },
            {
                "layer_id": "annual-2026",
                "layer_type": "annual",
                "applicability": {"years": ["2026"]},
                "rules": [{"rule_id": "annual"}],
            },
            {
                "layer_id": "zhejiang-cover",
                "layer_type": "jurisdiction",
                "applicability": {"regions": ["浙江省"]},
                "rules": [{"rule_id": "local"}],
            },
        ],
    }

    selected = select_project_algorithm_rules(
        pack,
        {"year": 2025, "province": "江苏省"},
    )

    assert selected["selected_layers"] == ["stable-management"]
    assert [rule["rule_id"] for rule in selected["rules"]] == ["stable"]


def test_native_all_any_combinator_supports_nested_tier_rule():
    rule = {
        "rule_id": "research-institute-rnd-tier",
        "type": "hard-threshold",
        "source": "正式管理办法",
        "logic": "any",
        "children": [
            {
                "rule_id": "low-revenue",
                "logic": "all",
                "children": [
                    {
                        "rule_id": "low-band",
                        "field": "revenue",
                        "operator": "lt",
                        "expected": 5000,
                    },
                    {
                        "rule_id": "low-ratio",
                        "field": "rnd_ratio",
                        "operator": "gte",
                        "expected": 5,
                    },
                ],
            },
            {
                "rule_id": "high-revenue",
                "logic": "all",
                "children": [
                    {
                        "rule_id": "high-band",
                        "field": "revenue",
                        "operator": "gte",
                        "expected": 5000,
                    },
                    {
                        "rule_id": "high-route",
                        "logic": "any",
                        "children": [
                            {
                                "rule_id": "high-ratio",
                                "field": "rnd_ratio",
                                "operator": "gte",
                                "expected": 4,
                            },
                            {
                                "rule_id": "high-expense",
                                "field": "rnd_expense",
                                "operator": "gte",
                                "expected": 250,
                            },
                        ],
                    },
                ],
            },
        ],
    }
    ledger = build_enterprise_fact_ledger(
        [
            {
                "field": "revenue",
                "value": 6000,
                "evidence_state": "verified",
                "source": "审计报告",
            },
            {
                "field": "rnd_ratio",
                "value": 3,
                "evidence_state": "verified",
                "source": "专项审计",
            },
            {
                "field": "rnd_expense",
                "value": 250,
                "evidence_state": "verified",
                "source": "专项审计",
            },
        ]
    )

    evaluated = evaluate_requirement(rule, ledger)

    assert evaluated["status"] == "passed"
    assert evaluated["evidence_state"] == "verified"
    assert evaluated["fields"] == ["revenue", "rnd_ratio", "rnd_expense"]


def test_policy_time_checker_blocks_current_rule_from_historical_fact():
    pack = {
        "rule_cards": [],
        "rule_layers": [
            {
                "layer_id": "stable-2025",
                "layer_type": "stable",
                "policy_time_type": "stable-management",
                "effective_from": "2025-01-01",
                "applicability": {},
                "rules": [
                    {
                        "rule_id": "current-rule",
                        "policy_status": "current",
                        "source": "2025年管理办法",
                    }
                ],
            }
        ],
    }

    selected = select_project_algorithm_rules(
        pack,
        {
            "year": 2023,
            "evaluation_mode": "historical-fact",
        },
    )

    assert selected["rules"] == []
    assert selected["policy_time"]["status"] == "blocked"
    assert selected["policy_time"]["formal_conclusion_allowed"] is False


def test_policy_time_checker_labels_current_rule_history_test_as_simulation():
    pack = {
        "rule_cards": [],
        "rule_layers": [
            {
                "layer_id": "stable-2025",
                "layer_type": "stable",
                "policy_time_type": "stable-management",
                "effective_from": "2025-01-01",
                "applicability": {},
                "rules": [
                    {
                        "rule_id": "current-rule",
                        "policy_status": "current",
                        "source": "2025年管理办法",
                    }
                ],
            }
        ],
    }

    selected = select_project_algorithm_rules(
        pack,
        {
            "year": 2023,
            "evaluation_mode": "backtest-simulation",
        },
    )

    assert [rule["rule_id"] for rule in selected["rules"]] == ["current-rule"]
    assert selected["policy_time"]["status"] == "simulation-only"
    assert selected["policy_time"]["output_label"] == "回测模拟"
    assert selected["policy_time"]["formal_conclusion_allowed"] is False


def test_policy_time_query_intent_requires_annual_notice_for_deadline():
    current = enrich_policy_time_context(
        "浙江省高企2026年度申报截止时间是什么时候",
        {"project_name": "高新技术企业", "year": 2026},
    )
    forecast = enrich_policy_time_context(
        "预测下一年度省研究院准备方向",
        {"project_name": "浙江省企业研究院", "year": 2027},
    )
    backtest = enrich_policy_time_context(
        "按最新规则回测2024年的企业数据",
        {"project_name": "浙江省企业研究院", "year": 2024},
    )

    assert current["annual_notice_required"] is True
    assert forecast["evaluation_mode"] == "forecast"
    assert backtest["evaluation_mode"] == "backtest-simulation"


def test_2026_notice_selection_distinguishes_verified_high_tech_from_missing_champion():
    portal_dir = Path(__file__).resolve().parents[1]
    pack_dir = portal_dir / "references" / "project-algorithm-packs"
    high_tech = json.loads(
        (pack_dir / "national-high-tech-enterprise.json").read_text(
            encoding="utf-8"
        )
    )
    selected_high_tech = select_project_algorithm_rules(
        high_tech,
        enrich_policy_time_context(
            "浙江省高企2026年度申报截止时间",
            {
                "project_name": "高新技术企业",
                "region": "浙江省",
                "year": 2026,
            },
        ),
    )
    assert selected_high_tech["policy_time"]["status"] == "allowed"
    annual_layer = next(
        layer
        for layer in high_tech["rule_layers"]
        if layer["layer_id"] == "zhejiang-high-tech-2026"
    )
    assert annual_layer["authority_recommendation_deadline"] == "2026-08-31"
    assert annual_layer["enterprise_deadline"] is None
    assert "地方" in annual_layer["enterprise_deadline_note"]

    champion = json.loads(
        (pack_dir / "manufacturing-single-champion-2.json").read_text(
            encoding="utf-8"
        )
    )
    selected_champion = select_project_algorithm_rules(
        champion,
        enrich_policy_time_context(
            "国家制造业单项冠军2026年度申报通知和截止时间",
            {
                "project_name": "国家制造业单项冠军企业",
                "year": 2026,
            },
        ),
    )
    assert selected_champion["policy_time"]["status"] == "blocked"
    assert selected_champion["policy_time"]["formal_conclusion_allowed"] is False
    assert all(
        "2025" not in layer_id
        for layer_id in selected_champion["selected_layers"]
    )


def test_project_algorithm_pack_gate_runs_all_gold_cases():
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "validate_project_algorithm_packs.py"
    )
    process = subprocess.run(
        [sys.executable, str(script)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert process.returncode == 0, process.stdout
    payload = json.loads(process.stdout)
    assert payload["status"] == "pass"
    assert payload["validated_packs"] >= 1


def test_release_gate_includes_project_algorithm_pack_validation():
    release_gate = (
        Path(__file__).resolve().parents[1] / "scripts" / "release_gate.sh"
    ).read_text(encoding="utf-8")

    assert "validate_project_algorithm_packs.py" in release_gate
