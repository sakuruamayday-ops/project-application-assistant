#!/usr/bin/env python3
"""Extract bounded text from a signed workspace document without network access."""

from __future__ import annotations

import argparse
import json
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


def workbook_sheet_names(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    except KeyError:
        return []
    return [node.attrib.get("name", "工作表") for node in root.iter() if local_name(node.tag) == "sheet"]


def cell_text(cell: ElementTree.Element, shared: list[str]) -> str:
    kind = cell.attrib.get("t")
    inline = "".join(node.text or "" for node in cell.iter() if local_name(node.tag) == "t")
    if inline:
        return inline
    value = next((node.text or "" for node in cell if local_name(node.tag) == "v"), "")
    if kind == "s" and value.isdigit():
        index = int(value)
        return shared[index] if index < len(shared) else value
    return value


def extract_xlsx(path: Path) -> dict[str, object]:
    with safe_archive(path) as archive:
        worksheet_paths = sorted(
            name for name in archive.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)
        )
        if not worksheet_paths:
            raise ValueError("XLSX 缺少工作表")
        names = workbook_sheet_names(archive)
        shared = shared_strings(archive)
        parts: list[str] = []
        for index, worksheet_path in enumerate(worksheet_paths):
            parts.append(f"## {names[index] if index < len(names) else f'工作表{index + 1}'}\n")
            root = ElementTree.fromstring(archive.read(worksheet_path))
            for row in (node for node in root.iter() if local_name(node.tag) == "row"):
                values = [cell_text(cell, shared) for cell in row if local_name(cell.tag) == "c"]
                parts.append("\t".join(values).rstrip() + "\n")
    text, truncated = bounded_join(parts)
    return {"kind": "xlsx", "status": "extracted", "sheets": len(worksheet_paths), "text": text, "truncated": truncated}


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
    handlers = {".docx": extract_docx, ".xlsx": extract_xlsx, ".pdf": extract_pdf, ".txt": extract_txt}
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
