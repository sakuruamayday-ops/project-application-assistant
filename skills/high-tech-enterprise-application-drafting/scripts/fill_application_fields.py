#!/usr/bin/env python3
"""Fill the bundled application by physical cells and named fields, never grid indexes."""

from __future__ import annotations

import argparse
import copy
import json
import runpy
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from lxml import etree
from docx import Document

from fill_rd_core_innovation import (
    NS, W, collect_rd_targets, element_text, normalize, replace_cell_content, table_rows,
)


def text(value):
    if value is None:
        return ""
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("字段须为文字、数值或null")
    return str(value)


def amount(value):
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("金额不得为布尔值")
    number = Decimal(str(value))
    if not number.is_finite() or number < 0:
        raise ValueError("金额须为非负有限数值")
    return number


def total(values):
    numbers = [amount(value) for value in values]
    return None if any(value is None for value in numbers) else sum(numbers, Decimal(0))


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


def fill_fields(table, values, allowed):
    if not isinstance(values, dict):
        raise ValueError("字段须为对象")
    aliases = {normalize(label).replace("（限400字）", ""): label for label in allowed}
    canonical = {}
    for label, value in values.items():
        name = aliases.get(normalize(label).replace("（限400字）", ""))
        if name is None or name in canonical:
            raise ValueError(f"不支持或重复的字段：{label}")
        if "限400字" in name and len("".join(text(value).split())) > 400:
            raise ValueError(f"{name}超过400字")
        canonical[name] = value
    # Resolve every label before changing content, so values can never become labels.
    writes = [(target(table, label), text(value)) for label, value in canonical.items()]
    for cell, value in writes:
        replace_cell_content(cell, value)


def normalize_leading_page_breaks(root):
    """Keep chapter starts without a standalone break spilling onto a blank page."""
    for paragraph in list(root.xpath("./w:body/w:p", namespaces=NS)):
        breaks = paragraph.xpath(".//w:br[@w:type='page']", namespaces=NS)
        if len(breaks) != 1 or paragraph.xpath("./w:pPr/w:sectPr", namespaces=NS):
            continue
        page_break = breaks[0]
        prefix_has_text = False
        for node in paragraph.iter():
            if node is page_break:
                break
            if node.tag == W + "t" and node.text and node.text.strip():
                prefix_has_text = True
        if prefix_has_text:
            continue
        target_paragraph = paragraph
        if not element_text(paragraph).strip():
            following = paragraph.getnext()
            if following is None or following.tag != W + "p" or not element_text(following).strip():
                continue
            target_paragraph = following
        properties = target_paragraph.find(W + "pPr")
        if properties is None:
            properties = etree.Element(W + "pPr")
            target_paragraph.insert(0, properties)
        if properties.find(W + "pageBreakBefore") is None:
            etree.SubElement(properties, W + "pageBreakBefore")
        page_break.getparent().remove(page_break)
        if target_paragraph is not paragraph:
            for bookmark in paragraph.xpath("./w:bookmarkStart|./w:bookmarkEnd", namespaces=NS):
                target_paragraph.append(bookmark)
            paragraph.getparent().remove(paragraph)


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


def fill_application(input_path: Path, spec: dict, output: Path):
    if output.exists() or input_path.resolve() == output.resolve():
        raise ValueError("必须使用尚不存在的输出路径，保留原件")
    allowed = {"registration", "summary", "annual_financials", "rd_financials", "rd_external", "rd_external_domestic",
               "ps", "innovation", "ip", "ip_counts", "personnel", "cover", "schema_version"}
    if set(spec) - allowed:
        raise ValueError("不支持的申请书输入字段：" + str(set(spec) - allowed))
    if "schema_version" in spec and (type(spec["schema_version"]) is not int or spec["schema_version"] != 1):
        raise ValueError("schema_version须为1或省略")
    with ZipFile(input_path) as source:
        root = etree.fromstring(source.read("word/document.xml"))
        tables = root.xpath("./w:body/w:tbl", namespaces=NS)
        cover = dict(spec.get("cover", {}))
        if "企业名称" in spec.get("registration", {}):
            cover.setdefault("企业名称", spec["registration"]["企业名称"])
        for label, value in cover.items():
            if label not in {"企业名称", "企业所在地区", "认定机构", "申请日期"}:
                raise ValueError(f"不支持的封面字段：{label}")
            paragraphs = [node for node in root.xpath("./w:body/w:p", namespaces=NS)
                          if normalize(element_text(node)).startswith(label + "：")]
            if len(paragraphs) != 1:
                raise ValueError(f"封面字段无法唯一定位：{label}")
            nodes = paragraphs[0].xpath(".//w:t", namespaces=NS)
            nodes[0].text = label + "：" + text(value)
            for node in nodes[1:]:
                node.text = ""
        registration = find_table(tables, "企业名称", "注册时间")
        summary = find_table(tables, "Ⅰ类", "科技人员数")
        fill_fields(registration, spec.get("registration", {}), REGISTRATION)
        fill_fields(summary, spec.get("summary", {}), SUMMARY)
        if "annual_financials" in spec:
            years = spec["annual_financials"]
            if len(years) != 3 or [row["year"] for row in years] != list(range(years[0]["year"], years[0]["year"] + 3)):
                raise ValueError("annual_financials须为连续三个实际年度")
            rows = table_rows(summary)
            for index, year in enumerate(years):
                row = next(row for row in rows if any(normalize(element_text(cell)) == f"第{'一二三'[index]}年" for cell in row))
                cells = row[1:]
                if len(cells) != 4:
                    raise ValueError("年度经营情况物理单元格不符合母版")
                for cell, value in zip(cells, [year["year"], year.get("net_assets"), year.get("sales"), year.get("profit")]):
                    replace_cell_content(cell, text(value))
            replace_cell_content(target(summary, "近三年研究开发费用总额（万元）"), text(total(row.get("rd") for row in years)))
            replace_cell_content(target(summary, "在中国境内研发费用总额（万元）"), text(total(row.get("domestic_rd") for row in years)))
        rd_targets = collect_rd_targets(root, require_field=False)
        for rd_id, values in spec.get("rd_financials", {}).items():
            if rd_id not in rd_targets or len(values) != 3:
                raise ValueError(f"{rd_id}须对应既有RD表及三个年度支出")
            table = rd_targets[rd_id]["core_cell"].getparent().getparent()
            for label, value in zip(["第一年", "第二年", "第三年"], values):
                replace_cell_content(target(table, label), text(amount(value)))
            replace_cell_content(target(table, "研发经费近三年总支出（万元）"), text(total(values)))
        if "annual_financials" in spec and "rd_financials" in spec:
            rd_ids = list(rd_targets)
            if set(rd_ids) != set(spec["rd_financials"]):
                raise ValueError("年度费用表须覆盖全部RD，不以部分RD合计替代企业总额")
            expense = find_table(tables, "研究开发费用（内、外部）小计", "委托外部研究开发费用")
            expense_rows = table_rows(expense)
            placeholder = expense.getprevious()
            if placeholder is not None and normalize(element_text(placeholder)) == "年度单位：万元":
                placeholder.getparent().remove(placeholder)
            capacity = len(expense_rows[0]) - 2
            if capacity < 1:
                raise ValueError("费用母版缺少项目列")
            anchor = expense
            for index, year in enumerate(spec["annual_financials"]):
                costs = [amount(spec["rd_financials"][rd_id][index]) for rd_id in rd_ids]
                aggregate = total(costs)
                if aggregate is not None and year.get("rd") is not None and aggregate != amount(year["rd"]):
                    raise ValueError(f"{year['year']}年度RD支出合计与企业研发费用不一致")
                category_values = {"研究开发费用（内、外部）小计": costs}
                for key, label in [("rd_external", "委托外部研究开发费用"),
                                   ("rd_external_domestic", "其中：境内的外部研发费用")]:
                    category_values[label] = [amount(spec.get(key, {}).get(rd_id, [None] * 3)[index]) for rd_id in rd_ids]
                outside = category_values["委托外部研究开发费用"]
                domestic = category_values["其中：境内的外部研发费用"]
                if any(cost is not None and external is not None and external > cost for cost, external in zip(costs, outside)):
                    raise ValueError("委外研发费用不得超过对应项目总支出")
                if any(local is not None and external is not None and local > external for local, external in zip(domestic, outside)):
                    raise ValueError("境内委外费用不得超过委外费用")
                category_values["内部研究开发费用"] = [None if cost is None or external is None else cost - external
                                                       for cost, external in zip(costs, outside)]
                # Keep the approved geometry and split projects, not years, across continuation tables.
                for start in range(0, len(rd_ids), capacity):
                    batch = rd_ids[start:start + capacity]
                    copy_table = copy.deepcopy(expense)
                    for positioning in copy_table.xpath("./w:tblPr/w:tblpPr", namespaces=NS):
                        positioning.getparent().remove(positioning)
                    rows = table_rows(copy_table)
                    replace_cell_content(rows[0][0], "科目\n累计发生额\n研发项目编号")
                    for cell, rd_id in zip(rows[0][1:-1], batch + [""] * (capacity - len(batch))):
                        replace_cell_content(cell, rd_id)
                    for row in rows[1:]:
                        for cell in row[1:]:
                            replace_cell_content(cell, "")
                    for label, values in category_values.items():
                        row = next(row for row in rows if normalize(element_text(row[0])) == normalize(label))
                        subset = values[start:start + capacity]
                        for cell, value in zip(row[1:-1], subset):
                            replace_cell_content(cell, text(value))
                        replace_cell_content(row[-1], text(total(subset)))
                    caption = etree.Element(W + "p")
                    caption_properties = etree.SubElement(caption, W + "pPr")
                    etree.SubElement(caption_properties, W + "keepNext")
                    if index > 0 or start > 0:
                        etree.SubElement(caption_properties, W + "pageBreakBefore")
                    for paragraph in copy_table.xpath(".//w:p", namespaces=NS):
                        properties = paragraph.find(W + "pPr")
                        if properties is None:
                            properties = etree.Element(W + "pPr")
                            paragraph.insert(0, properties)
                        for spacing in properties.findall(W + "spacing"):
                            properties.remove(spacing)
                        etree.SubElement(properties, W + "spacing", {
                            W + "before": "0", W + "after": "0", W + "line": "240", W + "lineRule": "auto",
                        })
                        for run in paragraph.findall(W + "r"):
                            run_properties = run.find(W + "rPr")
                            if run_properties is None:
                                run_properties = etree.Element(W + "rPr")
                                run.insert(0, run_properties)
                            for size in run_properties.findall(W + "sz"):
                                run_properties.remove(size)
                            etree.SubElement(run_properties, W + "sz", {W + "val": "21"})
                    suffix = (f"，{batch[0]}至{batch[-1]}，合计为本表项目小计"
                              if len(rd_ids) > capacity else "")
                    etree.SubElement(etree.SubElement(caption, W + "r"), W + "t").text = f"{year['year']}年度研究开发费用，单位：万元{suffix}"
                    anchor.addnext(caption)
                    caption.addnext(copy_table)
                    anchor = copy_table
            expense.getparent().remove(expense)
        ps_tables = [table for table in tables if normalize(PS_FIELDS[0]) in named_cells(table)]
        if "ps" in spec:
            if len(spec["ps"]) != len(ps_tables):
                raise ValueError("PS记录数必须等于已授权扩缩后的PS表数")
            for table, values in zip(ps_tables, spec["ps"]):
                fill_fields(table, values, PS_FIELDS)
        if "innovation" in spec:
            fill_fields(find_table(tables, INNOVATION[0]), spec["innovation"], INNOVATION)
        if "personnel" in spec:
            table = find_table(tables, "总   数（人）", "其中：在职人员")
            rows = table_rows(table)
            for label, values in spec["personnel"].items():
                matches = [row for row in rows if normalize(element_text(row[0])) == normalize(label)]
                if len(matches) != 1 or len(matches[0]) != 3 or len(values) != 2:
                    raise ValueError(f"人力资源字段不明确：{label}")
                for cell, value in zip(matches[0][1:], values):
                    replace_cell_content(cell, text(value))
        if "ip" in spec:
            table = find_table(tables, "知识产权名称", "授权号")
            rows = table_rows(table)
            if any(element_text(cell).strip() for row in rows[1:] for cell in row[1:]):
                raise ValueError("IP批量回填仅接受空白汇总表，保留既有内容")
            fields = [element_text(cell) for cell in rows[0]]
            for index, values in enumerate(spec["ip"], 1):
                if set(values) - set(fields[1:]):
                    raise ValueError("IP字段与母版不符")
                if index >= len(rows):
                    table.append(copy.deepcopy(table[-1]))
                    rows = table_rows(table)
                for cell, value in zip(rows[index], [f"IP{index:02d}"] + [values.get(field) for field in fields[1:]]):
                    replace_cell_content(cell, text(value))
            # This table was verified empty above; retain only requested records.
            for row in list(table.findall(W + "tr"))[len(spec["ip"]) + 1:]:
                table.remove(row)
        if "ip_counts" in spec:
            table = find_table(tables, "发明专利", "软件著作权")
            fill_fields(table, spec["ip_counts"], ["发明专利", "其中：国防专利", "植物新品种", "国家级农作物品种",
                                                   "国家新药", "国家一级中药保护品种", "集成电路布图设计专有权",
                                                   "实用新型", "外观设计", "软件著作权"])
        normalize_leading_page_breaks(root)
        package = BytesIO()
        with ZipFile(package, "w") as result:
            for entry in source.infolist():
                result.writestr(entry, etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
                                if entry.filename == "word/document.xml" else source.read(entry.filename))
        package.seek(0)
        document = Document(package)
        helper = Path(__file__).resolve().parents[2] / "project-feasibility/scripts/fill_report_template.py"
        runpy.run_path(str(helper))["_apply_portable_cjk_font"](document)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("xb") as handle:
            document.save(handle)
    return {"schema_version": "hightech-application-fields/v1", "status": "passed", "artifact": str(output.resolve()),
            "sections": list(spec), "rd_totals": {key: text(total(value)) for key, value in spec.get("rd_financials", {}).items()}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("spec", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(fill_application(args.input, json.loads(args.spec.read_text(encoding="utf-8")), args.output), ensure_ascii=False))


if __name__ == "__main__":
    main()
