#!/usr/bin/env python3
"""Fill the bundled application by physical cells and named fields, never grid indexes."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from decimal import Decimal
from functools import partial
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from lxml import etree

from expense_values import YEAR_SEPARATOR, expense_text, expense_value, expense_years
from fill_rd_core_innovation import NS, W, collect_rd_targets, element_text, normalize, table_rows, xml_cell_text
from import_batch import ImportBatch, pointer


def text(value):
    if value is None:
        return ""
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("字段须为文字、数值或null")
    return str(value)


def readback_text_key(value: str) -> str:
    return " ".join(value.split())


def write_cell_text(cell, value):
    """Use existing paragraph and line boundaries as available text slots."""
    slots = []
    for paragraph in cell.findall(W + "p"):
        runs = paragraph.findall(W + "r")
        carrier = None
        if runs and all(child.tag == W + "rPr" for child in runs[0]):
            carrier = runs[0]
        elif all(child.tag == W + "pPr" for child in paragraph):
            carrier = paragraph
        nodes = []
        for run in runs:
            for child in run:
                if child.tag == W + "t":
                    nodes.append(child)
                elif child.tag == W + "br":
                    if nodes or carrier is not None:
                        slots.append((nodes, carrier))
                    nodes, carrier = [], None
        if nodes or carrier is not None:
            slots.append((nodes, carrier))

    if not slots and value.strip():
        raise ValueError("目标单元格缺可用的原段落或文字运行")
    lines = value.split("\n", max(0, len(slots) - 1))
    for index, (nodes, carrier) in enumerate(slots):
        line = lines[index] if index < len(lines) else ""
        if carrier is not None and line.strip():
            run = etree.SubElement(carrier, W + "r") if carrier.tag == W + "p" else carrier
            etree.SubElement(run, W + "t").text = line
            line = ""
        for node in nodes:
            node.text, line = line, ""


def amount(value):
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("金额不得为布尔值")
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError("金额须为有限数值")
    return number


def total(values):
    numbers = [amount(value) for value in values]
    return None if not numbers or any(value is None for value in numbers) else sum(numbers, Decimal(0))


def named_cells(table):
    result = {}
    for row in table_rows(table):
        for index, cell in enumerate(row[:-1]):
            label = normalize(element_text(cell))
            if label:
                result.setdefault(label, []).append(row[index + 1])
    return result


def target(table, label):
    candidates = named_cells(table).get(normalize(label), [])
    if len(candidates) != 1:
        raise ValueError(f"字段无法唯一定位：{label}")
    return candidates[0]


def find_table(tables, *labels):
    matches = [table for table in tables if all(normalize(label) in named_cells(table) for label in labels)]
    if len(matches) != 1:
        raise ValueError(f"母版表无法唯一定位：{'、'.join(labels)}")
    return matches[0]


def fill_fields(table, values, allowed, group, batch, write_cell):
    if not isinstance(values, dict):
        raise ValueError("字段须为对象")
    aliases = {normalize(label).replace("（限400字）", ""): label for label in allowed}
    canonical = {}
    for label, value in values.items():
        name = aliases.get(normalize(label).replace("（限400字）", ""))
        if name is None or name in canonical:
            batch.add(pointer(*group, label), value, None, f"不支持或重复的字段：{label}")
            continue
        canonical[name] = (label, value)
    # Resolve every label before changing content, so values can never become labels.
    writes = []
    for name, (label, value) in canonical.items():
        field = pointer(*group, name)
        source = pointer(*group, label)
        try:
            cell = target(table, name)
        except ValueError as error:
            batch.add(field, value, None, str(error), source=source)
            continue
        writes.append((cell, field, value, source))
    for cell, field, value, source in writes:
        write_cell(cell, field, value, text(value), '按母版标签定位回填', source=source)


def annual_rows(summary):
    rows = table_rows(summary)
    labels = ({"年度", "年度种类"}, {"净资产"}, {"销售收入"}, {"利润总额"})
    for pos, row in enumerate(rows):
        headers = [normalize(element_text(cell)) for cell in row]
        indexes = [next((i for i, header in enumerate(headers) if header in names), None) for names in labels]
        if None in indexes:
            continue
        data_rows = rows[pos + 1:pos + 4]
        if len(data_rows) == 3 and all(len(row) > max(indexes) for row in data_rows):
            return [[row[index] for index in indexes] for row in data_rows]
        break
    raise ValueError("年度经营情况物理单元格不符合母版")


EXPENSE_SOURCES = {
    "研究开发费用（内、外部）小计": "rd_financials",
    "委托外部研究开发费用": "rd_external",
    "其中：境内的外部研发费用": "rd_external_domestic",
}


def existing_expense_layouts(tables, years, rd_ids, batch, warnings):
    expense_tables = [
        table for table in tables if all(normalize(label) in named_cells(table) for label in EXPENSE_SOURCES)
    ]
    layouts, covered = [], set()
    for expense in expense_tables:
        rows = table_rows(expense)
        columns = range(1, len(rows[0]) - 1)
        heading = expense.getprevious()
        if heading is None or heading.tag != W + "p" or not columns:
            continue
        heading_text = element_text(heading)
        table_years = expense_years(heading_text)
        texts = heading.findall(f"./{W}r/{W}t")
        original_year_slot = len(texts) > 1 and normalize(texts[1].text or "") == "年度"
        if len(expense_tables) == 1 and original_year_slot:
            indexes = tuple(range(len(years)))
            projects = list(zip(columns, rd_ids))
            if projects:
                texts[0].text = YEAR_SEPARATOR.join(str(year["year"]) for year in years) + " "
                for column in list(columns)[len(projects):]:
                    write_cell_text(rows[0][column], "")
        else:
            indexes = tuple(i for i, year in enumerate(years) if str(year["year"]) in table_years)
            projects = [(column, normalize(element_text(rows[0][column]))) for column in columns]
            projects = [(column, rd_id) for column, rd_id in projects if rd_id in rd_ids]
        if indexes and projects:
            layouts.append((rows, projects, indexes))
            covered.update((index, rd_id) for index in indexes for _, rd_id in projects)
    for index, year in enumerate(years):
        missing = [rd_id for rd_id in rd_ids if (index, rd_id) not in covered]
        if missing:
            reason = f"{year['year']}年费用表缺项目原列：{'、'.join(missing)}"
            warnings.append(reason)
            for rd_id in missing:
                batch.add(pointer("expense", year["year"], rd_id), rd_id, None, reason,
                          source=pointer("rd_financials", rd_id, index))
    return layouts


REGISTRATION = (
    "企业名称", "注册时间", "注册类型", "外资来源地", "注册资金", "所属行业",
    "企业规模", "统一社会信用代码", "行政区域", "邮政编码", "企业所得税征收方式",
    "通信地址", "企业是否上市", "上市时间", "股票代码", "上市类型",
    "是否属于国家级高新区内企业", "高新区名称", "技术领域", "经营范围", "企业简介",
)
SUMMARY = (
    "技术领域", "Ⅰ类", "Ⅱ类", "职工总数", "科技人员数",
    "基础研究投入费用总额（万元）", "近一年企业总收入（万元）",
    "近一年高新技术产品（服务）收入（万元）",
    "申请认定前一年内是否发生过重大安全、重大质量事故或严重环境违法行为",
)
PS_FIELDS = (
    "产品（服务）名称", "技术领域", "技术来源", "上年度销售收入（万元）",
    "是否主要产品（服务）", "知识产权编号", "关键技术及主要技术指标（限400字）",
    "与同类产品（服务）的竞争优势（限400字）",
    "知识产权获得情况及其对产品（服务）在技术上发挥的支持作用（限400字）",
)
INNOVATION = (
    "知识产权对企业竞争力的作用（限400字）", "科技成果转化情况（限400字）",
    "研究开发与技术创新组织管理情况（限400字）", "管理与科技人员情况（限400字）",
)


def read_application_counts(root, include_ip):
    tables = root.xpath("./w:body/w:tbl", namespaces=NS)
    result = {"PS": sum(normalize(PS_FIELDS[0]) in named_cells(table) for table in tables)}
    try:
        result["RD"] = len(collect_rd_targets(root, require_field=False))
    except ValueError:
        result["RD"] = None
    if include_ip:
        try:
            rows = table_rows(find_table(tables, "知识产权名称", "授权号"))
            result["IP"] = sum(bool(re.fullmatch(r"IP[0-9]+", normalize(element_text(row[0])))) for row in rows[1:])
        except ValueError:
            result["IP"] = None
    return result


def fill_application(input_path: Path, spec: dict, output: Path, *, spec_path=None):
    if not isinstance(spec, dict) or not spec.keys() - {"schema_version", "batch_check"}:
        raise ValueError("未提供申请书回填内容")
    if output.exists() or input_path.resolve() == output.resolve():
        raise ValueError("必须使用尚不存在的输出路径，保留原件")
    allowed = {"registration", "summary", "annual_financials", "rd_financials", "rd_external", "rd_external_domestic",
               "ps", "innovation", "ip", "ip_counts", "personnel", "cover", "schema_version"}
    if "schema_version" in spec and (type(spec["schema_version"]) is not int or spec["schema_version"] != 1):
        raise ValueError("schema_version须为1或省略")
    batch = ImportBatch(spec.get("batch_check", {}), spec_path, output)
    for field in sorted(spec.keys() - allowed - {"batch_check"}):
        batch.add(pointer(field), spec[field], None, "不支持的申请书输入字段")

    def write_cell(cell, field, original, converted, reason, **options):
        batch.add(field, original, converted, reason, node=cell, **options)
        write_cell_text(cell, converted)

    warnings = []
    financial_items = []
    with ZipFile(input_path) as source_package:
        root = etree.fromstring(source_package.read("word/document.xml"))
        tables = root.xpath("./w:body/w:tbl", namespaces=NS)
        cover = dict(spec.get("cover", {}))
        if "企业名称" in spec.get("registration", {}):
            cover.setdefault("企业名称", spec["registration"]["企业名称"])
        supplied_cover_fields = set()
        for input_label, value in cover.items():
            label = "企业所在地区" if input_label == "地区" else input_label
            field = pointer("cover", label)
            source_field = (pointer("cover", input_label) if input_label in spec.get("cover", {})
                            else pointer("registration", input_label))
            if label in supplied_cover_fields:
                batch.add(pointer("cover", input_label), value, None, f"重复的封面字段：{input_label}",
                          source=source_field)
                continue
            supplied_cover_fields.add(label)
            if label not in {"企业名称", "企业所在地区", "认定机构", "申请日期"}:
                batch.add(field, value, None, f"不支持的封面字段：{label}")
                continue
            paragraphs = [node for node in root.xpath("./w:body/w:p", namespaces=NS)
                          if normalize(element_text(node)).startswith(label + "：")]
            if len(paragraphs) != 1:
                batch.add(field, value, None, f"封面字段无法唯一定位：{label}", source=source_field)
                continue
            nodes = paragraphs[0].xpath(".//w:t", namespaces=NS)
            prefix = label + "："
            value_text = text(value)
            batch.add(field, value, prefix + value_text, "同步至封面", node=paragraphs[0], source=source_field)
            if len(nodes) > 1 and nodes[0].text == prefix:
                nodes = nodes[1:]
                nodes[0].text = value_text
            else:
                nodes[0].text = prefix + value_text
            for node in nodes[1:]:
                node.text = ""
        registration = find_table(tables, "企业名称", "注册时间")
        summary = find_table(tables, "Ⅰ类", "科技人员数")
        fill_fields(registration, spec.get("registration", {}), REGISTRATION, ("registration",), batch, write_cell)
        fill_fields(summary, spec.get("summary", {}), SUMMARY, ("summary",), batch, write_cell)
        if "annual_financials" in spec:
            years = spec["annual_financials"]
            if not isinstance(years, list) or any(not isinstance(row, dict) or "year" not in row for row in years):
                raise ValueError("annual_financials须为包含year的对象数组")
            if len(years) > 3:
                raise ValueError("母版仅有三个年度经营字段，请使用对应三个年度或另附补充年度表")
            if len(years) != 3 or not all(type(row["year"]) is int for row in years) or [row["year"] for row in years] != list(range(years[0]["year"], years[0]["year"] + 3)):
                warnings.append("年度资料不足三个连续年度，已按提供的年度填写，保留其余字段")
            for index, (cells, year) in enumerate(zip(annual_rows(summary), years)):
                for key in sorted(year.keys() - {"year", "net_assets", "sales", "profit", "rd", "domestic_rd"}):
                    batch.add(pointer("annual_financials", index, key), year[key], None, "不支持的年度经营字段")
                for cell, key in zip(cells, ("year", "net_assets", "sales", "profit")):
                    if key in year:
                        value = year[key]
                        write_cell(cell, pointer("annual_financials", index, key), value, text(value), "按年度回填")
            for key, label in (("rd", "近三年研究开发费用总额（万元）"), ("domestic_rd", "在中国境内研发费用总额（万元）")):
                values = [row.get(key) for row in years]
                write_cell(target(summary, label), pointer("summary", label), values, text(total(values)),
                           "汇总各年度原值，缺值时留空", source=pointer("annual_financials"), kind="total")
        rd_targets = collect_rd_targets(root, require_field=False)
        for rd_id, values in spec.get("rd_financials", {}).items():
            if rd_id not in rd_targets:
                batch.add(pointer("rd_financials", rd_id), values, None, "未定位对应研发项目表")
                continue
            if len(values) != 3:
                raise ValueError(f"{rd_id}须对应既有RD表及三个年度支出")
            table = rd_targets[rd_id]["core_cell"].getparent().getparent()
            for index, (label, value) in enumerate(zip(("第一年", "第二年", "第三年"), values)):
                write_cell(target(table, label), pointer("rd_financials", rd_id, index), value,
                           text(amount(value)), "金额按万元转换")
            label = "研发经费近三年总支出（万元）"
            write_cell(target(table, label), pointer("rd_financials", rd_id, label), values, text(total(values)),
                       "汇总项目三年支出，缺值时留空", source=pointer("rd_financials", rd_id), kind="total")
        for key in ("rd_external", "rd_external_domestic"):
            for rd_id, values in spec.get(key, {}).items():
                if not spec.get("annual_financials") or "rd_financials" not in spec or rd_id not in rd_targets:
                    batch.add(pointer(key, rd_id), values, None, "缺对应年度费用表或研发项目")
        if spec.get("annual_financials") and "rd_financials" in spec:
            rd_ids = list(rd_targets)
            if set(rd_ids) != set(spec["rd_financials"]):
                warnings.append("部分RD费用待补；项目费用表按已提供项目分列，缺项保留空白")
            layouts = existing_expense_layouts(tables, years, rd_ids, batch, warnings)
            expense_writes = defaultdict(list)
            for index, year in enumerate(years):
                raw_values = {label: [spec.get(key, {}).get(rd_id, [None] * 3)[index] for rd_id in rd_ids]
                              for label, key in EXPENSE_SOURCES.items()}
                category_values = {label: [amount(value) for value in values] for label, values in raw_values.items()}
                costs = category_values["研究开发费用（内、外部）小计"]
                aggregate = total(costs)
                if aggregate is not None and year.get("rd") is not None and aggregate != amount(year["rd"]):
                    reported = amount(year["rd"])
                    warnings.append(f"{year['year']}年度RD支出合计与企业研发费用不同，各自原值已保留")
                    financial_items.append({
                        "item": f"{year['year']}年度研发费用勾稽",
                        "gap": f"项目合计 {text(aggregate)} 万元，年度汇总 {text(reported)} 万元，差额 {text(aggregate - reported)} 万元",
                        "action": "核对研发辅助账、项目表和年度研发费用汇总表，确认项目归集和单位后重新回填",
                        "priority": "高",
                    })
                outside = category_values["委托外部研究开发费用"]
                domestic = category_values["其中：境内的外部研发费用"]
                if any(cost is not None and external is not None and external > cost for cost, external in zip(costs, outside)):
                    warnings.append("委外研发费用大于对应项目总支出，原值已保留，差额按原公式列示")
                    financial_items.append({
                        "item": f"{year['year']}年度委外费用",
                        "gap": "存在委外费用高于对应项目总支出的记录",
                        "action": "按项目核对委外合同、归集期间和总支出", "priority": "高",
                    })
                if any(local is not None and external is not None and local > external for local, external in zip(domestic, outside)):
                    warnings.append("境内委外费用大于委外费用，原值已保留")
                    financial_items.append({
                        "item": f"{year['year']}年度境内委外费用",
                        "gap": "存在境内委外费用高于同口径委外费用的记录",
                        "action": "按项目核对境内委外归集及总委外费用", "priority": "高",
                    })
                category_values["内部研究开发费用"] = [None if cost is None or external is None else cost - external
                                                       for cost, external in zip(costs, outside)]
                raw_values["内部研究开发费用"] = [
                    {"rd_financials": cost, "rd_external": external}
                    for cost, external in zip(raw_values["研究开发费用（内、外部）小计"], raw_values["委托外部研究开发费用"])
                ]
                for rows, projects, year_indexes in layouts:
                    if index not in year_indexes:
                        continue
                    project_ids = [rd_id for _, rd_id in projects]
                    for column, rd_id in projects:
                        write_cell(rows[0][column], pointer("expense", year["year"], rd_id, "研发项目编号"),
                                   rd_id, rd_id, "沿用母版研发项目编号", source=pointer("rd_financials", rd_id))
                    read_year = partial(expense_value, index=year_indexes.index(index), year_count=len(year_indexes))
                    for label, values in category_values.items():
                        row = next(row for row in rows if normalize(element_text(row[0])) == normalize(label))
                        source_group = EXPENSE_SOURCES.get(label)
                        reason = "按年度及项目回填万元金额" if source_group else "总支出减委外费用，缺值时留空"
                        subset, raw_subset = [], []
                        for column, rd_id in projects:
                            project_index = rd_ids.index(rd_id)
                            raw, value = raw_values[label][project_index], values[project_index]
                            subset.append(value)
                            raw_subset.append(raw)
                            field = pointer("expense", year["year"], rd_id, label)
                            source = pointer(source_group or "rd_financials", rd_id, index)
                            converted = text(value)
                            expense_writes[row[column]].append(converted)
                            batch.add(field, raw, converted, reason, node=row[column], source=source,
                                      read_value=read_year)
                        field = pointer("expense", year["year"], f"{project_ids[0]}至{project_ids[-1]}", label, "合计")
                        converted = text(total(subset))
                        expense_writes[row[-1]].append(converted)
                        batch.add(field, raw_subset, converted, "汇总本表项目，缺值时留空", node=row[-1],
                                  source=pointer(source_group or "rd_financials"), kind="total", read_value=read_year)
            for cell, values in expense_writes.items():
                write_cell_text(cell, expense_text(values))
        ps_tables = [table for table in tables if normalize(PS_FIELDS[0]) in named_cells(table)]
        if "ps" in spec:
            if len(spec["ps"]) > len(ps_tables):
                for index, values in enumerate(spec["ps"][len(ps_tables):], start=len(ps_tables)):
                    batch.add(pointer("ps", index), values, None, "缺该产品的目标表，请先扩展对应表格")
            if len(spec["ps"]) < len(ps_tables):
                warnings.append("部分PS表未提供新内容，已保留原表")
            for index, (table, values) in enumerate(zip(ps_tables, spec["ps"])):
                fill_fields(table, values, PS_FIELDS, ("ps", index), batch, write_cell)
        if "innovation" in spec:
            fill_fields(find_table(tables, INNOVATION[0]), spec["innovation"], INNOVATION, ("innovation",), batch, write_cell)
        if "personnel" in spec:
            table = find_table(tables, "总   数（人）", "其中：在职人员")
            rows = table_rows(table)
            for label, values in spec["personnel"].items():
                matches = [row for row in rows if normalize(element_text(row[0])) == normalize(label)]
                if len(matches) != 1 or len(matches[0]) != 3 or len(values) != 2:
                    batch.add(pointer("personnel", label), values, None, f"人力资源字段不明确：{label}")
                    continue
                for index, (cell, value) in enumerate(zip(matches[0][1:], values)):
                    write_cell(cell, pointer("personnel", label, index), value, text(value), "按人员类别回填")
        if "ip" in spec:
            table = find_table(tables, "知识产权名称", "授权号")
            rows = table_rows(table)
            if any(element_text(cell).strip() for row in rows[1:] for cell in row[1:]):
                raise ValueError("IP批量回填仅接受空白汇总表，保留既有内容")
            fields = [element_text(cell) for cell in rows[0]]
            for index, values in enumerate(spec["ip"], 1):
                for name in sorted(set(values) - set(fields[1:])):
                    batch.add(pointer("ip", index - 1, name), values[name], None, "IP字段与母版不符")
                if index >= len(rows):
                    batch.add(pointer("ip", index - 1), values, None, "母版知识产权表缺可用原行")
                    continue
                write_cell(rows[index][0], pointer("ip", index - 1, fields[0]), values, f"IP{index:02d}",
                           "按输入顺序生成知识产权编号", source=pointer("ip", index - 1))
                for cell, name in zip(rows[index][1:], fields[1:]):
                    value = values.get(name)
                    write_cell(cell, pointer("ip", index - 1, name), value, text(value), "按母版列回填")
        if "ip_counts" in spec:
            table = find_table(tables, "发明专利", "软件著作权")
            fill_fields(table, spec["ip_counts"], ["发明专利", "其中：国防专利", "植物新品种", "国家级农作物品种",
                                                   "国家新药", "国家一级中药保护品种", "集成电路布图设计专有权",
                                                   "实用新型", "外观设计", "软件著作权"], ("ip_counts",), batch, write_cell)
        batch.locate(root.getroottree())
        package = BytesIO()
        with ZipFile(package, "w") as result:
            for entry in source_package.infolist():
                result.writestr(entry, etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
                                if entry.filename == "word/document.xml" else source_package.read(entry.filename))
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("xb") as handle:
            handle.write(package.getbuffer())
    expected_counts = {"RD": len(rd_targets), "PS": len(ps_tables)}
    if "ip" in spec:
        expected_counts["IP"] = len(spec["ip"])
    actual_counts, readback_errors = {}, []
    try:
        with ZipFile(output) as saved:
            written_root = etree.fromstring(saved.read("word/document.xml"))
        batch.check(
            written_root, NS,
            lambda node: element_text(node) if node.tag == W + "p" else xml_cell_text(node),
            text_key=readback_text_key,
        )
        actual_counts = read_application_counts(written_root, "ip" in spec)
    except (OSError, BadZipFile, KeyError, etree.XMLSyntaxError) as error:
        readback_errors.append(f"成品回读失败：{error}")
    counts = {key: {"expected": number, "actual": actual_counts.get(key),
                    "status": "completed" if number == actual_counts.get(key) else "incomplete"}
              for key, number in expected_counts.items()}
    batch_report = batch.report(counts, output, readback_errors)
    warnings.extend(f"{label}超过表单400字容量，已保留全文" for values in [spec.get("innovation", {}), *spec.get("ps", [])]
                    for label, value in values.items() if normalize(label).replace("（限400字）", "") in
                    {normalize(item).replace("（限400字）", "") for item in (*INNOVATION, *PS_FIELDS) if "400字" in item}
                    and len("".join(text(value).split())) > 400)
    if any(amount(value) is not None and amount(value) < 0 for values in spec.get("rd_financials", {}).values() for value in values):
        warnings.append("含负数研发费用，已保留原值及计算结果，请核对调整口径")
    reconciliation = "not-run"
    if spec.get("annual_financials") and "rd_financials" in spec:
        reconciliation = "conflict" if financial_items else "no-conflict-detected"
    return {"schema_version": "hightech-application-fields/v1",
            "status": "passed" if batch_report["status"] == "completed" and not financial_items else "partial",
            "artifact": str(output.resolve()),
            "financial_reconciliation": {"status": reconciliation, "items": financial_items},
            "warnings": warnings, "sections": [key for key in spec if key in allowed],
            "rd_totals": {key: text(total(value)) for key, value in spec.get("rd_financials", {}).items() if key in rd_targets},
            "batch_check": batch_report}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("spec", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    print(json.dumps(fill_application(args.input, spec, args.output, spec_path=args.spec), ensure_ascii=False))


if __name__ == "__main__":
    main()
