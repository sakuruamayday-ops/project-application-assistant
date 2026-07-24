#!/usr/bin/env python3
"""校验财务核验结果的主体、口径、来源和计算可追溯性。"""

from __future__ import annotations

import json
import sys
from pathlib import Path


STATES = {"verified", "computed", "missing", "conflicting", "not-applicable"}


def validate(document: dict) -> list[str]:
    errors: list[str] = []
    identity = document.get("identity", {})
    if not (identity.get("company_name") or identity.get("credit_code")):
        errors.append("缺少企业身份")
    scope = document.get("scope", {})
    for field in ("period", "currency", "unit", "consolidation_scope"):
        if not scope.get(field):
            errors.append(f"scope缺少{field}")
    sources = document.get("sources")
    if not isinstance(sources, list) or not sources:
        errors.append("sources必须为非空列表")
    facts = document.get("facts")
    if not isinstance(facts, list):
        errors.append("facts必须为列表")
        facts = []
    for index, fact in enumerate(facts):
        if fact.get("status") not in STATES:
            errors.append(f"facts[{index}].status无效")
        if fact.get("status") in {"verified", "computed"} and not fact.get("source_ids"):
            errors.append(f"facts[{index}]可用事实缺少来源")
    for index, metric in enumerate(document.get("metrics", [])):
        required = ("metric", "formula", "inputs", "unit", "result", "status")
        if not all(field in metric for field in required):
            errors.append(f"metrics[{index}]字段不完整")
        if metric.get("status") == "computed" and not metric.get("source_ids"):
            errors.append(f"metrics[{index}]计算结果缺少来源")
    if "conflicts" not in document or "quality" not in document:
        errors.append("缺少conflicts或quality")
    return errors


def main() -> int:
    if len(sys.argv) != 2:
        print("用法: validate_financial_assessment.py <结果.json>", file=sys.stderr)
        return 2
    try:
        document = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "fail", "errors": [str(exc)]}, ensure_ascii=False))
        return 2
    errors = validate(document)
    print(json.dumps({"status": "pass" if not errors else "fail", "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
