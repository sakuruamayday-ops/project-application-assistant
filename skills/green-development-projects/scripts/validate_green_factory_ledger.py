#!/usr/bin/env python3
"""校验绿色工厂自评价台账的版本、证据、计分和单位勾稽。"""

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
RECOMMENDATIONS = {
    "recommendable",
    "conditional",
    "not_recommendable",
    "undetermined",
}
TOLERANCE = 1e-6


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def close(actual: float, expected: float) -> bool:
    return math.isclose(actual, expected, rel_tol=TOLERANCE, abs_tol=TOLERANCE)


def validate(document: dict[str, Any]) -> tuple[list[str], list[str], dict[str, float]]:
    errors: list[str] = []
    warnings: list[str] = []
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
        errors.append("顶层缺少:" + ",".join(missing_top))

    policy = document.get("policy")
    if not isinstance(policy, dict):
        policy = {}
        errors.append("policy必须为对象")
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
        "core_max_score",
        "bonus_max_score",
        "recommendation_threshold",
    }
    missing_policy = sorted(required_policy - set(policy))
    if missing_policy:
        errors.append("policy缺少:" + ",".join(missing_policy))
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
    for field in ("core_max_score", "bonus_max_score", "recommendation_threshold"):
        value = policy.get(field)
        if not is_number(value) or value < 0:
            errors.append(f"policy.{field}必须为非负数")

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
            errors.append(f"{metric_id}分母单位未在工厂边界卡锁定:{denominator_unit}")
        unit = str(metric.get("unit") or "")
        if denominator_unit and not unit.endswith("/" + str(denominator_unit)):
            errors.append(f"{metric_id}结果单位与分母单位不一致:{unit}")
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
                    errors.append(f"{metric_id}分母不能为0")
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

    score_rows = document.get("score_rows")
    if not isinstance(score_rows, list):
        score_rows = []
        errors.append("score_rows必须为数组")
    if not score_rows:
        errors.append("score_rows不能为空")
    core_score = 0.0
    bonus_score = 0.0
    core_max = 0.0
    bonus_max = 0.0
    mandatory_core_all_met = True
    for index, row in enumerate(score_rows, 1):
        if not isinstance(row, dict):
            errors.append(f"score_rows[{index}]必须为对象")
            mandatory_core_all_met = False
            continue
        criterion_id = str(row.get("id") or "").strip()
        if not criterion_id:
            errors.append(f"score_rows[{index}]缺少id")
            continue
        if criterion_id in criterion_ids:
            errors.append(f"评价要求编号重复:{criterion_id}")
        criterion_ids.add(criterion_id)
        for field in (
            "section",
            "category",
            "requirement_type",
            "status",
            "max_raw_score",
            "claimed_raw_score",
            "weight",
            "claimed_weighted_score",
            "evidence_ids",
            "metric_ids",
        ):
            if field not in row:
                errors.append(f"{criterion_id}缺少:{field}")
        section = row.get("section")
        requirement_type = row.get("requirement_type")
        status = row.get("status")
        if section not in SECTIONS:
            errors.append(f"{criterion_id}.section无效")
        if requirement_type not in REQUIREMENT_TYPES:
            errors.append(f"{criterion_id}.requirement_type无效")
        if status not in ROW_STATUSES:
            errors.append(f"{criterion_id}.status无效")
        maximum = row.get("max_raw_score")
        raw = row.get("claimed_raw_score")
        weight = row.get("weight")
        weighted = row.get("claimed_weighted_score")
        if not is_number(maximum) or maximum < 0:
            errors.append(f"{criterion_id}.max_raw_score必须为非负数")
            maximum = 0.0
        if not is_number(raw) or raw < 0 or raw > maximum:
            errors.append(f"{criterion_id}.claimed_raw_score越界")
            raw = 0.0
        if not is_number(weight) or weight < 0 or weight > 1:
            errors.append(f"{criterion_id}.weight必须在0到1之间")
            weight = 0.0
        if not is_number(weighted):
            errors.append(f"{criterion_id}.claimed_weighted_score必须为数值")
            weighted = 0.0
        expected_weighted = float(raw) * float(weight)
        if not close(float(weighted), expected_weighted):
            errors.append(
                f"{criterion_id}加权分不一致:填报{weighted},复算{expected_weighted}"
            )
        allowed_scores = row.get("allowed_raw_scores")
        if allowed_scores is not None:
            if not isinstance(allowed_scores, list) or not all(
                is_number(value) for value in allowed_scores
            ):
                errors.append(f"{criterion_id}.allowed_raw_scores必须为数值数组")
            elif not any(close(float(raw), float(value)) for value in allowed_scores):
                errors.append(f"{criterion_id}原始分不属于当期规则允许集合")
        if status in {"fail", "unknown", "not_applicable"} and not close(float(raw), 0.0):
            errors.append(f"{criterion_id}状态为{status}时确认原始分必须为0")
        evidence_ids = row.get("evidence_ids")
        metric_ids = row.get("metric_ids")
        if not isinstance(evidence_ids, list):
            errors.append(f"{criterion_id}.evidence_ids必须为数组")
            evidence_ids = []
        if not isinstance(metric_ids, list):
            errors.append(f"{criterion_id}.metric_ids必须为数组")
            metric_ids = []
        if raw > 0 and not evidence_ids and not metric_ids:
            errors.append(f"{criterion_id}取得正向得分但没有证据或指标")
        for evidence_id in evidence_ids:
            evidence = evidence_by_id.get(str(evidence_id))
            if evidence is None:
                errors.append(f"{criterion_id}引用不存在证据:{evidence_id}")
                continue
            if raw > 0 and evidence.get("status") != "verified":
                errors.append(f"{criterion_id}取得正向得分但证据未核验:{evidence_id}")
            if criterion_id not in (evidence.get("supports") or []):
                errors.append(f"{criterion_id}与证据{evidence_id}支持关系不对称")
        for metric_id in metric_ids:
            metric = metrics_by_id.get(str(metric_id))
            if metric is None:
                errors.append(f"{criterion_id}引用不存在指标:{metric_id}")
                continue
            if criterion_id not in (metric.get("supports") or []):
                errors.append(f"{criterion_id}与指标{metric_id}支持关系不对称")
        if section == "core":
            core_score += float(weighted)
            core_max += float(maximum) * float(weight)
            if requirement_type == "mandatory" and status not in {"pass", "not_applicable"}:
                mandatory_core_all_met = False
        elif section == "bonus":
            bonus_score += float(weighted)
            bonus_max += float(maximum) * float(weight)

    summary = document.get("summary")
    if not isinstance(summary, dict):
        summary = {}
        errors.append("summary必须为对象")
    for field in (
        "basic_requirements_met",
        "core_score",
        "bonus_score",
        "total_score",
        "recommendation",
    ):
        if field not in summary:
            errors.append(f"summary缺少:{field}")
    if not isinstance(summary.get("basic_requirements_met"), bool):
        errors.append("summary.basic_requirements_met必须为布尔值")
    elif summary.get("basic_requirements_met") != basic_all_met:
        errors.append("summary.basic_requirements_met与逐项基本要求不一致")
    for field, expected in (
        ("core_score", core_score),
        ("bonus_score", bonus_score),
        ("total_score", core_score + bonus_score),
    ):
        value = summary.get(field)
        if not is_number(value):
            errors.append(f"summary.{field}必须为数值")
        elif not close(float(value), expected):
            errors.append(f"summary.{field}不一致:填报{value},复算{expected}")
    recommendation = summary.get("recommendation")
    if recommendation not in RECOMMENDATIONS:
        errors.append("summary.recommendation无效")
    threshold = policy.get("recommendation_threshold")
    if recommendation == "recommendable":
        if policy.get("status") != "current":
            errors.append("推荐结论必须基于已核验现行政策")
        if not basic_all_met:
            errors.append("基本要求未全部通过时不得形成推荐结论")
        if not mandatory_core_all_met:
            errors.append("必选评分项未全部通过时不得形成推荐结论")
        if is_number(threshold) and core_score + bonus_score + TOLERANCE < float(threshold):
            errors.append("总分低于当期推荐阈值")
    if policy.get("evaluation_mode") != "current_application" and recommendation == "recommendable":
        errors.append("非当前申报模式不得形成推荐结论")

    policy_core_max = policy.get("core_max_score")
    policy_bonus_max = policy.get("bonus_max_score")
    if is_number(policy_core_max) and core_score > float(policy_core_max) + TOLERANCE:
        errors.append("评价指标确认分超过政策满分")
    if is_number(policy_bonus_max) and bonus_score > float(policy_bonus_max) + TOLERANCE:
        errors.append("加分项确认分超过政策满分")
    if policy.get("ledger_scope") == "complete":
        if is_number(policy_core_max) and not close(core_max, float(policy_core_max)):
            errors.append(f"完整台账评价指标理论满分不闭合:台账{core_max},政策{policy_core_max}")
        if is_number(policy_bonus_max) and not close(bonus_max, float(policy_bonus_max)):
            errors.append(f"完整台账加分项理论满分不闭合:台账{bonus_max},政策{policy_bonus_max}")
    elif policy.get("ledger_scope") == "partial":
        warnings.append("当前为部分台账，未校验评分表理论满分覆盖")

    totals = {
        "core_score": round(core_score, 10),
        "bonus_score": round(bonus_score, 10),
        "total_score": round(core_score + bonus_score, 10),
        "core_theoretical_max": round(core_max, 10),
        "bonus_theoretical_max": round(bonus_max, 10),
    }
    return errors, warnings, totals


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("ledger")
    args = parser.parse_args()
    path = Path(args.ledger)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "fail", "errors": [str(exc)]}, ensure_ascii=False, indent=2))
        return 2
    if not isinstance(document, dict):
        print(
            json.dumps(
                {"status": "fail", "errors": ["台账顶层必须为对象"]},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    errors, warnings, totals = validate(document)
    print(
        json.dumps(
            {
                "status": "pass" if not errors else "fail",
                "totals": totals,
                "warnings": warnings,
                "errors": errors,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
