#!/usr/bin/env python3
"""Calculate repeatable financial metrics from a normalized multi-year JSON file."""

from __future__ import annotations

import argparse
import json
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


def calc(data):
    missing = sorted(REQUIRED - data.keys())
    if missing:
        raise ValueError(f"missing fields: {', '.join(missing)}")
    average_assets = (data["assets"] + data["assets_open"]) / 2
    average_equity = (data["equity"] + data["equity_open"]) / 2
    average_receivables = (data["receivables"] + data["receivables_open"]) / 2
    average_inventory = (data["inventory"] + data["inventory_open"]) / 2
    return {
        "gross_margin": div(data["revenue"] - data["cost"], data["revenue"]),
        "net_margin": div(data["net_profit"], data["revenue"]),
        "debt_ratio": div(data["liabilities"], data["assets"]),
        "current_ratio": div(data["current_assets"], data["current_liabilities"]),
        "quick_ratio": div(data["current_assets"] - data["inventory"], data["current_liabilities"]),
        "cash_ratio": div(data["cash"], data["current_liabilities"]),
        "roe": div(data["net_profit"], average_equity),
        "roa": div(data["net_profit"], average_assets),
        "ar_days": div(average_receivables, data["revenue"]) * 365 if data["revenue"] else None,
        "inventory_days": div(average_inventory, data["cost"]) * 365 if data["cost"] else None,
        "other_ar_to_assets": div(data["other_receivables"], data["assets"]),
        "other_ar_to_revenue": div(data["other_receivables"], data["revenue"]),
        "advance_to_revenue": div(data["advances_from_customers"], data["revenue"]),
        "research_to_revenue": div(data["research_expense"], data["revenue"]),
        "cash_tax_payment_rate": div(data["taxes_paid"], data["revenue"]),
        "sales_cash_to_revenue": div(data["sales_cash"], data["revenue"]),
        "ocf_to_profit": div(data["operating_cash_flow"], data["net_profit"]),
        "free_cash_flow": data["operating_cash_flow"] - data["capex_cash"],
        "interest_coverage": div(
            data["profit_before_tax"] + data["interest_expense"], data["interest_expense"]
        ),
        "working_capital": data["current_assets"] - data["current_liabilities"],
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
    result = {"company": source.get("company", ""), "years": {}}
    for year in sorted(years):
        result["years"][year] = {"raw": years[year], "metrics": calc(years[year])}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
