#!/usr/bin/env python3
"""校验政府项目可行性结构化结果及结论推导。"""

from __future__ import annotations

import json
import sys
from pathlib import Path


CONCLUSIONS = {"eligible", "conditional", "ineligible", "undetermined"}
GATE_STATES = {"passed", "failed", "pending", "unknown", "not-applicable"}
EVIDENCE_STATES = {
    "verified",
    "computed",
    "claimed",
    "missing",
    "conflicting",
    "not-applicable",
}


def validate(document: dict) -> list[str]:
    errors: list[str] = []
    context = document.get("project_context")
    if not isinstance(context, dict):
        errors.append("缺少project_context")
        context = {}
    for field in ("project_name", "region", "year", "application_type", "policy_status"):
        if not context.get(field):
            errors.append(f"project_context缺少{field}")

    conclusion = document.get("overall_conclusion")
    if conclusion not in CONCLUSIONS:
        errors.append("overall_conclusion无效")

    gates = document.get("hard_gates")
    if not isinstance(gates, list) or not gates:
        errors.append("hard_gates必须为非空列表")
        gates = []
    failed = pending = unknown = False
    for index, gate in enumerate(gates):
        prefix = f"hard_gates[{index}]"
        state = gate.get("status")
        evidence = gate.get("evidence_state")
        if not gate.get("rule_id") or not gate.get("source"):
            errors.append(f"{prefix}缺少rule_id或source")
        if state not in GATE_STATES:
            errors.append(f"{prefix}.status无效")
        if evidence not in EVIDENCE_STATES:
            errors.append(f"{prefix}.evidence_state无效")
        if state == "passed" and evidence not in {"verified", "computed"}:
            errors.append(f"{prefix}证据不足却标记passed")
        failed |= state == "failed"
        pending |= state == "pending"
        unknown |= state == "unknown"

    if failed and conclusion != "ineligible":
        errors.append("存在failed硬门槛时结论必须为ineligible")
    if not failed and (pending or unknown) and conclusion == "eligible":
        errors.append("存在pending或unknown硬门槛时不得为eligible")
    if context.get("policy_status") != "current" and conclusion == "eligible":
        errors.append("政策状态非current时不得为eligible")

    for field in ("scoring", "calculations", "uncertainties", "evidence_gaps", "actions"):
        if field not in document:
            errors.append(f"缺少{field}")
    for index, calculation in enumerate(document.get("calculations", [])):
        if not all(key in calculation for key in ("formula", "inputs", "unit", "result", "review_status")):
            errors.append(f"calculations[{index}]字段不完整")
    return errors


def main() -> int:
    if len(sys.argv) != 2:
        print("用法: validate_feasibility_assessment.py <结果.json>", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "fail", "errors": [str(exc)]}, ensure_ascii=False))
        return 2
    errors = validate(document)
    print(json.dumps({"status": "pass" if not errors else "fail", "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
