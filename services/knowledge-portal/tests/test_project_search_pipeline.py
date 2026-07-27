import sqlite3
from contextlib import closing
from datetime import datetime, timedelta

from test_portal import load_app


def test_project_search_plan_expands_year_batch_stage_and_region(tmp_path):
    module = load_app(tmp_path)

    plan = module.project_search_plan("2024年杭州市小巨人名单")

    assert plan["year"] == 2024
    assert plan["batch"] == "第六批"
    assert plan["regions"] == ["杭州市"]
    assert plan["list_intent"] is True
    assert "公示名单" in plan["stages"]
    assert "认定名单" in plan["stages"]
    assert any("第六批" in variant for variant in plan["variants"])
    assert any("认定名单" in variant for variant in plan["variants"])


def test_deadline_parser_prefers_enterprise_deadline_and_counts_down(tmp_path):
    module = load_app(tmp_path)
    now = datetime(2026, 7, 25, 10, 0, tzinfo=module.ASSISTANT_TIMEZONE)
    text = (
        "企业网上申报截止时间为2026年8月5日下午17:00。"
        "各推荐单位审核报送截止时间为2026年8月10日下午17:00。"
    )

    candidates = module.parse_deadline_candidates(text, policy_year=2026, now=now)
    deadline, context, priority = min(candidates, key=lambda item: (item[2], item[0]))

    assert deadline.isoformat() == "2026-08-05T17:00:59+08:00"
    assert "企业网上申报" in context
    assert priority == 0


def test_public_search_runs_fulltext_structured_list_and_deadline_paths(tmp_path):
    content_path = tmp_path / "knowledge-index" / "knowledge_content.sqlite3"
    module = load_app(tmp_path)
    future = datetime.now(module.ASSISTANT_TIMEZONE) + timedelta(days=10)
    deadline_text = future.strftime("%Y年%m月%d日下午17:00")
    updated_at = module.isoformat(module.utc_now())

    with closing(sqlite3.connect(content_path)) as connection:
        connection.execute(
            """
            INSERT INTO documents(
                id,source_key,title,content,source,cloud_path,document_role,sensitivity,
                sha256,updated_at,canonical_project_name,region,document_stage,
                validity_status,policy_year,batch
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                1001,
                "little-giant-notice",
                "2026年第八批专精特新小巨人申报通知",
                f"企业网上申报截止时间为{deadline_text}。",
                "政策与目录/优质中小企业梯度培育/申报通知.pdf",
                "10_政策与目录/优质中小企业梯度培育/申报通知.pdf",
                "10_政策与目录",
                "internal",
                "a" * 64,
                updated_at,
                "国家专精特新“小巨人”企业",
                "杭州市",
                "申报通知",
                "active_candidate",
                2026,
                "第八批",
            ),
        )
        connection.execute(
            """
            INSERT INTO documents(
                id,source_key,title,content,source,cloud_path,document_role,sensitivity,
                sha256,updated_at,canonical_project_name,region,document_stage,
                validity_status,policy_year,batch
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                1002,
                "high-tech-center",
                "2026年高新技术企业研究开发中心申报通知",
                "这是另一个项目。",
                "政策与目录/研发机构/通知.pdf",
                "10_政策与目录/研发机构/通知.pdf",
                "10_政策与目录",
                "internal",
                "b" * 64,
                updated_at,
                "高新技术企业研究开发中心",
                "杭州市",
                "申报通知",
                "active_candidate",
                2026,
                "",
            ),
        )
        connection.execute(
            """
            INSERT INTO public_list_entities(
                document_id,enterprise_name,sequence_no,canonical_project_name,
                policy_year,batch,region,list_status,context,confidence
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                1001,
                "浙江测试制造有限公司",
                "1",
                "国家专精特新“小巨人”企业",
                2026,
                "第八批",
                "杭州市",
                "认定",
                "第八批认定名单",
                "high",
            ),
        )
        connection.execute(
            "INSERT INTO documents_fts_trigram(documents_fts_trigram) VALUES('rebuild')"
        )
        connection.execute("INSERT INTO documents_fts(documents_fts) VALUES('rebuild')")
        connection.commit()

    result = module.public_search_knowledge("2026年杭州市小巨人名单", 8)

    assert result["results"]
    assert all("研究开发中心" not in item["title"] for item in result["results"])
    assert any(
        item["result_type"] == "list_entity"
        and item["enterprise_name"] == "浙江测试制造有限公司"
        for item in result["structured_results"]
    )
    assert result["deadline_reminders"]
    assert "距离截止还有" in result["deadline_reminders"][0]["message"]


def test_growth_path_queries_enable_deadline_reminders(tmp_path):
    module = load_app(tmp_path)

    assert module.deadline_query_relevant("帮我规划这家企业未来五年的项目成长路径")


def test_every_high_frequency_alias_builds_a_resolved_search_plan(tmp_path):
    module = load_app(tmp_path)

    for rule in module.load_project_retrieval_rules():
        expected_targets = {str(target) for target in rule.get("targets", [])}
        for alias in rule.get("aliases", []):
            plan = module.project_search_plan(str(alias))
            assert expected_targets.intersection(plan["targets"]), (
                rule["id"],
                alias,
                plan,
            )
            assert plan["variants"], (rule["id"], alias)


def test_portal_exposes_one_internal_lifecycle_decision_entry(tmp_path):
    module = load_app(tmp_path)

    result = module.enterprise_lifecycle_decision(
        "这家企业能否申报小巨人",
        enterprise_facts=[
            {
                "field": "specialized_sme_status",
                "value": True,
                "evidence_state": "verified",
                "source": "认定名单",
            }
        ],
        project_context={
            "project_id": "little-giant",
            "project_name": "专精特新小巨人",
            "region": "全国",
            "year": 2026,
            "application_type": "recognition",
            "policy_status": "current",
        },
        requirements=[
            {
                "rule_id": "little-giant-prerequisite",
                "type": "hard-threshold",
                "field": "specialized_sme_status",
                "operator": "truthy",
                "expected": True,
                "source": "当期通知",
            }
        ],
    )

    assert result["decision_type"] == "enterprise-project-lifecycle"
    assert result["feasibility"]["overall_conclusion"] == "undetermined"
    assert any(
        gap["field"] == "market_years"
        for gap in result["feasibility"]["evidence_gaps"]
    )
    assert result["scoring"]["enabled"] is False


def test_portal_lifecycle_entry_compiles_materials_and_requires_rule_confirmation(
    tmp_path,
):
    module = load_app(tmp_path)
    arguments = {
        "query": "企业能否申报测试项目",
        "enterprise_facts": [],
        "project_context": {
            "project_id": "test-project",
            "project_name": "测试项目",
            "policy_status": "current",
        },
        "requirements": [],
        "enterprise_materials": [
            {
                "document_type": "audit_report",
                "source": "2025年度审计报告",
                "verified": True,
                "fields": {"营业收入": "6000万元"},
            }
        ],
        "policy_text": "企业上年度营业收入不低于5000万元。",
        "policy_source": "现行政策原文",
        "policy_status": "current",
    }

    candidate_result = module.enterprise_lifecycle_decision(**arguments)
    candidate = candidate_result["policy_rule_compilation"]["reviewed_candidates"][0]
    assert candidate_result["policy_rule_compilation"]["active_rules"] == []
    assert candidate_result["feasibility"]["overall_conclusion"] == "undetermined"

    confirmed_result = module.enterprise_lifecycle_decision(
        **arguments,
        rule_confirmations={candidate["rule_id"]: "confirmed"},
    )
    assert confirmed_result["feasibility"]["overall_conclusion"] == "eligible"


def test_portal_lifecycle_entry_uses_host_extraction_and_project_pack(tmp_path):
    module = load_app(tmp_path)

    result = module.enterprise_lifecycle_decision(
        "这家企业能否申报小巨人",
        enterprise_facts=[],
        project_context={
            "project_id": "little-giant",
            "project_name": "专精特新小巨人",
            "policy_status": "current",
        },
        requirements=[],
        host_extractions=[
            {
                "format": "xlsx",
                "file_name": "官方认定名单.xlsx",
                "document_type": "official_list",
                "verified": True,
                "worksheets": [
                    {
                        "rows": [
                            ["专精特新中小企业", "是"],
                        ]
                    }
                ],
            }
        ],
    )

    assert result["project_algorithm_pack"]["project_id"] == "little-giant"
    assert result["host_extraction"]["materials"][0]["fields"] == {
        "专精特新中小企业": "是"
    }
    assert result["feasibility"]["overall_conclusion"] == "undetermined"
    assert any(
        gate["field"] == "specialized_sme_status"
        and gate["status"] == "passed"
        for gate in result["feasibility"]["hard_gates"]
    )
    assert any(
        gap["field"] == "market_years"
        for gap in result["feasibility"]["evidence_gaps"]
    )
