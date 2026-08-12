from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "sme-score-preassessment"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_sme_preassessment_uses_four_part_presale_report() -> None:
    skill = read(SKILL_DIR / "SKILL.md")
    contract = read(
        SKILL_DIR / "references" / "pre-sale-assessment-report-contract.md"
    )

    required = (
        "总结结论",
        "项目申报路径图",
        "补短板主导产品与专利",
        "财务情况分析",
        "五至八页",
        "一至两页",
    )
    for phrase in required:
        assert phrase in skill or phrase in contract


def test_visible_project_path_is_compact_but_complete() -> None:
    contract = read(
        SKILL_DIR / "references" / "pre-sale-assessment-report-contract.md"
    )
    for column in (
        "申报项目",
        "建议年度",
        "核心申报条件",
        "企业现有值",
        "差距状态",
        "下一步",
    ):
        assert column in contract

    assert "每个项目原则上一行" in contract
    assert "不展开成专项方案" in contract
    assert "不把每个项目展开为十二字段路径卡" in contract


def test_missing_data_and_verified_absence_are_distinguished() -> None:
    contract = read(
        SKILL_DIR / "references" / "pre-sale-assessment-report-contract.md"
    )
    assert "企业值单元格可以留空" in contract
    assert "待定" in contract
    assert "待补强" in contract
    assert "已经明确检索、核对或询问" in contract
    assert "冲突待核" in contract


def test_product_patent_and_peer_logic_is_bounded() -> None:
    contract = read(
        SKILL_DIR / "references" / "pre-sale-assessment-report-contract.md"
    )
    assert "最小充分产品单元" in contract
    assert "团队知识库已认定同行" in contract
    assert "当前检索层未命中" in contract
    assert "不得把相邻企业冒充同产品同行" in contract
    assert "不补造具体专利事实" in contract


def test_presale_contract_does_not_change_other_project_analysis_skills() -> None:
    for skill_name in (
        "enterprise-panorama-analysis",
        "technology-innovation-projects",
        "project-feasibility",
    ):
        skill_path = ROOT / "skills" / skill_name / "SKILL.md"
        if skill_path.is_file():
            assert "pre-sale-assessment-report-contract.md" not in read(skill_path)


def test_completed_application_routes_to_late_stage_checkup() -> None:
    skill = read(SKILL_DIR / "SKILL.md")
    assert "已经形成完整申请书" in skill
    assert "改用 `sme-development-projects`" in skill
    assert "不适用本简版结构" in skill
