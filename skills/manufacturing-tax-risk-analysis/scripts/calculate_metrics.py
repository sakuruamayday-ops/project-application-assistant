#!/usr/bin/env python3
"""Calculate repeatable financial metrics from a normalized multi-year JSON file."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


REQUIRED = {
    "revenue", "cost", "profit_before_tax", "net_profit", "assets", "assets_open",
    "liabilities", "equity", "equity_open", "current_assets", "current_liabilities",
    "cash", "receivables", "receivables_open", "other_receivables", "inventory",
    "inventory_open", "advances_from_customers", "short_term_loans",
    "operating_cash_flow", "capex_cash", "taxes_paid", "sales_cash",
    "research_expense", "interest_expense", "income_tax_expense",
}


def div(numerator, denominator):
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def add(*values):
    if any(value is None for value in values):
        return None
    return sum(values)


def subtract(minuend, subtrahend):
    if minuend is None or subtrahend is None:
        return None
    return minuend - subtrahend


def average(first, second):
    total = add(first, second)
    return total / 2 if total is not None else None


def turnover_days(average_balance, denominator):
    ratio = div(average_balance, denominator)
    return ratio * 365 if ratio is not None else None


def calc(data):
    missing = sorted(REQUIRED - data.keys())
    if missing:
        raise ValueError(f"missing fields: {', '.join(missing)}")
    average_assets = average(data["assets"], data["assets_open"])
    average_equity = average(data["equity"], data["equity_open"])
    average_receivables = average(data["receivables"], data["receivables_open"])
    average_inventory = average(data["inventory"], data["inventory_open"])
    gross_profit = subtract(data["revenue"], data["cost"])
    quick_assets = subtract(data["current_assets"], data["inventory"])
    earnings_before_interest = add(data["profit_before_tax"], data["interest_expense"])
    return {
        "gross_margin": div(gross_profit, data["revenue"]),
        "net_margin": div(data["net_profit"], data["revenue"]),
        "debt_ratio": div(data["liabilities"], data["assets"]),
        "current_ratio": div(data["current_assets"], data["current_liabilities"]),
        "quick_ratio": div(quick_assets, data["current_liabilities"]),
        "cash_ratio": div(data["cash"], data["current_liabilities"]),
        "roe": div(data["net_profit"], average_equity),
        "roa": div(data["net_profit"], average_assets),
        "ar_days": turnover_days(average_receivables, data["revenue"]),
        "inventory_days": turnover_days(average_inventory, data["cost"]),
        "other_ar_to_assets": div(data["other_receivables"], data["assets"]),
        "other_ar_to_revenue": div(data["other_receivables"], data["revenue"]),
        "advance_to_revenue": div(data["advances_from_customers"], data["revenue"]),
        "research_to_revenue": div(data["research_expense"], data["revenue"]),
        "cash_tax_payment_rate": div(data["taxes_paid"], data["revenue"]),
        "sales_cash_to_revenue": div(data["sales_cash"], data["revenue"]),
        "ocf_to_profit": div(data["operating_cash_flow"], data["net_profit"]),
        "free_cash_flow": subtract(data["operating_cash_flow"], data["capex_cash"]),
        "interest_coverage": div(earnings_before_interest, data["interest_expense"]),
        "working_capital": subtract(data["current_assets"], data["current_liabilities"]),
    }


def company_identity(source):
    company = source.get("company", "")
    if isinstance(company, dict):
        return {
            "name": str(company.get("name") or "").strip(),
            "unified_social_credit_code": str(
                company.get("unified_social_credit_code") or ""
            ).strip(),
        }
    return {
        "name": str(company or "").strip(),
        "unified_social_credit_code": str(
            source.get("unified_social_credit_code") or ""
        ).strip(),
    }


def quality_for(source, year, facts):
    quality = source.get("quality", {}).get(year, {})
    if not isinstance(quality, dict):
        quality = {}
    missing_fields = [name for name in sorted(REQUIRED) if facts.get(name) is None]
    status = quality.get("status")
    if status not in {"verified", "partially_verified", "unverified"}:
        status = "partially_verified" if not missing_fields else "unverified"
    return {
        "status": status,
        "missing_fields": missing_fields,
        "notes": list(quality.get("notes") or []),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    source = json.loads(args.input.read_text(encoding="utf-8"))
    years = source.get("years")
    if not isinstance(years, dict) or not years:
        raise ValueError("input must contain a non-empty years object")
    basis = source.get("basis") if isinstance(source.get("basis"), dict) else {}
    result = {
        "schema": "enterprise-financial-facts/v1",
        "company": company_identity(source),
        "basis": {
            "currency": basis.get("currency", "CNY"),
            "unit": basis.get("unit", "yuan"),
            "consolidation_scope": basis.get("consolidation_scope", "unknown"),
            "accounting_standard": basis.get("accounting_standard", ""),
        },
        "periods": {},
        "source_artifacts": list(source.get("source_artifacts") or []),
        "producer": "manufacturing-tax-risk-analysis",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    evidence = source.get("evidence") if isinstance(source.get("evidence"), dict) else {}
    for year in sorted(years):
        facts = years[year]
        result["periods"][year] = {
            "facts": facts,
            "metrics": calc(facts),
            "evidence": evidence.get(year, {}),
            "quality": quality_for(source, year, facts),
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
