#!/usr/bin/env python3
"""检查投资台账凭证链和汇总金额。"""
import argparse, json
from decimal import Decimal
from pathlib import Path

REQUIRED = {"id", "contract", "invoice", "payment", "asset", "amount_tax_included", "amount_tax_excluded", "date"}
parser = argparse.ArgumentParser()
parser.add_argument("ledger")
args = parser.parse_args()
items = json.loads(Path(args.ledger).read_text(encoding="utf-8"))
errors, included, excluded = [], Decimal("0"), Decimal("0")
for index, item in enumerate(items, 1):
    missing = sorted(REQUIRED - set(item))
    if missing:
        errors.append(f"{index}:缺少{','.join(missing)}")
        continue
    try:
        included += Decimal(str(item["amount_tax_included"]))
        excluded += Decimal(str(item["amount_tax_excluded"]))
    except Exception:
        errors.append(f"{index}:金额不是有效十进制数")
print(json.dumps({"status": "pass" if not errors else "fail", "count": len(items), "total_tax_included": str(included), "total_tax_excluded": str(excluded), "errors": errors}, ensure_ascii=False, indent=2))
raise SystemExit(0 if not errors else 2)
