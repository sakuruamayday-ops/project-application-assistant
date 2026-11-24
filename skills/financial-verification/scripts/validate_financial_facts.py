#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from validate_financial_assessment import (BOUNDED_RATIOS, SHARED_METRICS, bounded_ratio, decimal_value,
                                           source_subjects, subject_text)

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
    name = subject_text(company.get("name")) if isinstance(company, dict) else ""
    if not name:
        errors.append("缺主体信息")
    names = [item for item in (expected_company.strip(), name) if item]
    for index, subject, source in source_subjects(payload.get("source_artifacts") or []):
        if subject:
            names.append(subject)
        else:
            errors.append(f"{source.get('path') or source.get('name') or index + 1}：缺主体信息")
    if len(set(names)) > 1:
        errors.append("主体不一致：" + "、".join(dict.fromkeys(names)))
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
        has_financial_rows = False
        for year, period in periods.items():
            if not str(year).isdigit() or len(str(year)) != 4 or not isinstance(period, dict):
                errors.append(f"无效财务期间：{year}")
                continue
            if not isinstance(period.get("facts"), dict):
                errors.append(f"{year}缺少facts")
            if not isinstance(period.get("metrics"), dict):
                errors.append(f"{year}缺少metrics")
            if isinstance(period.get("facts"), dict) and isinstance(period.get("metrics"), dict):
                has_financial_rows |= bool(period["facts"] or period["metrics"])
                for field, (formula_id, (numerator, denominator)) in SHARED_METRICS.items():
                    if formula_id not in BOUNDED_RATIOS:
                        continue
                    supplied = period["metrics"].get(field)
                    base = period["facts"].get(denominator)
                    part = period["facts"].get(numerator)
                    try:
                        if part is not None and base is not None and decimal_value(base):
                            bounded_ratio(decimal_value(part) / decimal_value(base), formula_id)
                        if supplied is not None:
                            bounded_ratio(decimal_value(supplied), formula_id)
                    except ValueError as error:
                        errors.append(f"{year}/{field}：{error}")
            quality = period.get("quality")
            if not isinstance(quality, dict) or quality.get("status") not in VALID_QUALITY:
                errors.append(f"{year}质量状态无效")
        if not has_financial_rows:
            errors.append("未提供财务事实或指标")
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
