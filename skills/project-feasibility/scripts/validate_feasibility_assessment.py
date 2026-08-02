#!/usr/bin/env python3
"""校验政府项目可行性结构化结果及结论推导。"""

from __future__ import annotations

import ast
import json
import math
import re
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
VERIFIED_CALCULATION_STATES = {"passed", "verified", "computed"}


def _numeric(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("不是数值")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("不是有限数值")
    return number


def _evaluate(node: ast.AST, inputs: dict[str, object]) -> float:
    if isinstance(node, ast.Expression):
        return _evaluate(node.body, inputs)
    if isinstance(node, ast.Constant):
        return _numeric(node.value)
    if isinstance(node, ast.Name):
        if node.id not in inputs:
            raise ValueError(f"公式变量{node.id}未在inputs中声明")
        return _numeric(inputs[node.id])
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _evaluate(node.operand, inputs)
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp) and isinstance(
        node.op,
        (ast.Add, ast.Sub, ast.Mult, ast.Div),
    ):
        left = _evaluate(node.left, inputs)
        right = _evaluate(node.right, inputs)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if right == 0:
            raise ValueError("公式除数为零")
        return left / right
    raise ValueError("公式含不允许的运算")


def _formula_result(formula: str, inputs: dict[str, object]) -> float:
    expression = formula.strip().replace("×", "*").replace("÷", "/")
    expression = re.sub(r"(?<=\d)%", "/100", expression)
    if "=" in expression:
        expression = expression.split("=", 1)[0].strip()
    if not expression:
        raise ValueError("公式为空")
    return _evaluate(ast.parse(expression, mode="eval"), inputs)


def _matches_result(expected: float, actual: float, unit: str) -> bool:
    candidates = [actual]
    if "%" in unit or "百分" in unit:
        candidates.extend((actual / 100, actual * 100))
    return any(math.isclose(expected, value, rel_tol=1e-6, abs_tol=1e-8) for value in candidates)


def _validate_calculation(calculation: dict, index: int) -> list[str]:
    prefix = f"calculations[{index}]"
    required = ("formula", "inputs", "unit", "result", "review_status")
    if not all(key in calculation for key in required):
        return [f"{prefix}字段不完整"]
    review_status = str(calculation.get("review_status") or "")
    if review_status not in VERIFIED_CALCULATION_STATES:
        return [f"{prefix}.review_status未通过语义复算"]
    inputs = calculation.get("inputs")
    if not isinstance(inputs, dict) or not inputs:
        return [f"{prefix}.inputs必须为可复算的数值对象"]
    try:
        expected = _formula_result(str(calculation["formula"]), inputs)
        actual = _numeric(calculation["result"])
    except (SyntaxError, ValueError) as error:
        return [f"{prefix}无法语义复算：{error}"]
    if not _matches_result(expected, actual, str(calculation.get("unit") or "")):
        return [f"{prefix}结果与公式不一致：复算值{expected:g}，填报值{actual:g}"]
    return []


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
    calculations = document.get("calculations", [])
    if not isinstance(calculations, list):
        errors.append("calculations必须为列表")
        calculations = []
    for index, calculation in enumerate(calculations):
        if not isinstance(calculation, dict):
            errors.append(f"calculations[{index}]必须为对象")
            continue
        errors.extend(_validate_calculation(calculation, index))
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
