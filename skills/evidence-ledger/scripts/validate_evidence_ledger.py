#!/usr/bin/env python3
"""校验证据台账JSON数组或JSONL。"""

import argparse
import json
from pathlib import Path

TYPES = {"fact", "calculation", "inference", "pending"}
STATUSES = {"verified", "unverified", "conflicted", "expired"}
REQUIRED = {"id", "subject", "claim", "type", "source", "retrieved_at", "location", "status"}


def load(path: Path):
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    value = json.loads(text)
    return value if isinstance(value, list) else value.get("records", [])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("ledger")
    args = parser.parse_args()
    records = load(Path(args.ledger))
    ids, errors = set(), []
    for index, item in enumerate(records, 1):
        missing = sorted(REQUIRED - set(item))
        if missing:
            errors.append(f"{index}:缺少{','.join(missing)}")
        if item.get("id") in ids:
            errors.append(f"{index}:证据编号重复")
        ids.add(item.get("id"))
        if item.get("type") not in TYPES or item.get("status") not in STATUSES:
            errors.append(f"{index}:类型或状态不合法")
        if item.get("type") == "calculation" and (not item.get("formula") or not item.get("inputs")):
            errors.append(f"{index}:计算项缺少公式或输入")
        if item.get("type") == "inference" and not item.get("supports"):
            errors.append(f"{index}:推断项缺少支撑证据")
    print(json.dumps({"status": "pass" if not errors else "fail", "records": len(records), "errors": errors}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if not errors else 2)


if __name__ == "__main__":
    main()
