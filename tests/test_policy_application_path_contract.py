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


def test_contract_copies_are_identical() -> None:
    copies = [
        read(ROOT / "skills" / skill / "references" / "policy-application-path-contract.md")
        for skill in CONTRACT_SKILLS
    ]
    assert len(set(copies)) == 1


def test_contract_requires_full_path_not_current_priority_only() -> None:
    contract = read(
        ROOT
        / "skills"
        / "project-matching"
        / "references"
        / "policy-application-path-contract.md"
    )
    required = (
        "暂不建议申报",
        "不能删除路径",
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
    assert "前期评估政策路径总闸门" in orchestrator
    assert "不得只列当前可申报" in orchestrator
    assert "不是硬门槛" in orchestrator


def test_sme_preassessment_delivery_contains_policy_route_outputs() -> None:
    content = read(ROOT / "skills" / "sme-score-preassessment" / "SKILL.md")
    required = (
        "后台建立完整相关项目池",
        "十二字段路径卡只作内部完整性检查",
        "研发中心、绿色工厂、数字化、知识产权和质量品牌",
        "每项原则上只占一行",
    )
    for phrase in required:
        assert phrase in content
