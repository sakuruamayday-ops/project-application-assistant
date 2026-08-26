#!/usr/bin/env python3
"""Extract bounded text from a signed workspace document without network access."""

from __future__ import annotations

import argparse
import json
import posixpath
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree


MAX_OUTPUT_CHARACTERS = 500_000
MAX_ARCHIVE_MEMBER_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_TOTAL_BYTES = 256 * 1024 * 1024
MAX_PDF_PAGES = 1_000


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def bounded_join(parts: list[str]) -> tuple[str, bool]:
    text = "".join(parts)
    compact = re.sub(r" {2,}", " ", text)
    compact = re.sub(r"\n{3,}", "\n\n", compact).strip()
    if len(compact) <= MAX_OUTPUT_CHARACTERS:
        return compact, False
    return compact[:MAX_OUTPUT_CHARACTERS].rstrip(), True


def safe_archive(path: Path) -> zipfile.ZipFile:
    archive = zipfile.ZipFile(path)
    total = 0
    for info in archive.infolist():
        if info.is_dir():
            continue
        if info.file_size < 0 or info.file_size > MAX_ARCHIVE_MEMBER_BYTES:
            archive.close()
            raise ValueError("文档内部单个文件过大")
        total += info.file_size
        if total > MAX_ARCHIVE_TOTAL_BYTES:
            archive.close()
            raise ValueError("文档解压后内容过大")
    return archive


def xml_text(data: bytes, paragraph_tags: set[str]) -> str:
    root = ElementTree.fromstring(data)
    parts: list[str] = []
    for element in root.iter():
        tag = local_name(element.tag)
        if tag == "t" and element.text:
            parts.append(element.text)
        elif tag in paragraph_tags:
            parts.append("\n")
        elif tag == "tab":
            parts.append("\t")
        elif tag == "br":
            parts.append("\n")
    return "".join(parts)


def extract_docx(path: Path) -> dict[str, object]:
    with safe_archive(path) as archive:
        names = set(archive.namelist())
        if "word/document.xml" not in names:
            raise ValueError("DOCX 缺少正文结构")
        ordered = ["word/document.xml"]
        ordered.extend(sorted(name for name in names if re.fullmatch(r"word/(?:header|footer)\d+\.xml", name)))
        parts = [xml_text(archive.read(name), {"p", "tr"}) for name in ordered]
    text, truncated = bounded_join([part + "\n" for part in parts])
    return {"kind": "docx", "status": "extracted", "text": text, "truncated": truncated}


def shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        data = archive.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ElementTree.fromstring(data)
    return ["".join(node.text or "" for node in item.iter() if local_name(node.tag) == "t") for item in root]


def workbook_sheets(archive: zipfile.ZipFile) -> list[tuple[str, str]]:
    try:
        workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        relationships = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    except KeyError:
        return []
    targets = {
        relation.attrib.get("Id", ""): relation.attrib.get("Target", "")
        for relation in relationships
        if local_name(relation.tag) == "Relationship"
    }
    sheets: list[tuple[str, str]] = []
    for index, node in enumerate(item for item in workbook.iter() if local_name(item.tag) == "sheet"):
        relationship_id = next(
            (value for key, value in node.attrib.items() if local_name(key) == "id"),
            "",
        )
        target = targets.get(relationship_id, "")
        if target.startswith("/"):
            worksheet_path = posixpath.normpath(target.lstrip("/"))
        else:
            worksheet_path = posixpath.normpath(posixpath.join("xl", target))
        if not worksheet_path.startswith("xl/worksheets/") or worksheet_path not in archive.namelist():
            raise ValueError("XLSX 工作表关系无效")
        sheets.append((node.attrib.get("name", f"工作表{index + 1}"), worksheet_path))
    return sheets


def workbook_uses_1904_epoch(archive: zipfile.ZipFile) -> bool:
    root = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    properties = next((node for node in root.iter() if local_name(node.tag) == "workbookPr"), None)
    return properties is not None and properties.attrib.get("date1904", "").lower() in {"1", "true"}


def workbook_number_formats(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ElementTree.fromstring(archive.read("xl/styles.xml"))
    except KeyError:
        return []
    from openpyxl.styles.numbers import BUILTIN_FORMATS

    custom = {
        int(node.attrib["numFmtId"]): node.attrib.get("formatCode", "General")
        for node in root.iter()
        if local_name(node.tag) == "numFmt" and node.attrib.get("numFmtId", "").isdigit()
    }
    cell_formats = next((node for node in root if local_name(node.tag) == "cellXfs"), None)
    if cell_formats is None:
        return []
    return [
        custom.get(int(node.attrib.get("numFmtId", "0")), BUILTIN_FORMATS.get(int(node.attrib.get("numFmtId", "0")), "General"))
        for node in cell_formats
        if local_name(node.tag) == "xf"
    ]


def xlsx_number_text(value_text: str, format_code: str, uses_1904_epoch: bool) -> str:
    value = float(value_text)
    if "%" in format_code:
        match = re.search(r"\.([0#]+)[^%]*%", format_code)
        places = len(match.group(1)) if match else 0
        return f"{value * 100:.{places}f}%"
    from openpyxl.styles.numbers import is_date_format
    from openpyxl.utils.datetime import CALENDAR_MAC_1904, CALENDAR_WINDOWS_1900, from_excel

    if is_date_format(format_code):
        epoch = CALENDAR_MAC_1904 if uses_1904_epoch else CALENDAR_WINDOWS_1900
        converted = from_excel(value, epoch=epoch)
        return converted.isoformat(sep=" ", timespec="seconds")
    return str(int(value)) if value.is_integer() else format(value, ".15g")


def cell_text(
    cell: ElementTree.Element,
    shared: list[str],
    number_formats: list[str],
    uses_1904_epoch: bool,
) -> str:
    kind = cell.attrib.get("t")
    inline = "".join(node.text or "" for node in cell.iter() if local_name(node.tag) == "t")
    if inline:
        return inline
    value = next((node.text or "" for node in cell if local_name(node.tag) == "v"), "")
    if kind == "s" and value.isdigit():
        index = int(value)
        return shared[index] if index < len(shared) else value
    if kind == "b":
        return "TRUE" if value == "1" else "FALSE"
    if kind in {"e", "str"} or value == "":
        return value
    style_index = int(cell.attrib.get("s", "0")) if cell.attrib.get("s", "0").isdigit() else 0
    format_code = number_formats[style_index] if style_index < len(number_formats) else "General"
    try:
        return xlsx_number_text(value, format_code, uses_1904_epoch)
    except (TypeError, ValueError, OverflowError):
        return value


def xlsx_column_index(reference: str, fallback: int) -> int:
    match = re.fullmatch(r"([A-Z]{1,3})\d+", reference.upper())
    if match is None:
        return fallback
    index = 0
    for letter in match.group(1):
        index = index * 26 + ord(letter) - ord("A") + 1
    if index > 16_384:
        raise ValueError("XLSX 单元格列号超出范围")
    return index


def extract_xlsx(path: Path) -> dict[str, object]:
    with safe_archive(path) as archive:
        worksheets = workbook_sheets(archive)
        if not worksheets:
            raise ValueError("XLSX 缺少工作表")
        shared = shared_strings(archive)
        number_formats = workbook_number_formats(archive)
        uses_1904_epoch = workbook_uses_1904_epoch(archive)
        parts: list[str] = []
        for worksheet_name, worksheet_path in worksheets:
            parts.append(f"## {worksheet_name}\n")
            root = ElementTree.fromstring(archive.read(worksheet_path))
            for row in (node for node in root.iter() if local_name(node.tag) == "row"):
                values: list[str] = []
                next_column = 1
                for cell in (item for item in row if local_name(item.tag) == "c"):
                    column = xlsx_column_index(cell.attrib.get("r", ""), next_column)
                    if column < next_column:
                        raise ValueError("XLSX 单元格顺序无效")
                    values.extend([""] * (column - next_column))
                    values.append(cell_text(cell, shared, number_formats, uses_1904_epoch))
                    next_column = column + 1
                parts.append("\t".join(values).rstrip() + "\n")
    text, truncated = bounded_join(parts)
    return {"kind": "xlsx", "status": "extracted", "sheets": len(worksheets), "text": text, "truncated": truncated}


def xls_number_text(book: object, cell: object) -> str:
    value = float(cell.value)
    format_code = ""
    try:
        xf = book.xf_list[cell.xf_index]
        format_code = book.format_map[xf.format_key].format_str
    except (AttributeError, IndexError, KeyError):
        pass
    if "%" in format_code:
        match = re.search(r"\.([0#]+)[^%]*%", format_code)
        places = len(match.group(1)) if match else 0
        return f"{value * 100:.{places}f}%"
    return str(int(value)) if value.is_integer() else format(value, ".15g")


def xls_cell_text(book: object, cell: object) -> str:
    import xlrd

    if cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
        return ""
    if cell.ctype == xlrd.XL_CELL_DATE:
        value = xlrd.xldate_as_datetime(cell.value, book.datemode)
        return value.isoformat(sep=" ", timespec="seconds")
    if cell.ctype == xlrd.XL_CELL_NUMBER:
        return xls_number_text(book, cell)
    if cell.ctype == xlrd.XL_CELL_BOOLEAN:
        return "TRUE" if cell.value else "FALSE"
    if cell.ctype == xlrd.XL_CELL_ERROR:
        return xlrd.error_text_from_code.get(cell.value, "#ERROR")
    return str(cell.value)


def extract_xls(path: Path) -> dict[str, object]:
    try:
        import xlrd
    except ImportError as error:
        raise RuntimeError("内置 XLS 解析组件不可用") from error
    workbook = xlrd.open_workbook(path, on_demand=True, formatting_info=True)
    sheet_count = workbook.nsheets
    parts: list[str] = []
    try:
        for worksheet in workbook.sheets():
            parts.append(f"## {worksheet.name}\n")
            for row_index in range(worksheet.nrows):
                values = [xls_cell_text(workbook, worksheet.cell(row_index, column)) for column in range(worksheet.ncols)]
                parts.append("\t".join(values).rstrip() + "\n")
    finally:
        workbook.release_resources()
    text, truncated = bounded_join(parts)
    return {"kind": "xls", "status": "extracted", "sheets": sheet_count, "text": text, "truncated": truncated}


def extract_pdf(path: Path) -> dict[str, object]:
    try:
        import pypdfium2 as pdfium
    except ImportError as error:
        raise RuntimeError("内置 PDF 解析组件不可用") from error
    document = pdfium.PdfDocument(str(path))
    pages = len(document)
    if pages > MAX_PDF_PAGES:
        document.close()
        raise ValueError(f"PDF 页数超过 {MAX_PDF_PAGES} 页")
    parts: list[str] = []
    has_text = False
    try:
        for index in range(pages):
            page = document[index]
            text_page = page.get_textpage()
            try:
                page_text = text_page.get_text_range()
            finally:
                text_page.close()
                page.close()
            if re.search(r"[A-Za-z0-9\u3400-\u9fff]", page_text):
                has_text = True
            parts.append(f"\n## 第 {index + 1} 页\n{page_text}\n")
    finally:
        document.close()
    text, truncated = bounded_join(parts)
    return {
        "kind": "pdf",
        "status": "extracted" if has_text else "needs_ocr",
        "pages": pages,
        "text": text if has_text else "",
        "truncated": truncated,
        "message": "未检测到可提取文本，需要使用已配置的 PaddleOCR 识别扫描页。" if not has_text else "",
    }


def extract_txt(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    text = None
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError("TXT 不是 UTF-8 或 GB18030 文本")
    text, truncated = bounded_join([text])
    return {"kind": "txt", "status": "extracted", "text": text, "truncated": truncated}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", type=Path)
    args = parser.parse_args()
    path = args.document
    handlers = {".docx": extract_docx, ".xls": extract_xls, ".xlsx": extract_xlsx, ".pdf": extract_pdf, ".txt": extract_txt}
    try:
        if not path.is_file() or path.is_symlink():
            raise ValueError("输入必须是普通文件")
        handler = handlers.get(path.suffix.lower())
        if handler is None:
            raise ValueError("不支持该文档类型")
        result = handler(path)
        result.update({"schema_version": "gongchuang-document-extraction/v1", "name": path.name})
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 0
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, ElementTree.ParseError) as error:
        print(json.dumps({
            "schema_version": "gongchuang-document-extraction/v1",
            "name": path.name,
            "status": "rejected",
            "error": str(error),
        }, ensure_ascii=False, separators=(",", ":")))
        return 2


if __name__ == "__main__":
    sys.exit(main())
