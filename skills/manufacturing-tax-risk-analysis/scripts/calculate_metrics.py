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

PERCENTAGE_METRICS = {
    "gross_margin", "net_margin", "debt_ratio", "roe", "roa",
    "other_ar_to_assets", "other_ar_to_revenue", "advance_to_revenue",
    "research_to_revenue", "cash_tax_payment_rate", "sales_cash_to_revenue",
    "ocf_to_profit",
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


def format_ratio(value):
    if value is None:
        return "无法计算"
    return f"{value * 100:.2f}%"


def format_amount(value, unit):
    if value is None:
        return "无法计算"
    if unit == "yuan" and abs(value) >= 10000:
        return f"{value:,.2f}元（{value / 10000:,.2f}万元）"
    return f"{value:,.2f}{unit}"


def unavailable_reason(metric, facts):
    requirements = {
        "inventory_days": (
            ("cost", "营业成本"),
            ("inventory", "期末存货"),
            ("inventory_open", "期初存货"),
        ),
    }
    missing = [label for field, label in requirements.get(metric, ()) if facts.get(field) in (None, 0)]
    return f"缺少{'、'.join(missing)}，无法计算" if missing else "输入不足，无法计算"


def build_metrics_summary(financial_facts):
    """Build report-ready deterministic rows so the model cannot omit material math."""
    periods = financial_facts["periods"]
    years = sorted(periods)
    unit = financial_facts["basis"]["unit"]
    indicators = {
        "revenue_growth": {
            "label": "营业收入同比增长率",
            "formula": "（本年营业收入－上年营业收入）÷上年营业收入",
            "values": {},
        },
        "receivables_growth": {
            "label": "应收账款同比增长率",
            "formula": "（本年应收账款－上年应收账款）÷上年应收账款",
            "values": {},
        },
        "research_to_revenue": {
            "label": "研发费用率",
            "formula": "研发费用÷营业收入",
            "values": {},
        },
        "balance_equation_gap": {
            "label": "资产负债表恒等式差额",
            "formula": "资产总额－负债总额－权益",
            "values": {},
        },
    }
    unavailable = []

    for index, year in enumerate(years):
        current = periods[year]
        facts = current["facts"]
        metrics = current["metrics"]
        indicators["research_to_revenue"]["values"][year] = metrics["research_to_revenue"]
        gap = subtract(subtract(facts.get("assets"), facts.get("liabilities")), facts.get("equity"))
        indicators["balance_equation_gap"]["values"][year] = gap
        if index:
            previous = periods[years[index - 1]]["facts"]
            indicators["revenue_growth"]["values"][year] = div(
                subtract(facts.get("revenue"), previous.get("revenue")),
                previous.get("revenue"),
            )
            indicators["receivables_growth"]["values"][year] = div(
                subtract(facts.get("receivables"), previous.get("receivables")),
                previous.get("receivables"),
            )
        if metrics.get("inventory_days") is None:
            unavailable.append(
                {
                    "indicator": "存货周转天数",
                    "year": year,
                    "reason": unavailable_reason("inventory_days", facts),
                }
            )

    report_rows = []
    recent_growth_years = years[-3:]
    for key in ("revenue_growth", "receivables_growth"):
        indicator = indicators[key]
        for year in recent_growth_years:
            if year not in indicator["values"]:
                continue
            value = indicator["values"][year]
            report_rows.append(
                {
                    "indicator": f"{year}年{indicator['label']}",
                    "formula": indicator["formula"],
                    "result": format_ratio(value),
                    "source": "enterprise-financial-facts/v1确定性复算",
                }
            )
    if years:
        latest = years[-1]
        research = indicators["research_to_revenue"]["values"][latest]
        report_rows.append(
            {
                "indicator": f"{latest}年研发费用率",
                "formula": indicators["research_to_revenue"]["formula"],
                "result": format_ratio(research),
                "source": "enterprise-financial-facts/v1确定性复算",
            }
        )
    for year in recent_growth_years:
        gap = indicators["balance_equation_gap"]["values"].get(year)
        if gap not in (None, 0):
            report_rows.append(
                {
                    "indicator": f"{year}年资产负债表恒等式差额",
                    "formula": indicators["balance_equation_gap"]["formula"],
                    "result": format_amount(gap, unit),
                    "source": "enterprise-financial-facts/v1确定性复算",
                }
            )
    if years:
        latest_unavailable = [item for item in unavailable if item["year"] == years[-1]]
        for item in latest_unavailable[:1]:
            report_rows.append(
                {
                    "indicator": f"{item['year']}年{item['indicator']}",
                    "formula": "平均存货÷营业成本×365",
                    "result": item["reason"],
                    "source": "enterprise-financial-facts/v1缺失字段检查",
                }
            )

    return {
        "schema": "manufacturing-tax-risk-metrics/v1",
        "company": financial_facts["company"],
        "basis": financial_facts["basis"],
        "period": {
            "start": f"{years[0]}年度",
            "end": f"{years[-1]}年度",
        },
        "indicators": indicators,
        "uncomputable_indicators": unavailable,
        "report_rows": report_rows,
        "producer": "manufacturing-tax-risk-analysis",
        "generated_at": financial_facts["generated_at"],
        "note": "本文件由确定性计算器生成；缺失输入不会按零处理。",
    }


def build_validation_values(financial_facts, metrics_summary):
    """Return deterministic display variants for Host-side evidence binding."""
    values = []
    seen = set()

    def add(value):
        text = str(value)
        if text not in seen:
            seen.add(text)
            values.append(text)

    def add_amount(value):
        if value is None or isinstance(value, bool):
            return
        numeric = float(value)
        unit = str(financial_facts["basis"].get("unit") or "").lower()
        add(value)
        add(f"{numeric:,.2f}")
        if unit in {"yuan", "元", "cny"}:
            add(f"{numeric:,.2f}元")
            add(f"{numeric / 10000:,.2f}万元")
        elif unit in {"wanyuan", "万元"}:
            add(f"{numeric:,.2f}万元")
            add(f"{numeric * 10000:,.2f}元")

    for year, period in financial_facts["periods"].items():
        add(year)
        for value in period["facts"].values():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                add_amount(value)
        for name, value in period["metrics"].items():
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            add(value)
            add(f"{value:.2f}")
            if name in PERCENTAGE_METRICS:
                add(f"{value * 100:.2f}%")
            if name in {"free_cash_flow", "working_capital"}:
                add_amount(value)

    if metrics_summary is not None:
        for name, indicator in metrics_summary["indicators"].items():
            for value in indicator["values"].values():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    add(value)
                    add(f"{value:.2f}")
                    if name in {"revenue_growth", "receivables_growth", "research_to_revenue"}:
                        add(f"{value * 100:.2f}%")
                    elif name == "balance_equation_gap":
                        add_amount(value)
        for row in metrics_summary["report_rows"]:
            add(row["result"])
    return values


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--metrics-output",
        type=Path,
        help="optional manufacturing-tax-risk-metrics/v1 companion output",
    )
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
    metrics_output = None
    if args.metrics_output:
        metrics_output = build_metrics_summary(result)
        args.metrics_output.parent.mkdir(parents=True, exist_ok=True)
        args.metrics_output.write_text(
            json.dumps(metrics_output, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps({
        "schema_version": "manufacturing-tax-risk-calculation-operation/v1",
        "financial_facts": str(args.output),
        "metrics": str(args.metrics_output) if args.metrics_output else None,
        # 这些值来自同一确定性计算过程，供客户端宿主直接绑定；模型不再逐页抄录数字。
        "validation_values": build_validation_values(result, metrics_output),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
