import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"


def load(name: str) -> dict:
    return json.loads((SKILLS / name).read_text(encoding="utf-8"))


def test_client_professional_routes_cover_identity_hightech_and_humanizer() -> None:
    contract = load("delivery-contracts.json")
    rules = contract["skills"]

    assert contract["schema_version"] == 3
    assert contract["contract_id"] == "gongchuang-professional-delivery-contract-v3"
    assert contract["rule_version"] == "1.6.14"
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


def test_natural_language_routes_and_local_first_peer_workflow() -> None:
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
    assert feasibility_text.index("天眼查") < feasibility_text.index("企查查")

    peer_text = (SKILLS / "peer-benchmarking/SKILL.md").read_text(encoding="utf-8")
    local = peer_text.index("先检索本地知识库")
    tyc = peer_text.index("先用天眼查", local)
    qcc = peer_text.index("再用企查查", tyc)
    web = peer_text.index("最后才调用官方网页或联网搜索", qcc)
    assert local < tyc < qcc < web


def test_client_runtime_registry_exposes_only_existing_first_party_scripts() -> None:
    suite = load("suite-manifest.json")
    registry = load("client-runtime-operations.json")

    assert "client-runtime-operations.json" in suite["shared_paths"]
    assert registry["schema_version"] == "gongchuang-signed-skill-operations/v1"
    assert registry["skill_bundle_version"] == "1.6.14"
    operations = registry["operations"]
    assert len(operations) >= 8
    assert len({operation["id"] for operation in operations}) == len(operations)
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
