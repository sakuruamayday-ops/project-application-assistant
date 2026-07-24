#!/usr/bin/env python3
"""校验绿色指标记录是否具备可比较边界。"""
import argparse, json
from pathlib import Path

REQUIRED = {"metric", "boundary", "baseline_period", "reporting_period", "unit", "source"}

parser = argparse.ArgumentParser()
parser.add_argument("records")
args = parser.parse_args()
items = json.loads(Path(args.records).read_text(encoding="utf-8"))
errors = []
for index, item in enumerate(items, 1):
    missing = sorted(REQUIRED - set(item))
    if missing:
        errors.append(f"{index}:缺少{','.join(missing)}")
    if item.get("baseline_period") == item.get("reporting_period"):
        errors.append(f"{index}:基准期与报告期相同")
print(json.dumps({"status": "pass" if not errors else "fail", "errors": errors}, ensure_ascii=False, indent=2))
raise SystemExit(0 if not errors else 2)
