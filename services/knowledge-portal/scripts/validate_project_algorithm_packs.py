#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PORTAL_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = PORTAL_DIR.parents[1]
if str(PORTAL_DIR) not in sys.path:
    sys.path.insert(0, str(PORTAL_DIR))

from app.project_decision import (  # noqa: E402
    activate_confirmed_policy_rules,
    build_enterprise_fact_ledger,
    evaluate_project_feasibility,
    merge_fact_contract,
    validate_project_algorithm_pack,
)


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def required_project_names(rules_path: Path) -> set[str]:
    payload = load_json(rules_path)
    if not isinstance(payload, dict):
        raise ValueError("高频项目检索规则顶层必须为对象")
    rules = payload.get("rules", [])
    if not isinstance(rules, list):
        raise ValueError("高频项目检索规则rules必须为列表")
    return {
        str(target).strip()
        for rule in rules
        if isinstance(rule, dict)
        for target in rule.get("targets", [])
        if str(target).strip()
    }


def validate_pack_gold_cases(
    pack: dict[str, object],
    base_contract: list[dict[str, object]],
) -> list[str]:
    errors: list[str] = []
    merge_fact_contract(base_contract, pack.get("fact_fields", []))
    rule_cards = pack.get("rule_cards", [])
    for case in pack.get("gold_cases", []):
        case_id = str(case.get("case_id") or "unnamed")
        confirmations = {
            str(rule_id): "confirmed"
            for rule_id in case.get("confirm_rule_ids", [])
        }
        activation = activate_confirmed_policy_rules(rule_cards, confirmations)
        feasibility = evaluate_project_feasibility(
            project_context={
                "project_id": pack.get("project_id"),
                "project_name": pack.get("project_name"),
                "policy_status": "current",
            },
            requirements=activation["active_rules"],
            fact_ledger=build_enterprise_fact_ledger(case.get("facts", [])),
        )
        expected = str(case.get("expected_conclusion") or "")
        if feasibility["overall_conclusion"] != expected:
            errors.append(
                f"{pack.get('project_id')}:{case_id} "
                f"期望{expected}，实际{feasibility['overall_conclusion']}"
            )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--packs-dir",
        type=Path,
        default=PORTAL_DIR / "references" / "project-algorithm-packs",
    )
    parser.add_argument(
        "--fact-contract",
        type=Path,
        default=PORTAL_DIR / "references" / "lifecycle-fact-contract.json",
    )
    parser.add_argument(
        "--retrieval-rules",
        type=Path,
        default=(
            ROOT_DIR
            / "skills"
            / "project-matching"
            / "references"
            / "high-frequency-project-retrieval-rules.json"
        ),
    )
    arguments = parser.parse_args()
    fact_payload = load_json(arguments.fact_contract)
    base_contract = fact_payload.get("fields", [])
    errors: list[str] = []
    validated = 0
    covered_projects: set[str] = set()
    for path in sorted(arguments.packs_dir.glob("*.json")):
        try:
            pack = load_json(path)
        except (OSError, json.JSONDecodeError) as error:
            errors.append(f"{path.name}: {error}")
            continue
        if not isinstance(pack, dict):
            errors.append(f"{path.name}: 顶层必须为对象")
            continue
        pack_errors = validate_project_algorithm_pack(pack)
        pack_errors.extend(validate_pack_gold_cases(pack, base_contract))
        errors.extend(f"{path.name}: {error}" for error in pack_errors)
        project_name = str(pack.get("project_name") or "").strip()
        if project_name:
            if project_name in covered_projects:
                errors.append(f"{path.name}: project_name重复：{project_name}")
            covered_projects.add(project_name)
        validated += 1
    if validated == 0:
        errors.append("没有发现项目算法包")
    try:
        required_projects = required_project_names(arguments.retrieval_rules)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        errors.append(f"高频项目覆盖校验失败：{error}")
        required_projects = set()
    missing_projects = sorted(required_projects - covered_projects)
    if missing_projects:
        errors.append(
            "高频项目缺少算法包：" + "、".join(missing_projects)
        )
    print(
        json.dumps(
            {
                "status": "pass" if not errors else "fail",
                "validated_packs": validated,
                "required_projects": len(required_projects),
                "covered_projects": len(required_projects & covered_projects),
                "coverage": (
                    "100%"
                    if required_projects
                    and required_projects <= covered_projects
                    else "incomplete"
                ),
                "missing_projects": missing_projects,
                "errors": errors,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
