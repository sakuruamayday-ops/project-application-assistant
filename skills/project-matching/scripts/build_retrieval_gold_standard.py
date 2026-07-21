#!/usr/bin/env python3
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RULES_PATH = ROOT / "references" / "high-frequency-project-retrieval-rules.json"
OUTPUT_PATH = ROOT / "references" / "high-frequency-project-gold-standard.jsonl"


def build_cases() -> list[dict[str, object]]:
    payload = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    cases: list[dict[str, object]] = []
    for rule in payload["rules"]:
        allowed = rule["allowed_title_terms"][0]
        excluded = rule["excluded_title_terms"][0]
        for alias in rule["aliases"]:
            cases.extend(
                [
                    {
                        "id": f"{rule['id']}:{alias}:positive",
                        "kind": "positive",
                        "alias": alias,
                        "query": f"{alias}申报条件",
                        "expected_targets": rule["targets"],
                        "expected_clarification": bool(
                            rule.get("selection_required")
                            or rule.get("required_region_level")
                        ),
                    },
                    {
                        "id": f"{rule['id']}:{alias}:cross-project",
                        "kind": "cross-project",
                        "alias": alias,
                        "query": f"{alias}申报条件",
                        "allowed_title": f"{allowed}申报通知",
                        "excluded_title": f"{excluded}申报通知",
                    },
                    {
                        "id": f"{rule['id']}:{alias}:stale",
                        "kind": "stale",
                        "alias": alias,
                        "query": f"{alias}申报条件",
                        "current_title": f"{allowed}管理办法",
                        "stale_title": f"2022年{allowed}申报指南",
                    },
                ]
            )
    return cases


def main() -> None:
    cases = build_cases()
    OUTPUT_PATH.write_text(
        "".join(json.dumps(case, ensure_ascii=False, sort_keys=True) + "\n" for case in cases),
        encoding="utf-8",
    )
    print(f"aliases={len(cases) // 3} cases={len(cases)} output={OUTPUT_PATH}")


if __name__ == "__main__":
    main()
