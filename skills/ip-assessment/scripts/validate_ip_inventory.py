#!/usr/bin/env python3
"""校验知识产权清单的主体、状态和关联字段。"""
import argparse, json
from pathlib import Path

REQUIRED = {"id", "type", "title", "owner", "status", "cutoff_date", "acquisition", "product_link"}
parser = argparse.ArgumentParser()
parser.add_argument("inventory")
args = parser.parse_args()
items = json.loads(Path(args.inventory).read_text(encoding="utf-8"))
errors = []
for index, item in enumerate(items, 1):
    missing = sorted(REQUIRED - set(item))
    if missing:
        errors.append(f"{index}:缺少{','.join(missing)}")
    if item.get("status") == "pending" and item.get("usable_as_granted") is True:
        errors.append(f"{index}:审中权利不能标记为已授权使用")
print(json.dumps({"status": "pass" if not errors else "fail", "errors": errors}, ensure_ascii=False, indent=2))
raise SystemExit(0 if not errors else 2)
