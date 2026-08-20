"""Regression coverage for the V1.6.7 minimal professional-report prompts."""

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
CONTRACT = SKILLS / "delivery-contracts.json"
REGISTRY = SKILLS / "project-feasibility/references/report-template-registry.json"
CALL_GRAPH = SKILLS / "skill-call-graph.json"

PROJECT_REQUESTS = (
    ("高企", "high-tech-enterprise", "高企双报告"),
    ("专精特新", "specialized-sme", "专精特新双报告"),
    ("小巨人", "little-giant", "小巨人双报告"),
    ("首台套", "first-equipment", "首台套双报告"),
    ("首批次", "first-material", "首批次双报告"),
    ("首版次", "first-software", "首版次双报告"),
    ("研发中心", "enterprise-rd-center", "研发中心双报告"),
    ("制造精品", "manufacturing-excellence", "制造精品双报告"),
    ("单项冠军", "single-champion", "单项冠军双报告"),
    ("绿色工厂", "green-factory", "绿色工厂双报告"),
    ("智能工厂", "digitalization", "智能工厂双报告"),
    ("科技计划", "science-plan", "科技计划双报告"),
)

PROHIBITED_PREFIX = re.compile(
    r"(?:不得|禁止|不要|无需|不用|不需|不做|不涉及|不计算|不判断|"
    r"不分析|不评估|不生成|不展示|不声称|避免)[^。！？；\n]{0,30}$"
)


def load_contract() -> dict:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def load_rules() -> dict[str, dict]:
    return load_contract()["skills"]


def contains_actionable_marker(prompt: str, marker: str) -> bool:
    """Mirror the first-party client's clause-local negation semantics."""
    offset = 0
    while offset < len(prompt):
        index = prompt.find(marker, offset)
        if index < 0:
            return False
        clause_start = max(
            prompt.rfind("。", 0, index),
            prompt.rfind("！", 0, index),
            prompt.rfind("？", 0, index),
            prompt.rfind("；", 0, index),
            prompt.rfind("\n", 0, index),
        ) + 1
        if not PROHIBITED_PREFIX.search(prompt[clause_start:index]):
            return True
        offset = index + len(marker)
    return False


def matched_skills(prompt: str) -> set[str]:
    return {
        skill
        for skill, rule in load_rules().items()
        if any(
            contains_actionable_marker(prompt, marker)
            for marker in rule["applies_when_prompt_contains"]
        )
    }


def test_minimal_report_prompts_are_declared_by_v167_routes() -> None:
    rules = load_rules()
    feasibility = set(rules["project-feasibility"]["applies_when_prompt_contains"])

    assert {
        "前期评估",
        "可行性分析报告",
        "高企评估",
        "专精特新评估",
        "小巨人评估",
        "给公司出报告",
        "给企业出报告",
    } <= feasibility
    assert "出报告" not in feasibility
    assert "双报告" not in feasibility
    assert "中期分析" not in feasibility

    assert {
        "高企前期评估",
        "高企可行性分析",
        "高企双报告",
    } <= set(
        rules["high-tech-enterprise-preassessment"][
            "applies_when_prompt_contains"
        ]
    )
    assert {
        "专精特新双报告",
        "小巨人双报告",
        "专精的前期报告和中期分析",
    } <= set(rules["sme-score-preassessment"]["applies_when_prompt_contains"])
    assert {
        "专精特新企业帮我查",
        "小巨人企业帮我查",
    } <= set(rules["peer-benchmarking"]["applies_when_prompt_contains"])


def test_all_twelve_projects_accept_company_name_without_a_fact_form() -> None:
    domain_markers = set(load_contract()["business_domain_markers"])

    for project, _project_id, _dual_alias in PROJECT_REQUESTS:
        assert project in domain_markers
        for report_request in ("前期评估报告", "可行性分析报告"):
            prompt = f"杭州示例科技有限公司，做{project}{report_request}。"
            assert "现有资料" not in prompt
            assert "project-feasibility" in matched_skills(prompt), (
                project,
                report_request,
            )


def test_all_twelve_safe_dual_report_aliases_map_to_exactly_two_reports() -> None:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    dual = registry["dual_report_requests"]
    project_aliases = dual["project_aliases"]
    expected_ids = {project_id for _project, project_id, _alias in PROJECT_REQUESTS}
    assert set(project_aliases) == expected_ids
    assert dual["report_types"] == ["preassessment", "feasibility"]
    assert set(registry["report_types"]) == {"preassessment", "feasibility"}

    feasibility = set(
        load_rules()["project-feasibility"]["applies_when_prompt_contains"]
    )
    for _project, project_id, preferred_alias in PROJECT_REQUESTS:
        aliases = project_aliases[project_id]
        assert preferred_alias in aliases
        assert set(aliases) <= feasibility
        for alias in aliases:
            prompt = f"杭州示例科技有限公司，出{alias}。"
            assert "project-feasibility" in matched_skills(prompt), alias


def test_legacy_midterm_wording_maps_to_preassessment_plus_feasibility() -> None:
    prompt = "杭州示例科技有限公司，给我专精的前期报告和中期分析。"
    assert {"project-feasibility", "sme-score-preassessment"} <= matched_skills(
        prompt
    )

    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    specialized_aliases = registry["dual_report_requests"]["project_aliases"][
        "specialized-sme"
    ]
    assert "专精的前期报告和中期分析" in specialized_aliases
    assert registry["report_types"]["preassessment"]["label"] == "项目前期评估报告"
    assert (
        registry["report_types"]["feasibility"]["label"]
        == "项目申报可行性分析报告"
    )
    assert "中期报告" not in registry["report_types"]


def test_positive_peer_lookup_and_refusal_boundaries() -> None:
    assert "peer-benchmarking" in matched_skills(
        "做阀门手轮的浙江省专精特新企业帮我查"
    )
    assert {"project-feasibility", "sme-score-preassessment"} <= matched_skills(
        "杭州示例科技有限公司，出专精特新双报告。"
    )

    rejected = (
        "不要做高企前期评估报告。",
        "不生成专精特新双报告。",
        "解释这份报告里的结论。",
        "把这段企业介绍改写得自然一点。",
        "给朋友出报告，写得幽默一点。",
        "解释什么是中期分析。",
    )
    for prompt in rejected:
        assert not matched_skills(prompt), prompt


def test_existing_report_explanation_never_creates_a_new_report() -> None:
    # Loading the business skill for a named existing report is acceptable, but
    # its cross-host instruction must explicitly refuse a new artifact.
    prompt = "解释这份高企前期评估报告的结论。"
    assert "project-feasibility" in matched_skills(prompt)
    skill = (SKILLS / "project-feasibility/SKILL.md").read_text(encoding="utf-8")
    assert "仅解释、摘录或普通改写已有报告时不新建报告" in skill
    assert "不得重新生成两类报告或创建新文件" in skill


def test_cross_host_frontmatter_exposes_colloquial_triggers() -> None:
    feasibility = (SKILLS / "project-feasibility/SKILL.md").read_text(
        encoding="utf-8"
    )
    peer = (SKILLS / "peer-benchmarking/SKILL.md").read_text(encoding="utf-8")
    feasibility_description = feasibility.split("---", 2)[1]
    peer_description = peer.split("---", 2)[1]
    assert "企业名称" in feasibility_description
    assert "前期评估报告" in feasibility_description
    assert "可行性分析报告" in feasibility_description
    assert "双报告" in feasibility_description
    assert "专精特新企业帮我查" in peer_description
    assert "先查本地知识库" in peer_description


def test_peer_lookup_contract_is_local_first_and_web_only_on_fallback() -> None:
    peer_skill = (SKILLS / "peer-benchmarking/SKILL.md").read_text(
        encoding="utf-8"
    )
    local = peer_skill.index("先检索本地知识库")
    local_before_web = peer_skill.index("再进行任何联网检索", local)
    fallback = peer_skill.index("本地知识库未命中、覆盖不足或服务不可用时", local)
    tyc = peer_skill.index("先用天眼查", fallback)
    qcc = peer_skill.index("再用企查查", tyc)
    web = peer_skill.index("最后才调用官方网页或联网搜索", qcc)
    assert local < local_before_web < fallback < tyc < qcc < web

    graph = json.loads(CALL_GRAPH.read_text(encoding="utf-8"))
    assert {
        "from": "peer-benchmarking",
        "to": "local-knowledge-retrieval",
        "type": "requires",
        "reason": "优先从公示、认定和复核名单中提取可追溯同行样本。",
    } in graph["relations"]
