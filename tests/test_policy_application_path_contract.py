from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_SKILLS = (
    "project-matching",
    "project-feasibility",
    "sme-score-preassessment",
    "sme-development-projects",
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_contract_references_resolve_to_one_source() -> None:
    import re
    source = ROOT / "skills" / "_runtime" / "policy-application-path-contract.md"
    for skill in CONTRACT_SKILLS:
        pointer = ROOT / "skills" / skill / "references" / source.name
        target = re.search(r"\]\(([^)]+)\)", read(pointer)).group(1)
        assert (pointer.parent / target).resolve() == source
        assert source.is_file()
    import json
    manifest = json.loads(read(ROOT / "skills" / "suite-manifest.json"))
    assert "_runtime/" + source.name in manifest["shared_paths"]


def test_contract_requires_full_path_not_current_priority_only() -> None:
    contract = read(
        ROOT
        / "skills"
        / "_runtime"
        / "policy-application-path-contract.md"
    )
    required = (
        "暂不建议申报",
        "保留一行建设路径",
        "研发机构",
        "绿色工厂",
        "建设后申报",
        "条件触发",
        "长期梯度",
        "十二项",
        "停项条件",
        "重新启动条件",
        "规划参考",
    )
    for phrase in required:
        assert phrase in contract


def test_active_skills_load_or_enforce_contract() -> None:
    for skill in CONTRACT_SKILLS:
        content = read(ROOT / "skills" / skill / "SKILL.md")
        assert "policy-application-path-contract.md" in content

    orchestrator = read(ROOT / "skills" / "project-application-assistant" / "SKILL.md")
    assert "policy-application-path-contract.md" in orchestrator
    assert "相关项目池" in orchestrator
    assert "现状、建设后申报或长期梯度" in orchestrator


def test_sme_preassessment_delivery_contains_policy_route_outputs() -> None:
    content = read(ROOT / "skills" / "sme-score-preassessment" / "SKILL.md")
    required = (
        "后台形成完整池",
        "十二字段路径底稿",
        "研发、绿色、数字化、IP 及质量品牌",
        "前台用一张表列项目",
    )
    for phrase in required:
        assert phrase in content
