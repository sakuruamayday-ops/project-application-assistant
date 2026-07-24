#!/usr/bin/env python3
"""校验产业化项目分类、成熟度和证据矩阵。"""

from __future__ import annotations

import json
import sys
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


def validate(document: dict) -> list[str]:
    errors: list[str] = []
    context = document.get("project_context", {})
    for field in ("product", "region", "year", "policy_status"):
        if not context.get(field):
            errors.append(f"project_context缺少{field}")
    if not document.get("primary_project"):
        errors.append("缺少primary_project")
    if not document.get("classification_basis"):
        errors.append("缺少classification_basis")
    if not document.get("maturity_stage"):
        errors.append("缺少maturity_stage")
    evidence = document.get("evidence")
    if not isinstance(evidence, dict):
        errors.append("evidence必须为对象")
        evidence = {}
    missing = EVIDENCE_FIELDS - set(evidence)
    if missing:
        errors.append(f"证据维度缺失:{sorted(missing)}")
    for name, item in evidence.items():
        if name in EVIDENCE_FIELDS and (not isinstance(item, dict) or item.get("status") not in STATES):
            errors.append(f"evidence.{name}状态无效")
    conclusion = document.get("conclusion")
    if conclusion not in {"candidate", "conditional", "eligible", "ineligible", "undetermined"}:
        errors.append("conclusion无效")
    if context.get("policy_status") != "current" and conclusion == "eligible":
        errors.append("政策非current时不得判eligible")
    if any(
        isinstance(evidence.get(field), dict)
        and evidence[field].get("status") in {"missing", "conflicting", "claimed"}
        for field in EVIDENCE_FIELDS
    ) and conclusion == "eligible":
        errors.append("关键证据未核验时不得判eligible")
    for field in ("alternative_projects", "exclusion_risks", "next_actions"):
        if field not in document:
            errors.append(f"缺少{field}")
    return errors


def main() -> int:
    if len(sys.argv) != 2:
        print("用法: validate_industrialization_assessment.py <结果.json>", file=sys.stderr)
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
