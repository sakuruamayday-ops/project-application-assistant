"""Regression coverage for the V1.6.7 minimal professional-report prompts."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "skills" / "delivery-contracts.json"


def load_rules() -> dict[str, dict]:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))["skills"]


def matched_skills(prompt: str) -> set[str]:
    return {
        skill
        for skill, rule in load_rules().items()
        if any(marker in prompt for marker in rule["applies_when_prompt_contains"])
    }


def test_minimal_dual_report_prompts_are_declared_by_v166_routes() -> None:
    rules = load_rules()
    feasibility = set(rules["project-feasibility"]["applies_when_prompt_contains"])

    assert {
        "前期评估",
        "可行性分析报告",
        "高企评估",
        "专精特新评估",
        "小巨人评估",
        "专精特新双报告",
        "给公司出报告",
        "给企业出报告",
    } <= feasibility
    assert "出报告" not in feasibility

    assert {
        "高企评估",
        "高企前期评估",
        "高企可行性分析",
    } <= set(rules["high-tech-enterprise-preassessment"]["applies_when_prompt_contains"])
    assert {
        "专精特新评估",
        "专精特新双报告",
        "小巨人评估",
        "小巨人双报告",
    } <= set(rules["sme-score-preassessment"]["applies_when_prompt_contains"])
    assert {
        "专精特新企业帮我查",
        "小巨人企业帮我查",
    } <= set(rules["peer-benchmarking"]["applies_when_prompt_contains"])


def test_minimal_prompt_examples_select_the_expected_professional_routes() -> None:
    assert "peer-benchmarking" in matched_skills("做阀门手轮的浙江省专精特新企业帮我查")
    assert {"project-feasibility", "sme-score-preassessment"} <= matched_skills(
        "杭州示例科技有限公司，现有资料如下，出具专精特新双报告。"
    )
    assert {"project-feasibility", "high-tech-enterprise-preassessment"} <= matched_skills(
        "高企前期评估"
    )
    assert {"project-feasibility", "sme-score-preassessment"} <= matched_skills("小巨人评估")
    assert "project-feasibility" in matched_skills("给公司出报告")
    assert not matched_skills("给朋友出报告，写得幽默一点")


def test_all_twelve_report_types_accept_enterprise_name_and_a_short_report_request() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    domain_markers = set(contract["business_domain_markers"])
    prompts = {
        "高企": "高企前期评估",
        "专精特新": "专精特新前期评估",
        "小巨人": "小巨人前期评估",
        "首台套": "首台套前期评估",
        "首批次": "首批次前期评估",
        "首版次": "首版次前期评估",
        "研发中心": "研发中心前期评估",
        "制造精品": "制造精品前期评估",
        "单项冠军": "单项冠军前期评估",
        "绿色工厂": "绿色工厂前期评估",
        "智能工厂": "智能工厂前期评估",
        "科技计划": "科技计划前期评估",
    }

    assert set(prompts) <= domain_markers
    for project, request in prompts.items():
        prompt = f"杭州示例科技有限公司，现有资料如下，做{request}。"
        assert "project-feasibility" in matched_skills(prompt), project


def test_peer_lookup_is_explicitly_local_knowledge_first() -> None:
    peer_skill = (
        ROOT / "skills" / "peer-benchmarking" / "SKILL.md"
    ).read_text(encoding="utf-8")
    local = peer_skill.index("先检索本地知识库")
    tyc = peer_skill.index("先用天眼查", local)
    qcc = peer_skill.index("再用企查查", tyc)
    web = peer_skill.index("最后才调用官方网页或联网搜索", qcc)
    assert local < tyc < qcc < web
