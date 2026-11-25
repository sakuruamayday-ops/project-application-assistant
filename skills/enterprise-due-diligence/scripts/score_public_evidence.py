#!/usr/bin/env python3
"""List disclosed risk signals and the public records needed to verify them."""

import argparse
import json
import math
import sys
from pathlib import Path


VERIFICATION_ACTIONS = (
    (("司法", "执行", "诉讼", "失信", "限高", "劳动", "裁判", "冻结"),
     "核对法院原文的主体、案号、案由、当事人角色和当前进展。"),
    (("行政", "处罚", "环保", "合规", "信用"),
     "调取主管部门决定和整改记录，核对时间、责任主体及当前状态。"),
    (("融资", "担保", "抵押", "质押"),
     "核对登记原件及解除记录，确认义务主体、期限和现存责任。"),
    (("股权", "实控", "治理", "主体", "关联"),
     "核对工商公示、股东变更和控制关系，确认登记主体及生效日期。"),
    (("知识产权", "专利", "商标", "软著"),
     "查权利登记及法律状态，核对权属、有效期和产品关联。"),
    (("经营", "客户", "市场", "产品", "土地", "设备", "项目"),
     "核对原始公告与企业提供的业务记录，确认事件是否仍有效。"),
)
DEFAULT_ACTION = "核对原始出处、企业身份和记录日期，补当前事实及处理状态。"
REQUIREMENT = "有可回查的原始记录，能核对主体、发生时间与当前状态"


def input_rows(records, field):
    if not isinstance(records, list) or any(not isinstance(row, dict) for row in records):
        raise ValueError(f"{field} 必须为对象数组")
    return records


def finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("旧版数值字段须为有限数值")
    return number


def validate_legacy_indicators(indicators, public_fields):
    observed = [row for row in indicators if row.get("score") is not None]
    if not observed:
        return
    weight_sum = sum(finite_float(row["weight"]) for row in observed)
    if not math.isfinite(weight_sum) or weight_sum <= 0:
        raise ValueError("已观察指标的权重合计须为正")
    for row in observed:
        finite_float(row["score"])
    if any(row.get("score") is None and "name" not in row for row in indicators):
        raise ValueError("缺记录的指标须填写名称")
    for record in public_fields:
        finite_float(record.get("weight", 1))


def risk_action(name):
    return next((action for words, action in VERIFICATION_ACTIONS if any(word in name for word in words)),
                DEFAULT_ACTION)


def finding(name, record, *, actual, gap, evidence, priority):
    return {
        "item": name,
        "requirement": str(record.get("requirement") or REQUIREMENT),
        "actual": actual,
        "gap": gap,
        "evidence": evidence,
        "action": str(record.get("action") or risk_action(name)),
        "priority": priority,
    }


def evidence_label(record):
    sources = record.get("evidence") or record.get("source")
    if isinstance(sources, (dict, list)):
        return json.dumps(sources, ensure_ascii=False)
    return str(sources) if sources else "缺原始出处"


def calculate(payload):
    if not isinstance(payload, dict):
        raise ValueError("输入须为对象")
    indicators = input_rows(payload.get("indicators", []), "indicators")
    public_fields = input_rows(payload.get("public_evidence") or [], "public_evidence")
    if not indicators and not public_fields:
        raise ValueError("至少登记一项指标或公开材料")
    validate_legacy_indicators(indicators, public_fields)

    items = []
    hits = set()
    for index, row in enumerate(indicators, 1):
        name = str(row.get("name") or f"公开指标第 {index} 项")
        state = row.get("risk_signal")
        fact = row.get("fact") or row.get("actual")
        if state is True:
            hits.add(name)
            actual = f"登记命中。{fact}" if fact else "登记命中，缺事项细节"
            gap = "须核对风险事项的原始记录与处置状态"
            priority = "高"
        elif state is False:
            actual = f"本次登记未命中。{fact}" if fact else "本次登记未命中"
            gap = "无" if row.get("evidence") or row.get("source") else "缺本次核验出处"
            priority = "低" if gap == "无" else "中"
        else:
            actual = str(fact) if fact else "输入缺事项事实及命中状态"
            gap = "缺可核实的命中或排除依据"
            priority = "中"
        items.append(finding(name, row, actual=actual, gap=gap, evidence=evidence_label(row), priority=priority))

    for index, record in enumerate(public_fields, 1):
        name = str(record.get("name") or f"公开材料第 {index} 项")
        found = record.get("found") is True
        source = evidence_label(record)
        if found and record.get("risk_signal") is True:
            hits.add(name)
            actual = record.get("fact") or "材料登记存在风险信号"
            gap = "须核对事项原文及当前状态"
            priority = "高"
        elif found:
            actual = record.get("fact") or "登记已取得材料"
            gap = "无" if record.get("evidence") or record.get("source") else "缺材料出处"
            priority = "低" if gap == "无" else "中"
        else:
            actual = "缺公开材料或检索记录"
            gap = "缺可回查的来源"
            priority = "中"
        items.append(finding(name, record, actual=str(actual), gap=gap, evidence=source, priority=priority))

    pending = sum(row["gap"] != "无" for row in items)
    return {"items": items, "summary": f"登记命中 {len(hits)} 类风险信号，共 {pending} 项需核实或补证。"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="JSON input path")
    args = parser.parse_args()
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        result = calculate(payload)
    except (OSError, ValueError, TypeError, KeyError, OverflowError) as exc:
        print(json.dumps({"items": [], "summary": f"输入校验未通过。{exc}"}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
