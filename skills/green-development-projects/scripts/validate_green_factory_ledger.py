#!/usr/bin/env python3
"""校验绿色工厂自评价台账，逐项报告要求、现状及补强动作。"""

from __future__ import annotations

import argparse
import json
import math
from datetime import date
from pathlib import Path
from typing import Any


POLICY_STATUSES = {"current", "stale", "unknown"}
EVALUATION_MODES = {"current_application", "historical_audit", "draft"}
LEDGER_SCOPES = {"complete", "partial"}
EVIDENCE_STATUSES = {"verified", "unverified", "conflicted", "expired"}
BASIC_STATUSES = {"pass", "fail", "unknown", "not_applicable"}
ROW_STATUSES = {"pass", "partial", "fail", "unknown", "not_applicable"}
REQUIREMENT_TYPES = {"mandatory", "optional"}
SECTIONS = {"core", "bonus"}
POLICY_VALUES = ("core_max_score", "bonus_max_score", "recommendation_threshold")
POLICY_IDENTITY = ("region", "level", "target_year", "guide_version")
ROW_VALUES = ("max_raw_score", "claimed_raw_score", "weight", "claimed_weighted_score")
RECOMMENDATIONS = {
    "recommendable",
    "conditional",
    "not_recommendable",
    "undetermined",
}
TOLERANCE = 1e-6
ROW_FINDINGS = {
    "pass": ("登记已满足", "无", "留存对应记录及核验依据。"),
    "partial": ("登记已有局部落实", "仍有条款未落实", "对照原条款逐条补齐现场措施和对应记录。"),
    "fail": ("登记未满足", "未达到条款要求", "按条款整改，完成后复测并登记证据。"),
    "unknown": ("缺核验结果", "缺可核验的事实", "取得原始记录或现场实测值，核对适用期间和口径。"),
    "not_applicable": ("登记不适用", "无", "留存适用性判断依据。"),
}
LEGACY_LABELS = {
    "score_rows": "评价条款数组",
    "core_max_score": "评价条款政策上限",
    "bonus_max_score": "附加条款政策上限",
    "max_raw_score": "原始值上限",
    "claimed_raw_score": "填报原始值",
    "claimed_weighted_score": "填报加权值",
    "core_score": "评价条款汇总值",
    "bonus_score": "附加条款汇总值",
    "total_score": "整表汇总值",
}
EVIDENCE_LABELS = {
    "verified": "已核验", "unverified": "待核验", "conflicted": "有冲突", "expired": "已失效",
}


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def close(actual: float, expected: float) -> bool:
    return math.isclose(actual, expected, rel_tol=TOLERANCE, abs_tol=TOLERANCE)


def score_rules(rules, policy, errors):
    if rules is None:
        if policy.get("ledger_scope") == "complete":
            errors.append("完整评分台账缺当期导则条款及分档规则，请提供 --rules")
        return {}
    if not isinstance(rules, dict) or any(rules.get(key) != policy.get(key) for key in POLICY_IDENTITY):
        errors.append("评分规则的地区、层级、年度或版本与台账不一致")
        return {}
    criteria = rules.get("criteria")
    if not isinstance(criteria, dict) or not criteria or not str(rules.get("source_ref") or "").strip():
        errors.append("评分规则缺导则来源或条款清单")
        return {}
    return criteria


def check_score_rule(rule, row, raw, maximum, weight, metrics_by_id, errors):
    criterion_id = row["id"]
    if not isinstance(rule, dict):
        errors.append(f"{criterion_id}缺有效条款规则")
        return
    rule_max = rule.get("max_raw_score")
    rule_weight = rule.get("weight")
    has_score = any(field in row for field in ROW_VALUES)
    if row.get("section") != rule.get("section") or (has_score and (
            not is_number(rule_max) or not is_number(rule_weight)
            or not close(maximum, rule_max) or not close(weight, rule_weight))):
        errors.append(f"{criterion_id}的分值上限、权重或所属分区与导则条款不一致")
    metric_rule = rule.get("metric_rule")
    if metric_rule is None or not has_score:
        return
    if not isinstance(metric_rule, dict) or metric_rule.get("direction") not in {"at_least", "at_most"}:
        errors.append(f"{criterion_id}缺有效的分档方向")
        return
    if row.get("status") in {"fail", "unknown", "not_applicable"} and raw == 0:
        return
    metric_id = metric_rule.get("metric_id")
    metric = metrics_by_id.get(metric_id, {}) if isinstance(metric_id, str) else {}
    value = metric.get("value")
    references = row.get("metric_ids")
    if (not isinstance(references, list) or metric_id not in references
            or not is_number(value) or not metric_rule.get("unit") or metric.get("unit") != metric_rule["unit"]):
        errors.append(f"{criterion_id}缺分档规则指定的实测指标或单位不一致:{metric_id}")
        return
    tiers = metric_rule.get("tiers")
    floor = metric_rule.get("floor_raw_score")
    if (not isinstance(tiers, list) or not tiers
            or not is_number(rule_max) or not is_number(floor) or not 0 <= floor <= rule_max
            or any(not isinstance(tier, dict) or not is_number(tier.get("threshold"))
                   or not is_number(tier.get("raw_score")) or not floor <= tier["raw_score"] <= rule_max
                   for tier in tiers)):
        errors.append(f"{criterion_id}的分档阈值或分值无效")
        return
    greater_is_better = metric_rule["direction"] == "at_least"
    eligible = [tier["raw_score"] for tier in tiers
                if (value >= tier["threshold"] if greater_is_better else value <= tier["threshold"])]
    cap = max(eligible, default=floor)
    if not any(close(raw, score) for score in (floor, *(tier["raw_score"] for tier in tiers))):
        errors.append(f"{criterion_id}填报分值不在导则档位集合中:{raw}")
    elif raw > cap and not close(raw, cap):
        errors.append(f"{criterion_id}实测 {value} {metric['unit']} 未达到填报档位，允许最高 {cap}，填报 {raw}")


def historical_disposition(policy, results, errors):
    if (policy.get("evaluation_mode") != "historical_audit" or policy.get("target_year") != 2025
            or not str(policy.get("level")).startswith("国家")
            or "工信厅节函〔2025〕390号" not in str(policy.get("guide_version"))):
        errors.append("历年末位复核须使用2025年国家绿色工厂历史动态管理规则")
        return None
    if not isinstance(results, list):
        errors.append("historical_results须为年度排名数组")
        return None
    by_year = {}
    for record in results:
        if not isinstance(record, dict):
            errors.append("历史排名的年度记录须为对象")
            continue
        year, rank, total, listed = (record.get(key) for key in ("年", "自末位起排名", "参评工厂", "当年在名单"))
        if (type(year) is not int or type(rank) is not int or type(total) is not int
                or not 1 <= rank <= total or type(listed) is not bool):
            errors.append(f"历史排名记录无效:{year}")
            continue
        if year in by_year:
            errors.append(f"历史排名年度重复:{year}")
            continue
        by_year[year] = {"year": year, "rank_from_bottom": rank, "factory_count": total,
                         "listed": listed, "bottom_five_percent": listed and rank * 20 <= total}
    years = list(range(policy["target_year"] - 3, policy["target_year"]))
    missing = [year for year in years if year not in by_year]
    ranked = [by_year[year] for year in years if year in by_year]
    if missing:
        decision, reason = "insufficient_history", "缺年度排名，无法判定连续三年"
    elif all(record["bottom_five_percent"] for record in ranked):
        decision, reason = "remove_from_list", "连续三年位于后5%，触发移出"
    else:
        decision, reason = "no_removal_trigger", "后5%记录未连续三年，未触发移出"
    return {"decision": decision, "reason": reason, "annual_results": ranked, "missing_years": missing}


def row_finding(
    row: dict[str, Any],
    criterion_id: str,
    kind: str,
    evidence_ids: list[Any],
    metric_ids: list[Any],
    evidence_by_id: dict[str, dict[str, Any]],
    metrics_by_id: dict[str, dict[str, Any]],
) -> dict[str, str]:
    actual, gap, action = ROW_FINDINGS.get(row.get("status"), ROW_FINDINGS["unknown"])
    sources = []
    measurements = []
    sources_complete = bool(evidence_ids or metric_ids)
    citations = dict.fromkeys((str(ref), criterion_id) for ref in evidence_ids)
    for ref in metric_ids:
        metric = metrics_by_id.get(str(ref))
        if metric is None:
            sources_complete = False
            sources.append(f"{ref} 未登记指标")
            continue
        if criterion_id not in (metric.get("supports") or []):
            sources_complete = False
        measurements.append(f"{metric.get('metric') or ref} {metric.get('value', '缺实测值')} {metric.get('unit', '')}".strip())
        metric_sources = metric.get("source_ids")
        if isinstance(metric_sources, list) and metric_sources:
            for evidence_id in metric_sources:
                citations[(str(evidence_id), str(ref))] = None
        else:
            sources_complete = False

    for ref, supported in citations:
        source = evidence_by_id.get(ref)
        if source is None:
            sources_complete = False
            sources.append(f"{ref} 未登记材料")
            continue
        state = source.get("status")
        if state != "verified" or supported not in (source.get("supports") or []):
            sources_complete = False
        sources.append(
            f"{ref} {source.get('title') or '缺材料标题'}"
            f"（附件 {source.get('attachment_ref') or '缺编号'}，{EVIDENCE_LABELS.get(state, '缺核验状态')}）"
        )

    if row.get("status") == "pass" and not sources_complete:
        gap = "缺完整可回查的支持材料"
        action = "补齐证据编号、附件及原始记录，核对证据与条款关系。"
    name = row.get("name") or row.get("category") or kind
    requirement = row.get("requirement") or f"{kind}，对照当期导则条款 {criterion_id}"
    if row.get("actual"):
        actual = f"{actual}。{row['actual']}"
    if measurements:
        actual = "。".join([actual, *measurements])
    if row.get("status") in {"partial", "fail", "unknown"}:
        declared_gap = row.get("gap")
        if isinstance(declared_gap, str) and declared_gap.strip() not in ("", "无"):
            gap = declared_gap
        action = row.get("action") or action

    return {
        "item": f"{criterion_id} {name}",
        "requirement": str(requirement),
        "actual": actual,
        "gap": str(gap),
        "evidence": "、".join(dict.fromkeys(sources)) or "缺支持材料登记",
        "action": str(action),
        "priority": "低" if gap == "无" else "高" if kind in {"基本要求", "必选要求"} else "中",
    }


def validate(document: dict[str, Any], rules=None) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    items: list[dict[str, str]] = []
    required_top = {
        "policy",
        "factory",
        "evidence",
        "basic_requirements",
        "score_rows",
        "metrics",
        "summary",
    }
    missing_top = sorted(required_top - set(document))
    if missing_top:
        errors.append("顶层缺少:" + ",".join(LEGACY_LABELS.get(field, field) for field in missing_top))

    policy = document.get("policy")
    if not isinstance(policy, dict):
        policy = {}
        errors.append("policy必须为对象")
    complete = policy.get("ledger_scope") == "complete"
    required_policy = {
        "region",
        "level",
        "target_year",
        "guide_title",
        "guide_version",
        "verified_on",
        "status",
        "evaluation_mode",
        "ledger_scope",
    }
    if complete:
        required_policy.update(POLICY_VALUES)
    missing_policy = sorted(required_policy - set(policy))
    if missing_policy:
        errors.append("policy缺少:" + ",".join(LEGACY_LABELS.get(field, field) for field in missing_policy))
    for field in ("region", "level", "guide_title", "guide_version"):
        if not isinstance(policy.get(field), str) or not policy.get(field, "").strip():
            errors.append(f"policy.{field}必须为非空字符串")
    target_year = policy.get("target_year")
    if not isinstance(target_year, int) or isinstance(target_year, bool):
        errors.append("policy.target_year必须为整数")
    verified_on = policy.get("verified_on")
    try:
        date.fromisoformat(str(verified_on))
    except ValueError:
        errors.append("policy.verified_on必须为YYYY-MM-DD日期")
    if policy.get("status") not in POLICY_STATUSES:
        errors.append("policy.status无效")
    if policy.get("evaluation_mode") not in EVALUATION_MODES:
        errors.append("policy.evaluation_mode无效")
    if policy.get("ledger_scope") not in LEDGER_SCOPES:
        errors.append("policy.ledger_scope无效")
    if (
        policy.get("evaluation_mode") == "current_application"
        and policy.get("status") != "current"
    ):
        errors.append("当前申报模式必须使用已核验现行政策")
    for field in POLICY_VALUES:
        if not complete and field not in policy:
            continue
        value = policy.get(field)
        if not is_number(value) or value < 0:
            errors.append(f"政策登记的{LEGACY_LABELS.get(field, field)}须为非负数")

    factory = document.get("factory")
    if not isinstance(factory, dict):
        factory = {}
        errors.append("factory必须为对象")
    for field in (
        "organization_boundary",
        "production_boundary",
        "reporting_period",
        "allowed_denominator_units",
    ):
        if not factory.get(field):
            errors.append(f"factory缺少:{field}")
    allowed_denominators = factory.get("allowed_denominator_units")
    if not isinstance(allowed_denominators, list) or not all(
        isinstance(item, str) and item.strip() for item in allowed_denominators
    ):
        errors.append("factory.allowed_denominator_units必须为非空字符串数组")
        allowed_denominators = []
    else:
        allowed_denominators = [item.strip() for item in allowed_denominators]

    evidence_items = document.get("evidence")
    if not isinstance(evidence_items, list):
        evidence_items = []
        errors.append("evidence必须为数组")
    evidence_by_id: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(evidence_items, 1):
        if not isinstance(item, dict):
            errors.append(f"evidence[{index}]必须为对象")
            continue
        evidence_id = str(item.get("id") or "").strip()
        if not evidence_id:
            errors.append(f"evidence[{index}]缺少id")
            continue
        if evidence_id in evidence_by_id:
            errors.append(f"证据编号重复:{evidence_id}")
        evidence_by_id[evidence_id] = item
        for field in ("attachment_ref", "title", "status", "supports"):
            if field not in item or item.get(field) in (None, ""):
                errors.append(f"{evidence_id}缺少:{field}")
        if item.get("status") not in EVIDENCE_STATUSES:
            errors.append(f"{evidence_id}证据状态无效")
        if not isinstance(item.get("supports"), list):
            errors.append(f"{evidence_id}.supports必须为数组")

    metrics = document.get("metrics")
    if not isinstance(metrics, list):
        metrics = []
        errors.append("metrics必须为数组")
    metrics_by_id: dict[str, dict[str, Any]] = {}
    for index, metric in enumerate(metrics, 1):
        if not isinstance(metric, dict):
            errors.append(f"metrics[{index}]必须为对象")
            continue
        metric_id = str(metric.get("id") or "").strip()
        if not metric_id:
            errors.append(f"metrics[{index}]缺少id")
            continue
        if metric_id in metrics_by_id:
            errors.append(f"指标编号重复:{metric_id}")
        metrics_by_id[metric_id] = metric
        for field in (
            "metric",
            "boundary",
            "period",
            "unit",
            "denominator_unit",
            "source_ids",
            "supports",
        ):
            if field not in metric or metric.get(field) in (None, ""):
                errors.append(f"{metric_id}缺少:{field}")
        denominator_unit = metric.get("denominator_unit")
        if denominator_unit not in allowed_denominators:
            errors.append(f"{metric_id}比值基数单位未在工厂边界卡锁定:{denominator_unit}")
        unit = str(metric.get("unit") or "")
        if denominator_unit and not unit.endswith("/" + str(denominator_unit)):
            errors.append(f"{metric_id}结果单位与比值基数单位不一致:{unit}")
        source_ids = metric.get("source_ids")
        if not isinstance(source_ids, list) or not source_ids:
            errors.append(f"{metric_id}.source_ids必须为非空数组")
        else:
            for evidence_id in source_ids:
                evidence = evidence_by_id.get(str(evidence_id))
                if evidence is None:
                    errors.append(f"{metric_id}引用不存在证据:{evidence_id}")
                elif evidence.get("status") != "verified":
                    errors.append(f"{metric_id}引用未核验证据:{evidence_id}")
                elif metric_id not in (evidence.get("supports") or []):
                    errors.append(f"{metric_id}与证据{evidence_id}支持关系不对称")
        if not isinstance(metric.get("supports"), list):
            errors.append(f"{metric_id}.supports必须为数组")
        calculation = metric.get("calculation")
        if calculation is not None:
            if not isinstance(calculation, dict) or calculation.get("kind") != "ratio":
                errors.append(f"{metric_id}.calculation仅支持ratio对象")
            else:
                numerator = calculation.get("numerator")
                denominator = calculation.get("denominator")
                multiplier = calculation.get("multiplier", 1)
                result = metric.get("value")
                if not all(is_number(value) for value in (numerator, denominator, multiplier, result)):
                    errors.append(f"{metric_id}比值计算字段必须为有限数值")
                elif denominator == 0:
                    errors.append(f"{metric_id}比值基数不能为 0")
                else:
                    expected = numerator / denominator * multiplier
                    if not close(float(result), expected):
                        errors.append(
                            f"{metric_id}结果与比值公式不一致:填报{result},复算{expected}"
                        )

    basic_items = document.get("basic_requirements")
    if not isinstance(basic_items, list):
        basic_items = []
        errors.append("basic_requirements必须为数组")
    if not basic_items:
        errors.append("basic_requirements不能为空")
    criterion_ids: set[str] = set()
    basic_all_met = True
    for index, item in enumerate(basic_items, 1):
        if not isinstance(item, dict):
            errors.append(f"basic_requirements[{index}]必须为对象")
            basic_all_met = False
            continue
        criterion_id = str(item.get("id") or "").strip()
        if not criterion_id:
            errors.append(f"basic_requirements[{index}]缺少id")
            basic_all_met = False
            continue
        if criterion_id in criterion_ids:
            errors.append(f"评价要求编号重复:{criterion_id}")
        criterion_ids.add(criterion_id)
        status = item.get("status")
        if status not in BASIC_STATUSES:
            errors.append(f"{criterion_id}基本要求状态无效")
            basic_all_met = False
        elif status not in {"pass", "not_applicable"}:
            basic_all_met = False
        evidence_ids = item.get("evidence_ids")
        if not isinstance(evidence_ids, list):
            errors.append(f"{criterion_id}.evidence_ids必须为数组")
            evidence_ids = []
        if status == "pass" and not evidence_ids:
            errors.append(f"{criterion_id}标记通过但没有证据")
        for evidence_id in evidence_ids:
            evidence = evidence_by_id.get(str(evidence_id))
            if evidence is None:
                errors.append(f"{criterion_id}引用不存在证据:{evidence_id}")
                continue
            if status == "pass" and evidence.get("status") != "verified":
                errors.append(f"{criterion_id}标记通过但证据未核验:{evidence_id}")
            if criterion_id not in (evidence.get("supports") or []):
                errors.append(f"{criterion_id}与证据{evidence_id}支持关系不对称")

        items.append(row_finding(item, criterion_id, "基本要求", evidence_ids, [], evidence_by_id, metrics_by_id))

    assessment_rows = document.get("score_rows")
    if not isinstance(assessment_rows, list):
        assessment_rows = []
        errors.append("评价条款须为数组")
    if not assessment_rows:
        errors.append("评价条款不能为空")
    criteria = score_rules(rules, policy, errors)
    assessment_ids: set[str] = set()
    core_entered = 0.0
    bonus_entered = 0.0
    core_limit = 0.0
    bonus_limit = 0.0
    mandatory_core_all_met = True
    for index, row in enumerate(assessment_rows, 1):
        if not isinstance(row, dict):
            errors.append(f"第 {index} 条评价记录须为对象")
            mandatory_core_all_met = False
            continue
        criterion_id = str(row.get("id") or "").strip()
        if not criterion_id:
            errors.append(f"第 {index} 条评价记录缺条款编号")
            continue
        if criterion_id in criterion_ids:
            errors.append(f"评价要求编号重复:{criterion_id}")
        criterion_ids.add(criterion_id)
        assessment_ids.add(criterion_id)
        for field in (
            "section",
            "category",
            "requirement_type",
            "status",
            "evidence_ids",
            "metric_ids",
        ):
            if field not in row:
                errors.append(f"{criterion_id} 缺 {LEGACY_LABELS.get(field, field)}")
        section = row.get("section")
        requirement_type = row.get("requirement_type")
        status = row.get("status")
        if section not in SECTIONS:
            errors.append(f"{criterion_id}.section无效")
        if requirement_type not in REQUIREMENT_TYPES:
            errors.append(f"{criterion_id}.requirement_type无效")
        if status not in ROW_STATUSES:
            errors.append(f"{criterion_id}.status无效")
        maximum = raw = weight = weighted = 0.0
        if complete or any(field in row for field in ROW_VALUES):
            for field in ROW_VALUES:
                if field not in row:
                    errors.append(f"{criterion_id} 缺 {LEGACY_LABELS.get(field, field)}")
            maximum, raw, weight, weighted = (row.get(field) for field in ROW_VALUES)
            if not is_number(maximum) or maximum < 0:
                errors.append(f"{criterion_id} 的原始值上限须为非负数")
                maximum = 0.0
            if not is_number(raw) or raw < 0 or raw > maximum:
                errors.append(f"{criterion_id} 的填报原始值超出范围")
                raw = 0.0
            if not is_number(weight) or weight < 0 or weight > 1:
                errors.append(f"{criterion_id}.weight必须在0到1之间")
                weight = 0.0
            if not is_number(weighted):
                errors.append(f"{criterion_id} 的填报加权值须为数值")
                weighted = 0.0
            if not close(float(weighted), float(raw) * float(weight)):
                errors.append(f"{criterion_id}已填加权值与原始值乘权重的结果不一致")
            allowed_values = row.get("allowed_raw_scores")
            if allowed_values is not None:
                if not isinstance(allowed_values, list) or not all(is_number(value) for value in allowed_values):
                    errors.append(f"{criterion_id} 的允许原始值须为数值数组")
                elif not any(close(float(raw), float(value)) for value in allowed_values):
                    errors.append(f"{criterion_id}旧版原始值不属于当期规则允许集合")
            if status in {"fail", "unknown", "not_applicable"} and not close(float(raw), 0.0):
                errors.append(f"{criterion_id}状态为{status}时旧版原始值必须为 0")
        evidence_ids = row.get("evidence_ids")
        metric_ids = row.get("metric_ids")
        if not isinstance(evidence_ids, list):
            errors.append(f"{criterion_id}.evidence_ids必须为数组")
            evidence_ids = []
        if not isinstance(metric_ids, list):
            errors.append(f"{criterion_id}.metric_ids必须为数组")
            metric_ids = []
        if raw > 0 and not evidence_ids and not metric_ids:
            errors.append(f"{criterion_id}原始值为正但缺证据或指标")
        for evidence_id in evidence_ids:
            evidence = evidence_by_id.get(str(evidence_id))
            if evidence is None:
                errors.append(f"{criterion_id}引用不存在证据:{evidence_id}")
                continue
            if raw > 0 and evidence.get("status") != "verified":
                errors.append(f"{criterion_id}原始值为正但证据未核验:{evidence_id}")
            if criterion_id not in (evidence.get("supports") or []):
                errors.append(f"{criterion_id}与证据{evidence_id}支持关系不对称")
        for metric_id in metric_ids:
            metric = metrics_by_id.get(str(metric_id))
            if metric is None:
                errors.append(f"{criterion_id}引用不存在指标:{metric_id}")
                continue
            if criterion_id not in (metric.get("supports") or []):
                errors.append(f"{criterion_id}与指标{metric_id}支持关系不对称")
        if criterion_id in criteria:
            check_score_rule(criteria[criterion_id], row, raw, maximum, weight, metrics_by_id, errors)
        elif criteria:
            errors.append(f"{criterion_id}未登记当期导则条款")
        elif not complete and raw > 0 and (metric_ids or row.get("allowed_raw_scores")):
            errors.append(f"{criterion_id}缺绑定实测值的分档规则，请提供 --rules")
        kind = "附加要求" if section == "bonus" else "必选要求" if requirement_type == "mandatory" else "评价要求"
        items.append(row_finding(row, criterion_id, kind, evidence_ids, metric_ids, evidence_by_id, metrics_by_id))
        # Existing input consistency checks use the legacy ledger values.
        if section == "core":
            core_entered += float(weighted)
            core_limit += float(maximum) * float(weight)
            if requirement_type == "mandatory" and status not in {"pass", "not_applicable"}:
                mandatory_core_all_met = False
        elif section == "bonus":
            bonus_entered += float(weighted)
            bonus_limit += float(maximum) * float(weight)

    summary = document.get("summary")
    if not isinstance(summary, dict):
        summary = {}
        errors.append("summary必须为对象")
    for field in ("basic_requirements_met", "recommendation"):
        if field not in summary:
            errors.append(f"台账汇总缺 {LEGACY_LABELS.get(field, field)}")
    if not isinstance(summary.get("basic_requirements_met"), bool):
        errors.append("summary.basic_requirements_met必须为布尔值")
    elif summary.get("basic_requirements_met") != basic_all_met:
        errors.append("summary.basic_requirements_met与逐项基本要求不一致")
    for field, expected in (
        ("core_score", core_entered),
        ("bonus_score", bonus_entered),
        ("total_score", core_entered + bonus_entered),
    ):
        if field not in summary:
            if complete:
                errors.append(f"台账汇总缺 {LEGACY_LABELS[field]}")
            continue
        value = summary.get(field)
        if not is_number(value):
            errors.append(f"台账汇总的{LEGACY_LABELS[field]}须为数值")
        elif not close(float(value), expected):
            errors.append(f"台账汇总的{LEGACY_LABELS[field]}与明细行汇总不一致")
    recommendation = summary.get("recommendation")
    if recommendation not in RECOMMENDATIONS:
        errors.append("summary.recommendation无效")
    threshold = policy.get("recommendation_threshold")

    threshold_met = None
    if complete and is_number(threshold) and threshold >= 0:
        threshold_met = core_entered + bonus_entered + TOLERANCE >= float(threshold)
        items.append({
            "item": "当期推荐线",
            "requirement": "达到台账登记的当期推荐条件",
            "actual": "已填条目达到推荐线" if threshold_met else "已填条目未达到推荐线",
            "gap": "无" if threshold_met else "台账现有结果低于适用推荐线",
            "evidence": f"{policy.get('guide_title') or '缺导则名称'} {policy.get('guide_version') or '缺版本'}",
            "action": "留存导则与完整台账。" if threshold_met else "补齐适用条目，核查未落实要求及证据后重核推荐条件。",
            "priority": "低" if threshold_met else "高",
        })
    if recommendation == "recommendable":
        if not complete:
            errors.append("推荐判断需覆盖当期全部评价条款")
        if policy.get("status") != "current":
            errors.append("推荐结论必须基于已核验现行政策")
        if not basic_all_met:
            errors.append("基本要求未全部通过时不得形成推荐结论")
        if not mandatory_core_all_met:
            errors.append("必选要求未全部通过")
        if threshold_met is False:
            errors.append("台账填报值未达到当期推荐线")
    if policy.get("evaluation_mode") != "current_application" and recommendation == "recommendable":
        errors.append("非当前申报模式不得形成推荐结论")

    policy_core_max = policy.get("core_max_score")
    policy_bonus_max = policy.get("bonus_max_score")
    if is_number(policy_core_max) and core_entered > float(policy_core_max) + TOLERANCE:
        errors.append("评价指标的填报合计超过政策上限")
    if is_number(policy_bonus_max) and bonus_entered > float(policy_bonus_max) + TOLERANCE:
        errors.append("附加项的填报合计超过政策上限")
    if complete:
        for criterion_id in sorted(criteria.keys() - assessment_ids):
            rule = criteria[criterion_id]
            name = rule.get("name", "") if isinstance(rule, dict) else ""
            errors.append(f"完整台账缺必评条款:{criterion_id} {name}".rstrip())
        if is_number(policy_core_max) and not close(core_limit, float(policy_core_max)):
            errors.append("完整台账的评价条款上限与政策不一致")
        if is_number(policy_bonus_max) and not close(bonus_limit, float(policy_bonus_max)):
            errors.append("完整台账的附加条款上限与政策不一致")
    elif policy.get("ledger_scope") == "partial":
        warnings.append("台账尚未覆盖全部条款，补齐当期导则全部条款。")
        items.append({"item": "评价条款覆盖", "requirement": "覆盖当期导则的全部评价条款",
                      "actual": "当前为单段台账", "gap": "缺完整的当期条款记录",
                      "evidence": str(policy.get("guide_title") or "缺导则名称"),
                      "action": "按原表补齐适用条款、证据及汇总，复核推荐条件", "priority": "高"})

    dynamic = None
    if "historical_results" in document:
        dynamic = historical_disposition(policy, document["historical_results"], errors)
    pending = sum(item["gap"] != "无" for item in items)
    blocking = sum(item["priority"] == "高" for item in items)
    summary_text = f"共 {pending} 项待处理，其中 {blocking} 项涉及基本、必选或推荐条件。"
    if errors:
        summary_text += f"台账另有 {len(errors)} 处校验问题。"
    return {
        "items": items,
        "summary": summary_text,
        "status": "pass" if not errors else "fail",
        "basic_requirements_met": basic_all_met if basic_items else None,
        "mandatory_requirements_met": mandatory_core_all_met if assessment_rows else None,
        "warnings": warnings,
        "errors": errors,
        **({"dynamic_review": dynamic} if dynamic is not None else {}),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger")
    parser.add_argument("--rules", type=Path, help="独立整理的适用导则条款及分档规则 JSON")
    args = parser.parse_args()
    path = Path(args.ledger)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError("台账顶层必须为对象")
        rules = json.loads(args.rules.read_text(encoding="utf-8")) if args.rules else None
        result = validate(document, rules)
    except (OSError, ValueError, TypeError) as exc:
        result = {"items": [], "summary": "台账输入校验未通过。", "status": "fail", "errors": [str(exc)]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
