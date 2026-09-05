#!/usr/bin/env python3
"""Safely fill RD core-technology and innovation cells in a high-tech application."""

from __future__ import annotations

import argparse
import copy
import json
import re
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from lxml import etree


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f"{{{W_NS}}}"
NS = {"w": W_NS}
RD_PATTERN = re.compile(r"研发活动编号[:：]?\s*(RD\d{2})", re.IGNORECASE)
ADVANCED_TERMS = (
    "人工智能",
    "深度学习",
    "机器学习",
    "神经网络",
    "数字孪生",
    "大数据平台",
    "区块链",
    "云边协同",
    "自主决策",
    "预测性维护",
)
VALIDATION_SENTENCE = "以上拟定指标以企业检测报告、产品规格书或现场运行记录校准。"
PENDING_FIELD = "待企业确认四级领域"
PENDING_INDICATOR = "技术指标待企业核定，当前资料未提供数值，不形成量化结论。"
BASIC_LABELS = (
    "研发活动名称", "起止时间", "技术领域", "技术来源", "知识产权编号",
    "研发经费总预算", "目的及组织实施方式",
)
UNIT_OR_BOUNDARY = re.compile(
    r"(%|秒|分钟|小时|天|毫米|厘米|微米|千米|米|赫兹|分贝|摄氏度|℃|兆帕|MPa|"
    r"伏|安|瓦|帧|次|个|类|项|套|点|条|不低于|不高于|不大于|不小于|不超过|不少于)"
)


def normalize(value: str) -> str:
    return "".join(value.replace("\u3000", " ").split())


def element_text(node: etree._Element) -> str:
    return "".join(text.text or "" for text in node.xpath(".//w:t", namespaces=NS))


def paragraph_text(node: etree._Element) -> str:
    return element_text(node)


def table_rows(table: etree._Element) -> list[list[etree._Element]]:
    return [row.xpath("./w:tc", namespaces=NS) for row in table.xpath("./w:tr", namespaces=NS)]


def find_label_row(rows: list[list[etree._Element]], prefix: str) -> tuple[list[etree._Element], int] | None:
    for cells in rows:
        for index, cell in enumerate(cells):
            if normalize(element_text(cell)).startswith(prefix):
                return cells, index
    return None


def collect_rd_targets(root: etree._Element, *, require_field: bool = True) -> dict[str, dict[str, object]]:
    body = root.find(".//w:body", namespaces=NS)
    if body is None:
        raise ValueError("DOCX正文缺少w:body")
    current_rd: str | None = None
    targets: dict[str, dict[str, object]] = {}
    for child in body:
        if child.tag == W + "p":
            match = RD_PATTERN.search(paragraph_text(child))
            if match:
                current_rd = match.group(1).upper()
            continue
        if child.tag != W + "tbl" or current_rd is None:
            continue
        rows = table_rows(child)
        title_row = find_label_row(rows, "研发活动名称")
        field_row = find_label_row(rows, "技术领域")
        core_row = find_label_row(rows, "核心技术及创新点")
        result_row = find_label_row(rows, "取得的阶段性成果")
        if not title_row or not field_row or not core_row or not result_row:
            continue
        field_cells, field_index = field_row
        core_cells, core_index = core_row
        result_cells, result_index = result_row
        if (
            field_index + 1 >= len(field_cells)
            or core_index + 1 >= len(core_cells)
            or result_index + 1 >= len(result_cells)
        ):
            raise ValueError(f"{current_rd}表的领域、核心技术或阶段性成果数据单元格缺失")
        field = element_text(field_cells[field_index + 1]).strip()
        if require_field and field != PENDING_FIELD and (not field or "—" not in field):
            raise ValueError(f"{current_rd}表头未填写完整四级领域：{field!r}")
        if current_rd in targets:
            raise ValueError(f"文档存在重复编号：{current_rd}")
        targets[current_rd] = {
            "field": field,
            "core_cell": core_cells[core_index + 1],
            "result_cell": result_cells[result_index + 1],
            "basic_cells": {
                label: pair[0][pair[1] + 1]
                for label in BASIC_LABELS
                if (pair := find_label_row(rows, label)) and pair[1] + 1 < len(pair[0])
            },
        }
    return targets


def ensure_sentence(value: str) -> str:
    value = value.strip()
    if not value:
        return value
    return value if value[-1] in "。；！？.!?" else value + "。"


def require_string(container: dict, key: str, context: str) -> str:
    value = container.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context}.{key}不能为空")
    return value.strip()


def validate_profile(data: dict) -> dict[str, object]:
    profile = data.get("enterprise_profile")
    if not isinstance(profile, dict):
        raise ValueError("enterprise_profile必须为对象")
    for key in ("name", "scale_summary", "main_business", "patent_summary"):
        require_string(profile, key, "enterprise_profile")
    for key in ("scale_evidence", "patent_evidence"):
        values = profile.get(key)
        if not isinstance(values, list) or not values or not all(isinstance(item, str) and item.strip() for item in values):
            raise ValueError(f"enterprise_profile.{key}必须是非空字符串数组")
    verified = profile.get("verified_advanced_terms", [])
    if not isinstance(verified, list) or not all(isinstance(item, str) and item.strip() for item in verified):
        raise ValueError("enterprise_profile.verified_advanced_terms必须是字符串数组")
    unknown = sorted(set(verified) - set(ADVANCED_TERMS))
    if unknown:
        raise ValueError("verified_advanced_terms含未受控词：" + "、".join(unknown))
    return profile


def format_technology(index: int, value: dict, rd_id: str) -> str:
    if not isinstance(value, dict):
        raise ValueError(f"{rd_id}.core_technologies[{index - 1}]必须为对象")
    name = require_string(value, "name", f"{rd_id}.core_technologies[{index - 1}]").rstrip("：:")
    description = require_string(value, "description", f"{rd_id}.core_technologies[{index - 1}]")
    if not name.endswith("技术"):
        raise ValueError(f"{rd_id}第{index}条核心技术名称必须以“技术”结尾")
    # 显式缺值写成待核定草稿，不能为满足数值检查而编造指标；正式核稿仍会报告缺口。
    if "indicators" in value and value["indicators"] is None:
        return f"{index}、{name}：{ensure_sentence(description)}{PENDING_INDICATOR}"
    indicators = require_string(value, "indicators", f"{rd_id}.core_technologies[{index - 1}]")
    if not re.search(r"\d", indicators) or not UNIT_OR_BOUNDARY.search(indicators):
        raise ValueError(f"{rd_id}第{index}条核心技术指标必须包含数值以及单位或阈值边界")
    indicators = re.sub(r"^拟定技术指标(?:为|：|:)?", "", indicators).strip()
    return f"{index}、{name}：{ensure_sentence(description)}拟定技术指标为{ensure_sentence(indicators)}"


def format_item(item: dict, field: str, max_body_chars: int) -> tuple[str, int]:
    rd_id = require_string(item, "rd_id", "item").upper()
    technologies = item.get("core_technologies")
    innovations = item.get("innovations")
    if not isinstance(technologies, list) or len(technologies) != 2:
        raise ValueError(f"{rd_id}.core_technologies必须且只能有2条")
    if not isinstance(innovations, list) or len(innovations) != 2:
        raise ValueError(f"{rd_id}.innovations必须且只能有2条")
    if not all(isinstance(value, str) and value.strip() for value in innovations):
        raise ValueError(f"{rd_id}.innovations必须为2条非空字符串")
    lines = [
        f"所属技术领域：{field}。",
        "核心技术：",
        format_technology(1, technologies[0], rd_id),
        format_technology(2, technologies[1], rd_id),
        "创新点：",
        f"1、{ensure_sentence(innovations[0])}",
        f"2、{ensure_sentence(innovations[1])}{VALIDATION_SENTENCE}",
    ]
    body_length = len("".join(lines[index] for index in (2, 3, 5, 6)))
    if body_length > max_body_chars:
        raise ValueError(f"{rd_id}核心技术与创新点合计{body_length}字，超过{max_body_chars}字上限")
    return "\n".join(lines), body_length


def format_stage_results(item: dict, max_body_chars: int) -> tuple[str | None, int]:
    rd_id = require_string(item, "rd_id", "item").upper()
    results = item.get("stage_results")
    if results is None:
        return None, 0
    if not isinstance(results, list) or len(results) != 4:
        raise ValueError(f"{rd_id}.stage_results必须且只能有4条")
    if not all(isinstance(value, str) and value.strip() for value in results):
        raise ValueError(f"{rd_id}.stage_results必须为4条非空字符串")
    lines = [f"{index}、{ensure_sentence(str(value))}" for index, value in enumerate(results, 1)]
    body_length = len("".join(lines))
    if body_length > max_body_chars:
        raise ValueError(f"{rd_id}阶段性成果合计{body_length}字，超过{max_body_chars}字上限")
    return "\n".join(lines), body_length


def set_simsun_xiaosi(run: etree._Element) -> None:
    rpr = run.find(W + "rPr")
    if rpr is None:
        rpr = etree.Element(W + "rPr")
        run.insert(0, rpr)
    fonts = rpr.find(W + "rFonts")
    if fonts is None:
        fonts = etree.Element(W + "rFonts")
        rpr.insert(0, fonts)
    for key in ("ascii", "hAnsi", "eastAsia", "cs"):
        fonts.set(W + key, "宋体")
    for key in ("sz", "szCs"):
        node = rpr.find(W + key)
        if node is None:
            node = etree.SubElement(rpr, W + key)
        node.set(W + "val", "24")


def replace_cell_content(cell: etree._Element, value: str) -> None:
    paragraphs = cell.xpath("./w:p", namespaces=NS)
    if not paragraphs:
        paragraph = etree.SubElement(cell, W + "p")
    else:
        paragraph = paragraphs[0]
    runs = paragraph.xpath("./w:r", namespaces=NS)
    run = runs[0] if runs else etree.SubElement(paragraph, W + "r")
    for child in list(run):
        if child.tag != W + "rPr":
            run.remove(child)
    set_simsun_xiaosi(run)
    lines = value.split("\n")
    for index, line in enumerate(lines):
        text = etree.SubElement(run, W + "t")
        text.text = line
        if index < len(lines) - 1:
            etree.SubElement(run, W + "br")
    for other_run in cell.xpath(".//w:r", namespaces=NS):
        if other_run is run:
            continue
        for child in list(other_run):
            if child.tag != W + "rPr":
                other_run.remove(child)
    for other_paragraph in paragraphs[1:]:
        for other_run in other_paragraph.xpath(".//w:r", namespaces=NS):
            for child in list(other_run):
                if child.tag != W + "rPr":
                    other_run.remove(child)


def verify_written_targets(root: etree._Element, expected: dict[str, dict[str, object]]) -> None:
    actual = collect_rd_targets(root, require_field=False)
    for rd_id, record in expected.items():
        target = actual.get(rd_id)
        if target is None:
            raise ValueError(f"写入后未找到目标RD表：{rd_id}")
        for label, value in record.get("basic_fields", {}).items():
            if xml_cell_text(target["basic_cells"][label]).strip() != value:
                raise ValueError(f"{rd_id}的{label}写入后置校验失败")
        core_text = xml_cell_text(target["core_cell"]).strip()
        if core_text != str(record["core_value"]):
            raise ValueError(f"{rd_id}核心技术及创新点写入后置校验失败")
        result_value = record.get("result_value")
        if result_value is not None:
            result_text = xml_cell_text(target["result_cell"]).strip()
            if result_text != str(result_value):
                raise ValueError(f"{rd_id}阶段性成果写入后置校验失败")


def xml_cell_text(cell: etree._Element) -> str:
    paragraphs: list[str] = []
    for paragraph in cell.xpath("./w:p", namespaces=NS):
        parts: list[str] = []
        for node in paragraph.iter():
            if node.tag == W + "t":
                parts.append(node.text or "")
            elif node.tag == W + "br":
                parts.append("\n")
            elif node.tag == W + "tab":
                parts.append("\t")
        paragraphs.append("".join(parts))
    return "\n".join(paragraphs)


def prepare_basic_fields(item: dict, target: dict[str, object], rd_id: str) -> dict[str, str]:
    fields = item.get("basic_fields", {})
    if not isinstance(fields, dict):
        raise ValueError(f"{rd_id}.basic_fields必须为对象")
    result: dict[str, str] = {}
    for label in fields:
        if label not in BASIC_LABELS or label not in target["basic_cells"]:
            raise ValueError(f"{rd_id}不支持或未找到基本字段：{label}")
        value = require_string(fields, label, f"{rd_id}.basic_fields")
        if label == "起止时间":
            match = re.fullmatch(r"(\d{4})\.(\d{1,2})\.(\d{1,2})\s*-\s*(\d{4})\.(\d{1,2})\.(\d{1,2})", value)
            if not match:
                raise ValueError(f"{rd_id}起止时间须为YYYY.MM.DD-YYYY.MM.DD")
            parts = [int(part) for part in match.groups()]
            start, end = datetime(*parts[:3]), datetime(*parts[3:])
            if start > end:
                raise ValueError(f"{rd_id}起止时间倒置")
            value = f"{start:%Y.%m.%d}-{end:%Y.%m.%d}"
        if label == "目的及组织实施方式" and len(value) > 400:
            raise ValueError(f"{rd_id}目的及组织实施方式超过400字上限")
        result[label] = value
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="按高企格式批量回填RD核心技术及创新点，并校准企业能力边界。")
    parser.add_argument("input", type=Path, help="输入DOCX")
    parser.add_argument("spec", type=Path, help="结构化JSON")
    parser.add_argument("output", type=Path, help="输出DOCX，不得与输入相同")
    parser.add_argument("--report", type=Path, help="JSON审计报告；默认输出DOCX同名.audit.json")
    parser.add_argument("--max-body-chars", type=int, default=400)
    parser.add_argument("--overwrite", action="store_true", help="允许覆盖已有输出；原文件先保存为时间戳备份")
    return parser.parse_args()


def unique_recovery_path(path: Path, marker: str) -> Path:
    """Return an unused sibling path without deleting or overwriting any file."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    candidate = path.with_name(path.name + f".{marker}-{timestamp}")
    suffix = 1
    while candidate.exists():
        candidate = path.with_name(path.name + f".{marker}-{timestamp}-{suffix}")
        suffix += 1
    return candidate


def main() -> None:
    args = parse_args()
    input_path = args.input.resolve()
    spec_path = args.spec.resolve()
    output_path = args.output.resolve()
    if input_path == output_path:
        raise SystemExit("输出文件不得与输入文件相同")
    if not input_path.is_file() or not spec_path.is_file():
        raise SystemExit("输入DOCX或JSON不存在")
    if args.max_body_chars < 1 or args.max_body_chars > 400:
        raise SystemExit("--max-body-chars必须在1至400之间")
    if output_path.exists() and not args.overwrite:
        raise SystemExit(f"输出文件已存在；如需覆盖请增加 --overwrite：{output_path}")

    try:
        data = json.loads(spec_path.read_text(encoding="utf-8"))
        if data.get("schema_version") != 1:
            raise ValueError("schema_version必须为1")
        profile = validate_profile(data)
        items = data.get("items")
        if not isinstance(items, list) or not items:
            raise ValueError("items必须为非空数组")

        with zipfile.ZipFile(input_path, "r") as source_zip:
            root = etree.fromstring(source_zip.read("word/document.xml"))
            targets = collect_rd_targets(root, require_field=False)
            seen: set[str] = set()
            formatted: dict[str, dict[str, object]] = {}
            all_text = []
            for raw_item in items:
                if not isinstance(raw_item, dict):
                    raise ValueError("items中的每一项必须为对象")
                rd_id = require_string(raw_item, "rd_id", "item").upper()
                if rd_id in seen:
                    raise ValueError(f"JSON存在重复编号：{rd_id}")
                if rd_id not in targets:
                    raise ValueError(f"文档中未找到目标RD表：{rd_id}")
                seen.add(rd_id)
                target = targets[rd_id]
                basic_fields = prepare_basic_fields(raw_item, target, rd_id)
                field = basic_fields.get("技术领域", str(target["field"]))
                if field != PENDING_FIELD and (not field or "—" not in field):
                    raise ValueError(f"{rd_id}表头未填写完整四级领域：{field!r}")
                core_value, body_length = format_item(raw_item, field, args.max_body_chars)
                result_value, result_length = format_stage_results(raw_item, args.max_body_chars)
                formatted[rd_id] = {
                    "field": field,
                    "body_length": body_length,
                    "core_value": core_value,
                    "result_value": result_value,
                    "result_length": result_length,
                    "basic_fields": basic_fields,
                }
                all_text.append(core_value)

            result_modes = {record["result_value"] is not None for record in formatted.values()}
            if len(result_modes) > 1:
                raise ValueError("同一批次的RD必须全部提供stage_results，或全部不提供")

            verified = set(profile.get("verified_advanced_terms", []))
            found = sorted(term for term in ADVANCED_TERMS if term in "\n".join(all_text))
            unsupported = sorted(set(found) - verified)
            if unsupported:
                raise ValueError(
                    "正文包含缺少企业能力证据的高阶技术词："
                    + "、".join(unsupported)
                    + "；请补充证据并列入verified_advanced_terms，或改写为企业实际技术"
                )

            for rd_id, record in formatted.items():
                # 同一物理表内按标签定位，避免合并单元格展开和RD编号延续到后续非RD表。
                for label, value in record["basic_fields"].items():
                    replace_cell_content(targets[rd_id]["basic_cells"][label], value)
                replace_cell_content(targets[rd_id]["core_cell"], str(record["core_value"]))
                if record["result_value"] is not None:
                    replace_cell_content(targets[rd_id]["result_cell"], str(record["result_value"]))
            verify_written_targets(root, formatted)
            new_xml = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            backup_path = None
            if output_path.exists():
                backup_path = unique_recovery_path(output_path, "backup")
                shutil.move(output_path, backup_path)
            with tempfile.NamedTemporaryFile(dir=output_path.parent, suffix=".docx", delete=False) as handle:
                temporary_path = Path(handle.name)
            try:
                with zipfile.ZipFile(temporary_path, "w") as output_zip:
                    for member in source_zip.infolist():
                        payload = new_xml if member.filename == "word/document.xml" else source_zip.read(member.filename)
                        output_zip.writestr(copy.deepcopy(member), payload)
                temporary_path.replace(output_path)
                with zipfile.ZipFile(output_path, "r") as written_zip:
                    written_root = etree.fromstring(written_zip.read("word/document.xml"))
                verify_written_targets(written_root, formatted)
            except Exception:
                if temporary_path.exists():
                    failed_path = unique_recovery_path(output_path, "failed-write")
                    shutil.move(temporary_path, failed_path)
                elif output_path.exists():
                    failed_path = unique_recovery_path(output_path, "failed-output")
                    shutil.move(output_path, failed_path)
                if backup_path and backup_path.exists():
                    shutil.move(backup_path, output_path)
                raise

        report_path = args.report.resolve() if args.report else output_path.with_suffix(output_path.suffix + ".audit.json")
        report = {
            "schema_version": 1,
            "status": "draft" if any(
                record["field"] == PENDING_FIELD or PENDING_INDICATOR in record["core_value"]
                for record in formatted.values()
            ) else "pass",
            "input": str(input_path),
            "spec": str(spec_path),
            "output": str(output_path),
            "backup": str(backup_path) if backup_path else None,
            "enterprise": {
                "name": profile["name"],
                "scale_summary": profile["scale_summary"],
                "main_business": profile["main_business"],
                "scale_evidence_count": len(profile["scale_evidence"]),
                "patent_summary": profile["patent_summary"],
                "patent_evidence_count": len(profile["patent_evidence"]),
            },
            "advanced_terms_found": found,
            "advanced_terms_verified": sorted(verified),
            "rd_count": len(formatted),
            "rd": {
                rd_id: {
                    "field": record["field"],
                    "body_length": record["body_length"],
                    "core_technology_count": 2,
                    "innovation_count": 2,
                    "stage_result_count": 4 if record["result_value"] is not None else 0,
                    "stage_result_length": record["result_length"],
                    "basic_fields": record["basic_fields"],
                    "pending_field": record["field"] == PENDING_FIELD,
                    "pending_indicators": str(record["core_value"]).count(PENDING_INDICATOR),
                }
                for rd_id, record in formatted.items()
            },
            "format": "所属技术领域 + 2条具名核心技术 + 2条创新点",
            "font": "宋体小四",
            "field_source": "each RD header",
            "indicator_status": "draft targets unless source-backed actual values are supplied outside this formatter",
            "postcondition_verified": True,
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
    except (ValueError, json.JSONDecodeError, zipfile.BadZipFile, etree.XMLSyntaxError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
