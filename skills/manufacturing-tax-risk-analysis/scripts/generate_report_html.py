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


def require_list(
    obj: dict[str, Any], key: str, path: str, *, allow_empty: bool = False
) -> list[Any]:
    if key not in obj or obj[key] in (None, ""):
        raise ValueError(f"missing required field: {path}.{key}")
    value = obj[key]
    if not isinstance(value, list):
        raise ValueError(f"field must be a list: {path}.{key}")
    if not allow_empty and not value:
        raise ValueError(f"missing required field: {path}.{key}")
    return value


def require_object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"field must be an object: {path}")
    return value


def require_text(value: Any, path: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"field must be text: {path}")
    return value


def require_text_field(obj: dict[str, Any], key: str, path: str) -> str:
    return require_text(require(obj, key, path), f"{path}.{key}")


def validate_text_list(items: list[Any], path: str) -> list[str]:
    return [require_text(item, f"{path}[{index}]") for index, item in enumerate(items)]


def limit(items: list[Any], maximum: int, path: str) -> None:
    if len(items) > maximum:
        raise ValueError(f"too many items: {path} supports at most {maximum}, got {len(items)}")


def text_limit(value: Any, maximum: int, path: str) -> None:
    if value is None:
        return
    text = require_text(value, path)
    if len(text) > maximum:
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
            require_text_field(row, key, f"metrics.report_rows[{index}]")
    return rows


def validate(data: dict[str, Any], metrics: dict[str, Any]) -> None:
    for key in ("company", "report_date", "risk_level", "one_line_conclusion"):
        require_text_field(data, key, "root")
    text_limit(data["company"], 40, "root.company")
    text_limit(data["one_line_conclusion"], 180, "root.one_line_conclusion")
    text_limit(data.get("use_restriction"), 120, "root.use_restriction")
    for key in ("preparer", "source_status"):
        if key in data:
            require_text(data[key], f"root.{key}")
    if "internal_only" in data and not isinstance(data["internal_only"], bool):
        raise ValueError("field must be boolean: root.internal_only")
    period = require_object(require(data, "period", "root"), "root.period")
    require_text_field(period, "start", "root.period")
    require_text_field(period, "end", "root.period")

    sources = require_list(data, "sources", "root")
    limit(sources, 6, "root.sources")
    for i, source_value in enumerate(sources):
        source = require_object(source_value, f"root.sources[{i}]")
        for key in ("name", "period", "status", "pages", "limitation"):
            require_text_field(source, key, f"root.sources[{i}]")
    if "missing_documents" in data:
        validate_text_list(require_list(data, "missing_documents", "root"), "root.missing_documents")

    executive = require_list(data, "executive_findings", "root")
    limit(executive, 5, "root.executive_findings")
    for i, finding_value in enumerate(executive):
        finding = require_object(finding_value, f"root.executive_findings[{i}]")
        for key in ("title", "conclusion", "level", "source"):
            require_text_field(finding, key, f"root.executive_findings[{i}]")
        text_limit(finding.get("conclusion"), 120, f"root.executive_findings[{i}].conclusion")

    overview = require_object(require(data, "financial_overview", "root"), "root.financial_overview")
    years = require_list(overview, "years", "root.financial_overview")
    if len(years) < 2:
        raise ValueError("financial_overview.years must contain at least two years")
    validate_text_list(years, "root.financial_overview.years")
    overview_rows = require_list(overview, "rows", "root.financial_overview")
    limit(overview_rows, 8, "root.financial_overview.rows")
    kpis = require_list(overview, "kpis", "root.financial_overview")
    limit(kpis, 4, "root.financial_overview.kpis")
    for i, kpi_value in enumerate(kpis):
        kpi = require_object(kpi_value, f"root.financial_overview.kpis[{i}]")
        for key in ("label", "value"):
            require_text_field(kpi, key, f"root.financial_overview.kpis[{i}]")
        if "note" in kpi:
            require_text(kpi["note"], f"root.financial_overview.kpis[{i}].note")
    for i, row in enumerate(overview_rows):
        if not isinstance(row, dict):
            raise ValueError(f"financial_overview.rows[{i}] must be an object")
        require_text_field(row, "name", f"root.financial_overview.rows[{i}]")
        values = require_list(row, "values", f"financial_overview.rows[{i}]")
        if len(values) != len(years):
            raise ValueError(f"financial_overview.rows[{i}].values length must match years")
        validate_text_list(values, f"root.financial_overview.rows[{i}].values")
        require_text_field(row, "source_pages", f"root.financial_overview.rows[{i}]")
        require_text_field(row, "formula", f"root.financial_overview.rows[{i}]")
    require_text_field(overview, "conclusion", "root.financial_overview")

    sections = require(data, "sections", "root")
    if not isinstance(sections, dict):
        raise ValueError("root.sections must be an object")
    for key, _, _ in SECTION_KEYS:
        section = require(sections, key, "root.sections")
        if not isinstance(section, dict):
            raise ValueError(f"root.sections.{key} must be an object")
        require_text_field(section, "conclusion", f"root.sections.{key}")
        if "title" in section:
            require_text(section["title"], f"root.sections.{key}.title")
        facts = require_list(section, "facts", f"root.sections.{key}")
        actions = require_list(section, "actions", f"root.sections.{key}")
        limit(facts, 4, f"root.sections.{key}.facts")
        limit(actions, 6, f"root.sections.{key}.actions")
        text_limit(section["conclusion"], 180, f"root.sections.{key}.conclusion")
        for i, fact_value in enumerate(facts):
            fact = require_object(fact_value, f"root.sections.{key}.facts[{i}]")
            for field in ("title", "text", "source"):
                require_text_field(fact, field, f"root.sections.{key}.facts[{i}]")
            text_limit(fact.get("text"), 140, f"root.sections.{key}.facts[{i}].text")
        for i, action in enumerate(actions):
            text_limit(action, 80, f"root.sections.{key}.actions[{i}]")
        if section.get("table") is not None:
            table_data = require_object(section["table"], f"root.sections.{key}.table")
            headers = require_list(table_data, "headers", f"root.sections.{key}.table")
            validate_text_list(headers, f"root.sections.{key}.table.headers")
            table_rows = require_list(table_data, "rows", f"root.sections.{key}.table")
            limit(table_rows, 8, f"root.sections.{key}.table.rows")
            for row_index, row_value in enumerate(table_rows):
                if not isinstance(row_value, list):
                    raise ValueError(f"field must be a list: root.sections.{key}.table.rows[{row_index}]")
                validate_text_list(row_value, f"root.sections.{key}.table.rows[{row_index}]")

    risks = require_list(data, "risks", "root")
    limit(risks, 8, "root.risks")
    for i, risk_value in enumerate(risks):
        risk = require_object(risk_value, f"root.risks[{i}]")
        for key in ("chain", "fact", "alternative", "missing_evidence", "action", "level"):
            require_text_field(risk, key, f"root.risks[{i}]")
        for key in ("fact", "alternative", "missing_evidence", "action"):
            text_limit(risk.get(key), 120, f"root.risks[{i}].{key}")
    roadmap = require_list(data, "roadmap", "root")
    if len(roadmap) != 3:
        raise ValueError("root.roadmap must contain exactly three stages")
    for i, stage in enumerate(roadmap):
        if not isinstance(stage, dict):
            raise ValueError(f"root.roadmap[{i}] must be an object")
        for key in ("period", "owner", "completion"):
            require_text_field(stage, key, f"root.roadmap[{i}]")
        if "goal" in stage:
            require_text(stage["goal"], f"root.roadmap[{i}].goal")
        validate_text_list(require_list(stage, "actions", f"root.roadmap[{i}]"), f"root.roadmap[{i}].actions")
    p0_documents = require_list(data, "p0_documents", "root")
    limit(p0_documents, 10, "root.p0_documents")
    validate_text_list(p0_documents, "root.p0_documents")
    # 确定性指标文件已经提供主计算表。补充计算可以为空，避免模型为了满足
    # 非业务必需的占位项反复改写 JSON，并把同一计算重复塞进固定页面。
    calculations = require_list(data, "calculations", "root", allow_empty=True)
    limit(calculations, 10, "root.calculations")
    for i, calculation_value in enumerate(calculations):
        calculation = require_object(calculation_value, f"root.calculations[{i}]")
        for key in ("indicator", "formula", "result", "source"):
            require_text_field(calculation, key, f"root.calculations[{i}]")
    validate_metrics(metrics, str(data["company"]))
    policies = require_list(data, "policies", "root", allow_empty=True)
    limit(policies, 5, "root.policies")
    for i, policy_value in enumerate(policies):
        policy = require_object(policy_value, f"root.policies[{i}]")
        for key in ("name", "issuer", "date", "url"):
            require_text_field(policy, key, f"root.policies[{i}]")
        if any("待核验" in str(policy[key]) for key in ("name", "issuer", "date", "url")):
            raise ValueError(f"placeholder policy is not allowed: root.policies[{i}]")
        if not str(policy["url"]).startswith(("https://", "http://")):
            raise ValueError(f"official policy URL is required: root.policies[{i}].url")
    final = require(data, "final_judgment", "root")
    if isinstance(final, dict):
        require_text_field(final, "title", "root.final_judgment")
        require_text_field(final, "text", "root.final_judgment")
    elif not isinstance(final, str):
        raise ValueError("field must be text or an object: root.final_judgment")
    monthly_indicators = require_list(data, "monthly_indicators", "root")
    limit(monthly_indicators, 5, "root.monthly_indicators")
    for i, indicator_value in enumerate(monthly_indicators):
        indicator = require_object(indicator_value, f"root.monthly_indicators[{i}]")
        for key in ("name", "rule", "owner", "frequency"):
            require_text_field(indicator, key, f"root.monthly_indicators[{i}]")
    if "limitations" in data:
        validate_text_list(require_list(data, "limitations", "root"), "root.limitations")
    text_limit(final if isinstance(final, str) else final.get("text"), 260, "root.final_judgment.text")


def tag(text: Any, cls: str = "tag") -> str:
    return f'<span class="{cls}">{esc(text)}</span>'


def bullets(items: list[str], ordered: bool = False) -> str:
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
    policy_draft = not data["policies"]
    status = "草稿：政策原文未核验" if policy_draft else data.get("source_status", "正式资料")
    internal = data.get("internal_only", False)
    restriction = data.get("use_restriction", "")
    warning = "草稿，不用于正式税务结论" if policy_draft else "仅供内部自查" if internal else status
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
            "；".join(stage["actions"]),
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
    body = '<h3>计算过程与来源</h3>' + table(["指标", "公式", "结果", "来源"], calc_rows, "calculation-table")
    if data["policies"]:
        policy_rows = [[x.get("name"), x.get("issuer"), x.get("date"), x.get("url")] for x in data["policies"]]
        body += '<h3>政策依据</h3>' + table(["文件", "发布机关", "日期", "链接"], policy_rows, "policy-table")
    else:
        body += '<h3>政策依据</h3><div class="callout risk">本轮未取得可逐字核验的官方政策原文，本报告为草稿，不得作为正式税务结论使用。</div>'
    return page("15", "计算过程与来源", "每个金额可回到原页，每个比例可复算", body)


def render_final(data: dict[str, Any]) -> str:
    final = data["final_judgment"]
    if isinstance(final, str):
        title, text = "最终判断", final
    else:
        title, text = final.get("title", "最终判断"), final.get("text", "—")
    indicator_rows = [
        [x["name"], x["rule"], x["owner"], x["frequency"]]
        for x in data["monthly_indicators"]
    ]
    limitations = data.get("limitations", ["本报告不替代税务鉴证或法律意见。"])
    body = f'<div class="hero-card"><div class="risk-level">{esc(data["risk_level"])}</div><h3>{esc(title)}</h3><p>{esc(text)}</p></div>'
    body += '<h3>月度监测指标</h3>' + table(
        ["指标", "监测规则", "责任岗位", "频率"], indicator_rows, "final-indicator-table"
    )
    body += f'<div class="callout risk final-limitations">{bullets(limitations)}</div>'
    return page("16", "最终判断", title, body, "final-page")


def render(data: dict[str, Any], metrics: dict[str, Any], css: str) -> str:
    pages = [render_cover(data), render_executive(data), render_scope(data), render_overview(data)]
    for key, number, label in SECTION_KEYS:
        pages.append(render_section(number, label, data["sections"][key]))
    pages.extend([render_risks(data), render_roadmap(data), render_sources(data, metrics), render_final(data)])
    suffix = "｜草稿" if not data["policies"] else ""
    title = f"{data['company']}｜金税四期财务分析报告{suffix}"
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
