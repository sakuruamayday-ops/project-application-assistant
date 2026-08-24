import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
CONTRACT = SKILLS / "delivery-contracts.json"


def rules() -> dict[str, dict]:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))["skills"]


def matched_skills(prompt: str) -> set[str]:
    return {
        skill
        for skill, rule in rules().items()
        if any(marker in prompt for marker in rule["applies_when_prompt_contains"])
    }


def test_professional_routes_separate_domain_from_answer_depth() -> None:
    for skill, rule in rules().items():
        assert rule.get("query_marker_groups") == [], skill
        assert rule.get("analysis_marker_groups") == [], skill

    orchestrator = (SKILLS / "project-application-assistant/SKILL.md").read_text(
        encoding="utf-8"
    )
    router = (SKILLS / "project-task-router/SKILL.md").read_text(encoding="utf-8")
    for marker in ("单点查询", "局部分析", "正式交付"):
        assert marker in orchestrator
        assert marker in router
    assert "领域词只决定调用哪个专业技能，不得自动扩大交付范围" in orchestrator


def test_ambiguous_terms_do_not_route_to_unrelated_full_deliverables() -> None:
    cases = {
        "接口设计采用B版，帮我解释这段代码": "enterprise-panorama-analysis",
        "请审核这份普通采购申请书": "sme-development-projects",
        "企业创新能力一般指什么": "high-tech-enterprise-application-drafting",
        "主体核验是什么意思": "enterprise-profile",
    }
    for prompt, forbidden in cases.items():
        assert forbidden not in matched_skills(prompt)


def test_explicit_deliverables_keep_their_professional_routes() -> None:
    cases = {
        "请生成企业全景B版报告": "enterprise-panorama-analysis",
        "请审核专精特新申请书": "sme-development-projects",
        "请撰写高企申请书": "high-tech-enterprise-application-drafting",
        "请做企业主体核验": "enterprise-profile",
        "请出具项目可行性分析报告": "project-feasibility",
    }
    for prompt, expected in cases.items():
        assert expected in matched_skills(prompt)


def test_single_patent_fit_question_stays_on_four_requested_outputs() -> None:
    patent = (SKILLS / "patent-router/SKILL.md").read_text(encoding="utf-8")
    for marker in ("技术关联", "近似专利检索结果", "授权前景", "修改建议"):
        assert marker in patent
    assert "不主动追加“拟申请尚未授权”" in patent
    assert "不启动完整专利案卷、企业画像或项目预评估" in patent
