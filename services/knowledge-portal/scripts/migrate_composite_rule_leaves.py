#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
from itertools import combinations
from pathlib import Path
from typing import Any


PORTAL_DIR = Path(__file__).resolve().parents[1]
SOURCE_DIR = PORTAL_DIR / "references" / "project-algorithm-rule-sources"


def fact(
    field: str,
    label: str,
    *,
    value_type: str = "boolean",
    unit: str = "",
    fact_semantics: str = "",
) -> dict[str, object]:
    result: dict[str, object] = {
        "field": field,
        "label": label,
        "aliases": [label],
        "value_type": value_type,
    }
    if unit:
        result["unit"] = unit
    if fact_semantics:
        result["fact_semantics"] = fact_semantics
    return result


def leaf(
    rule_id: str,
    field: str,
    label: str,
    *,
    operator: str = "truthy",
    expected: object = True,
    value_type: str = "boolean",
    unit: str = "",
    fact_semantics: str = "",
) -> dict[str, object]:
    rule: dict[str, object] = {
        "rule_id": rule_id,
        "field": field,
        "operator": operator,
        "expected": expected,
    }
    if unit:
        rule["unit"] = unit
    return {
        "rule": rule,
        "facts": [
            fact(
                field,
                label,
                value_type=value_type,
                unit=unit,
                fact_semantics=fact_semantics,
            )
        ],
    }


def group(
    rule_id: str,
    logic: str,
    children: list[dict[str, object]],
) -> dict[str, object]:
    facts: list[dict[str, object]] = []
    rules: list[dict[str, object]] = []
    for child in children:
        facts.extend(child["facts"])
        rules.append(child["rule"])
    return {
        "rule": {
            "rule_id": rule_id,
            "logic": logic,
            "children": rules,
        },
        "facts": facts,
    }


def atomic_assessment(
    rule_id: str,
    field: str,
    label: str,
) -> dict[str, object]:
    return leaf(
        rule_id,
        field,
        label,
        fact_semantics="assessment-conclusion",
    )


def pair_routes(
    rule_id: str,
    items: list[tuple[str, str]],
) -> dict[str, object]:
    item_map = {field: label for field, label in items}
    pairs = [
        group(
            f"{rule_id}-pair-{index}",
            "all",
            [
                leaf(
                    f"{rule_id}-pair-{index}-a",
                    first,
                    item_map[first],
                ),
                leaf(
                    f"{rule_id}-pair-{index}-b",
                    second,
                    item_map[second],
                ),
            ],
        )
        for index, (first, second) in enumerate(
            combinations([field for field, _ in items], 2),
            start=1,
        )
    ]
    return group(rule_id, "any", pairs)


def _migrations() -> dict[tuple[str, str], dict[str, object]]:
    result: dict[tuple[str, str], dict[str, object]] = {}

    for project_id, prefix in (
        ("digital-workshop", "digital_workshop"),
        ("future-factory", "future_factory"),
        ("intelligent-factory", "intelligent_factory"),
    ):
        result[(project_id, f"{prefix}-4")] = atomic_assessment(
            f"{prefix}-4",
            f"{prefix}_applicable_standard_assessment_passed",
            "适用建设层级评价标准自评结论通过",
        )
    result[("green-factory-4", "national-green-factory-standard")] = (
        atomic_assessment(
            "national-green-factory-standard",
            "green_factory_applicable_standard_assessment_passed",
            "适用行业标准或绿色工厂评价通则结论通过",
        )
    )

    result[("first-equipment", "first-equipment-3")] = group(
        "first-equipment-3",
        "all",
        [
            leaf(
                "first-equipment-license",
                "first_equipment_mandatory_license_obtained_or_not_required",
                "法定许可认证已取得或确认不适用",
            ),
            leaf(
                "first-equipment-test",
                "first_equipment_third_party_test_report_valid",
                "首台套第三方检测报告有效",
            ),
        ],
    )
    result[("first-equipment", "first-equipment-7")] = atomic_assessment(
        "first-equipment-7",
        "first_equipment_applicable_technical_tier_assessment_passed",
        "国际国内或省内首台套适用技术层级评价通过",
    )

    result[("first-material-batch", "first-material-2")] = group(
        "first-material-2",
        "all",
        [
            leaf(
                "first-material-trl",
                "first_material_technology_readiness_level",
                "新材料技术成熟度",
                operator="gte",
                expected=7,
                value_type="number",
                unit="级",
            ),
            leaf(
                "first-material-sales",
                "first_material_commercial_sales_realized",
                "新材料已经实现商业销售",
            ),
        ],
    )
    result[("first-material-batch", "first-material-3")] = group(
        "first-material-3",
        "all",
        [
            leaf(
                "first-material-test",
                "first_material_third_party_test_report_valid",
                "首批次新材料第三方检测报告有效",
            ),
            leaf(
                "first-material-license",
                "first_material_mandatory_license_obtained_or_not_required",
                "特殊许可或强制认证已取得或确认不适用",
            ),
        ],
    )
    result[("first-material-batch", "first-material-7")] = group(
        "first-material-7",
        "any",
        [
            leaf(
                "first-material-catalog-route",
                "first_material_catalog_listing_valid",
                "已进入国家或浙江省重点新材料目录",
            ),
            group(
                "first-material-expert-route",
                "all",
                [
                    leaf(
                        "first-material-expert-count",
                        "first_material_senior_expert_recommendation_count",
                        "符合条件的推荐专家人数",
                        operator="gte",
                        expected=3,
                        value_type="number",
                        unit="人",
                    ),
                    leaf(
                        "first-material-expert-title",
                        "first_material_expert_title_requirement_satisfied",
                        "推荐专家职称或院士身份符合",
                    ),
                    leaf(
                        "first-material-expert-other",
                        "first_material_expert_route_other_conditions_satisfied",
                        "专家推荐路径其他条件符合",
                    ),
                ],
            ),
        ],
    )
    result[("first-material-batch", "first-material-9")] = atomic_assessment(
        "first-material-9",
        "first_material_applicable_tier_assessment_passed",
        "国际或国内首批次适用技术与应用层级评价通过",
    )

    result[("first-software-version", "first-software-7")] = group(
        "first-software-7",
        "all",
        [
            leaf(
                "first-software-cnas",
                "first_software_test_agency_cnas_capability_valid",
                "检测机构CNAS能力有效",
            ),
            leaf(
                "first-software-cma",
                "first_software_test_agency_cma_capability_valid",
                "检测机构CMA能力有效",
            ),
            leaf(
                "first-software-test-result",
                "first_software_test_result_passed",
                "首版次软件功能性能检测通过",
            ),
        ],
    )
    result[("first-software-version", "first-software-8")] = pair_routes(
        "first-software-8",
        [
            ("first_software_domestic_technical_breakthrough", "国内首版次技术突破条件"),
            ("first_software_domestic_substitution", "国内首版次国产替代条件"),
            ("first_software_domestic_award_or_project", "国内首版次奖项课题条件"),
            ("first_software_domestic_xinchuang_adaptation", "国内首版次信创适配条件"),
            ("first_software_domestic_invention_patent", "国内首版次发明专利条件"),
            ("first_software_domestic_standard", "国内首版次标准条件"),
            ("first_software_domestic_other_notice_condition", "国内首版次通知列明其他条件"),
        ],
    )

    result[("hangzhou-enterprise-institute", "hz-rd-entity")] = group(
        "hz-rd-entity",
        "all",
        [
            leaf("hz-rd-hangzhou", "hz_rd_registered_in_hangzhou", "杭州市注册"),
            group(
                "hz-rd-enterprise-route",
                "any",
                [
                    leaf("hz-rd-tech-enterprise", "hz_rd_municipal_or_above_technology_enterprise", "市级以上科技型企业"),
                    leaf("hz-rd-hte", "hz_rd_high_tech_enterprise", "高新技术企业"),
                    leaf("hz-rd-scale", "hz_rd_above_scale_industrial_enterprise", "规模以上工业企业"),
                ],
            ),
        ],
    )
    result[("hangzhou-enterprise-institute", "hz-rd-staff")] = group(
        "hz-rd-staff",
        "any",
        [
            group(
                "hz-rd-staff-software",
                "all",
                [
                    leaf("hz-rd-software-type", "hz_rd_is_software_enterprise", "软件企业"),
                    leaf("hz-rd-software-staff", "hz_rd_full_time_research_staff", "专职研发人员", operator="gte", expected=15, value_type="number", unit="人"),
                ],
            ),
            group(
                "hz-rd-staff-general",
                "all",
                [
                    leaf("hz-rd-nonsoftware-type", "hz_rd_is_software_enterprise", "软件企业", operator="falsy", expected=False),
                    leaf("hz-rd-general-staff", "hz_rd_full_time_research_staff", "专职研发人员", operator="gte", expected=10, value_type="number", unit="人"),
                ],
            ),
        ],
    )
    result[("hangzhou-enterprise-institute", "hz-rd-equipment")] = (
        atomic_assessment(
            "hz-rd-equipment",
            "hz_rd_applicable_equipment_threshold_assessment_passed",
            "按企业类型和研发人员规模适用的科研设备门槛通过",
        )
    )
    result[("hangzhou-enterprise-institute", "hz-rd-investment")] = group(
        "hz-rd-investment",
        "any",
        [
            leaf("hz-rd-investment-amount", "hz_rd_self_funded_expense", "上年度研发自筹投入", operator="gte", expected=200, value_type="number", unit="万元"),
            leaf("hz-rd-investment-ratio", "hz_rd_self_funded_expense_ratio", "研发自筹投入占销售收入比例", operator="gte", expected=3, value_type="number", unit="%"),
        ],
    )
    result[("hangzhou-enterprise-institute", "hz-rd-projects")] = group(
        "hz-rd-projects",
        "any",
        [
            leaf("hz-rd-municipal-projects", "hz_rd_municipal_or_above_project_count", "市级以上科研项目", operator="gte", expected=1, value_type="number", unit="项"),
            leaf("hz-rd-self-projects", "hz_rd_self_innovation_project_count", "企业自主立项技术创新项目", operator="gte", expected=3, value_type="number", unit="项"),
        ],
    )
    result[("hangzhou-enterprise-institute", "hz-rd-ip")] = group(
        "hz-rd-ip",
        "any",
        [
            leaf("hz-rd-class-i-ip", "hz_rd_class_i_ip_count", "发明专利等I类成果", operator="gte", expected=1, value_type="number", unit="项"),
            leaf("hz-rd-other-ip", "hz_rd_other_ip_count", "实用新型外观设计或软件著作权", operator="gte", expected=3, value_type="number", unit="项"),
        ],
    )

    for rule_id, field, label in (
        ("hz-tech-center-4", "hz_tech_center_applicable_staff_threshold_assessment_passed", "企业类型适用人员门槛评价通过"),
        ("hz-tech-center-5", "hz_tech_center_applicable_revenue_threshold_assessment_passed", "企业类型适用收入门槛评价通过"),
        ("hz-tech-center-6", "hz_tech_center_applicable_equipment_threshold_assessment_passed", "企业类型适用设备门槛评价通过"),
    ):
        result[("hangzhou-enterprise-technology-center", rule_id)] = (
            atomic_assessment(rule_id, field, label)
        )

    result[("little-giant", "little-giant-ip")] = group(
        "little-giant-ip",
        "any",
        [
            group(
                "little-giant-ip-general",
                "all",
                [
                    leaf("little-giant-ip-count", "little_giant_relevant_class_i_ip_count", "主导产品相关I类知识产权", operator="gte", expected=4, value_type="number", unit="项"),
                    leaf("little-giant-ip-applied", "little_giant_class_i_ip_applied", "I类知识产权已实际应用"),
                    leaf("little-giant-ip-benefit", "little_giant_class_i_ip_economic_benefit", "I类知识产权已产生经济效益"),
                ],
            ),
            leaf("little-giant-ip-exemption", "little_giant_ip_exemption_route_confirmed", "小巨人知识产权豁免路径经政策条款确认", fact_semantics="atomic-policy-assertion"),
        ],
    )
    result[("little-giant", "little-giant-market-share")] = group(
        "little-giant-market-share",
        "any",
        [
            leaf("little-giant-market-share-ratio", "little_giant_market_share_ratio", "主导产品全国细分市场占有率", operator="gte", expected=10, value_type="number", unit="%"),
            leaf("little-giant-market-rank", "little_giant_domestic_market_rank", "主导产品国内细分市场排名", operator="lte", expected=3, value_type="number", unit="名"),
        ],
    )
    result[("little-giant", "little-giant-review-refined-management")] = group(
        "little-giant-review-refined-management",
        "all",
        [
            leaf("little-giant-review-governance", "little_giant_governance_standardized", "公司治理规范"),
            leaf("little-giant-review-it", "little_giant_core_business_information_system_count", "采用信息系统的核心业务", operator="gte", expected=1, value_type="number", unit="项"),
            leaf("little-giant-review-certification", "little_giant_management_or_product_certification_count", "管理体系或产品认证", operator="gte", expected=1, value_type="number", unit="项"),
        ],
    )
    result[("little-giant", "little-giant-review-market-share")] = group(
        "little-giant-review-market-share",
        "all",
        [
            leaf("little-giant-review-share", "little_giant_market_share_ratio", "主导产品全国细分市场占有率", operator="gte", expected=10, value_type="number", unit="%"),
            leaf("little-giant-review-influence", "little_giant_market_influence_confirmed", "主导产品具有较高知名度和影响力"),
        ],
    )
    result[("little-giant", "little-giant-review-rnd")] = atomic_assessment(
        "little-giant-review-rnd",
        "little_giant_review_applicable_rnd_route_assessment_passed",
        "按2022复核过渡标准适用收入分档或创新直通研发路线通过",
    )
    result[("little-giant", "little-giant-review-ip")] = group(
        "little-giant-review-ip",
        "any",
        [
            group(
                "little-giant-review-ip-general",
                "all",
                [
                    leaf("little-giant-review-ip-count", "little_giant_relevant_class_i_ip_count", "主导产品相关I类知识产权", operator="gte", expected=2, value_type="number", unit="项"),
                    leaf("little-giant-review-ip-applied", "little_giant_class_i_ip_applied", "I类知识产权已实际应用"),
                    leaf("little-giant-review-ip-benefit", "little_giant_class_i_ip_economic_benefit", "I类知识产权已产生经济效益"),
                ],
            ),
            leaf("little-giant-review-ip-direct", "little_giant_innovation_direct_route_confirmed", "创新直通条件经政策条款确认", fact_semantics="atomic-policy-assertion"),
        ],
    )
    result[("little-giant", "little-giant-review-product-field")] = leaf(
        "little-giant-review-product-field",
        "little_giant_leading_product_field_match",
        "主导产品属于规定重点领域",
        fact_semantics="atomic-policy-assertion",
    )

    result[("manufacturing-single-champion-1", "zj-single-champion-3")] = group(
        "zj-single-champion-3",
        "any",
        [
            leaf("zj-single-champion-global-rank", "zj_single_champion_global_market_rank", "全球市场占有率排名", operator="lte", expected=5, value_type="number", unit="名"),
            leaf("zj-single-champion-national-rank", "zj_single_champion_national_market_rank", "全国市场占有率排名", operator="lte", expected=3, value_type="number", unit="名"),
        ],
    )
    result[("manufacturing-single-champion-1", "zj-single-champion-4")] = group(
        "zj-single-champion-4",
        "any",
        [
            leaf("zj-single-champion-revenue", "zj_single_champion_max_main_business_revenue_three_years", "近三年单年最高主营业务收入", operator="gte", expected=40000, value_type="number", unit="万元"),
            leaf("zj-single-champion-revenue-exception", "zj_single_champion_revenue_exception_confirmed", "收入豁免或降低路径经政策条款确认", fact_semantics="atomic-policy-assertion"),
        ],
    )
    result[("manufacturing-single-champion-1", "zj-single-champion-5")] = group(
        "zj-single-champion-5",
        "all",
        [
            group(
                "zj-single-champion-rd-platform",
                "any",
                [
                    leaf("zj-single-champion-platform", "zj_single_champion_provincial_rd_platform", "省级以上研发平台"),
                    leaf("zj-single-champion-platform-exception", "zj_single_champion_rd_platform_exception_confirmed", "研发平台例外经政策条款确认", fact_semantics="atomic-policy-assertion"),
                ],
            ),
            group(
                "zj-single-champion-rnd",
                "any",
                [
                    leaf("zj-single-champion-rnd-ratio", "zj_single_champion_rnd_ratio", "研发强度", operator="gte", expected=3, value_type="number", unit="%"),
                    leaf("zj-single-champion-rnd-leading", "zj_single_champion_rnd_industry_leading", "研发强度处于行业领先"),
                ],
            ),
            leaf("zj-single-champion-ip", "zj_single_champion_core_ip_applied_and_benefited", "核心知识产权已应用并产生效益"),
            leaf("zj-single-champion-standard", "zj_single_champion_standard_achievement_present", "标准成果有效"),
        ],
    )

    result[("manufacturing-single-champion-2", "single-champion-specialization")] = (
        atomic_assessment(
            "single-champion-specialization",
            "single_champion_applicable_specialization_years_assessment_passed",
            "一般产品或新产品适用专业化年限评价通过",
        )
    )

    result[("technology-sme-1", "zj-tech-sme-2")] = group(
        "zj-tech-sme-2",
        "all",
        [
            group(
                "zj-tech-sme-ip-route",
                "any",
                [
                    leaf("zj-tech-sme-patent", "zj_tech_sme_patent_present", "拥有专利"),
                    leaf("zj-tech-sme-standard", "zj_tech_sme_standard_present", "拥有标准"),
                    leaf("zj-tech-sme-trademark", "zj_tech_sme_trademark_present", "拥有商标"),
                    leaf("zj-tech-sme-achievement", "zj_tech_sme_scientific_achievement_present", "拥有科技成果"),
                    leaf("zj-tech-sme-proprietary", "zj_tech_sme_proprietary_technology_present", "拥有其他专有技术"),
                ],
            ),
            leaf("zj-tech-sme-product", "zj_tech_sme_corresponding_product_or_service_formed", "已形成对应产品或服务"),
        ],
    )

    result[("technology-sme-2", "technology-sme-score-or-direct")] = group(
        "technology-sme-score-or-direct",
        "any",
        [
            group(
                "technology-sme-score-route",
                "all",
                [
                    leaf("technology-sme-score", "technology_sme_evaluation_score", "科技型中小企业综合评价分值", operator="gte", expected=60, value_type="number", unit="分"),
                    leaf("technology-sme-personnel-score", "technology_sme_personnel_indicator_score", "科技人员指标得分", operator="gt", expected=0, value_type="number", unit="分"),
                ],
            ),
            leaf("technology-sme-direct-hte", "technology_sme_valid_high_tech_enterprise", "有效期内高新技术企业"),
            leaf("technology-sme-direct-award", "technology_sme_national_award_top_three_within_five_years", "近五年国家科技奖励前三完成单位"),
            leaf("technology-sme-direct-platform", "technology_sme_provincial_or_above_rd_platform", "省部级以上研发机构"),
            leaf("technology-sme-direct-standard", "technology_sme_led_standard_within_five_years", "近五年主导制定国际国家或行业标准"),
        ],
    )

    result[("zhejiang-enterprise-technology-center", "zj-tech-center-4")] = (
        atomic_assessment(
            "zj-tech-center-4",
            "zj_tech_center_applicable_rnd_ratio_assessment_passed",
            "按行业和收入规模适用的研发经费比例评价通过",
        )
    )

    result[("zhejiang-hidden-champion", "hidden-credit")] = group(
        "hidden-credit",
        "any",
        [
            leaf("hidden-credit-bank", "hidden_champion_bank_credit_grade_a_or_above", "银行资信等级A级以上"),
            leaf("hidden-credit-pbc", "hidden_champion_pbc_credit_no_adverse_record", "人民银行征信无不良记录"),
        ],
    )
    for rule_id in ("hidden-market-rank", "hidden-review-market"):
        result[("zhejiang-hidden-champion", rule_id)] = group(
            rule_id,
            "any",
            [
                leaf(f"{rule_id}-global", "hidden_champion_global_market_rank", "主导产品全球细分市场排名", operator="lte", expected=10, value_type="number", unit="名"),
                leaf(f"{rule_id}-national", "hidden_champion_national_market_rank", "主导产品全国细分市场排名", operator="lte", expected=3, value_type="number", unit="名"),
            ],
        )
    result[("zhejiang-hidden-champion", "hidden-rd-it")] = group(
        "hidden-rd-it",
        "all",
        [
            leaf("hidden-rd-institution", "hidden_champion_rd_institution_established", "已自建或联合建立研发机构"),
            group(
                "hidden-core-it",
                "any",
                [
                    leaf("hidden-rd-system", "hidden_champion_rd_information_system_used", "研发核心业务采用信息系统"),
                    leaf("hidden-production-system", "hidden_champion_production_information_system_used", "生产核心业务采用信息系统"),
                    leaf("hidden-supply-system", "hidden_champion_supply_information_system_used", "供应核心业务采用信息系统"),
                ],
            ),
        ],
    )
    result[("zhejiang-hidden-champion", "hidden-standard-brand")] = group(
        "hidden-standard-brand",
        "all",
        [
            leaf("hidden-standard-count", "hidden_champion_standard_participation_count", "主导或参与国际国家或行业标准", operator="gte", expected=1, value_type="number", unit="项"),
            leaf("hidden-brand", "hidden_champion_independent_brand_owned", "拥有自主品牌"),
            leaf("hidden-certification", "hidden_champion_international_certification_count", "国际相关认证", operator="gte", expected=1, value_type="number", unit="项"),
        ],
    )

    result[("zhejiang-key-enterprise-institute", "zj-key-institute-platform")] = group(
        "zj-key-institute-platform",
        "any",
        [
            leaf("zj-key-platform-enterprise-institute", "key_institute_has_zhejiang_enterprise_institute", "已建省企业研究院"),
            leaf("zj-key-platform-rd-center", "key_institute_has_zhejiang_high_tech_rd_center", "已建省高新技术企业研究开发中心"),
            leaf("zj-key-platform-tech-center", "key_institute_has_provincial_technology_center", "已建省级企业技术中心"),
        ],
    )

    quality_routes: list[dict[str, object]] = []
    category_thresholds = [
        ("先进制造类", 800, 500),
        ("数字技术融合类", 600, 300),
        ("特色（消费品）类", 600, 300),
    ]
    for category_index, (category, general, mountain) in enumerate(
        category_thresholds, start=1
    ):
        for mountain_flag, threshold, suffix in (
            (False, general, "general"),
            (True, mountain, "mountain"),
        ):
            quality_routes.append(
                group(
                    f"quality-sales-{category_index}-{suffix}",
                    "all",
                    [
                        leaf(f"quality-category-{category_index}-{suffix}", "quality_product_category", "申报产品类别", operator="equals", expected=category, value_type="string"),
                        leaf(f"quality-mountain-{category_index}-{suffix}", "quality_mountain_county", "山区26县企业", operator="truthy" if mountain_flag else "falsy", expected=mountain_flag),
                        leaf(f"quality-sales-{category_index}-{suffix}-amount", "quality_annual_product_sales", "产品上市后每年销售收入", operator="gte", expected=threshold, value_type="number", unit="万元"),
                    ],
                )
            )
    result[("zhejiang-manufacturing-quality", "quality-sales-branch")] = group(
        "quality-sales-branch",
        "any",
        quality_routes,
    )

    result[("zhejiang-specialized-sme", "specialized-sme-revenue-or-investment")] = group(
        "specialized-sme-revenue-or-investment",
        "any",
        [
            leaf("specialized-sme-revenue", "revenue", "上年度营业收入", operator="gte", expected=1500, value_type="number", unit="万元"),
            leaf("specialized-sme-equity-investment", "qualified_equity_investment_two_years", "近两年合格机构投资者实缴股权投资", operator="gte", expected=2000, value_type="number", unit="万元"),
        ],
    )
    result[("zhejiang-specialized-sme", "specialized-sme-ip")] = group(
        "specialized-sme-ip",
        "any",
        [
            group(
                "specialized-sme-ip-general",
                "all",
                [
                    leaf("specialized-sme-ip-count", "specialized_sme_relevant_class_i_ip_count", "主导产品相关I类知识产权", operator="gte", expected=1, value_type="number", unit="项"),
                    leaf("specialized-sme-ip-applied", "specialized_sme_class_i_ip_applied", "I类知识产权已实际应用"),
                    leaf("specialized-sme-ip-benefit", "specialized_sme_class_i_ip_economic_benefit", "I类知识产权已产生经济效益"),
                ],
            ),
            leaf("specialized-sme-ip-exemption", "specialized_sme_ip_exemption_route_confirmed", "专精特新知识产权豁免路径经政策条款确认", fact_semantics="atomic-policy-assertion"),
        ],
    )

    result[("digital-workshop", "digital_workshop-1")] = group(
        "digital_workshop-1",
        "all",
        [
            leaf(
                "digital-workshop-zhejiang-manufacturer",
                "digital_workshop_applicant_is_zhejiang_manufacturer",
                "申报主体为浙江省制造业企业",
            ),
            leaf(
                "digital-workshop-project-scope",
                "digital_workshop_project_in_digital_transformation_scope",
                "项目属于制造业数字化转型梯度培育范围",
            ),
        ],
    )
    result[("digital-workshop", "digital_workshop-2")] = leaf(
        "digital_workshop-2",
        "digital_workshop_in_provincial_cultivation_pool",
        "数字化车间项目已纳入省级培育库",
        fact_semantics="atomic-policy-assertion",
    )
    result[("future-factory", "future_factory-1")] = group(
        "future_factory-1",
        "all",
        [
            leaf(
                "future-factory-zhejiang-manufacturer",
                "future_factory_applicant_is_zhejiang_manufacturer",
                "申报主体为浙江省制造业企业",
            ),
            leaf(
                "future-factory-project-scope",
                "future_factory_project_in_digital_transformation_scope",
                "项目属于制造业数字化转型梯度培育范围",
            ),
        ],
    )
    result[("future-factory", "future_factory-2")] = leaf(
        "future_factory-2",
        "future_factory_is_pilot_cultivation_enterprise",
        "企业属于未来工厂试点培育企业",
        fact_semantics="atomic-policy-assertion",
    )
    result[("intelligent-factory", "intelligent_factory-1")] = group(
        "intelligent_factory-1",
        "all",
        [
            leaf(
                "intelligent-factory-zhejiang-manufacturer",
                "intelligent_factory_applicant_is_zhejiang_manufacturer",
                "申报主体为浙江省制造业企业",
            ),
            leaf(
                "intelligent-factory-project-scope",
                "intelligent_factory_project_in_digital_transformation_scope",
                "项目属于制造业数字化转型梯度培育范围",
            ),
        ],
    )
    result[("intelligent-factory", "intelligent_factory-2")] = leaf(
        "intelligent_factory-2",
        "intelligent_factory_in_provincial_cultivation_pool",
        "智能工厂项目已纳入省级培育库",
        fact_semantics="atomic-policy-assertion",
    )

    result[("first-equipment", "first-equipment-4")] = group(
        "first-equipment-4",
        "all",
        [
            leaf(
                "first-equipment-market-performance",
                "first_equipment_initial_market_performance_realized",
                "产品已形成初步市场业绩",
            ),
            leaf(
                "first-equipment-first-promotion",
                "first_equipment_still_in_first_promotion_stage",
                "产品仍处于首台套首次推广应用阶段",
            ),
        ],
    )
    result[("first-equipment", "first-equipment-5")] = group(
        "first-equipment-5",
        "all",
        [
            leaf(
                "first-equipment-breakthrough",
                "first_equipment_major_technical_breakthrough_confirmed",
                "产品具有重大技术突破",
            ),
            leaf(
                "first-equipment-core-ip",
                "first_equipment_core_independent_ip_owned",
                "产品拥有核心自主知识产权",
            ),
        ],
    )
    result[("first-equipment", "first-equipment-6")] = group(
        "first-equipment-6",
        "any",
        [
            leaf(
                "first-equipment-acceptance-not-required",
                "first_equipment_engineering_acceptance_required",
                "工程化攻关入库验收要求",
                operator="falsy",
                expected=False,
            ),
            group(
                "first-equipment-acceptance-route",
                "all",
                [
                    leaf(
                        "first-equipment-acceptance-required",
                        "first_equipment_engineering_acceptance_required",
                        "工程化攻关入库验收要求",
                    ),
                    leaf(
                        "first-equipment-project-in-pool",
                        "first_equipment_engineering_project_in_pool",
                        "工程化攻关项目已纳入项目库",
                    ),
                    leaf(
                        "first-equipment-project-accepted",
                        "first_equipment_engineering_project_accepted",
                        "工程化攻关项目已经验收",
                    ),
                ],
            ),
        ],
    )

    result[("first-software-version", "first-software-3")] = group(
        "first-software-3",
        "all",
        [
            leaf(
                "first-software-premises",
                "first_software_development_premises_available",
                "具有与软件开发相适应的经营场所",
            ),
            leaf(
                "first-software-environment",
                "first_software_legal_hardware_software_environment_available",
                "具有合法软硬件开发环境",
            ),
            leaf(
                "first-software-talent",
                "first_software_development_talent_support_available",
                "具有软件开发人才支撑",
            ),
        ],
    )
    result[("first-software-version", "first-software-4")] = leaf(
        "first-software-4",
        "first_software_in_current_guidance_catalog",
        "软件产品属于当年度首版次申报指导目录",
        fact_semantics="atomic-policy-assertion",
    )
    result[("first-software-version", "first-software-5")] = group(
        "first-software-5",
        "all",
        [
            leaf(
                "first-software-copyright-date",
                "first_software_copyright_after_notice_cutoff",
                "软件著作权取得时间符合通知要求",
            ),
            group(
                "first-software-copyright-owner-route",
                "any",
                [
                    leaf(
                        "first-software-first-owner",
                        "first_software_applicant_is_first_copyright_owner",
                        "申报单位为第一著作权人",
                    ),
                    group(
                        "first-software-co-owner-route",
                        "all",
                        [
                            leaf(
                                "first-software-co-owned",
                                "first_software_copyright_is_co_owned",
                                "软件著作权为共有权",
                            ),
                            leaf(
                                "first-software-co-owner-consent",
                                "first_software_co_owner_consent_obtained",
                                "已取得其他共有人同意",
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )

    for green_project in ("green-factory-1", "green-factory-2", "green-factory-3"):
        result[(green_project, f"{green_project}-2")] = group(
            f"{green_project}-2",
            "all",
            [
                leaf(f"{green_project}-legal", f"{green_project.replace('-', '_')}_legally_established", "企业依法设立"),
                leaf(f"{green_project}-construction", f"{green_project.replace('-', '_')}_construction_compliance_clear", "建设活动合规"),
                leaf(f"{green_project}-production", f"{green_project.replace('-', '_')}_production_compliance_clear", "生产活动合规"),
                leaf(f"{green_project}-quality", f"{green_project.replace('-', '_')}_quality_compliance_clear", "质量合规"),
                leaf(f"{green_project}-safety", f"{green_project.replace('-', '_')}_safety_compliance_clear", "安全合规"),
                leaf(f"{green_project}-environment", f"{green_project.replace('-', '_')}_environmental_compliance_clear", "环保合规"),
                leaf(f"{green_project}-energy", f"{green_project.replace('-', '_')}_energy_compliance_clear", "节能合规"),
            ],
        )
        result[(green_project, f"{green_project}-3")] = group(
            f"{green_project}-3",
            "all",
            [
                leaf(f"{green_project}-green-system", f"{green_project.replace('-', '_')}_green_development_system_established", "绿色发展制度已建立"),
                leaf(f"{green_project}-energy-system", f"{green_project.replace('-', '_')}_energy_management_system_established", "能源管理体系已建立"),
                leaf(f"{green_project}-resource-system", f"{green_project.replace('-', '_')}_resource_management_system_established", "资源管理体系已建立"),
                leaf(f"{green_project}-environment-system", f"{green_project.replace('-', '_')}_environment_management_system_established", "环境管理体系已建立"),
                leaf(f"{green_project}-quality-system", f"{green_project.replace('-', '_')}_quality_management_system_established", "质量管理体系已建立"),
                leaf(f"{green_project}-safety-system", f"{green_project.replace('-', '_')}_safety_management_system_established", "安全管理体系已建立"),
            ],
        )
        result[(green_project, f"{green_project}-4")] = group(
            f"{green_project}-4",
            "all",
            [
                leaf(f"{green_project}-basic-requirements", f"{green_project.replace('-', '_')}_evaluation_basic_requirements_passed", "适用评价标准基本要求通过"),
                leaf(f"{green_project}-mandatory-indicators", f"{green_project.replace('-', '_')}_mandatory_indicators_passed", "适用评价标准必选指标通过"),
                leaf(f"{green_project}-local-score", f"{green_project.replace('-', '_')}_local_score_threshold_passed", "属地评分门槛通过"),
            ],
        )

    result[("hangzhou-enterprise-technology-center", "hz-tech-center-1")] = group(
        "hz-tech-center-1",
        "all",
        [
            leaf("hz-tech-center-operation", "hz_tech_center_innovation_operation_mechanism_sound", "创新运行机制健全"),
            leaf("hz-tech-center-investment", "hz_tech_center_innovation_investment_mechanism_sound", "创新投入机制健全"),
            leaf("hz-tech-center-incentive", "hz_tech_center_innovation_incentive_mechanism_sound", "创新激励机制健全"),
            leaf("hz-tech-center-strategy", "hz_tech_center_innovation_strategy_sound", "创新战略健全"),
            leaf("hz-tech-center-plan", "hz_tech_center_innovation_plan_sound", "创新计划健全"),
            leaf("hz-tech-center-ip-management", "hz_tech_center_ip_management_capability_sound", "知识产权管理能力健全"),
        ],
    )
    result[("hangzhou-enterprise-technology-center", "hz-tech-center-2")] = group(
        "hz-tech-center-2",
        "all",
        [
            leaf("hz-tech-center-economic-leading", "hz_tech_center_economic_technical_indicators_city_leading", "综合经济技术指标处于本市同行业前列"),
            leaf("hz-tech-center-development-leading", "hz_tech_center_technical_development_capability_city_leading", "技术开发能力处于本市同行业前列"),
        ],
    )

    result[("key-little-giant-support", "key-little-giant-3")] = group(
        "key-little-giant-3",
        "all",
        [
            leaf("key-lg-plan-momentum", "key_lg_plan_covers_new_momentum", "实施计划覆盖打造新动能"),
            leaf("key-lg-plan-technology", "key_lg_plan_covers_technology_breakthrough", "实施计划覆盖攻坚新技术"),
            leaf("key-lg-plan-product", "key_lg_plan_covers_new_product", "实施计划覆盖开发新产品"),
            leaf("key-lg-plan-chain", "key_lg_plan_covers_supply_chain_capability", "实施计划覆盖强化产业链配套能力"),
        ],
    )
    result[("key-little-giant-support", "key-little-giant-4")] = group(
        "key-little-giant-4",
        "all",
        [
            leaf("key-lg-project-scope", "key_lg_project_scope_complies", "实施项目符合支持范围"),
            leaf("key-lg-investment-plan", "key_lg_investment_plan_complies", "投资计划符合支持通知和实施方案"),
            leaf("key-lg-fund-use", "key_lg_fund_use_complies", "资金用途符合支持通知和实施方案"),
        ],
    )
    result[("key-little-giant-support", "key-little-giant-5")] = group(
        "key-little-giant-5",
        "all",
        [
            leaf("key-lg-target-quantifiable", "key_lg_performance_targets_quantifiable", "阶段性绩效目标可量化"),
            leaf("key-lg-target-assessable", "key_lg_performance_targets_assessable", "阶段性绩效目标可考核"),
        ],
    )
    result[("key-little-giant-support", "key-little-giant-6")] = group(
        "key-little-giant-6",
        "all",
        [
            leaf("key-lg-sme-recommendation", "key_lg_recommended_by_local_sme_authority", "经地方中小企业主管部门推荐"),
            leaf("key-lg-finance-recommendation", "key_lg_recommended_by_local_finance_authority", "经地方财政部门推荐"),
            leaf("key-lg-quota-procedure", "key_lg_recommendation_quota_and_procedure_complies", "推荐名额和程序符合要求"),
        ],
    )

    for rule_id, field, label in (
        ("little-giant-rnd", "little_giant_applicable_rnd_assessment_passed", "近两年研发费用合计和逐年研发强度适用门槛评价通过"),
        ("little-giant-industry-chain", "little_giant_industry_chain_role_assessment_passed", "主导产品产业链关键环节与作用评价通过"),
        ("little-giant-review-brand", "little_giant_independent_brand_assessment_passed", "自主品牌及市场竞争优势评价通过"),
        ("little-giant-review-industry-chain", "little_giant_review_industry_chain_role_assessment_passed", "复核产业链关键环节与补短板作用评价通过"),
    ):
        result[("little-giant", rule_id)] = atomic_assessment(
            rule_id,
            field,
            label,
        )

    specialization_routes: list[dict[str, object]] = []
    for is_mountain, product_type, threshold, suffix in (
        (False, "一般产品", 6, "general-normal"),
        (False, "新产品", 3, "new-normal"),
        (True, "一般产品", 5, "general-mountain"),
        (True, "新产品", 2, "new-mountain"),
    ):
        specialization_routes.append(
            group(
                f"zj-single-champion-specialization-{suffix}",
                "all",
                [
                    leaf(
                        f"zj-single-champion-product-type-{suffix}",
                        "zj_single_champion_product_type",
                        "产品类型",
                        operator="equals",
                        expected=product_type,
                        value_type="string",
                    ),
                    leaf(
                        f"zj-single-champion-mountain-{suffix}",
                        "zj_single_champion_mountain_island_county",
                        "山区海岛县企业",
                        operator="truthy" if is_mountain else "falsy",
                        expected=is_mountain,
                    ),
                    leaf(
                        f"zj-single-champion-years-{suffix}",
                        "zj_single_champion_specialization_years",
                        "从事相关领域年限",
                        operator="gte",
                        expected=threshold,
                        value_type="number",
                        unit="年",
                    ),
                ],
            )
        )
    result[("manufacturing-single-champion-1", "zj-single-champion-2")] = group(
        "zj-single-champion-2",
        "any",
        specialization_routes,
    )
    result[("manufacturing-single-champion-1", "zj-single-champion-6")] = group(
        "zj-single-champion-6",
        "all",
        [
            leaf("zj-single-champion-quality", "zj_single_champion_product_quality_domestic_leading", "产品质量国内领先"),
            leaf("zj-single-champion-process", "zj_single_champion_process_domestic_leading", "生产工艺国内领先"),
            leaf("zj-single-champion-performance", "zj_single_champion_key_performance_domestic_leading", "关键性能国内领先"),
            leaf("zj-single-champion-energy", "zj_single_champion_energy_use_industry_advanced", "能耗达到行业先进值"),
            leaf("zj-single-champion-green", "zj_single_champion_green_low_carbon_level_high", "绿色低碳水平较高"),
        ],
    )
    result[("manufacturing-single-champion-1", "zj-single-champion-7")] = group(
        "zj-single-champion-7",
        "all",
        [
            leaf("zj-single-champion-profit", "zj_single_champion_profitability_complies", "盈利能力符合要求"),
            leaf("zj-single-champion-lean", "zj_single_champion_lean_management_complies", "精益管理能力符合要求"),
            leaf("zj-single-champion-digital", "zj_single_champion_digital_capability_complies", "数字化能力符合要求"),
            leaf("zj-single-champion-talent", "zj_single_champion_talent_capability_complies", "人才能力符合要求"),
            leaf("zj-single-champion-brand", "zj_single_champion_brand_capability_complies", "品牌能力符合要求"),
            leaf("zj-single-champion-international", "zj_single_champion_internationalization_complies", "国际化能力符合要求"),
        ],
    )

    result[("manufacturing-single-champion-2", "single-champion-market")] = leaf(
        "single-champion-market",
        "single_champion_global_market_rank",
        "申请产品全球市场占有率排名",
        operator="lte",
        expected=3,
        value_type="number",
        unit="名",
    )
    result[("manufacturing-single-champion-2", "single-champion-product")] = group(
        "single-champion-product",
        "all",
        [
            leaf("single-champion-product-quality", "single_champion_product_quality_leading", "产品质量达到领先标准"),
            leaf("single-champion-product-performance", "single_champion_key_performance_leading", "关键性能达到领先标准"),
            leaf("single-champion-product-energy", "single_champion_energy_level_leading", "能耗水平达到领先标准"),
        ],
    )
    result[("manufacturing-single-champion-2", "single-champion-innovation")] = group(
        "single-champion-innovation",
        "all",
        [
            leaf("single-champion-rd-institution", "single_champion_high_level_rd_institution", "具备高水平研发机构"),
            leaf("single-champion-rd-investment", "single_champion_rd_investment_complies", "研发投入符合要求"),
            leaf("single-champion-core-ip", "single_champion_core_independent_ip_owned", "拥有核心自主知识产权"),
        ],
    )
    result[("manufacturing-single-champion-2", "single-champion-management")] = group(
        "single-champion-management",
        "all",
        [
            leaf("single-champion-benefit", "single_champion_operating_benefit_complies", "经营效益符合要求"),
            leaf("single-champion-system", "single_champion_management_system_complies", "管理体系符合要求"),
            leaf("single-champion-talent", "single_champion_talent_team_complies", "人才队伍符合要求"),
            leaf("single-champion-brand", "single_champion_brand_internationalization_complies", "品牌国际化能力符合要求"),
        ],
    )

    result[("municipal-enterprise-technology-center", "municipal-tech-center-3")] = atomic_assessment(
        "municipal-tech-center-3",
        "municipal_tc_applicable_local_threshold_assessment_passed",
        "按属地现行办法适用的收入研发人员设备组织及资质门槛评价通过",
    )
    result[("technology-sme-1", "zj-tech-sme-1")] = group(
        "zj-tech-sme-1",
        "all",
        [
            leaf("zj-tech-sme-zhejiang", "zj_tech_sme_registered_in_zhejiang", "企业在浙江省登记注册"),
            leaf("zj-tech-sme-age", "zj_tech_sme_registration_days", "企业成立时间", operator="gte", expected=365, value_type="number", unit="天"),
            leaf("zj-tech-sme-property", "zj_tech_sme_property_rights_clear", "企业产权明晰"),
            leaf("zj-tech-sme-accounting", "zj_tech_sme_independent_accounting", "企业实行独立核算"),
            leaf("zj-tech-sme-operation", "zj_tech_sme_independent_operation", "企业自主经营"),
            leaf("zj-tech-sme-risk", "zj_tech_sme_self_responsible_profit_loss", "企业自负盈亏"),
        ],
    )
    result[("technology-sme-1", "zj-tech-sme-3")] = group(
        "zj-tech-sme-3",
        "all",
        [
            leaf("zj-tech-sme-investment", "zj_tech_sme_has_innovation_investment", "企业具有科技创新经费投入"),
            leaf("zj-tech-sme-continuity", "zj_tech_sme_continuous_innovation_capability", "企业具备持续科技创新活动能力"),
        ],
    )
    result[("technology-sme-1", "zj-tech-sme-4")] = leaf(
        "zj-tech-sme-4",
        "zj_tech_sme_size_standard_confirmed",
        "企业符合中小企业划型标准",
        fact_semantics="atomic-policy-assertion",
    )

    result[("zhejiang-enterprise-institute", "zj-institute-foundation")] = group(
        "zj-institute-foundation",
        "all",
        [
            leaf("zj-institute-talent", "zj_institute_talent_team_satisfied", "人才队伍条件符合"),
            leaf("zj-institute-ip", "zj_institute_independent_ip_satisfied", "自主知识产权条件符合"),
            leaf("zj-institute-rd", "zj_institute_rd_foundation_satisfied", "研发基础条件符合"),
        ],
    )

    result[("zhejiang-enterprise-technology-center", "zj-tech-center-1")] = group(
        "zj-tech-center-1",
        "all",
        [
            leaf("zj-tech-center-economic", "zj_tech_center_economic_technical_indicators_comply", "综合经济技术指标符合要求"),
            leaf("zj-tech-center-development", "zj_tech_center_technical_development_capability_complies", "技术开发能力符合要求"),
            leaf("zj-tech-center-value", "zj_tech_center_product_added_value_complies", "产品附加值符合要求"),
        ],
    )
    tech_center_branches = [
        ("manufacturing-general", "制造业", False, 20000, 1200, 50),
        ("manufacturing-county", "制造业", True, 10000, 800, 30),
        ("construction", "建筑业", False, 150000, 800, 50),
        ("high-tech-service", "高技术服务业", False, 5000, 1000, 50),
    ]
    for rule_id, field, label, value_field, unit in (
        ("zj-tech-center-2", "revenue", "营业收入或结算收入", "revenue", "万元"),
        ("zj-tech-center-3", "equipment", "科研仪器设备原值", "equipment", "万元"),
        ("zj-tech-center-5", "staff", "研发或开发人员数量", "staff", "人"),
    ):
        routes: list[dict[str, object]] = []
        value_index = {"revenue": 3, "equipment": 4, "staff": 5}[value_field]
        for suffix, industry, county, revenue_value, equipment_value, staff_value in tech_center_branches:
            values = (revenue_value, equipment_value, staff_value)
            branch_children = [
                leaf(f"{rule_id}-{suffix}-industry", "zj_tech_center_industry_type", "企业行业类型", operator="equals", expected=industry, value_type="string"),
                leaf(f"{rule_id}-{suffix}-value", f"zj_tech_center_{field}_value", label, operator="gte", expected=values[value_index - 3], value_type="number", unit=unit),
            ]
            if industry == "制造业":
                branch_children.insert(
                    1,
                    leaf(f"{rule_id}-{suffix}-county", "zj_tech_center_accelerated_development_county", "加快发展县企业", operator="truthy" if county else "falsy", expected=county),
                )
            routes.append(
                group(
                    f"{rule_id}-{suffix}",
                    "all",
                    branch_children,
                )
            )
        result[("zhejiang-enterprise-technology-center", rule_id)] = group(
            rule_id,
            "any",
            routes,
        )

    for rule_id in ("hidden-specialization", "hidden-review-specialization"):
        result[("zhejiang-hidden-champion", rule_id)] = group(
            rule_id,
            "all",
            [
                leaf(f"{rule_id}-years", "hidden_champion_specialization_years", "持续深耕细分领域年限", operator="gte", expected=10, value_type="number", unit="年"),
                leaf(f"{rule_id}-products", "hidden_champion_leading_product_count", "主导产品数量", operator="lte", expected=3, value_type="number", unit="个"),
                leaf(f"{rule_id}-ratio", "hidden_champion_main_business_revenue_ratio", "主营业务收入占营业收入比例", operator="gte", expected=70, value_type="number", unit="%"),
            ],
        )
    result[("zhejiang-industrial-new-product", "industrial-new-product-2023-thresholds")] = atomic_assessment(
        "industrial-new-product-2023-thresholds",
        "industrial_new_product_2023_policy_assessment_passed",
        "按2023年度有效政策完成历史资格评价",
    )
    result[("zhejiang-key-enterprise-institute", "zj-key-institute-foundation")] = group(
        "zj-key-institute-foundation",
        "all",
        [
            leaf("zj-key-institute-core-ip", "zj_key_institute_core_independent_ip_satisfied", "核心自主知识产权条件符合"),
            leaf("zj-key-institute-talent", "zj_key_institute_talent_team_satisfied", "人才队伍条件符合"),
            leaf("zj-key-institute-rd", "zj_key_institute_rd_foundation_satisfied", "研发基础条件符合"),
        ],
    )
    result[("zhejiang-key-specialized-sme", "key-zj-sme-plan")] = group(
        "key-zj-sme-plan",
        "all",
        [
            leaf("key-zj-sme-plan-project", "key_zj_sme_plan_has_specific_projects", "推进计划包含具体项目"),
            leaf("key-zj-sme-plan-target", "key_zj_sme_plan_has_performance_targets", "推进计划包含绩效目标"),
            leaf("key-zj-sme-plan-theme", "key_zj_sme_plan_matches_four_improvements_one_strength", "推进计划符合融通入链四提一强方向", fact_semantics="atomic-policy-assertion"),
        ],
    )
    result[("zhejiang-key-specialized-sme", "key-zj-sme-project-scope")] = group(
        "key-zj-sme-project-scope",
        "all",
        [
            leaf("key-zj-sme-not-technical-renovation", "key_zj_sme_project_is_technical_renovation", "拟实施项目属于技术改造项目", operator="falsy", expected=False),
            leaf("key-zj-sme-not-digital-renovation", "key_zj_sme_project_is_digital_network_intelligent_renovation", "拟实施项目属于数字化网络化智能化改造", operator="falsy", expected=False),
            leaf("key-zj-sme-not-basic-research", "key_zj_sme_project_is_basic_research", "拟实施项目属于基础研究项目", operator="falsy", expected=False),
        ],
    )
    result[("zhejiang-key-specialized-sme", "key-zj-sme-size")] = leaf(
        "key-zj-sme-size",
        "key_zj_sme_size_standard_confirmed",
        "企业符合中小企业划型标准",
        fact_semantics="atomic-policy-assertion",
    )
    result[("zhejiang-key-specialized-sme", "key-zj-sme-industry")] = leaf(
        "key-zj-sme-industry",
        "key_zj_sme_in_priority_industry",
        "企业属于重点产业领域",
        fact_semantics="atomic-policy-assertion",
    )
    result[("zhejiang-manufacturing-2", "pin-zhejiang-manufacturing-3")] = group(
        "pin-zhejiang-manufacturing-3",
        "all",
        [
            leaf("pin-zhejiang-manufacturing-product", "pin_zhejiang_manufacturing_product_standard_passed", "产品满足适用标准和评价细则"),
            leaf("pin-zhejiang-manufacturing-process", "pin_zhejiang_manufacturing_process_standard_passed", "生产过程满足适用标准和评价细则"),
            leaf("pin-zhejiang-manufacturing-quality", "pin_zhejiang_manufacturing_quality_assurance_passed", "质量保证能力满足适用标准和评价细则"),
            leaf("pin-zhejiang-manufacturing-inspection", "pin_zhejiang_manufacturing_inspection_capability_passed", "检验能力满足适用标准和评价细则"),
        ],
    )
    result[("zhejiang-manufacturing-quality", "quality-product")] = group(
        "quality-product",
        "all",
        [
            leaf("quality-product-focus", "quality_product_focuses_niche_market", "产品聚焦细分市场"),
            leaf("quality-product-market", "quality_product_market_share_high", "产品市场占有率较高"),
            leaf("quality-product-technology", "quality_product_technology_leading", "产品技术领先"),
            leaf("quality-product-ip", "quality_product_core_technology_and_ip_owned", "产品具有关键核心技术和自主知识产权"),
        ],
    )
    result[("zhejiang-manufacturing-quality", "quality-listing-period")] = atomic_assessment(
        "quality-listing-period",
        "quality_product_current_notice_listing_period_assessment_passed",
        "产品上市时间符合当年度通知规定范围",
    )
    result[("zhejiang-manufacturing-quality", "quality-one-product")] = leaf(
        "quality-one-product",
        "quality_product_submission_count",
        "企业本次申报浙江制造精品数量",
        operator="lte",
        expected=1,
        value_type="number",
        unit="个",
    )
    result[("zhejiang-specialized-sme", "specialized-sme-entry-status")] = group(
        "specialized-sme-entry-status",
        "all",
        [
            leaf("specialized-sme-technology-status", "technology_sme_status", "科技型中小企业资格有效"),
            leaf("specialized-sme-innovative-status", "innovative_sme_status", "创新型中小企业资格有效"),
        ],
    )
    result[("zhejiang-specialized-sme", "specialized-sme-rnd")] = atomic_assessment(
        "specialized-sme-rnd",
        "specialized_sme_two_year_rd_assessment_passed",
        "近两年研发费用和逐年研发强度适用门槛评价通过",
    )
    result[("zhejiang-specialized-sme", "specialized-sme-market-influence")] = atomic_assessment(
        "specialized-sme-market-influence",
        "specialized_sme_market_influence_assessment_passed",
        "主导产品细分市场占有率与影响力评价通过",
    )
    return result


MIGRATIONS = _migrations()


def _walk_rule_lists(payload: dict[str, Any]) -> list[list[dict[str, Any]]]:
    lists: list[list[dict[str, Any]]] = []
    if isinstance(payload.get("rules"), list):
        lists.append(payload["rules"])
    for key in ("annual_overlays", "jurisdiction_overlays"):
        for overlay in payload.get(key, []):
            if isinstance(overlay, dict) and isinstance(overlay.get("rules"), list):
                lists.append(overlay["rules"])
    return lists


def _leaf_fields(rules: list[dict[str, Any]]) -> set[str]:
    fields: set[str] = set()
    for rule in rules:
        children = rule.get("children")
        if isinstance(children, list):
            fields.update(
                _leaf_fields(
                    [child for child in children if isinstance(child, dict)]
                )
            )
        elif str(rule.get("field") or ""):
            fields.add(str(rule["field"]))
    return fields


def normalize_source_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(payload)
    project_id = str(normalized.get("project_id") or "")
    added_facts: dict[str, dict[str, object]] = {}
    replaced: list[str] = []
    for rules in _walk_rule_lists(normalized):
        for index, rule in enumerate(rules):
            rule_id = str(rule.get("rule_id") or "")
            migration = MIGRATIONS.get((project_id, rule_id))
            if migration is None:
                continue
            migrated = copy.deepcopy(migration["rule"])
            migrated.update(
                {
                    key: copy.deepcopy(rule[key])
                    for key in ("type", "source", "source_quote", "unit")
                    if key in rule
                }
            )
            migrated["rule_id"] = rule_id
            rules[index] = migrated
            for fact_spec in migration["facts"]:
                added_facts[str(fact_spec["field"])] = copy.deepcopy(fact_spec)
            replaced.append(rule_id)
    if not replaced:
        return normalized

    rule_lists = _walk_rule_lists(normalized)
    referenced = set().union(*(_leaf_fields(rules) for rules in rule_lists))
    existing_facts = {
        str(item.get("field") or ""): item
        for item in normalized.get("fact_fields", [])
        if isinstance(item, dict)
    }
    existing_facts.update(added_facts)
    normalized["fact_fields"] = [
        fact_spec
        for field, fact_spec in existing_facts.items()
        if field in referenced
    ]
    normalized.pop("gold_cases", None)
    normalized["composite_rule_migration"] = {
        "version": "native-all-any-v1",
        "replaced_rule_ids": sorted(replaced),
        "legacy_rollup_inputs_removed": True,
    }
    return normalized


def write_json(path: Path, payload: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    changed: list[str] = []
    for path in sorted(SOURCE_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        normalized = normalize_source_payload(payload)
        if normalized != payload:
            write_json(path, normalized)
            changed.append(path.stem)
    print(
        json.dumps(
            {
                "status": "pass",
                "changed_projects": changed,
                "changed_count": len(changed),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
