from app.deliverable_contract import (
    build_delivery_contract,
    validate_delivery_contract,
)


def test_report_contract_blocks_workbuddy_from_silently_omitting_required_parts():
    deliverable = {
        "task_type": "analysis-report",
        "skill_template": {
            "skill_id": "enterprise-checkup",
            "template_id": "enterprise-analysis-v2",
            "template_version": "2.0",
            "template_hash": "sha256:abc",
            "required_sections": ["事实数据", "判断建议"],
        },
        "sections": {"事实数据": "已有内容", "判断建议": "已有内容"},
    }
    contract = build_delivery_contract("生成企业分析报告", deliverable)
    audit = validate_delivery_contract(deliverable, contract)

    assert contract["requires_peer_comparison"] is True
    assert contract["requires_four_question_review"] is True
    assert audit["status"] == "needs-revision"
    assert "peer_comparison.peers" in audit["missing_items"]
    assert "least_certain" in audit["missing_items"]
    assert audit["completion_allowed"] is False
    assert audit["repair_plan"]["status"] == "repair-required"
    assert audit["repair_plan"]["blocking_task_count"] == len(
        audit["failures"]
    )
    peer_task = next(
        task
        for task in audit["repair_plan"]["tasks"]
        if task["failure_code"] == "missing-peer-evidence"
    )
    assert peer_task["target_path"] == "peer_comparison.peers"
    assert "政府认定或公示名单" in peer_task["preferred_sources"]
    assert peer_task["acceptance_criteria"]


def test_complete_report_contract_passes_with_policy_fallback_trace():
    deliverable = {
        "task_type": "project-feasibility-report",
        "skill_template": {
            "skill_id": "gov-project-feasibility",
            "template_id": "feasibility-v1",
            "template_version": "1.0",
            "template_hash": "sha256:def",
            "required_sections": ["项目结论", "政策依据"],
        },
        "sections": {"项目结论": "可准备", "政策依据": "现行管理办法"},
        "policy_selection": {
            "status": "management-baseline-only",
            "selected_documents": [{"title": "现行管理办法"}],
            "prohibited_claims": [],
        },
        "peer_comparison": {
            "peers": [{"name": "同行A", "source_url": "https://gov.cn/a"}],
            "dimensions": ["技术", "市场"],
        },
        "four_question_review": {
            "least_certain": "当年度通知尚未发布。",
            "largest_omission": "企业研发台账尚未取得。",
            "most_valuable_innovation": "增加政策变化影响模拟。",
            "efficiency_improvement": "复用内容哈希。",
        },
    }
    audit = validate_delivery_contract(
        deliverable,
        build_delivery_contract("形成项目可行性报告", deliverable),
    )

    assert audit["status"] == "passed"
    assert audit["completion_allowed"] is True
    assert audit["repair_plan"]["status"] == "not-needed"
    assert audit["repair_plan"]["task_count"] == 0


def test_formal_application_omits_peer_gate_unless_explicitly_requested():
    deliverable = {
        "task_type": "formal-application-report",
        "policy_selection": {
            "status": "management-baseline-only",
            "selected_documents": [{"source_url": "https://example.gov.cn/a"}],
            "prohibited_claims": [],
        },
        "four_question_review": {
            "least_certain": "申报系统字段尚未发布。",
            "largest_omission": "企业附件尚未全部回填。",
            "most_valuable_innovation": "增加模板字段映射审计。",
            "efficiency_improvement": "按模板哈希复用底稿。",
        },
    }
    contract = build_delivery_contract("请撰写正式申请书", deliverable)

    assert contract["requires_peer_comparison"] is False
    assert validate_delivery_contract(deliverable, contract)[
        "completion_allowed"
    ] is True
