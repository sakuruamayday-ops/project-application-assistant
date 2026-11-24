#!/usr/bin/env python3
"""Report evidence gaps, growth and eligibility checks for high-tech enterprise scenarios."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from math import isfinite
from operator import ge, gt, le
from pathlib import Path
from typing import Any


NONFINANCIAL_KEYS = ("ip", "conversion", "organization")
LEVEL_KEYS = ("target", "conservative", "stress")
POLICY_PATH = Path(__file__).resolve().parent.parent / "references" / "policy-baseline-2026.json"
POLICY_DIMENSIONS = {
    "ip": "intellectual_property",
    "conversion": "transformation",
    "organization": "rd_management",
    "growth": "growth",
}
GROWTH_ITEMS = {"revenue": "销售收入增长率", "net_assets": "净资产增长率"}
MATERIAL_NAMES = {"ip": "知识产权", "conversion": "成果转化", "organization": "组织管理", "growth": "财务与成长性"}
INTAKE_GROUPS = ("qualification", *MATERIAL_NAMES, "next_window")
LEVEL_LABELS = dict(zip(LEVEL_KEYS, ("目标", "保守", "压力")))
COMPARISONS = {"gte": ge, "gt": gt, "lte": le}
BAND_SYMBOLS = {"gte": "≥", "gt": ">", "lte": "≤"}
SCHEMA_VERSION = "high-tech-scenario-calculation-operation/v2"
MATERIAL_ACTIONS = {
    "qualification": "补企业登记、科技人员、研发费用、高品收入及合规原件，按当期条件逐项核对。",
    "ip": "核对权属和有效期，补主导产品关键技术与对应权利要求的材料。",
    "conversion": "补成果来源、实施过程和实际应用凭证，按年度核对重复记录。",
    "organization": "补本项制度及报告期内执行记录，核对责任人和日期。",
    "growth": "补对应会计年度报表，核对主体、期间与金额口径。",
    "next_window": "登记次年窗口内新增和退出的成果、知识产权与财务年度。",
}
GROWTH_SOURCES = {"revenue": "输入的销售收入年度数列", "net_assets": "输入的净资产年度数列"}
INPUT_EXAMPLE = {
    "scenarios": [{
        "name": "example",
        "revenue": [100, 110, 121],
        "net_assets": [100, 105, None],
        "material_coverage": {"ip": "partial", "growth": "partial"},
    }],
}


@dataclass(frozen=True)
class GrowthTier:
    value: Decimal
    operator: str
    lower_bound: int


@dataclass(frozen=True)
class Policy:
    maxima: dict[str, int]
    growth_item_max: int
    growth_tiers: list[GrowthTier]
    pass_value: Decimal
    pass_operator: str


def finite_number(value: Any, field: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError(f"{field} must be a finite number")
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError(f"{field} must be a finite number")
    return number


def load_policy() -> Policy:
    try:
        criteria = json.loads(POLICY_PATH.read_text(encoding="utf-8"), parse_float=Decimal)["scoring"]
        dimensions = criteria["dimensions"]
        maxima = {key: dimensions[policy_key]["max"] for key, policy_key in POLICY_DIMENSIONS.items()}
        if any(type(maximum) is not int or maximum <= 0 for maximum in maxima.values()):
            raise ValueError("scoring.dimensions.*.max must be positive integers")
        if sum(maxima.values()) != criteria["total"]:
            raise ValueError("scoring.total must equal the sum of the dimension maxima")

        threshold = criteria["pass_threshold"]
        pass_value = finite_number(threshold["value"], "scoring.pass_threshold.value")
        pass_operator = threshold["operator"]
        if pass_operator not in ("gt", "gte") or not 0 <= pass_value <= criteria["total"]:
            raise ValueError("invalid scoring.pass_threshold")

        growth = dimensions["growth"]
        each_max = growth["each_max"]
        if type(each_max) is not int or each_max * len(GROWTH_ITEMS) != maxima["growth"]:
            raise ValueError("invalid scoring.dimensions.growth.each_max")
        raw_tiers = growth["tiers"]
        if not isinstance(raw_tiers, list) or len(raw_tiers) < 2:
            raise ValueError("scoring.dimensions.growth.tiers must define lower and upper rate bands")
        tiers = []
        for index, item in enumerate(raw_tiers):
            field = f"scoring.dimensions.growth.tiers[{index}]"
            value = finite_number(item["value"], f"{field}.value")
            low, high = item["score_range"]["min"], item["score_range"]["max"]
            if type(low) is not int or type(high) is not int or not 0 <= low <= high <= each_max:
                raise ValueError(f"invalid {field}.score_range")
            tiers.append(GrowthTier(value, item["operator"], low))
        if (
            any(tier.operator not in ("gt", "gte") for tier in tiers[:-1])
            or any(higher.value <= lower.value for higher, lower in zip(tiers[:-2], tiers[1:-1]))
            or tiers[-2].operator != "gt"
            or tiers[-1].operator != "lte"
            or tiers[-2].value != tiers[-1].value
        ):
            raise ValueError("scoring.dimensions.growth.tiers must form descending rate bands without gaps")
        return Policy(maxima, each_max, tiers, pass_value, pass_operator)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid policy baseline {POLICY_PATH}: {exc}") from exc


def growth_rate(values: list[int | float | Decimal | str | Fraction]) -> tuple[Fraction | None, str | None]:
    if len(values) != 3:
        raise ValueError("revenue and net_assets must each contain exactly three values")
    first, second, third = (value if isinstance(value, Fraction) else Fraction(str(value)) for value in values)
    if first < 0 or second < 0:
        return None, "前两个会计年度有负值，需复核财务口径"
    if second == 0:
        return Fraction(0), "第二个会计年度基数为 0，按原口径记录为 0%"
    if first == 0:
        return third / second - 1, "第一个会计年度基数为 0，使用后两个会计年度计算"
    return (second / first + third / second) / 2 - 1, None


def finding(name: str, requirement: str, actual: str, gap: str, evidence: str, action: str, priority: str) -> dict[str, str]:
    return {
        "item": name,
        "requirement": requirement,
        "actual": actual,
        "gap": gap,
        "evidence": evidence,
        "action": action,
        "priority": priority,
    }


def rate_label(tier: GrowthTier) -> str:
    percentage = format((tier.value * 100).normalize(), "f")
    return f"{BAND_SYMBOLS[tier.operator]}{percentage}%"


def growth_gap(rate: Fraction, threshold: Decimal) -> str:
    difference = (Fraction(threshold) - rate) * 100
    if difference == 0:
        return "需由零转为正增长"
    if difference < Fraction(1, 100):
        return "差不足 0.01 pp"
    return f"差 {float(difference):.2f} pp"


def issue(field_path: str, actual: Any, expected: str, fix: str, business_location: str) -> dict[str, Any]:
    if isinstance(actual, (dict, list)):
        kind = "对象" if isinstance(actual, dict) else "数组"
        actual = f"{kind}，含 {len(actual)} 项"
    return {
        "field_path": field_path,
        "actual": actual,
        "expected": expected,
        "fix": fix,
        "business_location": business_location,
    }


@dataclass
class ScenarioValidation:
    index: int
    name: str
    issues: list[dict[str, Any]]

    def add(self, field: str, actual: Any, expected: str, fix: str) -> None:
        path = f"scenarios[{self.index}]"
        table = "双年度预评估"
        if field:
            path += f".{field}"
            metric, _, period = field.partition("[")
            if metric in GROWTH_ITEMS:
                table = f"财务与成长性 / {GROWTH_ITEMS[metric].removesuffix('增长率')}"
                if period:
                    table += f" / 第 {int(period[:-1]) + 1} 个会计年度"
            elif field.startswith("scores."):
                dimension = field.split(".")[1]
                table = MATERIAL_NAMES[dimension]
        self.issues.append(issue(path, actual, expected, fix, f"{self.name} / {table}"))


def read_coverage(
    raw: dict[str, Any], policy: Policy, validation: ScenarioValidation,
) -> tuple[dict[str, Decimal], dict[str, list[str]]]:
    coverage = {}
    missing_evidence = {}
    for key in POLICY_DIMENSIONS:
        value = raw.get(key)
        metadata = value if isinstance(value, dict) else {}
        field = f"scores.{key}"
        if key == "growth" and key in raw and not isinstance(value, dict):
            validation.add(field, value, "包含成长性覆盖率与缺项名称的对象", "使用对象填写 coverage 和 missing_evidence")
            continue
        before = len(validation.issues)
        ratio_value = metadata.get("coverage", 1)
        try:
            ratio = finite_number(ratio_value, f"{field}.coverage")
            if not 0 <= ratio <= 1:
                raise ValueError
        except ValueError:
            validation.add(f"{field}.coverage", ratio_value, "0 到 1 的有限数值", "用已评权重除以该维度上限，填入数值")
            ratio = None

        evidence_field = f"{field}.missing_evidence"
        missing = metadata.get("missing_evidence", [])
        evidence_start = len(validation.issues)
        if not isinstance(missing, list):
            validation.add(evidence_field, missing, "评价点名称数组", "用数组逐项列出缺证据的评价点")
        else:
            for index, item in enumerate(missing):
                if key == "growth" and item not in GROWTH_ITEMS.values():
                    validation.add(
                        f"{evidence_field}[{index}]", item, "销售收入增长率或净资产增长率",
                        "按缺证据的成长性指标填写其完整名称",
                    )
                elif not isinstance(item, str) or not item.strip():
                    validation.add(f"{evidence_field}[{index}]", item, "非空评价点名称", "填写该缺项的评价点名称")
            if ratio == 1 and missing:
                validation.add(
                    evidence_field, missing, "覆盖率为 1 时缺项数组为空",
                    "仍有缺项时按已评权重下调 coverage，补齐后清空缺项数组",
                )
        if key == "growth" and ratio is not None and len(validation.issues) == evidence_start:
            if ratio == 0 and not missing:
                missing = list(GROWTH_ITEMS.values())
            if len(set(missing)) * policy.growth_item_max != policy.maxima["growth"] * (1 - ratio):
                validation.add(
                    evidence_field, metadata.get("missing_evidence"),
                    "成长性覆盖率与缺项对应的权重一致",
                    "在 missing_evidence 列出未评的成长性指标，按已评指标权重重填 coverage",
                )
        if ratio is not None:
            coverage[key] = ratio
        if len(validation.issues) == before and ratio < 1:
            missing_evidence[key] = missing
    return coverage, missing_evidence


def validate_levels(
    raw: Any, field: str, maximum: int, validation: ScenarioValidation, *, allow_scalar: bool,
) -> dict[str, Decimal]:
    expected_value = f"0 到 {maximum} 的有限数值"
    if isinstance(raw, dict):
        inputs = [(level, f"{field}.{level}", raw.get(level)) for level in LEVEL_KEYS]
    elif allow_scalar and isinstance(raw, (int, float, Decimal)) and not isinstance(raw, bool):
        inputs = [("target", field, raw)]
    else:
        expected = "数值或含 target、conservative、stress 的对象" if allow_scalar else "含 target、conservative、stress 的子项对象"
        validation.add(field, raw, expected, "按本年度证据填写目标、保守、压力三档")
        return {}

    levels = {}
    for level, path, value in inputs:
        try:
            value_received = Decimal(value) if isinstance(value, str) else finite_number(value, path)
            if not value_received.is_finite() or not 0 <= value_received <= maximum:
                raise ValueError
        except (InvalidOperation, ValueError):
            validation.add(path, value, expected_value, f"按本年度证据填写{LEVEL_LABELS[level]}情景值")
        else:
            levels[level] = value_received

    if not isinstance(raw, dict):
        return dict.fromkeys(LEVEL_KEYS, levels["target"]) if levels else {}
    present = [level for level in LEVEL_KEYS if level in levels]
    for higher, lower in zip(present, present[1:]):
        if levels[lower] > levels[higher]:
            validation.add(
                f"{field}.{lower}", raw[lower], f"{LEVEL_LABELS[lower]}情景值 ≤ {LEVEL_LABELS[higher]}情景值",
                f"按证据重核 {lower} 和 {higher}，使较保守的档位数值不高于上一档",
            )
    return levels


def validate_assessments(
    raw: dict[str, Any], maxima: dict[str, int], coverage: dict[str, Decimal], validation: ScenarioValidation,
) -> dict[str, dict[str, Decimal]]:
    normalized: dict[str, dict[str, Decimal]] = {}
    for key, value in raw.items():
        before = len(validation.issues)
        field = f"scores.{key}"
        if isinstance(value, dict) and "components" in value:
            components = value["components"]
            field += ".components"
            if not isinstance(components, list) or not components:
                validation.add(field, components, "非空评价子项数组", "按评价要求逐项填写三个情景值")
                continue
            components_by_level = [
                validate_levels(item, f"{field}[{index}]", maxima[key], validation, allow_scalar=False)
                for index, item in enumerate(components)
            ]
            levels = {
                level: sum(item[level] for item in components_by_level)
                for level in LEVEL_KEYS if all(level in item for item in components_by_level)
            }
            for level, value_received in levels.items():
                if value_received > maxima[key]:
                    validation.add(
                        field, components, f"{LEVEL_LABELS[level]}情景值合计 ≤ {maxima[key]}",
                        f"重核各子项的 {level} 数值，将合计修正到维度上限以内",
                    )
            actual = components
        else:
            levels = validate_levels(value, field, maxima[key], validation, allow_scalar=True)
            actual = value

        ratio = coverage.get(key)
        if ratio is not None and ratio < 1:
            covered_max = maxima[key] * ratio
            for level, value_received in levels.items():
                if covered_max < value_received <= maxima[key]:
                    path = field
                    current = actual
                    if isinstance(value, dict) and "components" not in value:
                        path, current = f"{field}.{level}", value[level]
                    validation.add(
                        path, current, f"{LEVEL_LABELS[level]}情景值 ≤ 已评权重 {covered_max:f}",
                        "按证据调整已评数值或 coverage",
                    )
                    if not isinstance(value, dict):
                        break
        if ratio is not None and len(validation.issues) == before:
            normalized[key] = levels
    return normalized


def growth_values(
    raw: Any, field: str, validation: ScenarioValidation, *, allow_missing: bool = False,
) -> list[Fraction] | None:
    expected = "由早到晚的三个同口径会计年度数值"
    if allow_missing and raw is None:
        return None
    if not isinstance(raw, list):
        validation.add(field, raw, expected, "从财务与成长性表按年度填写三个数值")
        return None
    if len(raw) != 3:
        validation.add(field, raw, expected, "按会计年度补齐或删减至三个数值")
    values = []
    for index, value in enumerate(raw):
        if allow_missing and value is None:
            continue
        try:
            values.append(Fraction(str(value)))
        except (ValueError, ZeroDivisionError):
            validation.add(f"{field}[{index}]", value, "有限财务数值", "按该会计年度财务报表填写同口径数值")
    return values if len(raw) == len(values) == 3 else None


def analyze_scenario(
    scenario: Any, policy: Policy, index: int, issues: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    label = f"第 {index + 1} 个申报年度"
    name = str(scenario.get("name", label)) if isinstance(scenario, dict) else label
    validation = ScenarioValidation(index, name, issues)
    before = len(issues)
    if not isinstance(scenario, dict):
        validation.add("", scenario, "年度情景对象", "填写年度名称、财务数组和材料覆盖")
        return None, []

    submitted = scenario.get("scores")
    if submitted is not None and not isinstance(submitted, dict):
        validation.add("scores", submitted, "可选的既有评价对象", "移除此字段，或按旧格式填写已有评价资料")
        submitted = None
    coverage, missing = read_coverage(submitted, policy, validation) if submitted else ({}, {})
    legacy_inputs = {}
    for key in NONFINANCIAL_KEYS:
        if not submitted or key not in submitted:
            continue
        value = submitted[key]
        if not isinstance(value, dict) or value.keys() - {"coverage", "missing_evidence"}:
            legacy_inputs[key] = value
    assessed = validate_assessments(legacy_inputs, policy.maxima, coverage, validation)

    intake = None
    intake_items = []
    if "material_coverage" in scenario:
        try:
            selected = select_intake_tier({"material_coverage": scenario["material_coverage"]})
            intake = selected["material_coverage"]
            intake_items = selected["items"]
        except ValueError as error:
            validation.add("material_coverage", scenario["material_coverage"], str(error),
                           "按本年度材料登记覆盖状态")

    evidence_coverage = {}
    items = []
    for key in POLICY_DIMENSIONS:
        ratio = coverage.get(key, Decimal(1))
        entry = (submitted or {}).get(key)
        has_ratio = isinstance(entry, dict) and "coverage" in entry
        state = intake.get(key) if intake else None
        evidence_coverage[key] = ratio if has_ratio or state == "complete" else None
        if state in {"none", "partial"} and ratio == 1:
            evidence_coverage[key] = None
        if evidence_coverage[key] is None:
            actual = "有局部材料" if state == "partial" else "未登记完整材料"
            items.append(finding(f"{name} / {MATERIAL_NAMES[key]}",
                                 "登记本年度该组材料覆盖",
                                 actual,
                                 "缺可定位的覆盖记录",
                                 f"{name} / 材料登记",
                                 MATERIAL_ACTIONS[key], "高"))

    for key, names in missing.items():
        if key == "growth":
            continue
        material = MATERIAL_NAMES[key]
        ratio = coverage[key]
        for criterion in dict.fromkeys(names or [material]):
            items.append(finding(
                f"{name} / {criterion}",
                "以可回查的材料支持本项判断",
                f"{material}证据覆盖率 {ratio:.2%}",
                "缺本项证明材料" if names else f"未覆盖比例 {1 - ratio:.2%}，缺具体评价点名称",
                f"{name} / {material}材料登记",
                MATERIAL_ACTIONS[key] if names else f"先列具体缺项。{MATERIAL_ACTIONS[key]}",
                "中",
            ))

    if not legacy_inputs:
        items.extend(
            {**item, "item": f"{name} / {item['item']}", "evidence": f"{name} / {item['evidence']}"}
            for item in intake_items if item["item"] in {"资格条件", "次年窗口"}
        )

    growth = {}
    growth_bounds = []
    for key, label in GROWTH_ITEMS.items():
        source = f"{name} / {GROWTH_SOURCES[key]}"
        display_name = f"{name} / {label}"
        action = MATERIAL_ACTIONS["growth"]
        if label in missing.get("growth", []):
            growth[key] = {"rate": None, "percentage": None, "band": None, "note": "缺资料"}
            items.append(finding(display_name, "具备三个同口径会计年度数值", "缺成长性证据",
                              "暂不能复算", source, action, "中"))
            continue

        raw = scenario.get(key)
        issue_count = len(issues)
        values = growth_values(raw, key, validation, allow_missing=not legacy_inputs)
        if values is None:
            if len(issues) == issue_count:
                periods = [str(i) for i, value in enumerate(raw or [None] * 3, 1) if value is None]
                note = f"缺第 {'、'.join(periods)} 个会计年度的数据"
                growth[key] = {"rate": None, "percentage": None, "band": None, "note": note}
                items.append(finding(display_name, "具备三个同口径会计年度数值", note,
                                     "暂不能复算", source, action, "中"))
            continue
        rate, note = growth_rate(values)
        if rate is None:
            growth[key] = {"rate": None, "percentage": None, "band": None, "note": note}
            items.append(finding(display_name, "使用适用的财务口径核对增长率", note,
                              "需财务专项复核", source, action, "中"))
            continue
        try:
            display_rate = float(round(rate, 6))
            percentage = f"{float(rate * 100):.2f}%"
        except OverflowError:
            validation.add(key, scenario[key], "可计算并展示增长率的同口径财务数组",
                           "核对金额单位和前两个会计年度基数")
            continue

        band_index = next(i for i, tier in enumerate(policy.growth_tiers)
                          if COMPARISONS[tier.operator](rate, tier.value))
        band = policy.growth_tiers[band_index]
        growth_bounds.append(band.lower_bound)
        growth[key] = {"rate": display_rate, "percentage": percentage, "band": rate_label(band), "note": note}
        if band_index:
            next_band = policy.growth_tiers[band_index - 1]
            items.append(finding(
                display_name, f"下一成长档 {rate_label(next_band)}", percentage,
                growth_gap(rate, next_band.value), source,
                "核对真实年度数据，并测算新增和退出年度对下个申报窗口的影响。",
                "中",
            ))
        else:
            items.append(finding(display_name, f"最高成长档 {rate_label(band)}", percentage,
                              "无", source, "留存三个会计年度同口径底稿。", "低"))

    gate = None
    complete_coverage = all(evidence_coverage.get(key) == 1 for key in POLICY_DIMENSIONS)
    if (
        len(issues) == before
        and complete_coverage
        and not missing
        and len(assessed) == len(NONFINANCIAL_KEYS)
        and len(growth_bounds) == len(GROWTH_ITEMS)
    ):
        gate = COMPARISONS[policy.pass_operator](
            sum(assessed[key]["conservative"] for key in NONFINANCIAL_KEYS) + sum(growth_bounds),
            policy.pass_value,
        )
    if gate is None:
        actual = "已有材料尚不足以完成门槛核对"
        gap = "缺该年度正式评价结果" if not legacy_inputs else "缺完整材料或财务口径需复核"
        action = "补该年度正式评价结果，按证据缺口完善材料。" if not legacy_inputs else "完成同年度缺项及输入校验后，重新核对创新能力要求。"
    elif gate:
        actual, gap = "按已填情景达到要求", "无"
        action = "留存本年度材料及评价依据。"
    else:
        actual, gap = "按已填情景未达到要求", "本年度创新能力条件有缺口"
        action = "核对知识产权、成果转化、研发组织管理和成长性，逐项落实证据与整改。"
    items.append(finding(f"{name} / 创新能力资格", "达到认定工作指引的创新能力要求",
                      actual, gap, "国科发火〔2016〕195号 / 创新能力评价", action,
                      "低" if gate else "高"))
    return {
        "name": name,
        "growth": growth,
        "coverage": {key: float(ratio) if ratio is not None else None
                     for key, ratio in evidence_coverage.items()},
        "innovation_requirement_met": gate,
    }, items


def select_intake_tier(payload: Any) -> dict[str, Any]:
    supplied = payload.get("material_coverage") if isinstance(payload, dict) else None
    if not isinstance(supplied, dict):
        raise ValueError("选档输入须包含 material_coverage 对象")
    for group, coverage in supplied.items():
        if group not in INTAKE_GROUPS or coverage not in ("none", "partial", "complete"):
            raise ValueError(f"material_coverage.{group} 须为已定义的材料组，覆盖状态取 none、partial 或 complete")
    coverage = {group: supplied.get(group, "none") for group in INTAKE_GROUPS}
    covered_groups = [group for group in MATERIAL_NAMES if coverage[group] != "none"]
    missing_for_complete = [group for group, status in coverage.items() if status != "complete"]
    if not missing_for_complete:
        tier = "完整"
        basis = "六组材料齐备，可评估本年和次年窗口。"
    elif covered_groups:
        tier = "局部"
        names = "、".join(MATERIAL_NAMES[group] for group in covered_groups)
        basis = f"已有材料支持 {names} 的局部判断。"
    else:
        tier = "初筛"
        basis = "按已有材料核对资格条件。"

    names = {"qualification": "资格条件", "next_window": "次年窗口", **MATERIAL_NAMES}
    items = [
        finding(names[group], "本组材料覆盖完整", "有局部材料" if coverage[group] == "partial" else "未登记材料",
             "缺完整材料", "材料覆盖登记", MATERIAL_ACTIONS[group],
             "高" if group == "qualification" else "中")
        for group in missing_for_complete
    ]
    return {
        "items": items,
        "summary": f"{tier}预评估，共 {len(items)} 个材料组待补。",
        "tier": tier, "basis": basis, "material_coverage": coverage,
        "covered_groups": covered_groups, "missing_for_complete": missing_for_complete,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Report evidence gaps, growth and eligibility checks.",
        epilog="Input: " + json.dumps(INPUT_EXAMPLE, ensure_ascii=False),
    )
    parser.add_argument("input", type=Path, help="JSON input file")
    parser.add_argument("--select-intake", action="store_true", help="Select an intake tier from material_coverage")
    return parser.parse_args()


def calculate_batch(payload: Any, policy: Policy) -> dict[str, Any]:
    errors = []
    results = []
    items = []
    if not isinstance(payload, dict):
        errors.append(issue("$", payload, "包含 scenarios 的输入对象", "按示例将年度情景放入 scenarios", "本批申报年度"))
    else:
        scenarios = payload.get("scenarios")
        if not isinstance(scenarios, list) or not scenarios:
            errors.append(issue("scenarios", scenarios, "非空年度情景数组", "为每个申报年度填写一个情景", "本批申报年度"))
        else:
            for index, scenario in enumerate(scenarios):
                result, findings = analyze_scenario(scenario, policy, index, errors)
                results.append(result)
                items.extend(findings)

    items.extend(
        finding(err["business_location"], err["expected"],
             "缺输入值" if err["actual"] is None else str(err["actual"]),
             "输入校验未通过", err["field_path"], err["fix"], "高")
        for err in errors
    )
    pending = sum(row["gap"] != "无" for row in items)
    eligible_pending = sum(row is not None and row["innovation_requirement_met"] is not True for row in results)
    summary = f"共 {pending} 项待处理，其中 {eligible_pending} 项涉及创新能力资格。"
    return {
        "schema_version": SCHEMA_VERSION,
        "items": items,
        "summary": summary,
        "scenarios": results,
        "validation_errors": errors,
    }


def decimal_for_json(value: Decimal) -> float | str:
    if not isinstance(value, Decimal):
        raise TypeError(f"{type(value).__name__} is not JSON serializable")
    display = float(value) if value.is_finite() else None
    if display is not None and isfinite(display) and Decimal(str(display)) == value:
        return display
    return str(value)


def emit_error(message: str, **details: Any) -> None:
    result = {
        "error": message,
        "items": [],
        "summary": "读取输入或政策依据失败。",
        **details,
    }
    print(json.dumps(result, ensure_ascii=False, default=decimal_for_json, allow_nan=False), file=sys.stderr)


def main() -> int:
    args = parse_args()
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"), parse_float=Decimal, parse_constant=Decimal)
        if args.select_intake:
            print(json.dumps(select_intake_tier(payload), ensure_ascii=False, indent=2))
            return 0
        policy = load_policy()
        result = calculate_batch(payload, policy)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        emit_error(str(exc))
        return 2
    if result["validation_errors"]:
        summary = "\n".join(
            f"{item['field_path']} 应为 {item['expected']}。{item['fix']}"
            for item in result["validation_errors"]
        )
        emit_error(summary, **result)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
