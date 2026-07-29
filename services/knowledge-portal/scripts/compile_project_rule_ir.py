#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PORTAL_DIR = Path(__file__).resolve().parents[1]
if str(PORTAL_DIR) not in sys.path:
    sys.path.insert(0, str(PORTAL_DIR))

from app.rule_ir import (  # noqa: E402
    compile_rule_ir,
    load_algorithm_packs,
    read_json,
    write_compiled_rule_ir,
)


def write_card(path: Path, card: object) -> str:
    encoded = json.dumps(card, ensure_ascii=False, indent=2) + "\n"
    if path.is_file() and path.read_text(encoding="utf-8") == encoded:
        return "hash_reused"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(encoded, encoding="utf-8")
    temporary.replace(path)
    return "compiled"


def main() -> int:
    parser = argparse.ArgumentParser(description="编译29项目统一规则中间语言")
    parser.add_argument(
        "--packs-dir",
        type=Path,
        default=PORTAL_DIR / "references" / "project-algorithm-packs",
    )
    parser.add_argument(
        "--lifecycle-rules",
        type=Path,
        default=PORTAL_DIR / "references" / "enterprise-lifecycle-rules.json",
    )
    parser.add_argument(
        "--fact-contract",
        type=Path,
        default=PORTAL_DIR / "references" / "lifecycle-fact-contract.json",
    )
    parser.add_argument(
        "--policy-baselines",
        type=Path,
        default=PORTAL_DIR / "references" / "project-policy-baselines.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PORTAL_DIR / "references" / "compiled-project-rule-ir.json",
    )
    parser.add_argument(
        "--cards-dir",
        type=Path,
        default=PORTAL_DIR / "references" / "project-algorithm-cards",
    )
    arguments = parser.parse_args()
    packs = load_algorithm_packs(arguments.packs_dir)
    lifecycle_payload = read_json(arguments.lifecycle_rules)
    fact_contract = read_json(arguments.fact_contract)
    baseline_registry = read_json(arguments.policy_baselines)
    if (
        not isinstance(lifecycle_payload, dict)
        or not isinstance(fact_contract, dict)
        or not isinstance(baseline_registry, dict)
    ):
        raise ValueError("生命周期规则、事实契约和政策基线顶层必须为对象")
    payload = compile_rule_ir(
        packs,
        lifecycle_payload,
        fact_contract,
        baseline_registry,
    )
    bundle_status = write_compiled_rule_ir(arguments.output, payload)
    card_statuses = {
        project_id: write_card(
            arguments.cards_dir / f"{project_id}.json",
            card,
        )
        for project_id, card in payload["algorithm_cards"].items()
    }
    result = {
        "status": "pass",
        "bundle_status": bundle_status,
        "source_digest": payload["source_digest"],
        "project_count": payload["metrics"]["project_count"],
        "shared_kernel_count": payload["metrics"]["shared_kernel_count"],
        "rules_confirmed_count": payload["metrics"]["rules_confirmed_count"],
        "policy_baseline_count": payload["metrics"]["policy_baseline_count"],
        "policy_covered_count": payload["metrics"]["policy_covered_count"],
        "routing_only_count": payload["metrics"]["routing_only_count"],
        "policy_dependency_nodes": payload["metrics"][
            "policy_dependency_nodes"
        ],
        "policy_dependency_edges": payload["metrics"][
            "policy_dependency_edges"
        ],
        "cards_compiled": sum(status == "compiled" for status in card_statuses.values()),
        "cards_reused": sum(status == "hash_reused" for status in card_statuses.values()),
        "output": str(arguments.output),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
