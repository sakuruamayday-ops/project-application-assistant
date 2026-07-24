#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


VALID_QUALITY = {"verified", "partially_verified", "unverified"}


def validate(
    payload: dict[str, object],
    expected_company: str = "",
    expected_credit_code: str = "",
) -> list[str]:
    errors: list[str] = []
    if payload.get("schema") != "enterprise-financial-facts/v1":
        errors.append("不支持的财务事实契约")
    company = payload.get("company")
    if not isinstance(company, dict) or not str(company.get("name") or "").strip():
        errors.append("缺少企业名称")
    elif expected_company and str(company.get("name")).strip() != expected_company.strip():
        errors.append("企业名称与当前任务不一致")
    if isinstance(company, dict) and expected_credit_code:
        actual_credit_code = str(company.get("unified_social_credit_code") or "").strip()
        if actual_credit_code != expected_credit_code.strip():
            errors.append("统一社会信用代码与当前任务不一致")
    basis = payload.get("basis")
    if not isinstance(basis, dict):
        errors.append("缺少财务口径")
    else:
        if basis.get("currency") != "CNY":
            errors.append("币种不是CNY")
        if basis.get("unit") not in {"yuan", "ten_thousand_yuan"}:
            errors.append("金额单位不可识别")
        if basis.get("consolidation_scope") not in {"standalone", "consolidated", "unknown"}:
            errors.append("合并口径不可识别")
    periods = payload.get("periods")
    if not isinstance(periods, dict) or not periods:
        errors.append("缺少财务期间")
    else:
        for year, period in periods.items():
            if not str(year).isdigit() or len(str(year)) != 4 or not isinstance(period, dict):
                errors.append(f"无效财务期间：{year}")
                continue
            if not isinstance(period.get("facts"), dict):
                errors.append(f"{year}缺少facts")
            if not isinstance(period.get("metrics"), dict):
                errors.append(f"{year}缺少metrics")
            quality = period.get("quality")
            if not isinstance(quality, dict) or quality.get("status") not in VALID_QUALITY:
                errors.append(f"{year}质量状态无效")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--company", default="")
    parser.add_argument("--credit-code", default="")
    arguments = parser.parse_args()
    payload = json.loads(arguments.path.read_text(encoding="utf-8"))
    errors = validate(payload, arguments.company, arguments.credit_code)
    print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
