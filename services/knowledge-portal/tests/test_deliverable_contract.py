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


def _review() -> dict[str, str]:
    return {
        "least_certain": "部分企业内部指标仍待原始材料核对。",
        "largest_omission": "尚未取得客户补充附件。",
        "most_valuable_innovation": "把交付物、表格和品牌审计绑定到同一哈希。",
        "efficiency_improvement": "复用已验证模板和生成器。",
    }


def _trace() -> tuple[list[dict[str, str]], list[dict[str, object]]]:
    sources = [
        {
            "id": "source-1",
            "title": "企业材料",
            "path": "inputs/enterprise-material.pdf",
        }
    ]
    evidence = [
        {
            "claim_id": "enterprise-name",
            "status": "verified",
            "source_ids": ["source-1"],
        }
    ]
    return sources, evidence


def _tables(contract: dict[str, object]) -> dict[str, dict[str, object]]:
    return {
        specification["id"]: {
            "columns": list(specification.get("required_columns") or []),
            "row_count": int(specification.get("min_rows") or 1),
        }
        for specification in contract["required_tables"]
    }


def _artifact(
    *,
    role: str,
    artifact_format: str,
    gate: str,
    digest: str,
) -> dict[str, object]:
    return {
        "role": role,
        "format": artifact_format,
        "path": f"artifacts/{role}.{artifact_format}",
        "sha256": digest,
        "validation": {
            "status": "passed",
            "gate": gate,
            "artifact_sha256": digest,
        },
    }


def test_panorama_standard_profile_blocks_missing_tables_word_and_brand_audit():
    deliverable = {
        "task_type": "analysis-report",
        "skill_id": "enterprise-panorama-analysis",
        "report_variant": "A",
        "sections": {},
        "four_question_review": _review(),
    }
    contract = build_delivery_contract("生成A标准销售版企业全景报告", deliverable)
    audit = validate_delivery_contract(deliverable, contract)

    assert contract["delivery_profile"] == "enterprise-panorama-standard"
    assert contract["branding_contracts"][0]["mode"] == "forbidden"
    assert "同行竞品与行业定位" in contract["required_sections"]
    assert "风险整改表" in audit["missing_items"]
    assert "standard_report" in audit["missing_items"]
    assert any(
        task["target_path"] == "branding_audits.standard_report"
        for task in audit["repair_plan"]["tasks"]
    )
    assert any(
        "不用模型临时重建近似表格" in task["action"]
        for task in audit["repair_plan"]["tasks"]
        if task["target_path"] == "tables.风险整改表"
    )


def test_panorama_standard_profile_accepts_default_word_same_hash_proof():
    digest = "a" * 64
    base = {
        "task_type": "analysis-report",
        "skill_id": "enterprise-panorama-analysis",
        "report_variant": "A",
        "four_question_review": _review(),
        "peer_comparison": {
            "peers": [{"name": "同行A", "source_url": "https://gov.cn/a"}],
            "dimensions": ["研发创新", "项目资质"],
        },
        "policy_selection": {
            "status": "official-original",
            "selected_documents": [{"title": "现行项目政策原文"}],
            "prohibited_claims": [],
        },
    }
    contract = build_delivery_contract("生成A标准销售版企业全景报告", base)
    sources, evidence = _trace()
    deliverable = {
        **base,
        "sections": {
            name: "已按模板生成" for name in contract["required_sections"]
        },
        "sources": sources,
        "evidence_items": evidence,
        "tables": _tables(contract),
        "artifacts": [
            _artifact(
                role="standard_report",
                artifact_format="docx",
                gate="document-render-and-structure-gate",
                digest=digest,
            )
        ],
        "branding_audits": [
            {
                "artifact_role": "standard_report",
                "status": "passed",
                "pages": 18,
                "watermarks": 0,
                "artifact_sha256": digest,
            }
        ],
    }

    audit = validate_delivery_contract(deliverable, contract)
    assert audit["completion_allowed"] is True


def test_tax_report_profile_requires_four_artifacts_and_gold_branding():
    digest = "b" * 64
    base = {
        "task_type": "analysis-report",
        "skill_id": "manufacturing-tax-risk-analysis",
        "four_question_review": _review(),
        "policy_selection": {
            "status": "official-original",
            "selected_documents": [{"title": "现行税收政策"}],
            "prohibited_claims": [],
        },
    }
    contract = build_delivery_contract("生成金税四期分析报告", base)
    sources, evidence = _trace()
    formats = {
        "tax_report_pdf": ("pdf", "delivery_gate.py"),
        "editable_html": ("html", "generate_report_html.py"),
        "metrics_json": ("json", "calculate_metrics.py"),
        "enterprise_financial_facts": (
            "json",
            "enterprise-financial-facts/v1",
        ),
    }
    deliverable = {
        **base,
        "sections": {
            name: "已完成" for name in contract["required_sections"]
        },
        "sources": sources,
        "evidence_items": evidence,
        "tables": _tables(contract),
        "artifacts": [
            _artifact(
                role=role,
                artifact_format=artifact_format,
                gate=gate,
                digest=digest,
            )
            for role, (artifact_format, gate) in formats.items()
        ],
        "branding_audits": [
            {
                "artifact_role": "tax_report_pdf",
                "status": "passed",
                "variant": "gold",
                "pages": 17,
                "watermarks": 17,
                "centered": True,
                "artifact_sha256": digest,
            }
        ],
    }
    audit = validate_delivery_contract(deliverable, contract)

    assert contract["delivery_profile"] == "manufacturing-tax-risk-report"
    assert audit["completion_allowed"] is True

    deliverable["branding_audits"][0]["watermarks"] = 16
    blocked = validate_delivery_contract(deliverable, contract)
    assert "tax_report_pdf" in blocked["missing_items"]
    assert any(
        item["code"] == "branding-audit-not-passed"
        for item in blocked["failures"]
    )


def test_sme_pre_and_post_profiles_bind_current_tables_and_validators():
    preflight = build_delivery_contract(
        "生成2026年专精特新前期预评估报告",
        {
            "skill_id": "sme-score-preassessment",
            "task_type": "analysis-report",
        },
    )
    postflight = build_delivery_contract(
        "生成专精特新后期体检报告",
        {
            "skill_id": "sme-development-projects",
            "task_type": "analysis-report",
        },
    )

    assert preflight["delivery_profile"] == "sme-score-preassessment-workbook"
    assert [item["id"] for item in preflight["required_tables"]] == [
        "项目申报路径图",
    ]
    assert preflight["required_artifacts"] == []
    assert (
        postflight["delivery_profile"]
        == "sme-application-checkup-report"
    )
    assert {
        item["validation_gate"] for item in postflight["required_artifacts"]
    } == {
        "validate_sme_assessment.py",
        "document-render-and-structure-gate",
    }


def test_panorama_profile_refuses_to_guess_a_or_b():
    deliverable = {
        "task_type": "analysis-report",
        "skill_id": "enterprise-panorama-analysis",
    }
    audit = validate_delivery_contract(
        deliverable,
        build_delivery_contract("生成企业全景报告", deliverable),
    )

    assert any(
        item["code"] == "missing-delivery-profile"
        for item in audit["failures"]
    )
    task = next(
        item
        for item in audit["repair_plan"]["tasks"]
        if item["failure_code"] == "missing-delivery-profile"
    )
    assert "不得由模型自行替用户选择" in task["acceptance_criteria"][1]


def test_patent_filing_ready_profile_requires_manifest_and_same_hash_artifacts():
    deliverable = {
        "task_type": "formal-application-report",
        "skill_id": "patent-router",
        "case_mode": "filing-ready",
        "sections": {},
        "four_question_review": _review(),
    }
    contract = build_delivery_contract("形成完整发明专利申请案卷", deliverable)
    audit = validate_delivery_contract(deliverable, contract)

    assert contract["delivery_profile"] == "patent-application-case"
    assert contract["requires_peer_comparison"] is False
    assert contract["requires_policy_selection_trace"] is False
    assert {
        item["role"] for item in contract["required_artifacts"]
    } == {
        "patent_case_manifest",
        "patent_application_docx",
        "claim_prior_art_matrix",
        "submission_checklist",
    }
    assert "patent_case_manifest" in audit["missing_items"]
    manifest_task = next(
        item
        for item in audit["repair_plan"]["tasks"]
        if item["target_path"] == "artifacts.patent_case_manifest"
    )
    assert manifest_task["blocking"] is True
    assert manifest_task["acceptance_criteria"]


def test_patent_router_without_filing_mode_keeps_narrow_tasks_unprofiled():
    contract = build_delivery_contract(
        "只做一次现有技术检索",
        {
            "task_type": "general-response",
            "skill_id": "patent-router",
        },
    )

    assert contract["delivery_profile"] == ""
    assert contract["delivery_profile_error"] == ""
