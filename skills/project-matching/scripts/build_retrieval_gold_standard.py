#!/usr/bin/env python3
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RULES_PATH = ROOT / "references" / "high-frequency-project-retrieval-rules.json"
OUTPUT_PATH = ROOT / "references" / "high-frequency-project-gold-standard.jsonl"


def build_cases() -> list[dict[str, object]]:
    payload = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    cases: list[dict[str, object]] = []
    for rule in payload["rules"]:
        for alias in rule["aliases"]:
            required_level = str(rule.get("required_region_level") or "")
            jurisdiction_regions = [
                str(region)
                for region in rule.get("jurisdiction_title_terms", {})
                if str(region) in alias
            ]
            title_rule = (
                rule.get("jurisdiction_title_terms", {}).get(jurisdiction_regions[0], rule)
                if jurisdiction_regions
                else rule
            )
            allowed = title_rule["allowed_title_terms"][0]
            excluded = title_rule["excluded_title_terms"][0]
            region_is_explicit = bool(
                required_level == "city"
                and re.search(r"[\u4e00-\u9fff]{2,8}市", alias)
                or required_level == "district"
                and re.search(r"[\u4e00-\u9fff]{2,8}(?:区|县)", alias)
            )
            cases.extend(
                [
                    {
                        "id": f"{rule['id']}:{alias}:positive",
                        "kind": "positive",
                        "alias": alias,
                        "query": f"{alias}申报条件",
                        "expected_targets": [
                            " ".join((jurisdiction_regions[0], target))
                            if jurisdiction_regions and jurisdiction_regions[0] not in target
                            else target
                            for target in rule["targets"]
                        ],
                        "expected_clarification": bool(
                            rule.get("selection_required")
                            or required_level and not region_is_explicit
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
