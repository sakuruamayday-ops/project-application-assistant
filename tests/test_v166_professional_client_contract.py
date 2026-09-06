import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"


def load(name: str) -> dict:
    return json.loads((SKILLS / name).read_text(encoding="utf-8"))


def test_client_professional_routes_cover_identity_hightech_and_humanizer() -> None:
    contract = load("delivery-contracts.json")
    suite = load("suite-manifest.json")
    rules = contract["skills"]

    assert contract["schema_version"] == 3
    assert contract["contract_id"] == "gongchuang-professional-delivery-contract-v3"
    assert contract["rule_version"] == suite["release"]["version"]
    assert {"找同行", "评分", "测评", "体检", "出报告", "生成报告"} <= (
        set(contract["business_domain_markers"])
        | set(contract["peer_task_markers"])
    )
    assert "企业数字身份证" in rules["enterprise-profile"]["applies_when_prompt_contains"]
    assert rules["gongchuang-humanizer-zh"]["required_marker_groups"] == []
    assert {
        "project-feasibility",
        "high-tech-enterprise-application-drafting",
        "sme-score-preassessment",
        "patent-router",
        "financial-verification",
        "standard-drafting",
    } <= set(contract["route_resolution_skills"])
    assert "evidence-ledger" not in contract["route_resolution_skills"]

    hightech = rules["high-tech-enterprise-application-drafting"]
    assert hightech["required_marker_groups"][:4] == [
        ["知识产权对企业竞争力的作用"],
        ["科技成果转化情况"],
        ["研究开发与技术创新组织管理情况"],
        ["管理与科技人员情况"],
    ]


def test_hightech_drafting_has_a_machine_readable_consistency_gate() -> None:
    graph = load("skill-call-graph.json")
    relations = {
        (row["from"], row["to"], row["type"])
        for row in graph["relations"]
    }

    assert (
        "high-tech-enterprise-application-drafting",
        "consistency-check",
        "quality_gate",
    ) in relations
    assert (
        "gongchuang-humanizer-zh",
        "consistency-check",
        "quality_gate",
    ) in relations


def test_sme_chat_and_artifact_contracts_share_the_same_action_heading() -> None:
    contract = load("delivery-contracts.json")
    skill = contract["skills"]["sme-development-projects"]
    profile = contract["delivery_profiles"]["sme-application-checkup-report"]

    # chat 预检和文件画像曾分别要求“整改行动表”与“行动清单”，
    # 导致正文预检通过后才在 DOCX 阶段失败。源合同必须共用标题。
    action_heading = profile["required_sections"][-1]
    assert action_heading == "整改行动表"
    assert [action_heading] in skill["required_marker_groups"]
    assert action_heading in {table["id"] for table in profile["required_tables"]}


def test_natural_language_routes_and_finite_enterprise_source_fallback() -> None:
    contract = load("delivery-contracts.json")
    rules = contract["skills"]
    feasibility = set(rules["project-feasibility"]["applies_when_prompt_contains"])
    assert {"前期评估", "可行性分析报告", "给企业出报告"} <= feasibility
    assert {"专精特新双报告", "小巨人双报告"} <= set(
        rules["sme-score-preassessment"]["applies_when_prompt_contains"]
    )
    peer = set(rules["peer-benchmarking"]["applies_when_prompt_contains"])
    assert {"专精特新企业帮我查", "查专精特新同行"} <= peer

    feasibility_text = (SKILLS / "project-feasibility/SKILL.md").read_text(encoding="utf-8")
    assert "企业名称加项目名和报告意图即可启动" in feasibility_text
    assert "现有资料可同时提供但不是启动前提" in feasibility_text
    assert "企业数据源有限降级协议" in feasibility_text

    peer_text = (SKILLS / "peer-benchmarking/SKILL.md").read_text(encoding="utf-8")
    assert "先检索本地知识库" in peer_text
    assert "企业数据源有限降级协议" in peer_text

    # 数据源顺序集中在共享协议中，避免多个 Skill 各自复制后再次形成无限重试。
    fallback = (SKILLS / "_runtime/enterprise-source-fallback.md").read_text(
        encoding="utf-8"
    )
    assert "天眼查 → 企查查" in fallback
    assert "最多重试一次" in fallback
    assert "不重试，也不再次弹出授权" in fallback
    assert "第二次失败立即转下一来源" in fallback
    assert "不重复调用刷新回执" in fallback


def test_client_runtime_registry_exposes_only_existing_first_party_scripts() -> None:
    suite = load("suite-manifest.json")
    registry = load("client-runtime-operations.json")

    assert "client-runtime-operations.json" in suite["shared_paths"]
    assert registry["schema_version"] == "gongchuang-signed-skill-operations/v1"
    assert registry["skill_bundle_version"] == suite["release"]["version"]
    operations = registry["operations"]
    assert len(operations) >= 8
    assert len({operation["id"] for operation in operations}) == len(operations)
    calculation = next(
        operation
        for operation in operations
        if operation["id"] == "manufacturing-tax-risk-analysis.calculate-metrics"
    )
    assert calculation["stdout_json_schema_version"] == (
        "manufacturing-tax-risk-calculation-operation/v1"
    )
    assert set(calculation["parameters"]) == {
        "input", "financialFactsOutput", "metricsOutput"
    }
    assert calculation["sandbox_mode"] == "workspace-write"
    branding = next(
        operation
        for operation in operations
        if operation["id"] == "evidence-ledger.apply-office-branding"
    )
    assert branding["skill"] == "evidence-ledger"
    assert branding["sandbox_mode"] == "workspace-write"
    assert branding["stdout_json_schema_version"] == (
        "gongchuang-office-branding-operation/v1"
    )
    assert branding["parameters"]["artifact"]["extensions"] == [
        ".docx", ".xlsx", ".xlsm"
    ]
    generation = next(
        operation
        for operation in operations
        if operation["id"] == "evidence-ledger.create-docx"
    )
    assert generation["skill"] == "evidence-ledger"
    assert generation["sandbox_mode"] == "workspace-write"
    assert generation["stdout_json_schema_version"] == (
        "gongchuang-docx-generation-operation/v1"
    )
    assert generation["parameters"]["content"]["max_length"] == 8192
    assert generation["parameters"]["output"]["extensions"] == [".docx"]
    for operation in operations:
        skill = operation["skill"]
        script = operation["script"]
        assert script.startswith(f"{skill}/scripts/")
        assert script.endswith(".py")
        assert (SKILLS / script).is_file()
        for additional_file in operation["files"]:
            assert (SKILLS / additional_file).is_file()
        assert operation["network"] == "none"
        assert operation["sandbox_mode"] in {"read-only", "workspace-write"}
        assert set(operation["passing_exit_codes"]) <= set(operation["result_exit_codes"])
        parameter_names = set(operation["parameters"])
        referenced = {
            argument["parameter"]
            for argument in operation["argv"]
            if "parameter" in argument
        }
        assert parameter_names == referenced
        if operation["sandbox_mode"] == "read-only":
            assert all(
                definition["type"] != "workspace-output-file"
                for definition in operation["parameters"].values()
            )
