#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PORTAL_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PORTAL_DIR / "references" / "project-algorithm-rule-sources"
BASELINES_PATH = PORTAL_DIR / "references" / "project-policy-baselines.json"
APPROVED_BY = "主人授权；焦糖依据政策原文、正式附件和适用边界核验"
APPROVED_AT = "2026-07-30 09:00:00"


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}顶层必须为对象")
    return payload


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def fact(
    field: str,
    label: str,
    *,
    value_type: str = "boolean",
    unit: str = "",
    derivation: list[str] | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "field": field,
        "label": label,
        "aliases": [label],
        "value_type": value_type,
    }
    if unit:
        result["unit"] = unit
    if derivation:
        result["derivation_requirements"] = derivation
    return result


def rule(
    rule_id: str,
    field: str,
    source: str,
    quote: str,
    *,
    operator: str = "truthy",
    expected: object = True,
    rule_type: str = "hard-threshold",
    unit: str = "",
) -> dict[str, object]:
    result: dict[str, object] = {
        "rule_id": rule_id,
        "type": rule_type,
        "field": field,
        "operator": operator,
        "expected": expected,
        "source": source,
        "source_quote": quote,
    }
    if unit:
        result["unit"] = unit
    return result


def boolean_rules(
    prefix: str,
    source: str,
    items: list[tuple[str, str, str]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    facts = [
        fact(
            field_name,
            label,
            derivation=[quote],
        )
        for field_name, label, quote in items
    ]
    rules = [
        rule(f"{prefix}-{index}", field_name, source, quote)
        for index, (field_name, _, quote) in enumerate(items, start=1)
    ]
    return facts, rules


def source(
    *,
    project_id: str,
    project_name: str,
    version: str,
    aliases: list[str],
    retrieval_ids: list[str],
    source_url: str,
    source_title: str,
    facts: list[dict[str, object]],
    rules: list[dict[str, object]],
    stable_applicability: dict[str, object] | None = None,
    annual_overlays: list[dict[str, object]] | None = None,
    jurisdiction_overlays: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "project_id": project_id,
        "project_name": project_name,
        "version": version,
        "aliases": aliases,
        "source_retrieval_rule_ids": retrieval_ids,
        "policy_status": "current",
        "approved_by": APPROVED_BY,
        "approved_at": APPROVED_AT,
        "source_url": source_url,
        "source_title": source_title,
        "stable_applicability": stable_applicability or {},
        "fact_fields": facts,
        "rules": rules,
        "annual_overlays": annual_overlays or [],
        "jurisdiction_overlays": jurisdiction_overlays or [],
    }


def overlay(
    overlay_id: str,
    label: str,
    year: int,
    source_url: str,
    rules: list[dict[str, object]],
    *,
    application_types: list[str] | None = None,
    regions: list[str] | None = None,
    policy_status: str = "current",
) -> dict[str, object]:
    return {
        "overlay_id": overlay_id,
        "label": label,
        "year": year,
        "regions": regions or [],
        "application_types": application_types or [],
        "policy_status": policy_status,
        "approved_by": APPROVED_BY,
        "approved_at": APPROVED_AT,
        "source_url": source_url,
        "rules": rules,
    }


def baseline_urls() -> dict[str, list[str]]:
    registry = read_json(BASELINES_PATH)
    return {
        str(item["project_id"]): [
            str(document["official_url"])
            for document in item.get("policy_documents", [])
            if isinstance(document, dict)
        ]
        for item in registry.get("baselines", [])
        if isinstance(item, dict)
    }


def build_sources() -> list[dict[str, object]]:
    urls = baseline_urls()
    sources: list[dict[str, object]] = []

    digital_specs = (
        (
            "digital-workshop",
            "浙江省数字化车间",
            ["数字化车间"],
            "digital_workshop",
            "数字化车间",
        ),
        (
            "intelligent-factory",
            "浙江省智能工厂",
            ["智能工厂"],
            "intelligent_factory",
            "智能工厂",
        ),
        (
            "future-factory",
            "浙江省未来工厂",
            ["未来工厂"],
            "future_factory",
            "未来工厂",
        ),
    )
    for project_id, project_name, aliases, prefix, label in digital_specs:
        source_title = "《浙江省未来工厂梯度培育工作指南（2025年版）》"
        items = [
            (
                f"{prefix}_zhejiang_entity_met",
                f"{label}浙江主体要求",
                "申报主体及项目须属于浙江省制造业数字化转型梯度培育范围。",
            ),
            (
                f"{prefix}_cultivation_status_met",
                f"{label}培育入库要求",
                (
                    "未来工厂须为未来工厂试点培育企业；智能工厂、数字化车间"
                    "项目须纳入省级培育库。"
                ),
            ),
            (
                f"{prefix}_completed_operational",
                f"{label}完工投产要求",
                "申报项目应按当年度通知规定完成建设并投入运行。",
            ),
            (
                f"{prefix}_assessment_standard_met",
                f"{label}评定标准符合情况",
                "企业须按对应未来工厂、智能工厂或数字化车间评定标准完成自评。",
            ),
            (
                f"{prefix}_materials_complete",
                f"{label}材料完整性",
                "应提交申报书、自评材料、软硬件投入清单及知识产权、标准等佐证。",
            ),
            (
                f"{prefix}_compliance_clear",
                f"{label}合规核验",
                "申报材料应真实完整，项目建设和运行不得存在影响推荐的重大违法违规情形。",
            ),
        ]
        facts, rules = boolean_rules(prefix, source_title, items)
        sources.append(
            source(
                project_id=project_id,
                project_name=project_name,
                version="2025-guide-2025-cycle-20260730",
                aliases=aliases,
                retrieval_ids=[project_id],
                source_url=urls[project_id][0],
                source_title=source_title,
                facts=facts,
                rules=rules,
            )
        )

    equipment_title = "《浙江省制造业首台（套）提升工程工作指南（试行）》及2025年度通知"
    equipment_items = [
        ("first_equipment_zhejiang_entity", "浙江独立法人及省内研发生产", "申报单位应在浙江省内依法设立、具有独立法人资格，并在省内具备研发和生产基础。"),
        ("first_equipment_supported_direction", "装备方向符合性", "申报装备应符合首台套支持方向和当年度申报范围。"),
        ("first_equipment_license_and_test_met", "许可认证与检测", "法律法规要求许可或认证的应已取得，并具有符合要求的第三方检测报告。"),
        ("first_equipment_initial_market_met", "初期市场业绩", "产品应已形成初步市场业绩，但仍符合首台套首次推广应用阶段要求。"),
        ("first_equipment_breakthrough_and_ip_met", "重大技术突破及自主知识产权", "产品应具有重大技术突破并拥有核心自主知识产权。"),
        ("first_equipment_engineering_acceptance_met", "工程化攻关验收", "按指南要求应纳入工程化攻关项目库并完成验收的，须已完成相应程序。"),
        ("first_equipment_technical_tier_met", "技术水平分档", "国际、国内或省内首台套应分别达到对应技术水平和替代能力。"),
        ("first_equipment_novelty_report_valid", "两年内查新报告", "应提供具有资质机构近两年内出具的查新报告。"),
        ("first_equipment_exclusions_clear", "首台套排除项核验", "不得属于限制淘汰类，且不得存在重大质量、安全、环保、失信或重复认定等排除情形。"),
    ]
    facts, rules = boolean_rules("first-equipment", equipment_title, equipment_items)
    sources.append(
        source(
            project_id="first-equipment",
            project_name="首台（套）装备",
            version="2022-guide-2025-cycle-20260730",
            aliases=["首台套"],
            retrieval_ids=["first-equipment"],
            source_url=urls["first-equipment"][0],
            source_title=equipment_title,
            facts=facts,
            rules=rules,
        )
    )

    material_title = "《关于开展2025年度浙江省首批次新材料认定工作的通知》"
    material_items = [
        ("first_material_zhejiang_entity", "浙江独立法人及省内研发生产", "申报单位在浙江省内依法设立，具有独立法人资格，并在省内从事新材料研发及生产业务。"),
        ("first_material_maturity_sales_met", "技术成熟度及商业销售", "产品技术成熟度达到7级及以上且已实现商业销售。"),
        ("first_material_test_and_license_met", "检测及许可", "产品应具有符合要求的第三方检测报告；存在特殊许可或强制认证要求的须取得资质。"),
        ("first_material_novelty_valid", "两年内一级查新", "产品应具有国家一级查新资质单位近两年内出具的查新报告。"),
        ("first_material_domestic_leading", "国内领先及以上", "产品达到国内领先及以上技术水平。"),
        ("first_material_independent_ip", "自主知识产权", "产品具有自主知识产权。"),
        ("first_material_route_met", "目录或推荐认定路径", "应进入国家或浙江省重点新材料目录，或由院士、三名以上正高级专家推荐并满足通知列明的推荐条件。"),
        ("first_material_exclusions_clear", "首批次排除项", "产品不得属于限制淘汰类，能耗排放资源和碳强度应达先进水平，不得存在重大质量影响或无重大突破的三年内重复认定。"),
        ("first_material_tier_requirement_met", "国际或国内首批次附加条件", "申报国际或国内首批次的，应达到相应技术水平、进口替代和知名用户或重大工程销售要求。"),
    ]
    facts, rules = boolean_rules("first-material", material_title, material_items)
    sources.append(
        source(
            project_id="first-material-batch",
            project_name="重点新材料首批次",
            version="2025-cycle-20260730",
            aliases=["首批次"],
            retrieval_ids=["first-material-batch"],
            source_url=urls["first-material-batch"][0],
            source_title=material_title,
            facts=facts,
            rules=rules,
            stable_applicability={"years": ["2025"]},
        )
    )

    software_title = "《关于开展2025年度浙江省首版次软件产品认定工作的通知》"
    software_items = [
        ("first_software_zhejiang_entity", "浙江独立法人主体", "申报单位应在浙江省内依法设立并具有独立法人资格。"),
        ("first_software_compliance_clear", "近三年信用及安全质量合规", "近三年不得存在失信、债务违约、重大质量或生产安全等风险事件。"),
        ("first_software_environment_talent_met", "软件开发环境及人才", "应具有与软件开发相适应的经营场所、合法软硬件开发环境和人才支撑。"),
        ("first_software_catalog_met", "指导目录范围", "申报软件产品应属于当年度浙江省首版次软件产品申报指导目录范围。"),
        ("first_software_copyright_met", "著作权时间及第一作者", "应在通知规定时间后取得软件著作权，申报单位为第一著作权人；共有权须取得同意。"),
        ("first_software_first_release_sale", "首次正式发布销售", "软件产品应为首次正式发布并进行销售，具有市场推广应用前景。"),
        ("first_software_cnas_cma_test_met", "CNAS与CMA检测", "产品功能、性能指标应通过同时具备相应CNAS和CMA能力的第三方机构检测。"),
        ("first_software_domestic_tier_met", "国内首版次附加条件", "申报国内首版次的，须在技术突破、国产替代、奖项课题、信创适配、发明专利或标准等七项中至少满足两项。"),
        ("first_software_exclusions_clear", "首版次排除项", "不得属于限制淘汰类，不得在能耗排放、质量稳定性或同系列重复认定方面触发排除条件。"),
    ]
    facts, rules = boolean_rules("first-software", software_title, software_items)
    facts.append(fact("first_software_rnd_investment", "首版次产品研发投入", value_type="number", unit="万元"))
    rules.append(rule("first-software-rnd-investment", "first_software_rnd_investment", software_title, "申报软件产品研发投入在100万元人民币以上。", operator="gt", expected=100, unit="万元"))
    sources.append(
        source(
            project_id="first-software-version",
            project_name="首版次软件",
            version="2025-cycle-20260730",
            aliases=["首版次"],
            retrieval_ids=["first-software-version"],
            source_url=urls["first-software-version"][0],
            source_title=software_title,
            facts=facts,
            rules=rules,
            stable_applicability={"years": ["2025"]},
        )
    )

    green_title = "《浙江省绿色（低碳）工厂梯度培育管理实施细则》及评价要求"
    for project_id, project_name, aliases, regions in (
        ("green-factory-1", "区级绿色工厂", ["绿色工厂"], ["县（市、区）"]),
        ("green-factory-2", "市级绿色工厂", ["绿色工厂"], ["设区市"]),
        ("green-factory-3", "浙江省绿色低碳工厂", ["绿色工厂"], ["浙江省"]),
    ):
        prefix = project_id.replace("-", "_")
        items = [
            (f"{prefix}_jurisdiction_rule_resolved", "属地和层级规则已解析", "应先解析申报企业所在地、申报层级及对应主管部门现行实施细则。"),
            (f"{prefix}_basic_compliance_met", "绿色工厂基本合规", "企业应依法设立并在建设、生产、质量、安全、环保、节能等方面保持合规。"),
            (f"{prefix}_management_system_met", "绿色管理体系", "应建立绿色发展制度和能源、资源、环境、质量、安全等管理体系。"),
            (f"{prefix}_mandatory_indicators_met", "评价必选及门槛指标", "须满足适用评价标准中的基本要求、必选指标和属地评分门槛。"),
            (f"{prefix}_self_evaluation_complete", "绿色工厂自评价材料", "应按适用标准完成自评价报告，并提供能源资源、排放、绩效和证明材料。"),
            (f"{prefix}_dynamic_management_clear", "动态管理风险核验", "不得存在应移出梯度培育名单的重大违法、事故、失信、弄虚作假或停产注销等情形。"),
        ]
        facts, rules = boolean_rules(project_id, green_title, items)
        sources.append(
            source(
                project_id=project_id,
                project_name=project_name,
                version="2024-guide-dynamic-jurisdiction-20260730",
                aliases=aliases,
                retrieval_ids=["green-factory"],
                source_url=urls[project_id][0],
                source_title=green_title,
                facts=facts,
                rules=rules,
                jurisdiction_overlays=[
                    {
                        "overlay_id": f"{project_id}-jurisdiction",
                        "label": f"{project_name}属地实施细则",
                        "regions": regions,
                        "policy_status": "current",
                        "approved_by": APPROVED_BY,
                        "approved_at": APPROVED_AT,
                        "source_url": urls[project_id][0],
                        "application_types": ["recognition", "evaluation"],
                        "rules": [
                            rule(
                                f"{project_id}-local-thresholds",
                                f"{prefix}_jurisdiction_rule_resolved",
                                green_title,
                                "运行时必须选择对应层级与属地规则版本；未解析时只能输出待补政策，不能判定符合。",
                            )
                        ],
                    }
                ],
            )
        )

    hz_rd_title = "《杭州市企业高新技术研究开发中心管理办法》"
    hz_rd_facts = [
        fact("hz_rd_enterprise_type_met", "杭州注册且属于适用企业类型"),
        fact("hz_rd_staff_branch_met", "专职研发人员分支要求"),
        fact("hz_rd_site_area", "集中科研场地面积", value_type="number", unit="平方米"),
        fact("hz_rd_equipment_branch_met", "科研设备原值分支要求"),
        fact("hz_rd_investment_branch_met", "研发自筹投入分支要求"),
        fact("hz_rd_project_branch_met", "科研项目分支要求"),
        fact("hz_rd_ip_branch_met", "知识产权分支要求"),
        fact("hz_rd_independent_accounting", "研发活动单独建账"),
        fact("hz_rd_compliance_clear", "前一年度至申请日合规"),
        fact("hz_rd_materials_complete", "研发中心申请及实施方案完整"),
    ]
    hz_rd_rules = [
        rule("hz-rd-entity", "hz_rd_enterprise_type_met", hz_rd_title, "本市注册，且为市级以上科技型企业、高新技术企业或规上工业企业。"),
        rule("hz-rd-staff", "hz_rd_staff_branch_met", hz_rd_title, "专职从事研发活动人员一般10人以上；软件企业15人以上，须按企业类型选择对应分支。"),
        rule("hz-rd-site", "hz_rd_site_area", hz_rd_title, "科研场地相对集中，面积200平方米以上。", operator="gt", expected=200, unit="平方米"),
        rule("hz-rd-equipment", "hz_rd_equipment_branch_met", hz_rd_title, "专用科研设备原值一般200万元以上；软件、农业企业及软件企业50人以上研发队伍适用相应降低分支。"),
        rule("hz-rd-investment", "hz_rd_investment_branch_met", hz_rd_title, "上一年度研发费用自筹投入200万元以上，或占销售收入3%以上。"),
        rule("hz-rd-projects", "hz_rd_project_branch_met", hz_rd_title, "获市级以上科研项目1项以上，或企业自主立项技术创新项目3项以上。"),
        rule("hz-rd-ip", "hz_rd_ip_branch_met", hz_rd_title, "取得发明专利等I类成果1项以上，或实用新型、外观设计、软件著作权等3项以上。"),
        rule("hz-rd-accounting", "hz_rd_independent_accounting", hz_rd_title, "研发活动应单独建账核算，规章制度健全。"),
        rule("hz-rd-compliance", "hz_rd_compliance_clear", hz_rd_title, "申请前一年度至申请日未发生重大安全质量事故及严重环境、知识产权、税务、科研失信。"),
        rule("hz-rd-materials", "hz_rd_materials_complete", hz_rd_title, "应提交申请书、建设实施方案及规定佐证材料。", rule_type="submission"),
    ]
    sources.append(
        source(
            project_id="hangzhou-enterprise-institute",
            project_name="杭州市企业研究院",
            version="2022-method-valid-through-2027-20260730",
            aliases=["杭州研发中心", "杭州市研发中心", "市高企研发中心"],
            retrieval_ids=["hangzhou-enterprise-institute"],
            source_url=urls["hangzhou-enterprise-institute"][0],
            source_title=hz_rd_title,
            facts=hz_rd_facts,
            rules=hz_rd_rules,
        )
    )

    hz_tc_title = "《杭州市企业技术中心管理办法》"
    hz_tc_items = [
        ("hz_tech_center_innovation_system_met", "创新机制与知识产权管理", "企业创新运行、投入、激励机制及战略、计划和知识产权管理能力应健全。"),
        ("hz_tech_center_competitive_met", "行业竞争和创新能力", "综合经济技术指标和技术开发能力应处于本市同行业前列。"),
        ("hz_tech_center_independent_accounting", "技术中心财务单独立账", "技术中心经费纳入年度预算并单独立账。"),
        ("hz_tech_center_staff_branch_met", "研发人员队伍分支要求", "制造业、高技术服务业科技活动人员占比、学历职称结构和研发人数，或建筑业执业人员数须达到对应标准。"),
        ("hz_tech_center_revenue_branch_met", "主营收入分支要求", "制造业、高技术服务业、高新技术企业、建筑房地产或勘察设计企业须达到各自收入门槛。"),
        ("hz_tech_center_equipment_branch_met", "技术开发设备分支要求", "制造业、高技术服务业或建设行业须达到对应技术开发仪器设备原值门槛。"),
        ("hz_tech_center_credit_clear", "信用黑名单核验", "申请受理截止日不得被列入国家、省、市企业信用黑名单。"),
    ]
    facts, rules = boolean_rules("hz-tech-center", hz_tc_title, hz_tc_items)
    facts.append(fact("hz_tech_center_rnd_expense", "年度研发经费支出", value_type="number", unit="万元"))
    rules.append(rule("hz-tech-center-rnd-expense", "hz_tech_center_rnd_expense", hz_tc_title, "企业年度研发经费支出额不低于200万元。", operator="gte", expected=200, unit="万元"))
    sources.append(
        source(
            project_id="hangzhou-enterprise-technology-center",
            project_name="杭州市企业技术中心",
            version="2018-method-still-effective-20260730",
            aliases=["杭州企业技术中心"],
            retrieval_ids=["hangzhou-enterprise-technology-center"],
            source_url=urls["hangzhou-enterprise-technology-center"][0],
            source_title=hz_tc_title,
            facts=facts,
            rules=rules,
        )
    )

    municipal_title = "《浙江省企业技术中心管理办法》第二十四条及属地现行办法"
    municipal_items = [
        ("municipal_tc_jurisdiction_resolved", "目标设区市已解析", "市级企业技术中心由各地依法制定认定和评价政策，必须先解析企业注册地。"),
        ("municipal_tc_current_local_rule_resolved", "属地现行办法版本已锁定", "判断必须加载目标设区市查询日最新有效办法及当年度通知。"),
        ("municipal_tc_local_thresholds_met", "属地全部硬门槛符合", "企业收入、研发投入、人员、设备、组织和前置资质按属地现行办法逐项比较。"),
        ("municipal_tc_local_compliance_clear", "属地排除项核验", "严重违法失信、重大质量安全事故及属地列明排除项须逐项核验。"),
        ("municipal_tc_submission_complete", "属地申报材料完整", "申请报告、评价表及属地通知要求的证明材料须完整。"),
    ]
    facts, rules = boolean_rules("municipal-tech-center", municipal_title, municipal_items)
    sources.append(
        source(
            project_id="municipal-enterprise-technology-center",
            project_name="市级企业技术中心",
            version="dynamic-11-city-rule-compiler-20260730",
            aliases=["市企业技术中心"],
            retrieval_ids=["municipal-enterprise-technology-center"],
            source_url=urls["municipal-enterprise-technology-center"][0],
            source_title=municipal_title,
            facts=facts,
            rules=rules,
            jurisdiction_overlays=[
                {
                    "overlay_id": "municipal-tech-center-11-city-runtime",
                    "label": "浙江11个设区市动态阈值层",
                    "regions": ["浙江省11个设区市"],
                    "application_types": ["recognition", "evaluation"],
                    "policy_status": "current",
                    "approved_by": APPROVED_BY,
                    "approved_at": APPROVED_AT,
                    "source_url": urls["municipal-enterprise-technology-center"][0],
                    "rules": [
                        rule("municipal-tech-center-runtime-gate", "municipal_tc_current_local_rule_resolved", municipal_title, "未加载具体城市现行办法和年度通知时，正式结论必须保持待核验。")
                    ],
                }
            ],
        )
    )

    zj_tc_title = "《浙江省企业技术中心管理办法》浙经信技术〔2019〕128号"
    zj_tc_items = [
        ("zj_tech_center_competitive_met", "行业竞争和创新能力", "企业综合经济技术指标、技术开发能力及产品附加值应符合第五条第一项。"),
        ("zj_tech_center_revenue_branch_met", "行业收入分支要求", "制造业一般2亿元、加快发展县1亿元；建筑业结算收入15亿元；高技术服务业主营收入5000万元。"),
        ("zj_tech_center_equipment_branch_met", "设备原值分支要求", "制造业一般1200万元、加快发展县800万元；建筑业800万元；高技术服务业1000万元。"),
        ("zj_tech_center_rnd_ratio_branch_met", "研发经费比例分支要求", "制造业按主营收入规模适用1.5%、2%或3%；建筑业0.5%；高技术服务业2.5%。"),
        ("zj_tech_center_staff_branch_met", "创新人员分支要求", "制造业一般50人、加快发展县30人；建筑业一级注册人员50人；高技术服务业开发人员50人。"),
        ("zj_tech_center_municipal_one_year", "市级技术中心满一年", "申请企业已取得市级企业技术中心资格一年以上。"),
        ("zj_tech_center_three_year_compliance", "申请前三年合规", "申请受理截止日前三年不得存在严重税收、海关、失信或技术原因重大质量安全事故。"),
        ("zj_tech_center_materials_complete", "申请报告和评价材料", "应提交企业技术中心申请报告、评价表及评价指标体系所需证明材料。"),
    ]
    facts, rules = boolean_rules("zj-tech-center", zj_tc_title, zj_tc_items)
    sources.append(
        source(
            project_id="zhejiang-enterprise-technology-center",
            project_name="浙江省企业技术中心",
            version="2019-method-still-effective-20260730",
            aliases=["省技中心", "省企业技术中心"],
            retrieval_ids=["zhejiang-enterprise-technology-center"],
            source_url=urls["zhejiang-enterprise-technology-center"][0],
            source_title=zj_tc_title,
            facts=facts,
            rules=rules,
        )
    )

    key_lg_title = "《关于进一步支持专精特新中小企业高质量发展的通知》财建〔2024〕148号"
    key_lg_items = [
        ("key_lg_valid_little_giant", "有效期内小巨人资格", "支持对象应为有效期内专精特新小巨人企业，并符合支持批次和推荐范围。"),
        ("key_lg_no_duplicate_support", "无重复支持", "同一企业和项目不得违反中央财政资金重复支持及通知列明的排除要求。"),
        ("key_lg_three_transformations_plan_met", "三新一强项目计划", "企业应围绕打造新动能、攻坚新技术、开发新产品和强化产业链配套能力提出实施计划。"),
        ("key_lg_project_investment_met", "项目投资及资金用途", "实施项目、投资计划和资金用途应符合支持通知和地方实施方案。"),
        ("key_lg_performance_targets_met", "绩效目标可量化", "应设置可量化、可考核的阶段性绩效目标。"),
        ("key_lg_local_recommendation_met", "地方择优推荐", "企业须经地方中小企业主管部门、财政部门按名额和程序择优推荐。"),
        ("key_lg_compliance_clear", "合规核验", "不得存在重大事故、严重失信、违法违规、弄虚作假等不予支持情形。"),
    ]
    facts, rules = boolean_rules("key-little-giant", key_lg_title, key_lg_items)
    sources.append(
        source(
            project_id="key-little-giant-support",
            project_name="重点小巨人企业高质量发展奖补项目",
            version="2024-2026-support-cycle-20260730",
            aliases=["重点小巨人"],
            retrieval_ids=["key-little-giant-support"],
            source_url=urls["key-little-giant-support"][0],
            source_title=key_lg_title,
            facts=facts,
            rules=rules,
            stable_applicability={"years": ["2024", "2025", "2026"]},
        )
    )

    zj_sc_title = "《浙江省制造业单项冠军企业认定管理办法（试行）》浙经信大企〔2025〕179号"
    zj_sc_items = [
        ("zj_single_champion_independent_entity", "独立法人资格", "省单项冠军申报单位应具有独立法人资格。"),
        ("zj_single_champion_specialization_branch_met", "专业化年限分支", "一般产品从事相关领域6年以上、新产品3年以上；山区海岛县一般产品5年以上、新产品2年以上。"),
        ("zj_single_champion_market_rank_met", "市场占有率排名", "申请产品市场占有率位居全球前5或全国前3。"),
        ("zj_single_champion_revenue_branch_met", "主营收入分支", "近三年其中一年主营业务收入原则上达到4亿元；有效小巨人、山区海岛县及特定排名或历史经典产业适用豁免或降低分支。"),
        ("zj_single_champion_innovation_met", "创新能力", "原则上具有省级以上研发平台，研发强度达到3%或行业领先，并拥有实际应用、产生效益的核心知识产权和标准成果。"),
        ("zj_single_champion_quality_energy_met", "质量性能能耗", "产品质量、工艺和关键性能国内领先，能耗达到行业先进值，绿色低碳水平较高。"),
        ("zj_single_champion_management_met", "经营管理和国际化", "盈利、精益管理、数字化、人才、品牌和国际化能力应符合管理办法。"),
        ("zj_single_champion_compliance_clear", "近三年合规", "不得列入经营异常或严重失信，产品不属于禁止限制淘汰类，近三年无重大事故、偷漏税、数据造假等违法违规。"),
    ]
    facts, rules = boolean_rules("zj-single-champion", zj_sc_title, zj_sc_items)
    sources.append(
        source(
            project_id="manufacturing-single-champion-1",
            project_name="浙江省制造业单项冠军企业",
            version="2025.179-current-2026-cycle",
            aliases=["单项冠军"],
            retrieval_ids=["manufacturing-single-champion"],
            source_url=urls["manufacturing-single-champion-1"][0],
            source_title=zj_sc_title,
            facts=facts,
            rules=rules,
            annual_overlays=[
                overlay(
                    "zj-single-champion-2026",
                    "2026年度浙江省制造业单项冠军遴选",
                    2026,
                    urls["manufacturing-single-champion-1"][1],
                    [
                        rule("zj-single-champion-2026-one-product", "zj_single_champion_independent_entity", zj_sc_title, "同一年度按通知要求仅申报一个产品，并经属地审核推荐。", rule_type="submission")
                    ],
                    application_types=["recognition"],
                )
            ],
        )
    )

    tech_sme_title = "《浙江省科技型中小企业认定管理办法》浙科发高〔2016〕88号"
    tech_sme_items = [
        ("zj_tech_sme_entity_met", "浙江注册一年以上并独立核算", "在本省登记注册成立一年以上，产权明晰，实行独立核算、自主经营、自负盈亏。"),
        ("zj_tech_sme_ip_product_met", "知识产权及对应产品服务", "拥有专利、标准、商标、科技成果或其他专有技术，并形成相应产品或服务。"),
        ("zj_tech_sme_innovation_investment_met", "持续科技创新投入", "企业具有科技创新经费投入并具备持续开展科技创新活动的能力。"),
        ("zj_tech_sme_size_standard_met", "中小企业划型符合", "企业规模符合中小企业划型标准。"),
        ("zj_tech_sme_materials_complete", "平台申请材料完整", "企业通过平台提交申请书和附件，由市县审核、公示并报省备案。"),
    ]
    facts, rules = boolean_rules("zj-tech-sme", tech_sme_title, tech_sme_items)
    facts.append(fact("zj_tech_sme_tech_staff_ratio", "科技人员占职工比例", value_type="number", unit="%"))
    rules.append(rule("zj-tech-sme-staff-ratio", "zj_tech_sme_tech_staff_ratio", tech_sme_title, "研发和相关技术活动科技人员占当年职工总数比例原则上不低于10%。", operator="gte", expected=10, unit="%"))
    sources.append(
        source(
            project_id="technology-sme-1",
            project_name="浙江省科技型中小企业",
            version="2016-method-still-effective-20260730",
            aliases=["科小"],
            retrieval_ids=["technology-sme"],
            source_url=urls["technology-sme-1"][0],
            source_title=tech_sme_title,
            facts=facts,
            rules=rules,
        )
    )

    hidden_title = "《关于开展2026年度浙江省制造业单项冠军（隐形冠军）企业遴选认定工作的通知》附件4、5"
    hidden_facts = [
        fact("hidden_champion_zhejiang_ten_year_entity", "浙江独立法人连续经营年限符合"),
        fact("hidden_champion_revenue", "上年度营业收入", value_type="number", unit="万元"),
        fact("hidden_champion_revenue_growth_two_years", "近两年营业收入持续增长"),
        fact("hidden_champion_net_profit_avg_growth", "近两年净利润平均增长率", value_type="number", unit="%"),
        fact("hidden_champion_debt_ratio", "资产负债率", value_type="number", unit="%"),
        fact("hidden_champion_credit_met", "A级资信或征信无不良"),
        fact("hidden_champion_specialization_met", "细分领域年限与主导产品结构"),
        fact("hidden_champion_market_rank_met", "细分市场排名"),
        fact("hidden_champion_rnd_ratio_two_years", "近两年研发投入占比均达标"),
        fact("hidden_champion_invention_patents", "相关有效发明专利", value_type="number", unit="项"),
        fact("hidden_champion_rd_it_met", "研发机构和信息系统"),
        fact("hidden_champion_standard_brand_cert_met", "标准品牌和国际认证"),
        fact("hidden_champion_compliance_clear", "近三年合规"),
        fact("hidden_champion_conflict_identity_clear", "无单项冠军或小巨人身份冲突"),
        fact("hidden_champion_review_operation_normal", "复核期近三年经营正常"),
        fact("hidden_champion_review_participated", "按规定参加复核"),
    ]
    recognition_rules = [
        rule("hidden-entity", "hidden_champion_zhejiang_ten_year_entity", hidden_title, "在浙江省内工商登记、连续经营10年以上并具有独立法人资格。"),
        rule("hidden-revenue-min", "hidden_champion_revenue", hidden_title, "上年度营业收入5000万元及以上，一般不超过20亿元。", operator="gte", expected=5000, unit="万元"),
        rule("hidden-revenue-growth", "hidden_champion_revenue_growth_two_years", hidden_title, "近2年营业收入持续增长。"),
        rule("hidden-profit-growth", "hidden_champion_net_profit_avg_growth", hidden_title, "近2年净利润平均增长率达到10%以上。", operator="gte", expected=10, unit="%"),
        rule("hidden-debt-ratio", "hidden_champion_debt_ratio", hidden_title, "资产负债率不高于75%。", operator="lte", expected=75, unit="%"),
        rule("hidden-credit", "hidden_champion_credit_met", hidden_title, "银行资信等级A级以上或人行征信报告无不良记录。"),
        rule("hidden-specialization", "hidden_champion_specialization_met", hidden_title, "细分领域10年以上，主导产品不超过3个，主营业务收入占营业收入70%以上。"),
        rule("hidden-market-rank", "hidden_champion_market_rank_met", hidden_title, "主导产品细分市场占有率位于全球前10或全国前3。"),
        rule("hidden-rnd", "hidden_champion_rnd_ratio_two_years", hidden_title, "近2年研发投入占营业收入比重每年均不低于4%。"),
        rule("hidden-invention", "hidden_champion_invention_patents", hidden_title, "拥有与主导产品相关且实际应用、产生经济效益的有效发明专利4项及以上。", operator="gte", expected=4, unit="项"),
        rule("hidden-rd-it", "hidden_champion_rd_it_met", hidden_title, "自建或联合建立研发机构，研发、生产、供应等至少一项核心业务采用信息系统。"),
        rule("hidden-standard-brand", "hidden_champion_standard_brand_cert_met", hidden_title, "主导或参与国际、国家或行业标准1项以上，拥有自主品牌并取得国际相关认证1项以上。"),
        rule("hidden-compliance", "hidden_champion_compliance_clear", hidden_title, "近三年无重大事故、严重失信、偷税漏税、数据造假等违法违规。"),
        rule("hidden-conflict", "hidden_champion_conflict_identity_clear", hidden_title, "已认定国家制造业单项冠军或有效小巨人的，不再推荐新申请隐形冠军。"),
    ]
    review_rules = [
        rule("hidden-review-operation", "hidden_champion_review_operation_normal", hidden_title, "近三年生产经营正常，并符合复核适用的申报条件。"),
        rule("hidden-review-participation", "hidden_champion_review_participated", hidden_title, "未按规定参加复核的，撤销隐形冠军称号。"),
        rule("hidden-review-debt", "hidden_champion_debt_ratio", hidden_title, "复核资产负债率不高于75%。", operator="lte", expected=75, unit="%"),
        rule("hidden-review-specialization", "hidden_champion_specialization_met", hidden_title, "复核继续满足细分领域、主导产品数量和主营占比要求。"),
        rule("hidden-review-market", "hidden_champion_market_rank_met", hidden_title, "复核继续满足全球前10或全国前3市场排名要求。"),
        rule("hidden-review-rnd", "hidden_champion_rnd_ratio_two_years", hidden_title, "复核近2年研发投入占比每年不低于4%。"),
        rule("hidden-review-invention", "hidden_champion_invention_patents", hidden_title, "复核有效发明专利4项及以上并实际应用。", operator="gte", expected=4, unit="项"),
        rule("hidden-review-compliance", "hidden_champion_compliance_clear", hidden_title, "复核期不得存在事故、失信、违法违规或数据造假。"),
    ]
    hidden_source = source(
        project_id="zhejiang-hidden-champion",
        project_name="浙江省隐形冠军企业",
        version="2026-recognition-review",
        aliases=["隐形冠军"],
        retrieval_ids=["zhejiang-hidden-champion"],
        source_url=urls["zhejiang-hidden-champion"][0],
        source_title=hidden_title,
        facts=hidden_facts,
        rules=recognition_rules,
        stable_applicability={"years": ["2026"], "application_types": ["recognition"]},
        annual_overlays=[
            overlay(
                "hidden-champion-review-2026",
                "2026年度隐形冠军复核",
                2026,
                urls["zhejiang-hidden-champion"][0],
                review_rules,
                application_types=["review"],
            )
        ],
    )
    hidden_source["source_archive_path"] = (
        "10_政策与目录/政策数据库/企策顾问/申报通知/宁波市/"
        "优质中小企业梯度培育/"
        "2026-03-26__关于开展2026年度浙江省制造业单项冠军"
        "（隐形冠军）企业遴选认定工作的通知__"
        "8c65d358e6284a548ccb3f9726c51729/"
        "附件/4.浙江省隐形冠军企业申请条件和要求.doc"
    )
    hidden_source["source_archive_sha256"] = (
        "2c2212e47b2952085b1e49d622a4fbdcb5b5065eb7476340c4295027042a17fe"
    )
    hidden_source["annual_overlays"][0]["source_archive_path"] = (
        "10_政策与目录/政策数据库/企策顾问/申报通知/宁波市/"
        "优质中小企业梯度培育/"
        "2026-03-26__关于开展2026年度浙江省制造业单项冠军"
        "（隐形冠军）企业遴选认定工作的通知__"
        "8c65d358e6284a548ccb3f9726c51729/"
        "附件/5.浙江省隐形冠军企业复核条件和要求.doc"
    )
    hidden_source["annual_overlays"][0]["source_archive_sha256"] = (
        "c3d0734c2e17f0bd083d8dca1c67eff50728a8c23cdc3537a732fef098a7864c"
    )
    sources.append(hidden_source)

    industrial_title = "浙江省工业新产品历史认定证据及浙江制造精品后续项目"
    industrial_facts = [
        fact("industrial_new_product_current_notice_open", "当前年度工业新产品申报通知有效"),
        fact("industrial_new_product_historical_thresholds_met", "历史年度工业新产品条件符合"),
        fact("industrial_new_product_successor_route_resolved", "后续项目路径已解析"),
        fact("industrial_new_product_materials_complete", "历史申报材料完整"),
    ]
    industrial_rules = [
        rule("industrial-new-product-current-open", "industrial_new_product_current_notice_open", industrial_title, "当前查询年度必须存在有效申报通知；未发现现行通知时不得把历史规则当作当前资格结论。"),
        rule("industrial-new-product-successor", "industrial_new_product_successor_route_resolved", industrial_title, "历史项目停止或转轨时，应保留历史身份，并解析浙江制造精品等现行后续路径。", rule_type="submission"),
    ]
    sources.append(
        source(
            project_id="zhejiang-industrial-new-product",
            project_name="浙江省工业新产品",
            version="historical-2023-successor-2025",
            aliases=["工业新产品"],
            retrieval_ids=["zhejiang-industrial-new-product"],
            source_url=urls["zhejiang-industrial-new-product"][1],
            source_title=industrial_title,
            facts=industrial_facts,
            rules=industrial_rules,
            annual_overlays=[
                overlay(
                    "industrial-new-product-2023-history",
                    "2023年度工业新产品历史回放",
                    2023,
                    urls["zhejiang-industrial-new-product"][0],
                    [
                        rule("industrial-new-product-2023-thresholds", "industrial_new_product_historical_thresholds_met", industrial_title, "仅按2023年度有效政策和名单附件回放当年资格与认定事实。"),
                        rule("industrial-new-product-2023-materials", "industrial_new_product_materials_complete", industrial_title, "历史回放应保留当年申请、评价及名单附件证据。", rule_type="submission"),
                    ],
                    application_types=["historical-replay"],
                    policy_status="historical_reference",
                )
            ],
        )
    )

    key_sme_title = "《2026年支持专精特新中小企业高质量发展项目申报通知》及遴选标准"
    key_sme_facts = [
        fact("key_zj_sme_valid_status", "有效期内浙江省专精特新中小企业"),
        fact("key_zj_sme_excluded_little_giant_clear", "非有效期内小巨人"),
        fact("key_zj_sme_public_listing_clear", "未在境内外公开发行股票"),
        fact("key_zj_sme_four_improvements_plan_met", "四提一强计划符合"),
        fact("investment_amount", "推进计划投资总额", value_type="number", unit="万元"),
        fact("key_zj_sme_project_scope_met", "拟实施项目范围符合"),
        fact("key_zj_sme_no_duplicate_funding", "无重复专项资金支持"),
        fact("revenue", "上年度营业收入", value_type="number", unit="万元"),
        fact("key_zj_sme_size_standard_met", "中小企业划型符合"),
        fact("key_zj_sme_debt_ratio", "上年度资产负债率", value_type="number", unit="%"),
        fact("rnd_ratio", "上年度研发费用强度", value_type="number", unit="%"),
        fact("rnd_expense", "上年度研发费用", value_type="number", unit="万元"),
        fact("key_zj_sme_class1_ip_count", "主导产品相关I类知识产权", value_type="number", unit="项"),
        fact("key_zj_sme_priority_industry_met", "重点产业领域符合"),
        fact("key_zj_sme_review_failure_clear", "非复核未通过小巨人"),
        fact("key_zj_sme_compliance_clear", "经营异常失信及近三年事故违法核验"),
    ]
    key_sme_rules = [
        rule("key-zj-sme-valid", "key_zj_sme_valid_status", key_sme_title, "申请企业须为有效期内浙江省专精特新中小企业，宁波市除外。"),
        rule("key-zj-sme-not-little-giant", "key_zj_sme_excluded_little_giant_clear", key_sme_title, "不含有效期内专精特新小巨人企业。"),
        rule("key-zj-sme-not-listed", "key_zj_sme_public_listing_clear", key_sme_title, "企业未在上交所、深交所、北交所或境外公开发行股票。"),
        rule("key-zj-sme-plan", "key_zj_sme_four_improvements_plan_met", key_sme_title, "须提出有具体项目和绩效目标支撑的融通入链四提一强推进计划。"),
        rule("key-zj-sme-investment", "investment_amount", key_sme_title, "推进计划投资总额需超过1000万元。", operator="gt", expected=1000, unit="万元"),
        rule("key-zj-sme-project-scope", "key_zj_sme_project_scope_met", key_sme_title, "技术改造、数字化网络化智能化改造、基础研究项目不在拟实施项目支持范围。"),
        rule("key-zj-sme-no-duplicate", "key_zj_sme_no_duplicate_funding", key_sme_title, "同一项目已获超长期国债、工信部或省级工信专项资金支持的不得重复申报。"),
        rule("key-zj-sme-revenue", "revenue", key_sme_title, "上年度营业收入原则上不低于1000万元。", operator="gte", expected=1000, unit="万元"),
        rule("key-zj-sme-size", "key_zj_sme_size_standard_met", key_sme_title, "企业须符合中小企业划型标准。"),
        rule("key-zj-sme-debt", "key_zj_sme_debt_ratio", key_sme_title, "上年度资产负债率原则上不高于100%。", operator="lte", expected=100, unit="%"),
        rule("key-zj-sme-rnd-ratio", "rnd_ratio", key_sme_title, "上年度研发费用强度原则上不低于3%。", operator="gte", expected=3, unit="%"),
        rule("key-zj-sme-rnd-expense", "rnd_expense", key_sme_title, "上年度研发费用原则上不少于300万元。", operator="gte", expected=300, unit="万元"),
        rule("key-zj-sme-ip", "key_zj_sme_class1_ip_count", key_sme_title, "已授权且与主导产品相关的I类知识产权原则上不少于2项。", operator="gte", expected=2, unit="项"),
        rule("key-zj-sme-industry", "key_zj_sme_priority_industry_met", key_sme_title, "企业应属于重点产业领域。"),
        rule("key-zj-sme-review-clear", "key_zj_sme_review_failure_clear", key_sme_title, "复核未通过的专精特新小巨人原则上不予支持。"),
        rule("key-zj-sme-compliance", "key_zj_sme_compliance_clear", key_sme_title, "不得列入经营异常或严重失信，近三年无重大事故、偷漏税等违法违规。"),
    ]
    sources.append(
        source(
            project_id="zhejiang-key-specialized-sme",
            project_name="浙江省重点专精特新中小企业",
            version="2026-support-cycle",
            aliases=["重点省专", "重专"],
            retrieval_ids=["zhejiang-key-specialized-sme"],
            source_url=urls["zhejiang-key-specialized-sme"][0],
            source_title=key_sme_title,
            facts=key_sme_facts,
            rules=key_sme_rules,
            stable_applicability={"years": ["2026"]},
        )
    )

    pin_title = "品字标浙江制造认证、自我声明和品牌授权现行规则"
    pin_items = [
        ("pin_zhejiang_manufacturing_standard_valid", "适用浙江制造标准有效", "产品应具有现行有效且适用的浙江制造团体标准或标准体系依据。"),
        ("pin_zhejiang_manufacturing_route_resolved", "认证或自我声明路径已解析", "应明确采用第三方认证或符合规则的自我声明路径，并满足对应评价要求。"),
        ("pin_zhejiang_manufacturing_conformity_met", "产品符合性评价通过", "产品、生产过程、质量保证和检验能力应满足适用标准及评价细则。"),
        ("pin_zhejiang_manufacturing_authorization_complete", "品牌授权材料完整", "申请品牌标识使用授权时，应按平台要求提交证书、声明、标准和主体材料。"),
        ("pin_zhejiang_manufacturing_continuing_compliance", "持续合规及标识使用", "获授权后应在证书或声明有效期内规范使用标识并接受监督。"),
    ]
    facts, rules = boolean_rules("pin-zhejiang-manufacturing", pin_title, pin_items)
    sources.append(
        source(
            project_id="zhejiang-manufacturing-2",
            project_name="品字标浙江制造",
            version="current-certification-self-declaration-20260730",
            aliases=["浙江制造"],
            retrieval_ids=["zhejiang-manufacturing"],
            source_url=urls["zhejiang-manufacturing-2"][0],
            source_title=pin_title,
            facts=facts,
            rules=rules,
        )
    )

    quality_title = "《关于组织开展2025年“浙江制造精品”遴选工作的通知》"
    quality_facts = [
        fact("quality_zhejiang_entity_rd_production", "浙江独立法人且省内研发生产"),
        fact("quality_product_competitiveness_met", "细分市场和核心技术符合"),
        fact("quality_product_category", "申报产品类别", value_type="string"),
        fact("quality_mountain_county", "山区26县企业"),
        fact("quality_annual_product_sales", "产品上市后每年销售收入", value_type="number", unit="万元"),
        fact("quality_sales_branch_met", "类别与山区销售收入分支要求"),
        fact("quality_three_year_avg_rnd_ratio", "近三年平均研发投入占主营收入", value_type="number", unit="%"),
        fact("quality_listing_period_met", "产品上市时间符合"),
        fact("quality_one_product_limit_met", "企业申报产品数量符合"),
        fact("quality_materials_complete", "申报及佐证材料完整"),
    ]
    quality_rules = [
        rule("quality-entity", "quality_zhejiang_entity_rd_production", quality_title, "主体应在浙江省内依法设立、具有独立法人资格，在省内建有研发机构和生产基地。"),
        rule("quality-product", "quality_product_competitiveness_met", quality_title, "产品应聚焦细分市场，市场占有率高、技术领先并具有关键核心技术和自主知识产权。"),
        rule("quality-category", "quality_product_category", quality_title, "申报类别须为先进制造类、数字技术融合类或特色消费品类。", operator="in", expected=["先进制造类", "数字技术融合类", "特色（消费品）类"]),
        rule("quality-listing-period", "quality_listing_period_met", quality_title, "申报产品须符合通知规定的近三年上市产品时间范围。"),
        rule("quality-sales-branch", "quality_sales_branch_met", quality_title, "先进制造、数字技术融合、特色消费品三类每年销售收入一般分别不低于800、600、600万元；山区26县适用500、300、300万元分支，须按类别和地区逐项选择。"),
        rule("quality-rnd", "quality_three_year_avg_rnd_ratio", quality_title, "申报企业近三年平均研发投入占主营业务收入比重不低于3%。", operator="gte", expected=3, unit="%"),
        rule("quality-one-product", "quality_one_product_limit_met", quality_title, "原则上每家企业申报浙江制造精品数量不超过1个。"),
        rule("quality-materials", "quality_materials_complete", quality_title, "应在线填报申报信息并上传申报书及相关佐证材料。", rule_type="submission"),
    ]
    sources.append(
        source(
            project_id="zhejiang-manufacturing-quality",
            project_name="浙江制造精品",
            version="2025-cycle-20260730",
            aliases=["制造精品", "浙江制造"],
            retrieval_ids=["zhejiang-manufacturing-quality", "zhejiang-manufacturing"],
            source_url=urls["zhejiang-manufacturing-quality"][0],
            source_title=quality_title,
            facts=quality_facts,
            rules=quality_rules,
            stable_applicability={"years": ["2025"]},
        )
    )
    return sources


def main() -> int:
    sources = build_sources()
    if len(sources) != 21:
        raise ValueError(f"预期21个规则源，实际{len(sources)}")
    for payload in sources:
        write_json(
            OUTPUT_DIR / f"{payload['project_id']}.json",
            payload,
        )
    print(
        json.dumps(
            {
                "status": "pass",
                "generated": len(sources),
                "project_ids": [item["project_id"] for item in sources],
                "output_dir": str(OUTPUT_DIR),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
