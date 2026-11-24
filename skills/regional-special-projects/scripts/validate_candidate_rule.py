#!/usr/bin/env python3
"""校验临时专项候选规则结构。"""
import argparse, json
from pathlib import Path

REQUIRED = {"project_name", "region", "authority", "year", "source_url", "applicants", "hard_gates", "exclusions", "materials", "deadline", "status"}
parser = argparse.ArgumentParser()
parser.add_argument("rule")
args = parser.parse_args()
value = json.loads(Path(args.rule).read_text(encoding="utf-8"))
missing = sorted(REQUIRED - set(value))
errors = [f"缺少字段:{key}" for key in missing]
if value.get("status") not in {"candidate", "verified"}:
    errors.append("status只能为candidate或verified")
print(json.dumps({"status": "pass" if not errors else "fail", "errors": errors}, ensure_ascii=False, indent=2))
raise SystemExit(0 if not errors else 2)
