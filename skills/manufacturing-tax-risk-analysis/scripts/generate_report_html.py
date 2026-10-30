#!/usr/bin/env python3
"""Generate a deep-gold tax-risk report with 17 base pages and source continuations."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import date
from itertools import zip_longest
from pathlib import Path
from typing import Any

BRANDING_SCRIPTS = Path(__file__).resolve().parents[2] / "_runtime" / "gongchuang-branding" / "scripts"
sys.path.insert(0, str(BRANDING_SCRIPTS))
from html_branding import fixed_page_branding  # noqa: E402

# Printed page margins are 13 mm above and 15 mm below the content box.
BRAND_CENTER_OFFSET_MM = (15 - 13) / 2


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
GENERIC_COMPLETION_VALUES = {
    "完成",
    "已完成",
    "完成整改",
    "通过",
    "已通过",
    "达标",
    "已达标",
    "待完成",
}


def esc(value: Any) -> str:
    if value is None:
        return "—"
    return html.escape(str(value), quote=True)


def resolve_financial_references(value: Any, metrics: dict[str, Any]) -> Any:
    """Fill report text from named calculator fields without asking the model to convert units."""
    if isinstance(value, dict):
        return {key: resolve_financial_references(item, metrics) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_financial_references(item, metrics) for item in value]
    if not isinstance(value, str):
        return value

    def substitute(match: re.Match[str]) -> str:
        year, category, field = match.groups()
        result = metrics.get("display_values", {}).get(year, {}).get(category, {}).get(field)
        if not isinstance(result, str):
            return "待补指标：" + year + "." + category + "." + field
        return result

    return re.sub(r"\{\{financial\.(\d{4})\.(facts|metrics)\.([a-z_]+)\}\}", substitute, value)


def prepare_report_input(metrics: dict[str, Any]) -> dict[str, Any]:
    """Create editable analysis fields around calculator-owned numeric references."""
    company = metrics.get("company")
    if isinstance(company, dict):
        company = company.get("name")
    validate_metrics(metrics, str(company or ""))
    years = sorted(metrics.get("display_values", {}))
    latest = years[-1] if years else "期间待补"

    def ref(year: str, category: str, field: str) -> str:
        return "{{financial." + year + "." + category + "." + field + "}}"

    fields = {
        "profitability": [("营业收入", "facts", "revenue"), ("营业成本", "facts", "cost"), ("毛利率", "metrics", "gross_margin"), ("净利率", "metrics", "net_margin")],
        "cash_flow": [("经营活动现金流量净额", "facts", "operating_cash_flow"), ("购建长期资产现金支出", "facts", "capex_cash"), ("自由现金流", "metrics", "free_cash_flow"), ("经营现金流与净利润之比", "metrics", "ocf_to_profit")],
        "solvency": [("资产负债率", "metrics", "debt_ratio"), ("流动比率", "metrics", "current_ratio"), ("速动比率", "metrics", "quick_ratio"), ("现金比率", "metrics", "cash_ratio")],
        "asset_quality": [("应收账款", "facts", "receivables"), ("应收账款周转天数", "metrics", "ar_days"), ("存货", "facts", "inventory"), ("存货周转天数", "metrics", "inventory_days")],
        "related_parties": [("其他应收款", "facts", "other_receivables"), ("其他应收款占总资产", "metrics", "other_ar_to_assets")],
        "income_tax_rd": [("所得税费用", "facts", "income_tax_expense"), ("会计研发费用", "facts", "research_expense"), ("会计研发费用率", "metrics", "research_to_revenue"), ("现金税费支付率", "metrics", "cash_tax_payment_rate")],
        "accrual_revenue": [("预收账款", "facts", "advances_from_customers"), ("销售收现率", "metrics", "sales_cash_to_revenue")],
    }
    sections = {}
    for key, _, title in SECTION_KEYS:
        selected = fields.get(key, [])
        facts = [{"title": label, "text": f"{latest}年{label}为{ref(latest, category, field)}。", "source": "本轮财务资料及指标复算"} for label, category, field in selected]
        sections[key] = {
            "title": title, "conclusion": "结合财务指标与业务资料判断，交易性质按对应凭据确认。",
            "facts": facts or [{"title": "资料范围", "text": "本专题事项结合财务指标、附注与明细判断。", "source": "本轮资料范围"}],
            "actions": ["结合已取得的附注与明细补充分析，未取得的资料明确列为缺口。"],
        }
        if selected:
            sections[key]["table"] = {"headers": ["指标", *years], "rows": [[label, *(ref(year, category, field) for year in years)] for label, category, field in selected]}
    overview_fields = [("营业收入", "facts", "revenue"), ("净利润", "facts", "net_profit"), ("资产总额", "facts", "assets"), ("负债总额", "facts", "liabilities"), ("其他应收款", "facts", "other_receivables"), ("经营活动现金流量净额", "facts", "operating_cash_flow"), ("资产负债率", "metrics", "debt_ratio"), ("现金税费支付率", "metrics", "cash_tax_payment_rate")]
    return {
        "company": company, "period": {"start": years[0] if years else "期间待补", "end": latest},
        "report_date": date.today().isoformat(), "preparer": "共创知识产权",
        "source_status": "分析草稿", "internal_only": True,
        "use_restriction": "分析尚未定稿，仅供内部核对。",
        "risk_level": "待判断", "one_line_conclusion": "待结合财务指标、附注及交易资料形成综合判断。",
        "sources": [{"name": "本轮财务输入资料", "period": f"{years[0] if years else '期间待补'}至{latest}", "status": "待核对资料性质", "pages": "待补原始资料位置", "limitation": "汇总金额与对应交易及申报资料结合使用。"}],
        "executive_findings": [{"title": "财务概览", "conclusion": f"{latest}年营业收入为{ref(latest, 'facts', 'revenue')}，净利润为{ref(latest, 'facts', 'net_profit')}。", "level": "待判断", "source": "本轮财务资料及指标复算"}],
        "financial_overview": {
            "years": years,
            "kpis": [{"label": f"{latest}年{label}", "value": ref(latest, category, field)} for label, category, field in overview_fields[:4]],
            "rows": [{"name": label, "values": [ref(year, category, field) for year in years], "source_pages": "待补原始资料位置", "formula": "原始财务科目或对应复算指标"} for label, category, field in overview_fields],
            "conclusion": "待结合跨年变化及业务资料解释财务表现。",
        },
        "sections": sections,
        "risks": [{"chain": "资料与交易核验", "fact": "交易性质待结合凭据核对。", "alternative": "结合实际业务解释及相关依据分析。", "missing_evidence": "按已提供资料补充实际缺项。", "action": "逐项核对相关交易及申报资料。", "level": "待判断"}],
        "roadmap": [{"period": period, "goal": goal, "actions": [action], "owner": "财务负责人", "completion": completion} for period, goal, action, completion in [
            ("0—30天", "资料核对", "核对报表、附注与申报资料。", "形成资料位置及缺项明细。"),
            ("31—60天", "差异分析", "逐项解释财务与业务差异。", "形成有来源的差异解释及处理意见。"),
            ("61—90天", "跟踪改进", "按确认的整改事项跟踪落实。", "形成责任人复核的整改记录。"),
        ]],
        "p0_documents": ["结合现有资料确认实际需要补充的附注、明细及申报资料。"],
        "calculations": [], "policies": [],
        "final_judgment": {"title": "待完成综合分析", "text": "结合财务表现与业务资料形成结论，涉税事项逐项列明事实和适用依据。"},
        "monthly_indicators": [{"name": "现金税费支付率", "rule": "支付税费除以营业收入，不等同于增值税税负率。", "owner": "财务负责人", "frequency": "每月"}],
        "limitations": ["本轮分析资料与判断口径见来源清单。"],
    }


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


def limit(items: list[Any], maximum: int, path: str) -> str | None:
    if len(items) > maximum:
        return f"{path}: {len(items)}项，超过原版式建议{maximum}项，已保留全部内容"
    return None


def text_limit(value: Any, maximum: int, path: str) -> str | None:
    if value is not None and len(str(value)) > maximum:
        return f"{path}: 超过原版式建议{maximum}字，已保留原文"
    return None


def validate_metrics(metrics: dict[str, Any], company: str) -> list[dict[str, Any]]:
    if metrics.get("schema") != METRICS_SCHEMA:
        raise ValueError(f"metrics JSON must use {METRICS_SCHEMA}")
    rows = metrics.setdefault("report_rows", [])
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("metrics.report_rows must be a list of objects")
    return rows


def validate(data: dict[str, Any], metrics: dict[str, Any]) -> list[str]:
    """Adapt missing content to the existing layout; keep findings advisory."""
    warnings: list[str] = []

    def texts(obj: dict[str, Any], keys: tuple[str, ...], path: str) -> None:
        for key in keys:
            value = obj.get(key)
            if value is None or value == "":
                warnings.append(f"{path}.{key}: 资料待补")
                obj[key] = "—"
            elif not isinstance(value, (str, int, float, bool)):
                raise ValueError(f"field must be scalar text: {path}.{key}")
            else:
                obj[key] = str(value)

    def objects(obj: dict[str, Any], key: str, fields: tuple[str, ...], path: str) -> list[dict[str, Any]]:
        value = obj.setdefault(key, [])
        if value is None:
            value = obj[key] = []
        if not isinstance(value, list):
            raise ValueError(f"field must be a list: {path}.{key}")
        for index, item in enumerate(value):
            require_object(item, f"{path}.{key}[{index}]")
            texts(item, fields, f"{path}.{key}[{index}]")
        return value

    def strings(obj: dict[str, Any], key: str, path: str) -> list[str]:
        value = obj.setdefault(key, [])
        if value is None:
            value = obj[key] = []
        if not isinstance(value, list):
            raise ValueError(f"field must be a list: {path}.{key}")
        obj[key] = ["—" if item is None else require_text(item, f"{path}.{key}[{index}]") for index, item in enumerate(value)]
        return obj[key]

    company = metrics.get("company")
    if isinstance(company, dict):
        company = company.get("name")
    if not data.get("company") and company:
        data["company"] = company
    texts(data, ("company", "report_date", "risk_level", "one_line_conclusion"), "root")
    if company and str(company).strip() != data["company"].strip():
        warnings.append("计算资料主体与报告主体不同，计算表保留原始来源，需核对归属")
    for key, maximum in (("company", 40), ("one_line_conclusion", 180), ("use_restriction", 120)):
        if message := text_limit(data.get(key), maximum, f"root.{key}"):
            warnings.append(message)
    period = data.setdefault("period", {})
    require_object(period, "root.period")
    texts(period, ("start", "end"), "root.period")
    sources = objects(data, "sources", ("name", "period", "status", "pages", "limitation"), "root")
    executive = objects(data, "executive_findings", ("title", "conclusion", "level", "source"), "root")
    overview = data.setdefault("financial_overview", {})
    require_object(overview, "root.financial_overview")
    years = strings(overview, "years", "root.financial_overview")
    rows = objects(overview, "rows", ("name", "source_pages", "formula"), "root.financial_overview")
    kpis = objects(overview, "kpis", ("label", "value"), "root.financial_overview")
    texts(overview, ("conclusion",), "root.financial_overview")
    for index, row in enumerate(rows):
        values = strings(row, "values", f"root.financial_overview.rows[{index}]")
        if len(values) != len(years):
            warnings.append(f"financial_overview.rows[{index}]: 数值与期间数量不同，已保留全部值")
    sections = data.setdefault("sections", {})
    require_object(sections, "root.sections")
    for key, _, _ in SECTION_KEYS:
        section = sections.setdefault(key, {})
        require_object(section, f"root.sections.{key}")
        texts(section, ("conclusion",), f"root.sections.{key}")
        facts = objects(section, "facts", ("title", "text", "source"), f"root.sections.{key}")
        actions = strings(section, "actions", f"root.sections.{key}")
        if section.get("table") is not None:
            table_data = require_object(section["table"], f"root.sections.{key}.table")
            strings(table_data, "headers", f"root.sections.{key}.table")
            table_data.setdefault("rows", [])
            if not isinstance(table_data["rows"], list) or any(not isinstance(row, list) for row in table_data["rows"]):
                raise ValueError(f"table rows must be lists: root.sections.{key}.table")
        for values, maximum, name in ((facts, 4, "facts"), (actions, 6, "actions")):
            if message := limit(values, maximum, f"root.sections.{key}.{name}"):
                warnings.append(message)
    risks = objects(data, "risks", ("chain", "fact", "alternative", "missing_evidence", "action", "level"), "root")
    roadmap = objects(data, "roadmap", ("period", "owner", "completion"), "root")
    for index, stage in enumerate(roadmap):
        strings(stage, "actions", f"root.roadmap[{index}]")
        if stage["completion"].strip() in GENERIC_COMPLETION_VALUES:
            warnings.append(f"root.roadmap[{index}].completion: 完成条件待具体化，原文已保留")
    strings(data, "p0_documents", "root")
    objects(data, "calculations", ("indicator", "formula", "result", "source"), "root")
    validate_metrics(metrics, data["company"])
    policies = objects(data, "policies", ("name", "issuer", "date", "url"), "root")
    for index, policy in enumerate(policies):
        if any(any(marker in policy[field] for marker in ("待核验", "待补", "—")) for field in ("name", "issuer", "date", "url")) or not policy["url"].startswith(("https://", "http://")):
            warnings.append(f"root.policies[{index}]: 政策信息待核对，已保留当前条目")
    final = data.setdefault("final_judgment", "—")
    if isinstance(final, dict):
        texts(final, ("title", "text"), "root.final_judgment")
    elif final is None:
        data["final_judgment"] = "—"
    elif not isinstance(final, str):
        raise ValueError("field must be text or an object: root.final_judgment")
    objects(data, "monthly_indicators", ("name", "rule", "owner", "frequency"), "root")
    strings(data, "limitations", "root")
    strings(data, "missing_documents", "root")
    if message := text_limit(final if isinstance(final, str) else (final or {}).get("text"), 260, "root.final_judgment.text"):
        warnings.append(message)
    for values, maximum, path in ((sources, 6, "sources"), (executive, 5, "executive_findings"), (rows, 8, "financial_overview.rows"), (kpis, 4, "financial_overview.kpis"), (risks, 8, "risks")):
        if message := limit(values, maximum, f"root.{path}"):
            warnings.append(message)
    return list(dict.fromkeys(warnings))


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
        f'{fixed_page_branding(variant="gold", vertical_offset_mm=BRAND_CENTER_OFFSET_MM)}'
        f'<header class="page-header"><span class="page-no">{esc(number)}</span><b>{esc(label)}</b></header>'
        f'<h2>{esc(title)}</h2>{content}'
        '<footer class="page-footer">金税四期财务分析｜共创知识产权</footer>'
        '</section>'
    )


def render_cover(data: dict[str, Any]) -> str:
    period = data["period"]
    status = data.get("source_status", "资料状态见正文")
    internal = data.get("internal_only", False)
    restriction = data.get("use_restriction", "")
    warning = "内部自查" if internal else status
    return f"""
    <section class="page cover">
      {fixed_page_branding(variant="gold", cover=True, vertical_offset_mm=BRAND_CENTER_OFFSET_MM)}
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
    findings = data["executive_findings"]
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
    body += '<div class="callout risk"><b>判断边界：</b>风险信号只代表优先核验顺序，不等于违法认定。</div>'
    return page("02", "口径与证据", "资料边界决定结论强度", body)


def render_overview(data: dict[str, Any]) -> str:
    overview = data["financial_overview"]
    years = [year if year.endswith(("年", "年度")) else f"{year}年" for year in overview["years"]]
    rows = []
    for row in overview["rows"]:
        annual_values = "；".join(
            f"{year}：{value}" for year, value in zip_longest(years, row["values"], fillvalue="待补")
        )
        rows.append([row["name"], annual_values, row["source_pages"], row["formula"]])
    kpis = "".join(
        f'<article class="card kpi"><small>{esc(x.get("label"))}</small><div class="num">{esc(x.get("value"))}</div><p>{esc(x.get("note", ""))}</p></article>'
        for x in overview.get("kpis", [])
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
    # 分页只改变呈现，不能截掉已经核验的指标或补充计算。
    calculations = [*metrics["report_rows"], *data["calculations"]]
    chunks = [calculations[index:index + 10] for index in range(0, len(calculations), 10)] or [[]]
    pages = []
    for index, chunk in enumerate(chunks):
        calc_rows = [[x.get("indicator"), x.get("formula"), x.get("result"), x.get("source")] for x in chunk]
        body = '<h3>计算过程与来源</h3>' + table(["指标", "公式", "结果", "来源"], calc_rows, "calculation-table")
        if index < len(chunks) - 1:
            pages.append(page("15" if index == 0 else f"15.{index + 1}", "计算过程与来源", "金额对应原始资料，比例列明计算依据", body))
    if data["policies"]:
        policy_rows = [[x.get("name"), x.get("issuer"), x.get("date"), x.get("url")] for x in data["policies"]]
        body += '<h3>政策依据</h3>' + table(["文件", "发布机关", "日期", "链接"], policy_rows, "policy-table")
    else:
        body += '<h3>政策依据</h3><div class="callout risk">本轮政策原文待核对，相关判断按已取得的财务和业务资料列示。</div>'
    pages.append(page("15" if len(chunks) == 1 else f"15.{len(chunks)}", "计算过程与来源", "金额对应原始资料，比例列明计算依据", body))
    return "".join(pages)


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
    limitations = data.get("limitations", ["本轮分析资料与判断口径见来源清单。"])
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
<meta name="author" content="{esc(data.get('preparer', '共创知识产权'))}">
<title>{esc(title)}</title><style>{css}</style></head><body>{''.join(pages)}</body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="report-data JSON")
    parser.add_argument("output", type=Path, nargs="?", help="generated HTML")
    parser.add_argument(
        "--metrics-json",
        type=Path,
        help="optional manufacturing-tax-risk-metrics/v1 JSON from the calculator",
    )
    parser.add_argument("--css", type=Path, help="gold-advisor.css path")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--prepare-input", action="store_true", help="create a new editable report input from calculator fields")
    args = parser.parse_args()

    metrics = (json.loads(args.metrics_json.read_text(encoding="utf-8")) if args.metrics_json
               else {"schema": METRICS_SCHEMA, "report_rows": [], "display_values": {}})
    if not isinstance(metrics, dict):
        raise ValueError("metrics JSON root must be an object")
    if args.prepare_input:
        data = prepare_report_input(metrics)
        validate(resolve_financial_references(data, metrics), metrics)
        args.input.parent.mkdir(parents=True, exist_ok=True)
        with args.input.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(data, ensure_ascii=False, indent=2))
        print(json.dumps({"status": "draft-input", "input": str(args.input)}, ensure_ascii=False))
        return
    data = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("input root must be an object")
    data = resolve_financial_references(data, metrics)
    warnings = validate(data, metrics)
    if args.validate_only:
        print(json.dumps({"status": "valid", "input": str(args.input), "warnings": warnings}, ensure_ascii=False))
        return
    if not args.output:
        parser.error("output is required unless --validate-only is used")
    css_path = args.css or Path(__file__).resolve().parent.parent / "assets" / "gold-advisor.css"
    css = css_path.read_text(encoding="utf-8")
    result = render(data, metrics, css)
    body_html = result.split("</style>", 1)[-1]
    if "{{" in body_html or "}}" in body_html:
        warnings.append("正文含待填写模板标记，已保留当前内容")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(result, encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "ok",
                "pages": result.count('<section class="page'),
                "output": str(args.output),
                "metrics": str(args.metrics_json) if args.metrics_json else None,
                "warnings": warnings,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
