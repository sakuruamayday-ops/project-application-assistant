#!/usr/bin/env python3
"""校验绿色指标记录是否具备可比较边界。"""
import argparse, json
from pathlib import Path

REQUIRED = {"metric", "boundary", "baseline_period", "reporting_period", "unit", "source"}

parser = argparse.ArgumentParser()
parser.add_argument("records")
args = parser.parse_args()
try:
    content = Path(args.records).read_text(encoding="utf-8-sig").strip()
    items = json.loads(content) if content else []
    if not isinstance(items, list) or not items:
        raise ValueError("未提供绿色指标记录，需提供非空 JSON 数组")
    if any(not isinstance(item, dict) for item in items):
        raise ValueError("绿色指标记录每行须为对象")
    errors = []
    for index, item in enumerate(items, 1):
        missing = sorted(REQUIRED - set(item))
        if missing:
            errors.append(f"{index}:缺少{','.join(missing)}")
        if item.get("baseline_period") == item.get("reporting_period"):
            errors.append(f"{index}:基准期与报告期相同")
except (OSError, ValueError) as error:
    errors = [str(error)]
print(json.dumps({"status": "pass" if not errors else "fail", "errors": errors}, ensure_ascii=False, indent=2))
raise SystemExit(0 if not errors else 2)
