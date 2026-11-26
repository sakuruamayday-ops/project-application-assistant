"""Fill fixed HTML reports from validated facts without a DOCX master."""
from copy import deepcopy
from pathlib import Path
import re

from lxml import etree, html

from fill_report_template import (CONDITION_COLUMNS, PLACEHOLDER, ReportInputError, _condition_values,
                                 _fallback_for_placeholder, _pending_items_summary, _replace_training_text,
                                 POLICY_ROW_KINDS, normalize_text, policy_kinds, retained_condition_rows, table_header_key)
from report_html import html_table


def _text(node):
    return node.text_content().strip()


def _set_text(node, value):
    first = next(iter(node), None)
    formatted = deepcopy(first) if first is not None and first.tag in {"span", "strong", "em"} else None
    for child in list(node):
        node.remove(child)
    node.text = None if formatted is not None else str(value)
    if formatted is not None:
        _set_text(formatted, value)
        formatted.tail = None
        node.append(formatted)


def _set_cell(cell, value):
    paragraph = cell.find("p")
    paragraph = deepcopy(paragraph) if paragraph is not None else etree.Element("p")
    for child in list(cell):
        cell.remove(child)
    cell.text = None
    _set_text(paragraph, value)
    cell.append(paragraph)
    return paragraph


def _cells(row):
    return row.xpath("./th|./td")


def _rows(table):
    return table.xpath("./tbody/tr|./tr")


def _replace_rows(table, values):
    rows = _rows(table)
    template = rows[-1]
    parent = template.getparent()
    for row in rows[1:]:
        row.getparent().remove(row)
    for values_row in values:
        row = deepcopy(template)
        for cell, value in zip(_cells(row), values_row, strict=True):
            _set_cell(cell, value)
        parent.append(row)


def _fill_policy(table, fixture):
    header = _cells(_rows(table)[0])
    _set_cell(header[2 if len(header) == 4 else 3], "官方来源")
    for row in _rows(table)[1:]:
        cells = _cells(row)
        expected = POLICY_ROW_KINDS.get(_text(cells[0]))
        policy = next((p for p in fixture["policies"] if expected in policy_kinds(p)), None)
        if policy is None and expected != "management":
            row.getparent().remove(row)
            continue
        values = (["当前未取得独立文件", "—", "待核验"] if len(cells) == 4 else
                  ["当前未取得独立文件", "—", "—", "待核验"])
        if policy is not None:
            values = ([str(policy["title"]), str(policy["locator"]), str(policy.get("status") or "已锁定基线")]
                      if len(cells) == 4 else
                      [str(policy["title"]), str(policy.get("scope") or "按管理办法适用范围"),
                       str(policy["locator"]), str(policy.get("status") or "已锁定基线")])
        for cell, value in zip(cells[1:], values, strict=True):
            _set_cell(cell, value)
        if policy is not None and str(policy["locator"]).startswith(("https://", "http://")):
            paragraph = _set_cell(cells[2 if len(cells) == 4 else 3], "")
            link = etree.SubElement(paragraph, "a", href=str(policy["locator"]))
            link.text = "查看官方原文"


def _fill_summary(table, fixture):
    values = {
        "当前可行性": (fixture["conclusion"], fixture["conclusion_basis"]),
        "申报结论": (fixture["conclusion"], fixture["conclusion_basis"]),
        "评估年度": (fixture["suggested_year"], fixture.get("year_basis") or "客户选择评估年度"),
        "首要短板": (fixture["primary_gap"], fixture["next_action"]),
        "预计满足硬门槛": (fixture.get("gate_summary") or "待企业补齐数据后复算", "按管理办法条款核对"),
        "关键前置任务": (fixture["next_action"], fixture.get("target_period") or "客户填写"),
    }
    for row in _rows(table)[1:]:
        cells = _cells(row)
        label = _text(cells[0])
        pair = next((value for key, value in values.items() if key in label), None)
        if label == "待补事项数":
            pair = _pending_items_summary(fixture)
        elif "申报层级" in label or "档次" in label:
            pair = (fixture.get("level") or "待企业确认适用层级", fixture.get("level_basis") or "按项目属地和管理办法")
        if pair is not None:
            _set_cell(cells[1], pair[0])
            _set_cell(cells[2], pair[1])


def _fill_conditions(table, fixture):
    for row in _rows(table)[1:]:
        cells = _cells(row)
        value, source, state, gap, action, priority = _condition_values(fixture, _text(cells[0]))
        values = (value, state, gap, action) if len(cells) == 5 else (value, source, state, gap, action, priority)
        for cell, text in zip(cells[1:], values, strict=True):
            _set_cell(cell, text)


def _fill_tasks(table, fixture):
    configured = [item for item in fixture.get("strengthening_tasks", [])
                  if isinstance(item, dict) and str(item.get("task") or "").strip()]
    tasks = configured or [{"task": _text(_cells(row)[1])} for row in _rows(table)[1:]]
    period = fixture.get("target_period") or "客户填写"
    default_deliverables = {
        "国内产品技术水平评价咨询报告": "国内产品技术水平评价咨询报告",
        "国际产品技术水平评价咨询报告": "国际产品技术水平评价咨询报告",
        "技术查新或科技咨询": "技术查新报告或科技咨询意见",
        "任务指标检测方案和项目预算底稿": "任务指标对照表、检测方案和项目预算底稿",
    }
    _replace_rows(table, [[str(index), item["task"], item.get("status") or "当前资料未提供该项成果，是否已有待确认",
                           item.get("target_period") or fixture.get("target_period") or period,
                           item.get("deliverable") or default_deliverables.get(item["task"], "形成可核验的成果文件")]
                          for index, item in enumerate(tasks, 1)])


def _fill_tables(body, fixture):
    for table in body.xpath("./table"):
        rows = _rows(table)
        columns = tuple(_text(cell) for cell in _cells(rows[0]))
        header = " | ".join(columns)
        if "政策层级" in header and ("现行文件" in header or "文件名称与文号" in header):
            _fill_policy(table, fixture)
        elif ("判断项" in header and "一句话依据" in header) or ("事项" in header and "依据及限制" in header):
            _fill_summary(table, fixture)
        elif "现行条件 | 企业值" in header or columns == CONDITION_COLUMNS:
            _fill_conditions(table, fixture)
        elif table_header_key(columns)[:3] == ("项目", "评估年度", "准备节点"):
            for cell, label in zip(_cells(rows[0])[1:3], ("评估年度", "准备节点"), strict=True):
                _set_cell(cell, label)
            for row in rows[1:]:
                for cell, value in zip(_cells(row)[1:], [fixture["suggested_year"], fixture.get("target_period") or "客户填写",
                                      fixture["conclusion"], fixture["next_action"]], strict=True):
                    _set_cell(cell, value)
        elif "补强任务" in header and "成果证据" in header:
            _fill_tasks(table, fixture)


def _fill_custom_tables(body, fixture):
    used = set()
    for entry in fixture["table_content"]:
        columns, rows = entry.get("columns"), entry.get("rows")
        key = table_header_key(columns)
        if key in used:
            raise ReportInputError("重复回填同一表头:" + " | ".join(key), "report-table-target", ["table_content.columns"])
        used.add(key)
        matches = [table for table in body.xpath("./table")
                   if table_header_key([_text(c) for c in _cells(_rows(table)[0])]) == key]
        if not matches:
            etree.SubElement(body, "h2").text = "补充分析"
            body.append(html.fromstring(html_table(columns, rows)))
            fixture["_input_warnings"].append("补充分析中的表格内容和位置尚需复核")
            continue
        if len(matches) != 1:
            raise ReportInputError("表头必须唯一匹配母版:" + " | ".join(key), "report-table-target", ["table_content.columns"])
        if rows:
            table = matches[0]
            rows = retained_condition_rows(fixture, key, [[_text(cell) for cell in _cells(row)]
                                                         for row in _rows(table)[1:]], rows)
            _replace_rows(table, rows)


def _fill_associations(body, fixture):
    rows = fixture.get("core_associations")
    if rows is None:
        return
    if fixture["project_id"] != "high-tech-enterprise":
        raise ValueError("core_associations 仅用于高企四关联矩阵")
    columns = ["研发项目", "核心技术", "知识产权及状态", "成果转化", "高新产品及收入", "对应依据与缺口"]
    if (not isinstance(rows, list) or not rows or any(not isinstance(row, list) or len(row) != len(columns)
            or not all(isinstance(value, str) and value.strip() for value in row) for row in rows)):
        raise ValueError("core_associations 每行须按四关联矩阵提供六列非空文本")
    headings = [node for node in body if _text(node) in {"三、项目专属核心对象", "四、项目专属核心对象"}]
    if len(headings) != 1:
        raise ValueError("高企母版缺少项目专属核心对象章节")
    headings[0].addnext(html.fromstring(html_table(columns, rows)))


def _remove_guidance(body):
    removing = False
    for node in list(body):
        if node.tag in {"h1", "h2", "h3"}:
            removing = _text(node) in {"2.1 政策原文摘录规则", "4.2 补强顺序", "6.2 任务排序"}
        if removing:
            body.remove(node)
            continue
        if node.tag == "table" and len(_rows(node)) == 1 and len(_cells(_rows(node)[0])) == 1:
            cell = deepcopy(_cells(_rows(node)[0])[0])
            for element in cell.xpath(".//br|.//p"):
                element.tail = "\n" + (element.tail or "")
            if _text(cell).split("\n", 1)[0] in {"使用说明", "判定规则", "项目路由", "专项要求"}:
                body.remove(node)


def _fill_paragraphs(body, fixture, placeholders, release_tag):
    prefixes = {"申报主体：": f"申报主体：{fixture['enterprise']}",
                "主导产品或申报对象：": f"主导产品或申报对象：{fixture['project_object']}",
                "建议口径：": f"建议口径：{fixture.get('recommended_scope') or fixture['project_object']}"}
    for paragraph in body.xpath(".//p|.//h1|.//h2|.//h3"):
        original = _text(paragraph)
        value = next((text for prefix, text in prefixes.items() if original.startswith(prefix)), original)
        value = _replace_training_text(value, fixture, release_tag)
        if "□可申报" in value or "□建议申报" in value:
            value = str(fixture["conclusion"])
        for before, after in (("□已核验 □待补", "☐已核验 ☒待补"),
                              ("□已有 □待确认 □待补强", "☐已有 ☒待确认 ☐待补强"), ("□通过 □不通过", "☐通过 ☒不通过")):
            value = value.replace(before, after)
        value = placeholders.sub(lambda match: _fallback_for_placeholder(match.group(), value, fixture), value)
        value = value.replace("待核验", "待企业确认") if "政策" not in value else value
        value = value.replace("企业提供待核/待补强", "待企业确认")
        if value != original:
            _set_text(paragraph, value)


def _append_sources(body, fixture, action_layout):
    heading = etree.SubElement(body, "h1")
    heading.text = "数据来源" if action_layout else "附录 C、数据来源"
    table = html.fromstring(html_table(["序号", "文件名称", "链接"],
                                      [[str(index), source["name"], source["public_source"]["label"]]
                                       for index, source in enumerate(fixture["_validated_sources"], 1)]))
    for row, source in zip(_rows(table)[1:], fixture["_validated_sources"], strict=True):
        reference = source["public_source"]
        if reference["url"]:
            paragraph = _set_cell(_cells(row)[2], "")
            etree.SubElement(paragraph, "a", href=reference["url"]).text = reference["label"]
    body.append(table)
    if action_layout:
        for policy in fixture["policies"]:
            paragraph = etree.SubElement(body, "p")
            paragraph.text = str(policy["title"]) + "，" + str(policy["locator"])
            if str(policy.get("url", "")).startswith("https://"):
                etree.SubElement(paragraph, "a", href=policy["url"]).text = " 官方原文"


def render_report(template_path: Path, fixture, report_type, release_tag):
    """Return escaped HTML, visible text and original-template tokens for final checks."""
    root = html.document_fromstring(template_path.read_text(encoding="utf-8"))
    tokens = set(PLACEHOLDER.findall(root.text_content()))
    placeholders = re.compile("|".join(re.escape(token) for token in sorted(tokens)) or r"(?!)")
    action_layout = fixture.get("report_layout") == "sme-action"
    if action_layout:
        from sme_action_report import build_action_html
        root = html.document_fromstring(build_action_html(fixture))
    body = root.find("body")
    if not action_layout:
        _remove_guidance(body)
        _fill_tables(body, fixture)
        _fill_paragraphs(body, fixture, placeholders, release_tag)
        _fill_custom_tables(body, fixture)
        _fill_associations(body, fixture)
        label = "项目前期评估报告" if report_type == "preassessment" else "项目申报可行性分析报告"
        root.find("head/title").text = f"{fixture['enterprise']}_{fixture['project_object']}_{label}"
    _append_sources(body, fixture, action_layout)
    if normalize_text(str(fixture["project_object"])) not in normalize_text(body.text_content()):
        etree.SubElement(body, "p").text = f"项目核心对象：{fixture['project_object']}"
    if fixture["_input_warnings"]:
        etree.SubElement(body, "h2").text = "初稿说明与待补事项"
        for warning in dict.fromkeys(fixture["_input_warnings"]):
            etree.SubElement(body, "p").text = warning
    text = "\n".join(_text(node) for node in body.xpath(".//p|.//h1|.//h2|.//h3"))
    return html.tostring(root, encoding="unicode", doctype="<!doctype html>"), text, placeholders
