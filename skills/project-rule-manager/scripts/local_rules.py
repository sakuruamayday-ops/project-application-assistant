#!/usr/bin/env python3
"""Create and query local rule records without editing an existing rule directory."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


STATUSES = {"draft", "candidate", "verified", "stale", "superseded", "withdrawn"}


def validate(data):
    """Validate rule identities and status values without deciding policy validity."""
    if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
        raise ValueError("input must contain a rules array")
    ids = []
    for rule in data["rules"]:
        if not isinstance(rule, dict) or not isinstance(rule.get("id"), str) or not rule["id"].strip():
            raise ValueError("each rule needs a non-empty id")
        if rule.get("status") not in STATUSES:
            raise ValueError(f"rule {rule['id']}: invalid status {rule.get('status')!r}")
        ids.append(rule["id"])
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate rule id")

    def check_status(value, location="root"):
        if isinstance(value, dict):
            for key, item in value.items():
                # 更正关系不是状态；比较表也不能写出 corrected_value 等新状态。
                if key in {"status", "old_status", "new_status"} and item not in STATUSES:
                    raise ValueError(f"{location}.{key}: invalid status {item!r}")
                check_status(item, f"{location}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                check_status(item, f"{location}[{index}]")

    check_status(data)
    return data


def create(data, output):
    """Write a new canonical rule file and a real-time audit; refuse overwrites."""
    validate(data)
    if any(rule["status"] == "verified" for rule in data["rules"]):
        raise ValueError("new extraction cannot claim verified; keep candidate pending confirmation")
    now = datetime.now(timezone.utc).isoformat()
    document = {**data, "recorded_at": now}
    # JSON 是 YAML 的稳定子集；只写一份规则源，避免 YAML/JSON 双份漂移。
    rendered = json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    with (output / "rule.yaml").open("x", encoding="utf-8") as file:
        file.write(rendered)
    for name in ("sources", "versions"):
        (output / name).mkdir()
    audit = {"at": now, "action": "create", "rule_ids": [rule["id"] for rule in data["rules"]]}
    with (output / "audit.jsonl").open("x", encoding="utf-8") as file:
        file.write(json.dumps(audit, ensure_ascii=False) + "\n")
    return {"path": str(output / "rule.yaml"), "count": len(data["rules"]), "recorded_at": now}


def query(data, statuses, year=None):
    """Filter recorded statuses and year; this is not a legal-effectiveness judgment."""
    validate(data)
    return [rule for rule in data["rules"] if rule["status"] in statuses
            and (year is None or str(rule.get("year", "")) == str(year))]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    writer = commands.add_parser("create", help="create a new directory from a JSON input")
    writer.add_argument("--input", type=Path, required=True)
    writer.add_argument("--output", type=Path, required=True)
    reader = commands.add_parser("query", help="query a rule.yaml written by this script")
    reader.add_argument("--input", type=Path, required=True)
    reader.add_argument("--status", action="append", choices=sorted(STATUSES), required=True)
    reader.add_argument("--year")
    args = parser.parse_args()
    try:
        data = json.loads(args.input.read_text(encoding="utf-8"))
        result = create(data, args.output) if args.command == "create" else query(data, args.status, args.year)
    except (ValueError, TypeError, OSError) as error:
        parser.exit(1, f"local rules: {error}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
