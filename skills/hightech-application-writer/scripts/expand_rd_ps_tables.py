#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import sys
from bisect import bisect_right
from datetime import datetime
from pathlib import Path

from docx import Document
from docx.opc.constants import CONTENT_TYPE
from docx.opc.oxml import serialize_part_xml
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn
from docx.table import Table, _Cell

from rd_ps_codes import FORM_LABELS, iter_codes, number_code, number_width, parse_form_code


TEMPLATE_NUMBERING_NOTE = "IP、RD、PS后取两位数（01、02、……）。"
ADAPTIVE_NUMBERING_NOTE = (
    "IP后取两位数（01、02、……）。RD、PS表按用户申报的研发项目与产品数量生成，"
    "编号分别按各自表数统一位数，最少两位。"
)
REFERENCE_PARTS = {
    CONTENT_TYPE.WML_HEADER, CONTENT_TYPE.WML_FOOTER, CONTENT_TYPE.WML_COMMENTS,
    CONTENT_TYPE.WML_FOOTNOTES, CONTENT_TYPE.WML_ENDNOTES,
}

RD_LABELS = {
    "研发活动名称",
    "起止时间",
    "技术领域",
    "技术来源",
    "知识产权编号",
    "研发经费总预算（万元）",
    "研发经费近三年总支出（万元）",
    "其中",
    "第一年",
    "第二年",
    "第三年",
    "目的及组织实施方式（限400字）",
    "核心技术及创新点（限400字）",
    "取得的阶段性成果（限400字）",
}

PS_LABELS = {
    "产品（服务）名称",
    "技术领域",
    "技术来源",
    "上年度销售收入（万元）",
    "是否主要产品（服务）",
    "□是□否",
    "知识产权编号",
    "关键技术及主要技术指标（限400字）",
    "与同类产品（服务）的竞争优势（限400字）",
    "知识产权获得情况及其对产品（服务）在技术上发挥的支持作用（限400字）",
}


def normalize(text: str) -> str:
    return "".join(text.replace("\u3000", " ").split())


def unique_cells(row):
    """Yield physical OOXML cells; row.cells expands merged grid positions."""
    for cell_element in row._tr.findall(qn("w:tc")):
        yield _Cell(cell_element, row._parent)


def table_kind(table) -> str | None:
    text = normalize("".join(cell.text for row in table.rows for cell in unique_cells(row)))
    if "研发活动名称" in text and "目的及组织实施方式" in text and "阶段性成果" in text:
        return "rd"
    if "产品（服务）名称" in text and "关键技术及主要技术指标" in text and "竞争优势" in text:
        return "ps"
    return None


def paragraph_text(element) -> str:
    return "".join(node.text or "" for node in element.iter(qn("w:t")))


def find_previous_marker(table_element, kind: str):
    kind = kind.upper()
    placeholder = FORM_LABELS[kind] if kind == "RD" else f"{FORM_LABELS[kind]}：PS"
    current = table_element.getprevious()
    while current is not None:
        if current.tag == qn("w:p"):
            text = paragraph_text(current)
            if placeholder in normalize(text) or parse_form_code(text, kind):
                return current
        current = current.getprevious()
    return None


def set_paragraph_text_preserve_format(paragraph_element, text: str) -> None:
    text_nodes = list(paragraph_element.iter(qn("w:t")))
    if text_nodes:
        text_nodes[0].text = text
        for node in text_nodes[1:]:
            node.text = ""
        return

    run = OxmlElement("w:r")
    text_node = OxmlElement("w:t")
    text_node.text = text
    run.append(text_node)
    paragraph_element.append(run)


def clear_cell_preserve_format(cell) -> None:
    for paragraph in cell.paragraphs:
        text_nodes = list(paragraph._p.iter(qn("w:t")))
        for node in text_nodes:
            node.text = ""


def set_cell_text_preserve_format(cell, text: str) -> None:
    if not cell.paragraphs:
        cell.add_paragraph()
    set_paragraph_text_preserve_format(cell.paragraphs[0]._p, text)
    for paragraph in cell.paragraphs[1:]:
        for node in paragraph._p.iter(qn("w:t")):
            node.text = ""


def clear_table_data(table, kind: str) -> None:
    labels = RD_LABELS if kind == "rd" else PS_LABELS
    for row in table.rows:
        for cell in unique_cells(row):
            if normalize(cell.text) not in labels:
                clear_cell_preserve_format(cell)
    if kind == "ps":
        for row in table.rows:
            cells = list(unique_cells(row))
            if cells and normalize(cells[0].text) == "是否主要产品（服务）" and len(cells) >= 2:
                set_cell_text_preserve_format(cells[1], "□是 □否")


def make_page_break_paragraph() -> OxmlElement:
    paragraph = OxmlElement("w:p")
    run = OxmlElement("w:r")
    page_break = OxmlElement("w:br")
    page_break.set(qn("w:type"), "page")
    run.append(page_break)
    paragraph.append(run)
    return paragraph


def is_page_break_only(paragraph_element) -> bool:
    if paragraph_element is None or paragraph_element.tag != qn("w:p"):
        return False
    if normalize(paragraph_text(paragraph_element)):
        return False
    breaks = list(paragraph_element.iter(qn("w:br")))
    if not breaks or any(node.get(qn("w:type")) != "page" for node in breaks):
        return False
    forbidden = ("w:drawing", "w:object", "w:pict", "w:tab")
    return not any(list(paragraph_element.iter(qn(tag))) for tag in forbidden)


def collect_units(document, kind: str):
    units = []
    for table in document.tables:
        if table_kind(table) != kind:
            continue
        marker_paragraph = find_previous_marker(table._tbl, kind)
        if marker_paragraph is None:
            raise ValueError(f"找到{kind.upper()}表，但未找到其编号段落")
        units.append((marker_paragraph, table))
    return units


def renumber_units(units, kind: str, prefix: str, count: int) -> None:
    marker = f"{FORM_LABELS[kind.upper()]}："
    for index, (paragraph, _) in enumerate(units, 1):
        set_paragraph_text_preserve_format(paragraph, marker + number_code(prefix, index, count))


def replace_paragraph_references(paragraph, replacements, removed_codes=(), *, adapt_note=False) -> bool:
    paragraph_tag = qn("w:p")
    text_tag = qn("w:t")
    separators = {qn(tag) for tag in ("w:tab", "w:br", "w:cr")}
    nodes, parts, ends = [], [], []
    length = 0
    for node in paragraph.iter():
        if node.tag != text_tag and node.tag not in separators:
            continue
        if next(node.iterancestors(paragraph_tag), None) is not paragraph:
            continue
        text = (node.text or "") if node.tag == text_tag else "\n"
        if text:
            length += len(text)
            nodes.append(node)
            parts.append(text)
            ends.append(length)

    text = "".join(parts)
    edits = []
    for match in iter_codes(text):
        original = match[0].upper()
        if original in removed_codes:
            raise ValueError(f"原编号{original}仍有引用，无法删除对应空白表")
        if original not in replacements:
            continue
        replacement = replacements[original]
        if replacement is None:
            raise ValueError(f"原编号{original}重复，无法同步引用")
        edits.append((*match.span(), replacement))
    if adapt_note and (start := text.find(TEMPLATE_NUMBERING_NOTE)) != -1:
        edits.append((start, start + len(TEMPLATE_NUMBERING_NOTE), ADAPTIVE_NUMBERING_NOTE))

    # Use the original offsets from right to left, including edits spanning runs.
    for start, end, replacement in sorted(edits, reverse=True):
        first = bisect_right(ends, start)
        last = bisect_right(ends, end - 1)
        for index in range(first, last + 1):
            offset = ends[index - 1] if index else 0
            left, right = max(0, start - offset), min(ends[index], end) - offset
            width = right - left if index < last else len(replacement)
            node = nodes[index]
            node.text = node.text[:left] + replacement[:width] + node.text[right:]
            replacement = replacement[width:]
            if node.text != node.text.strip():
                node.set(qn("xml:space"), "preserve")
    return bool(edits)


def replace_references(root, replacements, removed_codes, excluded=(), *, adapt_note=False) -> bool:
    changed = False
    for paragraph in root.iter(qn("w:p")):
        if paragraph not in excluded:
            changed |= replace_paragraph_references(
                paragraph, replacements, removed_codes, adapt_note=adapt_note,
            )
    return changed


def collect_reference_changes(targets):
    replacements = {}
    removed_codes = set()
    for kind, count, prefix, units in targets:
        for position, (paragraph, _) in enumerate(units, 1):
            original = parse_form_code(paragraph_text(paragraph), kind.upper())
            if original is None:
                continue
            if position > count:
                if number_width(len(units)) > 2:
                    removed_codes.add(original)
                continue
            updated = number_code(prefix, position, count)
            if replacements.setdefault(original, updated) != updated:
                replacements[original] = None

    removed_codes.difference_update(replacements)
    replacements = {original: updated for original, updated in replacements.items() if original != updated}
    return replacements, removed_codes


def update_blank_expense_headers(document, count: int, prefix: str):
    """The blank expense template has example columns before any RD is numbered."""
    updated_paragraphs = set()
    for table in document.element.body.findall(qn("w:tbl")):
        rows = table.findall(qn("w:tr"))
        if not rows:
            continue
        cells = rows[0].findall(qn("w:tc"))
        labels = [normalize(paragraph_text(cell)) for cell in cells]
        if not labels or "研发项目编号" not in labels[0] or "RD…" not in labels:
            continue
        if any(
            normalize(paragraph_text(cell))
            for row in rows[1:] for cell in row.findall(qn("w:tc"))[1:]
        ):
            continue
        for paragraph in rows[0].iter(qn("w:p")):
            replacements = {}
            for match in iter_codes(paragraph_text(paragraph)):
                code = match[0].upper()
                if code.startswith("RD"):
                    replacements[code] = number_code(prefix, int(code[2:]), count)
            if replacements:
                replace_paragraph_references(paragraph, replacements)
                updated_paragraphs.add(paragraph)
    return updated_paragraphs


def update_number_references(document, replacements, removed_codes, excluded, *, adapt_note):
    if not replacements and not removed_codes and not adapt_note:
        return
    replace_references(document.element, replacements, removed_codes, excluded, adapt_note=adapt_note)
    if not replacements and not removed_codes:
        return
    for part in document.part.related_parts.values():
        if part.content_type not in REFERENCE_PARTS:
            continue
        root = getattr(part, "element", None)
        if root is not None:
            replace_references(root, replacements, removed_codes)
        else:
            # python-docx loads footnotes and endnotes as raw XML parts.
            root = parse_xml(part.blob)
            if replace_references(root, replacements, removed_codes):
                part._blob = serialize_part_xml(root)


def meaningful_table_values(table, kind: str):
    labels = RD_LABELS if kind == "rd" else PS_LABELS
    normalized_labels = {normalize(label) for label in labels}
    values = []
    for row_index, row in enumerate(table.rows, 1):
        for column_index, cell in enumerate(unique_cells(row), 1):
            raw_value = cell.text.strip()
            normalized_value = normalize(raw_value)
            if normalized_value and normalized_value not in normalized_labels:
                values.append(
                    {
                        "row": row_index,
                        "column": column_index,
                        "value": raw_value[:120],
                    }
                )
    return values


def remove_unit(marker_paragraph, table) -> None:
    page_break = marker_paragraph.getprevious()
    table_parent = table._tbl.getparent()
    marker_parent = marker_paragraph.getparent()
    table_parent.remove(table._tbl)
    marker_parent.remove(marker_paragraph)
    if is_page_break_only(page_break) and page_break.getparent() is not None:
        page_break.getparent().remove(page_break)


def resize_kind(
    kind: str,
    target_count: int,
    prefix: str,
    units,
    markers,
    trim_empty_tail: bool = False,
):
    original_count = len(units)
    if original_count == 0:
        raise ValueError(f"文档中未找到可复制的{kind.upper()}表")
    if target_count < original_count:
        if not trim_empty_tail:
            raise ValueError(
                f"{kind.upper()}目标数量{target_count}小于现有数量{original_count}；"
                "默认禁止缩表。如确认只删除末尾完全空白表，请增加 --trim-empty-tail"
            )

        trailing_units = units[target_count:]
        blocked = []
        for original_index, (_, table) in enumerate(
            trailing_units, target_count + 1
        ):
            values = meaningful_table_values(table, kind)
            if values:
                blocked.append(
                    {
                        "code": number_code(prefix, original_index, original_count),
                        "values": values,
                    }
                )
        if blocked:
            details = []
            for item in blocked:
                evidence = "；".join(
                    f"第{value['row']}行第{value['column']}列={value['value']!r}"
                    for value in item["values"][:3]
                )
                details.append(f"{item['code']}（{evidence}）")
            raise ValueError(
                f"{kind.upper()}缩表已阻断：待删除的末尾表中存在已填写内容："
                + "、".join(details)
                + "。未删除任何表格"
            )

        removed = []
        for index, (marker_paragraph, _) in enumerate(
            trailing_units, target_count + 1
        ):
            removed.append(
                {
                    "position": index,
                    "code": number_code(prefix, index, original_count),
                    "original_marker": paragraph_text(marker_paragraph).strip(),
                    "reason": "末尾完全空白表",
                }
            )
        for marker_paragraph, table in reversed(trailing_units):
            remove_unit(marker_paragraph, table)

        renumber_units(units[:target_count], kind, prefix, target_count)
        return {
            "before": original_count,
            "requested": target_count,
            "after": target_count,
            "operation": "trim",
            "added": [],
            "removed": removed,
            "renumbered_continuously": True,
        }

    renumber_units(units, kind, prefix, target_count)
    added = []
    if target_count == original_count:
        return {
            "before": original_count,
            "requested": target_count,
            "after": original_count,
            "operation": "unchanged",
            "added": added,
            "removed": [],
            "renumbered_continuously": True,
        }

    source_paragraph, source_table = units[-1]
    cursor = source_table._tbl
    marker = f"{FORM_LABELS[kind.upper()]}："
    for index in range(original_count + 1, target_count + 1):
        paragraph_clone = copy.deepcopy(source_paragraph)
        table_clone = copy.deepcopy(source_table._tbl)
        page_break = make_page_break_paragraph()

        cursor.addnext(page_break)
        page_break.addnext(paragraph_clone)
        paragraph_clone.addnext(table_clone)

        clear_table_data(Table(table_clone, source_table._parent), kind)

        code = number_code(prefix, index, target_count)
        set_paragraph_text_preserve_format(paragraph_clone, f"{marker}{code}")
        markers.add(paragraph_clone)

        cursor = table_clone
        added.append(code)

    return {
        "before": original_count,
        "requested": target_count,
        "after": target_count,
        "operation": "expand",
        "added": added,
        "removed": [],
        "renumbered_continuously": True,
    }


def parse_args():
    parser = argparse.ArgumentParser(
        description="按高企申请书原格式安全扩缩RD和PS表，并连续编号。"
    )
    parser.add_argument("input", type=Path, help="输入DOCX")
    parser.add_argument("output", type=Path, help="输出DOCX，不得与输入相同")
    parser.add_argument("--rd-count", type=int, help="最终RD表总数")
    parser.add_argument("--ps-count", type=int, help="最终PS表总数")
    parser.add_argument("--rd-prefix", default="RD")
    parser.add_argument("--ps-prefix", default="PS")
    parser.add_argument(
        "--trim-empty-tail",
        action="store_true",
        help="允许从末尾删除完全空白的RD/PS表；任一待删除表有内容即整体阻断",
    )
    parser.add_argument("--report", type=Path, help="可选JSON审计报告")
    parser.add_argument("--overwrite", action="store_true", help="允许覆盖已有输出文件")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.rd_count is None and args.ps_count is None:
        raise SystemExit("必须至少提供 --rd-count 或 --ps-count")
    for label, value in (("RD", args.rd_count), ("PS", args.ps_count)):
        if value is not None and value < 1:
            raise SystemExit(f"{label}数量必须不小于1")

    input_path = args.input.resolve()
    output_path = args.output.resolve()
    if input_path == output_path:
        raise SystemExit("输出文件不得与输入文件相同")
    if not input_path.exists():
        raise SystemExit(f"输入文件不存在：{input_path}")
    if output_path.exists() and not args.overwrite:
        raise SystemExit(f"输出文件已存在；如需覆盖请增加 --overwrite：{output_path}")

    document = Document(input_path)
    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "input": str(input_path),
        "output": str(output_path),
        "trim_empty_tail_authorized": args.trim_empty_tail,
        "deletion_policy": (
            "仅允许删除末尾完全空白的RD、PS表；任一待删除表存在填写内容即阻断整个操作"
        ),
        "rd": None,
        "ps": None,
    }

    targets = [
        (kind, count, prefix, collect_units(document, kind))
        for kind, count, prefix in (("rd", args.rd_count, args.rd_prefix), ("ps", args.ps_count, args.ps_prefix))
        if count is not None
    ]
    replacements, removed_codes = collect_reference_changes(targets)
    markers = {paragraph for _, _, _, units in targets for paragraph, _ in units}
    for kind, count, prefix, units in targets:
        report[kind] = resize_kind(kind, count, prefix, units, markers, trim_empty_tail=args.trim_empty_tail)
        if kind == "rd" and number_width(max(count, len(units))) > 2:
            markers.update(update_blank_expense_headers(document, count, prefix))
    update_number_references(
        document, replacements, removed_codes, markers,
        adapt_note=any(number_width(count) > 2 for _, count, _, _ in targets),
    )

    trim_performed = any(
        report[kind] is not None and report[kind]["operation"] == "trim"
        for kind in ("rd", "ps")
    )
    report_path = args.report.resolve() if args.report else None
    if trim_performed and report_path is None:
        report_path = output_path.with_suffix(output_path.suffix + ".audit.json")
    if report_path is not None:
        if report_path in (input_path, output_path):
            raise ValueError("审计报告路径不得与输入或输出DOCX相同")
        if report_path.exists() and not args.overwrite:
            raise ValueError(
                f"审计报告已存在；如需覆盖请增加 --overwrite：{report_path}"
            )
        report["audit_report"] = str(report_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    document.save(output_path)

    report_text = json.dumps(report, ensure_ascii=False, indent=2)
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_text, encoding="utf-8")
    print(report_text)


if __name__ == "__main__":
    try:
        main()
    except ValueError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        raise SystemExit(2)
