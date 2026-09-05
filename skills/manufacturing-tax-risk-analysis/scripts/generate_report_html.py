#!/usr/bin/env python3
"""Generate a complete 17-page deep-gold tax-risk HTML report from JSON."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any


SECTION_KEYS = [
    ("profitability", "04", "盈利能力"),
    ("cash_flow", "05", "现金流"),
    ("solvency", "06", "偿债能力"),
    ("asset_quality", "07", "资产质量"),
    ("bills_deposits", "08", "票据与保证金"),
    ("related_parties", "09", "往来与关联方"),
    ("guarantees", "10", "对外担保"),
    ("income_tax_rd", "11", "所得税与研发"),
    ("accrual_revenue", "12", "暂估预提与收入"),
]
METRICS_SCHEMA = "manufacturing-tax-risk-metrics/v1"


def esc(value: Any) -> str:
    if value is None:
        return "—"
    return html.escape(str(value), quote=True)


def require(obj: dict[str, Any], key: str, path: str) -> Any:
    if key not in obj or obj[key] in (None, "", []):
        raise ValueError(f"missing required field: {path}.{key}")
    return obj[key]


def require_list(obj: dict[str, Any], key: str, path: str) -> list[Any]:
    value = require(obj, key, path)
    if not isinstance(value, list):
        raise ValueError(f"field must be a list: {path}.{key}")
    return value


def limit(items: list[Any], maximum: int, path: str) -> None:
    if len(items) > maximum:
        raise ValueError(f"too many items: {path} supports at most {maximum}, got {len(items)}")


def text_limit(value: Any, maximum: int, path: str) -> None:
    if value is not None and len(str(value)) > maximum:
        raise ValueError(f"text too long: {path} supports at most {maximum} characters")


def validate_metrics(metrics: dict[str, Any], company: str) -> list[dict[str, Any]]:
    if metrics.get("schema") != METRICS_SCHEMA:
        raise ValueError(f"metrics JSON must use {METRICS_SCHEMA}")
    metrics_company = metrics.get("company")
    if isinstance(metrics_company, dict):
        metrics_company = metrics_company.get("name")
    if str(metrics_company or "").strip() != company.strip():
        raise ValueError("metrics JSON company does not match report company")
    rows = require_list(metrics, "report_rows", "metrics")
    limit(rows, 8, "metrics.report_rows")
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"metrics.report_rows[{index}] must be an object")
        for key in ("indicator", "formula", "result", "source"):
            require(row, key, f"metrics.report_rows[{index}]")
    return rows


def validate(data: dict[str, Any], metrics: dict[str, Any]) -> None:
    for key in ("company", "report_date", "risk_level", "one_line_conclusion"):
        require(data, key, "root")
    text_limit(data["company"], 40, "root.company")
    text_limit(data["one_line_conclusion"], 180, "root.one_line_conclusion")
    text_limit(data.get("use_restriction"), 120, "root.use_restriction")
    period = require(data, "period", "root")
    if not isinstance(period, dict):
        raise ValueError("root.period must be an object")
    require(period, "start", "root.period")
    require(period, "end", "root.period")
    limit(require_list(data, "sources", "root"), 6, "root.sources")
    executive = require_list(data, "executive_findings", "root")
    limit(executive, 5, "root.executive_findings")
    for i, finding in enumerate(executive):
        text_limit(finding.get("conclusion"), 120, f"root.executive_findings[{i}].conclusion")

    overview = require(data, "financial_overview", "root")
    if not isinstance(overview, dict):
        raise ValueError("root.financial_overview must be an object")
    years = require_list(overview, "years", "root.financial_overview")
    if len(years) < 2:
        raise ValueError("financial_overview.years must contain at least two years")
    overview_rows = require_list(overview, "rows", "root.financial_overview")
    limit(overview_rows, 8, "root.financial_overview.rows")
    limit(overview.get("kpis", []), 4, "root.financial_overview.kpis")
    for i, row in enumerate(overview_rows):
        if not isinstance(row, dict):
            raise ValueError(f"financial_overview.rows[{i}] must be an object")
        require(row, "name", f"financial_overview.rows[{i}]")
        values = require_list(row, "values", f"financial_overview.rows[{i}]")
        if len(values) != len(years):
            raise ValueError(f"financial_overview.rows[{i}].values length must match years")
        require(row, "source_pages", f"financial_overview.rows[{i}]")
        require(row, "formula", f"financial_overview.rows[{i}]")

    sections = require(data, "sections", "root")
    if not isinstance(sections, dict):
        raise ValueError("root.sections must be an object")
    for key, _, _ in SECTION_KEYS:
        section = require(sections, key, "root.sections")
        if not isinstance(section, dict):
            raise ValueError(f"root.sections.{key} must be an object")
        require(section, "conclusion", f"root.sections.{key}")
        facts = require_list(section, "facts", f"root.sections.{key}")
        actions = require_list(section, "actions", f"root.sections.{key}")
        limit(facts, 4, f"root.sections.{key}.facts")
        limit(actions, 6, f"root.sections.{key}.actions")
        text_limit(section["conclusion"], 180, f"root.sections.{key}.conclusion")
        for i, fact in enumerate(facts):
            text_limit(fact.get("text"), 140, f"root.sections.{key}.facts[{i}].text")
        for i, action in enumerate(actions):
            text_limit(action, 80, f"root.sections.{key}.actions[{i}]")
        if section.get("table"):
            limit(section["table"].get("rows", []), 8, f"root.sections.{key}.table.rows")

    risks = require_list(data, "risks", "root")
    limit(risks, 8, "root.risks")
    for i, risk in enumerate(risks):
        for key in ("fact", "alternative", "missing_evidence", "action"):
            text_limit(risk.get(key), 120, f"root.risks[{i}].{key}")
    roadmap = require_list(data, "roadmap", "root")
    if len(roadmap) != 3:
        raise ValueError("root.roadmap must contain exactly three stages")
    for i, stage in enumerate(roadmap):
        if not isinstance(stage, dict):
            raise ValueError(f"root.roadmap[{i}] must be an object")
        for key in ("period", "actions", "owner", "completion"):
            require(stage, key, f"root.roadmap[{i}]")
        if not isinstance(stage["actions"], list):
            raise ValueError(f"root.roadmap[{i}].actions must be a list")
    limit(require_list(data, "p0_documents", "root"), 10, "root.p0_documents")
    calculations = require_list(data, "calculations", "root")
    limit(calculations, 10, "root.calculations")
    validate_metrics(metrics, str(data["company"]))
    limit(require_list(data, "policies", "root"), 5, "root.policies")
    require(data, "final_judgment", "root")
    limit(require_list(data, "monthly_indicators", "root"), 5, "root.monthly_indicators")
    final = data["final_judgment"]
    text_limit(final if isinstance(final, str) else final.get("text"), 260, "root.final_judgment.text")


def tag(text: Any, cls: str = "tag") -> str:
    return f'<span class="{cls}">{esc(text)}</span>'


def bullets(items: list[Any], ordered: bool = False) -> str:
    element = "ol" if ordered else "ul"
    lis = "".join(f"<li>{esc(x)}</li>" for x in items)
    return f'<{element} class="clean-list">{lis}</{element}>'


def table(headers: list[Any], rows: list[list[Any]], classes: str = "") -> str:
    head = "".join(f"<th>{esc(x)}</th>" for x in headers)
    body = "".join("<tr>" + "".join(f"<td>{esc(x)}</td>" for x in row) + "</tr>" for row in rows)
    return f'<table class="{esc(classes)}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def page(number: str, label: str, title: str, content: str, extra: str = "") -> str:
    return (
        f'<section class="page {esc(extra)}">'
        f'<header class="page-header"><span class="page-no">{esc(number)}</span><b>{esc(label)}</b></header>'
        f'<h2>{esc(title)}</h2>{content}'
        '<footer class="page-footer">金税四期财务分析｜共创知识产权</footer>'
        '</section>'
    )


def render_cover(data: dict[str, Any]) -> str:
    period = data["period"]
    status = data.get("source_status", "正式资料")
    internal = data.get("internal_only", False)
    restriction = data.get("use_restriction", "")
    warning = "仅供内部自查" if internal else status
    return f"""
    <section class="page cover">
      <div class="cover-inner">
        <p class="eyebrow">GOLDEN TAX RISK ADVISORY</p>
        <h1>金税四期<br>财务分析报告</h1>
        <div class="rule"></div>
        <h2 class="company-name">{esc(data['company'])}</h2>
        <div class="cover-warning">{esc(warning)}</div>
        <div class="meta">
          <div><small>分析期间</small><strong>{esc(period['start'])}—{esc(period['end'])}</strong></div>
          <div><small>报告日期</small><strong>{esc(data['report_date'])}</strong></div>
          <div><small>资料状态</small><strong>{esc(status)}</strong></div>
          <div><small>完成人</small><strong>{esc(data.get('preparer', '共创知识产权'))}</strong></div>
        </div>
        {f'<p class="cover-note">{esc(restriction)}</p>' if restriction else ''}
      </div>
    </section>"""


def render_executive(data: dict[str, Any]) -> str:
    findings = data["executive_findings"][:5]
    cards = "".join(
        f'<article class="card {"risk" if f.get("level") == "高" else "warn" if f.get("level") == "中" else ""}">'
        f'<div class="card-top">{tag(f.get("level", "关注"), "risk-tag")}</div>'
        f'<h3>{esc(f.get("title", "重点判断"))}</h3><p>{esc(f.get("conclusion", "—"))}</p>'
        f'<small>{esc(f.get("source", ""))}</small></article>'
        for f in findings
    )
    body = (
        f'<div class="hero-card"><div class="risk-level">{esc(data["risk_level"])}</div>'
        f'<p>{esc(data["one_line_conclusion"])}</p></div>'
        f'<div class="card-grid">{cards}</div>'
    )
    return page("01", "执行摘要", "五项优先判断", body)


def render_scope(data: dict[str, Any]) -> str:
    source_rows = []
    for source in data["sources"]:
        source_rows.append([
            source.get("name", "—"), source.get("period", "—"), source.get("status", "—"),
            source.get("pages", "—"), source.get("limitation", "—"),
        ])
    missing = data.get("missing_documents", [])
    body = table(["资料", "期间", "状态", "关键页", "用途限制"], source_rows)
    if missing:
        body += '<div class="callout"><h3>当前数据缺口</h3>' + bullets(missing) + '</div>'
    body += '<div class="callout risk"><b>证据闸门：</b>风险信号只代表优先核验顺序，不等于违法认定。</div>'
    return page("02", "口径与证据", "资料边界决定结论强度", body)


def render_overview(data: dict[str, Any]) -> str:
    overview = data["financial_overview"]
    years = overview["years"]
    rows = []
    for row in overview["rows"]:
        annual_values = "；".join(
            f"{year}年：{value}" for year, value in zip(years, row["values"], strict=True)
        )
        rows.append([row["name"], annual_values, row["source_pages"], row["formula"]])
    kpis = "".join(
        f'<article class="card kpi"><small>{esc(x.get("label"))}</small><div class="num">{esc(x.get("value"))}</div><p>{esc(x.get("note", ""))}</p></article>'
        for x in overview.get("kpis", [])[:4]
    )
    body = f'<div class="kpi-grid">{kpis}</div>'
    body += '<h3>财务总览</h3>'
    body += table(["指标", "年度值", "来源页码", "公式"], rows, "overview-table")
    body += f'<div class="callout">{esc(overview.get("conclusion", ""))}</div>'
    return page("03", "三年财务总览", "规模、利润、现金与负债同屏观察", body)


def render_section(number: str, label: str, section: dict[str, Any]) -> str:
    facts = "".join(
        f'<article class="card"><h3>{esc(f.get("title", "事实"))}</h3>'
        f'<p>{esc(f.get("text", "—"))}</p><small>{esc(f.get("source", ""))}</small></article>'
        for f in section["facts"]
    )
    body = f'<div class="callout"><b>结论：</b>{esc(section["conclusion"])}</div><div class="card-grid">{facts}</div>'
    table_data = section.get("table")
    if table_data:
        body += table(table_data.get("headers", []), table_data.get("rows", []))
    body += '<div class="actions"><h3>核验与整改动作</h3>' + bullets(section["actions"], ordered=True) + '</div>'
    return page(number, label, section.get("title", label), body)


def render_risks(data: dict[str, Any]) -> str:
    rows = []
    for risk in data["risks"]:
        rows.append([
            risk.get("chain", "—"), risk.get("fact", "—"), risk.get("alternative", "—"),
            risk.get("missing_evidence", "—"), risk.get("action", "—"), risk.get("level", "—"),
        ])
    body = '<h3>风险地图</h3>'
    body += table(["风险链", "事实", "替代解释", "缺失证据", "动作", "等级"], rows, "risk-table")
    return page("13", "金税风险地图", "以证据强度管理优先级", body)


def render_roadmap(data: dict[str, Any]) -> str:
    rows = [
        [
            stage["period"],
            "；".join(str(action) for action in stage["actions"]),
            stage["owner"],
            stage["completion"],
        ]
        for stage in data["roadmap"]
    ]
    body = '<h3>90天整改路线</h3>'
    body += table(["阶段", "动作", "责任岗位", "完成条件"], rows, "roadmap-table")
    body += f'<div class="callout risk"><h3>P0补充资料</h3>{bullets(data["p0_documents"])}</div>'
    return page("14", "90天整改路线", "90天内完成证据封存、复算与机制固化", body)


def render_sources(data: dict[str, Any], metrics: dict[str, Any]) -> str:
    # Deterministic rows take priority; authored rows fill the remaining page capacity.
    calculations = [*metrics["report_rows"], *data["calculations"]][:10]
    calc_rows = [[x.get("indicator"), x.get("formula"), x.get("result"), x.get("source")] for x in calculations]
    policy_rows = [[x.get("name"), x.get("issuer"), x.get("date"), x.get("url")] for x in data["policies"]]
    body = '<h3>计算过程与来源</h3>' + table(["指标", "公式", "结果", "来源"], calc_rows, "calculation-table")
    body += '<h3>政策依据</h3>' + table(["文件", "发布机关", "日期", "链接"], policy_rows, "policy-table")
    return page("15", "计算过程与来源", "每个金额可回到原页，每个比例可复算", body)


def render_final(data: dict[str, Any]) -> str:
    final = data["final_judgment"]
    if isinstance(final, str):
        title, text = "最终判断", final
    else:
        title, text = final.get("title", "最终判断"), final.get("text", "—")
    indicators = "".join(
        f'<article class="card"><h3>{esc(x.get("name", "指标"))}</h3><div class="metric-rule">{esc(x.get("rule", "—"))}</div>'
        f'<p>{esc(x.get("owner", "财务负责人"))}｜{esc(x.get("frequency", "每月"))}</p></article>'
        for x in data["monthly_indicators"]
    )
    limitations = data.get("limitations", ["本报告不替代税务鉴证或法律意见。"])
    body = f'<div class="hero-card"><div class="risk-level">{esc(data["risk_level"])}</div><h3>{esc(title)}</h3><p>{esc(text)}</p></div>'
    body += f'<div class="card-grid">{indicators}</div><div class="callout risk">{bullets(limitations)}</div>'
    return page("16", "最终判断", title, body, "final-page")


def render(data: dict[str, Any], metrics: dict[str, Any], css: str) -> str:
    pages = [render_cover(data), render_executive(data), render_scope(data), render_overview(data)]
    for key, number, label in SECTION_KEYS:
        pages.append(render_section(number, label, data["sections"][key]))
    pages.extend([render_risks(data), render_roadmap(data), render_sources(data, metrics), render_final(data)])
    title = f"{data['company']}｜金税四期财务分析报告"
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title><style>{css}</style></head><body>{''.join(pages)}</body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="report-data JSON")
    parser.add_argument("output", type=Path, nargs="?", help="generated HTML")
    parser.add_argument(
        "--metrics-json",
        type=Path,
        required=True,
        help="deterministic manufacturing-tax-risk-metrics/v1 JSON",
    )
    parser.add_argument("--css", type=Path, help="gold-advisor.css path")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    data = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("input root must be an object")
    metrics = json.loads(args.metrics_json.read_text(encoding="utf-8"))
    if not isinstance(metrics, dict):
        raise ValueError("metrics JSON root must be an object")
    validate(data, metrics)
    if args.validate_only:
        print(json.dumps({"status": "valid", "input": str(args.input)}, ensure_ascii=False))
        return
    if not args.output:
        parser.error("output is required unless --validate-only is used")
    css_path = args.css or Path(__file__).resolve().parent.parent / "assets" / "gold-advisor.css"
    css = css_path.read_text(encoding="utf-8")
    result = render(data, metrics, css)
    body_html = result.split("</style>", 1)[-1]
    if "{{" in body_html or "}}" in body_html:
        raise ValueError("unresolved template marker detected in generated HTML")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(result, encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "ok",
                "pages": 17,
                "output": str(args.output),
                "metrics": str(args.metrics_json),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
