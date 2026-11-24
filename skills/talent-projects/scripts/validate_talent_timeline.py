#!/usr/bin/env python3
"""检查人才关键日期的基本先后关系。"""
import argparse, json
from datetime import date
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("timeline")
args = parser.parse_args()
errors = []
dates = {}
try:
    content = Path(args.timeline).read_text(encoding="utf-8-sig").strip()
    value = json.loads(content) if content else {}
    if not isinstance(value, dict) or not value:
        raise ValueError("未提供人才关键日期，需提供非空 JSON 对象")
    for key, raw in value.items():
        try:
            dates[key] = date.fromisoformat(raw)
        except (TypeError, ValueError):
            errors.append(f"{key}:日期格式应为YYYY-MM-DD")
except (OSError, ValueError) as error:
    errors.append(str(error))
if dates.get("employment_start") and dates.get("application_deadline") and dates["employment_start"] > dates["application_deadline"]:
    errors.append("劳动关系开始日晚于申报截止日")
if dates.get("company_established") and dates.get("application_deadline") and dates["company_established"] > dates["application_deadline"]:
    errors.append("企业成立日晚于申报截止日")
print(json.dumps({"status": "pass" if not errors else "fail", "errors": errors}, ensure_ascii=False, indent=2))
raise SystemExit(0 if not errors else 2)
