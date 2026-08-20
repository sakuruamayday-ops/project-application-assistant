import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"


def load(name: str) -> dict:
    return json.loads((SKILLS / name).read_text(encoding="utf-8"))


def test_curated_catalog_is_a_small_business_outcome_layer_over_formal_skills():
    suite = load("suite-manifest.json")
    catalog = load("curated-skill-catalog.json")
    formal = set(suite["skills"])
    entries = catalog["entries"]

    assert catalog["schema_version"] == "gongchuang-curated-skill-catalog/v1"
    assert catalog["release_tag"] == suite["release"]["tag"]
    assert catalog["title"] == "共创精选"
    assert catalog["subtitle"] == "为中小企业探路点灯"
    assert 8 <= len(entries) <= 16
    assert len({item["id"] for item in entries}) == len(entries)
    assert all(item["skills"] for item in entries)
    assert all(set(item["skills"]) <= formal for item in entries)

    names = {item["name"] for item in entries}
    assert {
        "企业申报体检",
        "政策检索与项目匹配",
        "高新技术企业申报",
        "专精特新与小巨人",
        "知识产权与专利工作台",
        "材料核稿与一致性门禁",
    } <= names


def test_community_sources_browse_directly_but_install_only_after_local_review():
    catalog = load("curated-skill-catalog.json")
    sources = {item["id"]: item for item in catalog["community_sources"]}
    policy = catalog["external_install_policy"]

    assert sources["modelscope"]["url"] == "https://modelscope.cn/skills"
    assert sources["skillhub"]["url"] == "https://skillhub.cn"
    assert policy["direct_install_without_review"] is False
    assert "license" in policy["required_checks"]
    assert "network-and-command-review" in policy["required_checks"]


def test_client_runtime_contract_makes_hooks_host_enforced_and_fail_closed():
    suite = load("suite-manifest.json")
    contract = load("client-runtime-gates.json")
    points = {item["point"]: item for item in contract["lifecycle"]}

    assert contract["release_tag"] == suite["release"]["tag"]
    assert contract["enforcement"]["mode"] == "fail-closed"
    assert contract["enforcement"]["owner"] == "signed-desktop-host-plus-native-cordis-plugin"
    assert contract["enforcement"]["model_compliance_is_not_enforcement"] is True
    assert contract["dsh_hook_compatibility"]["trusted_enforcement_boundary"] is False
    assert {
        item["component"] for item in contract["enforcement_components"]
    } == {
        "signed-desktop-host",
        "native-cordis-policy-gate",
        "central-tool-broker",
        "artifact-delivery-gate",
    }
    assert points["session-start"]["blocking"] is True
    assert points["user-prompt-submit"]["blocking"] is True
    assert points["skill-activation"]["blocking"] is True
    assert points["tool-pre-execute"]["blocking"] is True
    assert points["turn-stopping"]["blocking"] is True
    assert "use-awaited-agent-pre-step-for-first-request-gating" in next(
        item["responsibility"]
        for item in contract["enforcement_components"]
        if item["component"] == "native-cordis-policy-gate"
    )
    assert "windows-and-macos-produce-equivalent-decisions" in contract["mandatory_regressions"]


def test_client_runtime_contract_preserves_professional_skills_across_providers():
    contract = load("client-runtime-gates.json")
    professional = contract["professional_execution"]

    assert professional["binding"] == "same-host-verified-skill-suite"
    assert professional["contract_files"] == [
        "delivery-contracts.json",
        "skill-call-graph.json",
    ]
    assert professional["provider_independent"] is True
    assert professional["unmatched_business_task"] == (
        "require-project-task-router-and-refuse-generic-fallback"
    )
    assert {
        "SKILL.md",
        "references",
        "scripts",
        "templates-and-assets",
        "tests-and-machine-validators",
    } == set(professional["skill_is_execution_bundle"])
    assert professional["humanizer_order"][-1] == "rerun-consistency-check"
    assert "load-every-required-skill" in professional["required_chain"]
    assert "validate-exact-candidate-with-local-professional-kernel" in professional["required_chain"]
    assert "bind-final-chat-answer-to-validated-candidate-sha256" in professional["required_chain"]
    assert "validate-required-response-structure-in-contract-order" in professional["required_chain"]
