#!/usr/bin/env python3
"""Fill the existing sales master with supplied business content and status dots."""
from __future__ import annotations

import argparse
import base64
import html
import json
import re
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
ASSETS = SKILL_ROOT / "assets"
PENDING = "请企业提供相应资料后判断"
FONTS = {
    "FONT_CJK_REGULAR": "NotoSansCJKsc-Regular.otf",
    "FONT_CJK_BOLD": "NotoSansCJKsc-Bold.otf",
    "FONT_LATIN_REGULAR": "DejaVuSans.ttf",
    "FONT_LATIN_BOLD": "DejaVuSans-Bold.ttf",
}
# Original master table types, plus the four existing required report tables.
# Each type owns its headers; input rows never define columns or CSS.
TABLES = {
    "shareholders": ("股东构成", ("股东", "持股比例", "认缴出资", "实缴出资", "实缴率", "职务", "首次持股")),
    "management": ("管理层", ("姓名", "职务", "关联企业数", "备注")),
    "investments": ("被投资企业", ("被投资企业", "持股", "注册资本", "法代", "成立", "状态")),
    "business": ("主营业务", ("业务板块", "具体内容")),
    "milestones": ("发展里程碑", ("时间", "事件", "意义")),
    "qualifications": ("资质情况", ("序号", "资质名称", "等级", "发证机关")),
    "licenses": ("许可情况", ("许可类型", "等级", "升级情况", "业务含义")),
    "certifications": ("认证情况", ("认证类型", "证书编号", "认证机构")),
    "intellectual-property": ("知识产权", ("类型", "数量", "详情")),
    "assets": ("土地、资产与投资资料", ("项目", "详情")),
    "related-risk": ("关联企业风险", ("被投资企业", "持股", "注册资本", "状态", "风险等级")),
    "court-cases": ("司法记录", ("案号", "案由", "被告", "法院", "时间")),
    "claims": ("其他司法记录", ("案号", "案由", "原告", "状态")),
    "verification": ("资料核验", ("维度", "状态", "说明")),
    "risk-dimensions": ("风险维度", ("风险维度", "评级", "说明")),
    "risk-actions": ("风险整改表", ("事实或信号", "实际影响", "解决动作", "关联项目", "完成时间")),
    "operating-metrics": ("经营与财务资料", ("指标", "数据", "来源")),
    "tax-record": ("纳税信用记录", ("年度", "等级")),
    "paid-capital": ("出资情况", ("股东", "认缴", "实缴", "实缴率", "认缴出资日期")),
    "policy-trends": ("政策与行业趋势", ("政策/趋势", "对本企业的影响")),
    "peer-comparison": ("同行项目对比表", ("企业", "已有荣誉资质及项目", "差距", "可复制动作", "来源")),
    "historical-projects": ("已做项目", ("项目名称", "中标金额", "招标人/业主", "时间")),
    "client-types": ("经营资料", ("业主类型", "代表客户", "占比评估")),
    "project-criteria": ("项目条件核对", ("条件", "匹配度", "说明")),
    "project-options": ("项目方向", ("项目", "匹配度", "建议")),
    "project-plan": ("可申报项目表", ("项目", "现有基础", "还缺什么")),
    "development": ("发展方向", ("方向", "建议", "优先级")),
    "roadmap": ("五年规划表", ("年度", "行动", "启动条件", "所需资料")),
    "summary-risks": ("核心风险", ("序号", "风险类别", "风险描述", "严重程度")),
    "positive-factors": ("正面因素", ("序号", "正面因素", "说明")),
    "recommendations": ("结论与建议", ("场景", "建议", "风险等级")),
}
REQUIRED_TABLES = {"06": "risk-actions", "08": "peer-comparison", "10": "project-plan", "11": "roadmap"}
SECTION_TABLES = {
    "01": (), "02": ("shareholders", "management", "investments"),
    "03": ("business", "milestones"), "04": ("qualifications", "licenses", "certifications", "intellectual-property"),
    "05": ("assets", "related-risk"), "06": ("court-cases", "claims", "verification", "risk-dimensions", "risk-actions"),
    "07": ("operating-metrics", "tax-record", "paid-capital"), "08": ("policy-trends", "peer-comparison"),
    "09": ("historical-projects", "client-types"), "10": ("project-criteria", "project-options", "project-plan"),
    "11": ("development", "roadmap"), "12": ("summary-risks", "positive-factors"), "13": ("recommendations",),
}
COMPANY_FIELDS = (
    ("name", "企业名称"), ("former_name", "曾用名"), ("credit_code", "统一社会信用代码"),
    ("founded_date", "成立日期"), ("registered_capital", "注册资本"), ("paid_in_capital", "实缴资本"),
    ("legal_representative", "法定代表人"), ("company_type", "企业类型"), ("registration_status", "登记状态"),
    ("address", "注册地址"), ("business_scope", "经营范围"), ("tax_qualification", "纳税人资质"),
    ("industry", "所属行业"), ("registration_authority", "登记机关"), ("website", "官网"),
)


def text(value: object) -> str:
    if value is None or value == "":
        return PENDING
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise ValueError("业务文字必须是字符串或用户提供的数值")
    result = str(value)
    return result


COLOR_MARKER = re.compile(r"[（(]\s*([绿綠黄黃⻩红紅])\s*[）)]")
COLOR_LEVEL = {"绿": "low", "綠": "low", "黄": "medium", "黃": "medium", "⻩": "medium", "红": "high", "紅": "high"}


def marked_text(value: object) -> str:
    """Use the master's existing circle component for supplied color markers."""
    label = text(value)
    parts: list[str] = []
    start = 0
    for marker in COLOR_MARKER.finditer(label):
        parts.append(f'<span class="risk {COLOR_LEVEL[marker[1]]}">{html.escape(label[start:marker.start()])}</span>')
        start = marker.end()
    parts.append(html.escape(label[start:]))
    return "".join(parts)


def cell(value: object) -> str:
    if not isinstance(value, dict):
        return marked_text(value)
    label = text(value.get("text"))
    severity = value.get("severity")
    status = value.get("status")
    if isinstance(severity, str) and severity in {"low", "medium", "high", "pending"}:
        return f'<span class="severity {severity}">{marked_text(label)}</span>'
    if isinstance(status, str) and status in {"low", "medium", "high"}:
        label = COLOR_MARKER.sub(lambda marker: "" if COLOR_LEVEL[marker[1]] == status else marker[0], label)
        return f'<span class="risk {status}">{marked_text(label)}</span>'
    return marked_text(label)


def table(kind: str, rows: list, *, source_kind: str | None = None) -> str:
    if kind not in TABLES:
        raise ValueError(f"不支持的固定表格类型：{kind}")
    caption, headers = TABLES[kind]
    if not isinstance(rows, list):
        raise ValueError("表格 rows 必须是数组")
    if not rows:
        rows = [[PENDING for _ in headers]]
    rendered = []
    for row in rows:
        if not isinstance(row, list) or len(row) > len(headers):
            raise ValueError(f"表格 {kind} 行数据需与 {len(headers)} 个现有栏目对应")
        row = [*row, *([None] * (len(headers) - len(row)))]
        rendered.append("<tr>" + "".join(f"<td>{cell(value)}</td>" for value in row) + "</tr>")
    return (f'<h2>{caption}</h2><table data-table-type="{kind}"><thead><tr>'
            + "".join(f"<th>{header}</th>" for header in headers)
            + "</tr></thead><tbody>" + "".join(rendered) + "</tbody></table>")


def summary_card(value: dict) -> str:
    if not isinstance(value, dict):
        raise ValueError("摘要只接受 title、text 业务文字")
    return f'<div class="summary-card"><h3>{cell(value.get("title"))}</h3><p>{cell(value.get("text"))}</p></div>'


def callout(value: dict) -> str:
    if not isinstance(value, dict):
        raise ValueError("提示只接受 kind、title、text")
    kind = value.get("kind")
    if kind not in {"warning", "success", "info", "danger"}:
        kind = "info"
    source = "data:image/png;base64," + base64.b64encode((ASSETS / "icons" / f"callout-{kind}.png").read_bytes()).decode("ascii")
    return (f'<div class="callout {kind}"><img class="callout-icon" alt="" src="{source}">'
            f'<strong>{cell(value.get("title"))}：</strong>{cell(value.get("text"))}</div>')


def section(number: str, data: dict, company: dict) -> str:
    if not isinstance(data, dict):
        raise ValueError("章节内容需为业务数据对象")
    parts = []
    if number == "01":
        parts.append('<table class="basic-info"><thead><tr><th>项目</th><th>内容</th></tr></thead><tbody>'
                     + "".join(f"<tr><td>{label}</td><td>{cell(company.get(key))}</td></tr>" for key, label in COMPANY_FIELDS)
                     + "</tbody></table>")
        parts.append('<p class="scope-note">企业主体核验以本次来源为限，待核字段请企业提供相应资料后判断。</p>')
    if number == "07":
        parts.append('<p class="scope-note">经营、财务数据按本次提供内容及来源列示，待核实口径随相应条目注明。</p>')
    paragraphs = data.get("paragraphs", [])
    notes = data.get("notes", [])
    tables = data.get("tables", [])
    if not all(isinstance(items, list) for items in (paragraphs, notes, tables)):
        raise ValueError("paragraphs、tables、notes 必须是数组")
    parts.extend(f"<p>{cell(value)}</p>" for value in paragraphs)
    if "summary" in data:
        parts.append(summary_card(data["summary"]))
    if "points" in data:
        if not isinstance(data["points"], list): raise ValueError("points 必须是业务要点数组")
        parts.append("<ul>" + "".join(f"<li>{cell(value)}</li>" for value in data["points"]) + "</ul>")
    if "callouts" in data:
        if not isinstance(data["callouts"], list): raise ValueError("callouts 必须是数组")
        parts.extend(callout(value) for value in data["callouts"])
    supplied_tables = {}
    for item in tables:
        if not isinstance(item, dict):
            raise ValueError("表格内容需为业务数据对象")
        kind = item.get("type")
        if kind is None and not item.get("rows"):
            continue
        if kind not in TABLES:
            raise ValueError(f"表格type无法匹配现有列定义：{kind}")
        if kind in supplied_tables:
            previous = supplied_tables[kind]
            if not isinstance(previous.get("rows", []), list) or not isinstance(item.get("rows", []), list):
                raise ValueError("表格rows需为数组")
            previous["rows"] = [*previous.get("rows", []), *item.get("rows", [])]
            previous.setdefault("_continuations", []).append(item)
        else:
            supplied_tables[kind] = {key: item[key] for key in ("type", "rows", "source_kind", "summary", "callouts") if key in item}
    required = REQUIRED_TABLES.get(number)
    for kind in (*SECTION_TABLES[number], *(kind for kind in supplied_tables if kind not in SECTION_TABLES[number])):
        item = supplied_tables.get(kind)
        if item is not None:
            parts.append(table(kind, item.get("rows", []), source_kind=item.get("source_kind")))
            for detail in (item, *item.get("_continuations", [])):
                if "summary" in detail:
                    parts.append(summary_card(detail["summary"]))
                if "callouts" in detail:
                    if not isinstance(detail["callouts"], list): raise ValueError("callouts 必须是数组")
                    parts.extend(callout(value) for value in detail["callouts"])
        elif kind == required or number == "07" and kind == "operating-metrics":
            parts.append(table(kind, []))
    parts.extend(f'<p class="notice">{cell(value)}</p>' for value in notes)
    return "\n".join(parts) or f'<p class="notice">{cell({"text": PENDING, "status": "medium"})}</p>'


def font_uri(path: Path) -> str:
    """Path.as_uri encodes spaces, quotes, Han names and Windows drive paths."""
    return path.as_uri()


def build_sales_html(input_path: Path, output_path: Path) -> dict:
    data = json.loads(input_path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("输入需为业务数据对象")
    company = data.get("company", {})
    if not isinstance(company, dict):
        raise ValueError("company需为工商信息对象")
    company = {**company, "name": text(company.get("name"))}
    output_path = output_path.expanduser().resolve()
    if output_path.suffix.lower() != ".html" or output_path.is_relative_to(SKILL_ROOT):
        raise ValueError("输出必须是技能目录之外的新 .html 文件")
    if output_path.exists():
        raise FileExistsError("已有输出不覆盖，请使用新的 HTML 路径")
    sections = data.get("sections", {})
    if not isinstance(sections, dict):
        raise ValueError("sections需为章节业务数据对象")
    sections = {key: value for key, value in sections.items() if key in {f"{number:02}" for number in range(1, 14)}}
    if any(not isinstance(value, dict) for value in sections.values()):
        raise ValueError("每章内容必须是业务数据对象")
    css = (ASSETS / "sales-style.css").read_text(encoding="utf-8")
    for token, filename in FONTS.items():
        path = (ASSETS / "fonts" / filename).resolve(strict=True)
        css = css.replace("{{" + token + "}}", font_uri(path))
    replacements = {
        "STYLE": css, "COMPANY_NAME": html.escape(company["name"]),
        "CREDIT_CODE": html.escape(text(company.get("credit_code", {}).get("text") if isinstance(company.get("credit_code"), dict) else company.get("credit_code"))),
        "REPORT_DATE": html.escape(text(data.get("report_date"))),
        "DATA_AS_OF": html.escape(text(data.get("data_as_of"))),
    }
    assessment = sections.get("12", {}).get("assessment", {})
    if not isinstance(assessment, dict):
        raise ValueError("assessment 只接受本企业的 level、description、summary，不自动评分")
    replacements.update({"ASSESSMENT_LEVEL": html.escape(text(assessment.get("level", "待核"))),
                         "ASSESSMENT_DESCRIPTION": html.escape(text(assessment.get("description"))),
                         "ASSESSMENT_SUMMARY": html.escape(text(assessment.get("summary")))})
    comparison = sections.get("08", {}).get("comparison", {})
    if not isinstance(comparison, dict):
        raise ValueError("comparison 只接受本企业 advantages、limitations 要点")
    for field in ("advantages", "limitations"):
        values = comparison.get(field, [PENDING])
        if not isinstance(values, list): raise ValueError("竞争比较要点必须是数组")
        replacements[field.upper()] = "".join(f"<li>{cell(value)}</li>" for value in values) or f"<li>{PENDING}</li>"
    for name in ("warning", "success", "danger", "info", "negative"):
        image = ASSETS / "icons" / f"callout-{name}.png"
        replacements[f"CALLOUT_{name.upper()}"] = "data:image/png;base64," + base64.b64encode(image.read_bytes()).decode("ascii")
    for number in range(1, 14):
        key = f"{number:02}"
        icon = ASSETS / "icons" / f"section-{key}.png"
        replacements[f"ICON_{key}"] = "data:image/png;base64," + base64.b64encode(icon.read_bytes()).decode("ascii")
        replacements[f"BODY_{key}"] = section(key, sections.get(key, {}), company)
    sources = data.get("sources", [])
    if not isinstance(sources, list):
        raise ValueError("sources 必须是实际来源数组")
    source_rows = []
    for item in sources:
        if not isinstance(item, dict):
            raise ValueError("来源只接受 name、url、queried_at，不能传 HTML")
        source_rows.append("<tr>" + "".join(f"<td>{cell(item.get(key))}</td>" for key in ("name", "url", "queried_at")) + "</tr>")
    replacements["SOURCES"] = "\n".join(source_rows) or '<tr><td colspan="3">请补充本企业实际来源，当前未提供来源清单。</td></tr>'
    template = (ASSETS / "sales-master-template.html").read_text(encoding="utf-8")
    # Substitute the source template once. Business text containing a template
    # token remains text and cannot insert another section or stylesheet.
    output = re.sub(r"\{\{([A-Z_0-9]+)\}\}", lambda match: replacements[match[1]], template)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as destination:
        destination.write(output)
    return {"schema_version": "gongchuang-project-report-operation/v1", "status": "pass",
            "output_path": str(output_path), "format": "html"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = build_sales_html(args.input, args.output)
    except (ValueError, FileNotFoundError, FileExistsError) as error:
        print(json.dumps({"schema_version": "gongchuang-project-report-operation/v1", "status": "fail", "errors": [str(error)]}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
