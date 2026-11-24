#!/usr/bin/env python3
"""校验产业化项目分类、成熟度和证据矩阵。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


EVIDENCE_FIELDS = {
    "innovation",
    "maturity",
    "intellectual_property",
    "testing",
    "user_application",
    "transaction",
    "industrialization",
}
STATES = {"verified", "claimed", "missing", "conflicting", "not-applicable"}
CONCLUSIONS = {"candidate", "conditional", "eligible", "ineligible", "undetermined"}


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def findings(document: dict) -> list[dict[str, str]]:
    items = []

    def add(field, gap, action):
        items.append({"item": field, "gap": gap, "action": action, "priority": "高"})

    if not isinstance(document, dict):
        add("结果", "缺项目评估对象", "按案例填写项目、证据和结论")
        return items
    context = document.get("project_context")
    if not isinstance(context, dict):
        context = {}
    for field in ("product", "region", "year", "policy_status"):
        if not context.get(field):
            add("project_context." + field, "缺项目边界信息", "补齐产品、地区、年度及政策状态")
    for field in ("primary_project", "classification_basis", "maturity_stage"):
        if not document.get(field):
            add(field, "缺申报方向或成熟度判断", "按产品形态及现有证据填写")
    conclusion = document.get("conclusion")
    eligible = conclusion == "eligible"
    if not isinstance(conclusion, str) or conclusion not in CONCLUSIONS:
        add("conclusion", "结论状态无效", "选择候选、条件、满足、不满足或未确定的状态")
    if eligible and (context.get("policy_status") != "current" or not nonempty(context.get("policy_locator"))):
        add("project_context.policy_locator", "缺现行管理办法的原文位置", "填写管理办法标题、文号及条款或页码")

    evidence = document.get("evidence")
    if not isinstance(evidence, dict):
        add("evidence", "证据须按维度组织", "填写七类证据对象")
        evidence = {}
    for name in sorted(EVIDENCE_FIELDS):
        item = evidence.get(name)
        field = f"evidence.{name}"
        state = item.get("status") if isinstance(item, dict) else None
        if not isinstance(state, str) or state not in STATES:
            add(field, "缺有效的证据状态", "登记该项证据状态及原件位置")
        elif eligible and state == "verified" and not nonempty(item.get("source_locator")):
            add(field, "标为已核验，缺原件位置", "补对应原件名称及条款、页码、行号或单元格")
        elif eligible and state == "not-applicable" and not nonempty(item.get("policy_locator")):
            add(field, "缺不适用的政策条款", "填写支持不适用的管理条款位置")
        elif eligible and state in {"missing", "conflicting", "claimed"}:
            add(field, "证据状态未支持资格结论", "补原件或核对冲突后重新判断")
    for field in ("alternative_projects", "exclusion_risks", "next_actions"):
        if field not in document:
            add(field, "缺输出项", "补候选方向、排除条件和后续动作")
    return items


def validate(document: dict) -> list[str]:
    return [f"{item['item']}：{item['gap']}" for item in findings(document)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("assessment", type=Path)
    args = parser.parse_args()
    try:
        items = findings(json.loads(args.assessment.read_text(encoding="utf-8")))
    except (OSError, ValueError) as error:
        items = [{"item": "结果文件", "gap": str(error), "action": "检查路径和 UTF-8 JSON 格式", "priority": "高"}]
    errors = [f"{item['item']}：{item['gap']}" for item in items]
    print(json.dumps({"status": "fail" if errors else "pass", "errors": errors, "items": items}, ensure_ascii=False, indent=2))
    return 2 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
