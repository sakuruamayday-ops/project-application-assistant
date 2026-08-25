import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
CONTRACT = SKILLS / "project-feasibility" / "references" / "two-report-contract.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_dual_report_contract_has_distinct_depth_and_deadlines() -> None:
    text = read(CONTRACT)
    for phrase in (
        "报告一：项目前期评估报告",
        "报告二：项目申报可行性分析报告",
        "申报截止日期",
        "已截止",
        "待当年通知",
        "现行条件或完整评分表逐项拆解",
        "确定得分",
        "条件得分",
        "完成节点",
    ):
        assert phrase in text


def test_dual_report_contract_covers_twelve_project_types() -> None:
    text = read(CONTRACT)
    for project in (
        "高新技术企业",
        "专精特新中小企业",
        "专精特新“小巨人”",
        "首台套",
        "首批次新材料",
        "首版次软件",
        "研发中心",
        "制造精品",
        "单项冠军",
        "绿色工厂",
        "数字化项目",
        "科技计划",
    ):
        assert f"| {project} |" in text


def test_all_project_domain_routes_load_the_shared_contract() -> None:
    for skill in (
        "high-tech-enterprise-preassessment",
        "sme-score-preassessment",
        "industrialization-projects",
        "technology-innovation-projects",
        "quality-brand-projects",
        "green-development-projects",
        "digitalization-projects",
    ):
        assert "project-feasibility/references/two-report-contract.md" in read(
            SKILLS / skill / "SKILL.md"
        )


def test_common_strengthening_and_watermark_contract_are_mandatory() -> None:
    text = read(CONTRACT)
    for phrase in (
        "国内产品技术水平评价咨询报告",
        "国际产品技术水平评价咨询报告",
        "国内领先、国际先进",
        "共创红色居中水印",
        "默认只输出一份可编辑 Word",
        "用户明确要求 PDF",
        "不设置文档加密或编辑限制",
    ):
        assert phrase in text


def test_sme_digital_diagnostic_is_soft_strengthening_without_invented_score() -> None:
    text = read(
        SKILLS
        / "sme-score-preassessment"
        / "references"
        / "digital-transformation-diagnostic-strengthening.md"
    )
    for phrase in (
        "软提升与证据补强",
        "发展战略",
        "业务创新转型",
        "新型能力",
        "系统性解决方案",
        "治理体系",
        "全国与同行对标",
        "待企业确认，建议补强",
    ):
        assert phrase in text
    assert "不得提前写入成熟度等级、指数、全国排名或同行排名" in text


def test_hightech_super_deduction_chain_is_complete_and_sanitized() -> None:
    text = read(
        SKILLS
        / "high-tech-enterprise-preassessment"
        / "references"
        / "rd-super-deduction-strengthening.md"
    )
    for phrase in (
        "立项及可行性报告",
        "研发人员名单",
        "研发设备清单",
        "人员工时记录",
        "研发材料领用记录",
        "小试、中试或试制过程记录",
        "研发项目结题报告",
        "专利与研发项目关联台账",
        "研发费用辅助账工作簿",
        "研发费用明细账",
        "专项审计和纳税申报",
    ):
        assert phrase in text
    for customer_marker in ("杭州彭公", "研发费用归集(1)"):
        assert customer_marker not in text


def test_delivery_contract_registers_both_report_categories() -> None:
    payload = json.loads(read(SKILLS / "delivery-contracts.json"))
    role = payload["skill_roles"]["project-feasibility"]
    assert role["owns"] == [
        "project-presale-assessment-report",
        "project-feasibility-analysis-report",
    ]
    for profile_name in role["owns"]:
        profile = payload["delivery_profiles"][profile_name]
        artifact = profile["required_artifacts"][0]
        assert artifact["formats"] == ["docx", "pdf"]
        assert profile["branding_contracts"] == [
            {
                "mode": "required",
                "variant": "default",
                "artifact_roles": [artifact["role"]],
            }
        ]


def test_v1652_keeps_v165_report_and_project_logic_boundaries() -> None:
    text = read(CONTRACT)
    assert "企业分析报告 A、B、C 版" in text
    assert "尖兵领雁、市级重大及科技计划类的既有分析逻辑保持不变" in text
    manifest = json.loads(read(SKILLS / "suite-manifest.json"))
    assert manifest["release"]["tag"] == "V1.6.12"


def test_enterprise_panorama_keeps_business_modes_but_defaults_each_to_word() -> None:
    text = read(SKILLS / "enterprise-panorama-analysis" / "SKILL.md")
    manifest = json.loads(read(SKILLS / "suite-manifest.json"))
    assert "A 第一版｜标准销售版" in text
    assert "B 第二版｜GCIP深度顾问版" in text
    assert "C 全生成｜同时生成A和B" in text
    assert "每种已选报告默认只交付一份可编辑 Word" in text
    assert "用户明确要求 PDF 时才生成对应 PDF" in text
    assert "不再提供标准销售版" not in text
    assert manifest["release"]["version"] == "1.6.12"
