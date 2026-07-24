#!/usr/bin/env python3
"""检查外经贸记录的订单、凭证、币种和期间字段。"""
import argparse, json
from pathlib import Path

REQUIRED = {"id", "trade_type", "order", "evidence", "amount", "currency", "period"}
parser = argparse.ArgumentParser()
parser.add_argument("records")
args = parser.parse_args()
items = json.loads(Path(args.records).read_text(encoding="utf-8"))
errors = []
for index, item in enumerate(items, 1):
    missing = sorted(REQUIRED - set(item))
    if missing:
        errors.append(f"{index}:缺少{','.join(missing)}")
    if item.get("converted_amount") is not None and not all(item.get(key) is not None for key in ("exchange_rate", "rate_date", "rate_source")):
        errors.append(f"{index}:折算金额缺少汇率、日期或来源")
print(json.dumps({"status": "pass" if not errors else "fail", "errors": errors}, ensure_ascii=False, indent=2))
raise SystemExit(0 if not errors else 2)
