#!/usr/bin/env python3
"""按用户提供的整数维度分对专利布局候选排序。"""
import argparse, json
from pathlib import Path

FIELDS = ("business", "maturity", "difference", "detectability", "difficulty", "evidence", "urgency")
parser = argparse.ArgumentParser()
parser.add_argument("candidates")
args = parser.parse_args()
items = json.loads(Path(args.candidates).read_text(encoding="utf-8"))
errors = []
for index, item in enumerate(items, 1):
    for field in FIELDS:
        value = item.get(field)
        if not isinstance(value, int) or not 0 <= value <= 5:
            errors.append(f"{index}:{field}应为0至5整数")
    item["score"] = sum(item.get(field, 0) for field in FIELDS)
items.sort(key=lambda item: item.get("score", 0), reverse=True)
print(json.dumps({"status": "pass" if not errors else "fail", "errors": errors, "candidates": items}, ensure_ascii=False, indent=2))
raise SystemExit(0 if not errors else 2)
