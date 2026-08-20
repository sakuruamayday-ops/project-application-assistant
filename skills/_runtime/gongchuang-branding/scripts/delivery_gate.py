#!/usr/bin/env python3
"""Portable delivery gate for the shared Gongchuang branding runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import fitz

from brand_config import public_identity


RUNTIME_ROOT = Path(__file__).resolve().parent.parent
ASSET_DIR = RUNTIME_ROOT / "assets"
WATERMARK_NAME = "Gongchuang Institute Centered Watermark v4"
XLSX_MARKER = "_GONGCHUANG_INSTITUTE_UNIFORM_WATERMARK_V4"


class GateFailure(RuntimeError):
    pass


def _asset_alpha_hashes() -> set[str]:
    hashes: set[str] = set()
    assets = sorted(ASSET_DIR.glob("brand-*.png"))
    if not assets:
        raise GateFailure(f"品牌资产缺失：{ASSET_DIR}")
    for path in assets:
        pixmap = fitz.Pixmap(str(path))
        if pixmap.alpha:
            alpha = bytes(pixmap.samples[pixmap.n - 1 :: pixmap.n])
            hashes.add(hashlib.sha256(alpha).hexdigest())
    if not hashes:
        raise GateFailure("品牌资产未提供可验证的透明度通道")
    return hashes


def pdf_brand_watermark_rects(document: fitz.Document, page: fitz.Page) -> list[fitz.Rect]:
    """Return actual placements without recounting shared image xrefs."""
    alpha_hashes = _asset_alpha_hashes()
    brand_xrefs: set[int] = set()
    for image in page.get_images(full=True):
        xref, soft_mask = int(image[0]), int(image[1])
        if xref in brand_xrefs or not soft_mask:
            continue
        alpha = fitz.Pixmap(document, soft_mask)
        if hashlib.sha256(alpha.samples).hexdigest() in alpha_hashes:
            brand_xrefs.add(xref)
    marks: list[fitz.Rect] = []
    for xref in sorted(brand_xrefs):
        marks.extend(fitz.Rect(rect) for rect in page.get_image_rects(xref))
    return marks


def validate_pdf(
    path: str | Path,
    *,
    expected_pages: int | None = None,
    expected_author: str | None = None,
    expected_title_contains: str | None = None,
) -> dict[str, Any]:
    pdf_path = Path(path)
    if not pdf_path.is_file():
        raise FileNotFoundError(pdf_path)
    document = fitz.open(pdf_path)
    try:
        if not document.page_count:
            raise GateFailure("PDF没有页面")
        if expected_pages is not None and document.page_count != expected_pages:
            raise GateFailure(f"PDF页数为{document.page_count}，要求为{expected_pages}")
        metadata = document.metadata or {}
        if expected_author and metadata.get("author") != expected_author:
            raise GateFailure(f"PDF作者元数据为{metadata.get('author')!r}，要求为{expected_author!r}")
        if expected_title_contains and expected_title_contains not in (metadata.get("title") or ""):
            raise GateFailure(f"PDF标题元数据未包含{expected_title_contains!r}")

        sizes: list[tuple[float, float]] = []
        page_audit: list[dict[str, Any]] = []
        for page_number, page in enumerate(document, start=1):
            marks = pdf_brand_watermark_rects(document, page)
            if len(marks) != 1:
                raise GateFailure(f"PDF第{page_number}页品牌水印数量为{len(marks)}，要求为1")
            mark = marks[0]
            if abs((mark.x0 + mark.x1) / 2 - page.rect.width / 2) > 0.75:
                raise GateFailure(f"PDF第{page_number}页水印未水平居中")
            if abs((mark.y0 + mark.y1) / 2 - page.rect.height / 2) > 0.75:
                raise GateFailure(f"PDF第{page_number}页水印未垂直居中")
            size = (round(mark.width, 3), round(mark.height, 3))
            sizes.append(size)
            page_audit.append({"page": page_number, "watermarks": 1, "size": list(size), "centered": True})
        base_width, base_height = sizes[0]
        for page_number, (width, height) in enumerate(sizes[1:], start=2):
            if abs(width - base_width) > 0.25 or abs(height - base_height) > 0.25:
                raise GateFailure(f"PDF第{page_number}页水印尺寸为{width}×{height}，基准为{base_width}×{base_height}")
        return {
            "status": "passed",
            "path": str(pdf_path),
            "format": "pdf",
            "pages": document.page_count,
            "watermarks": len(sizes),
            "watermark_size": list(sizes[0]),
            "metadata": {
                "title": metadata.get("title", ""),
                "author": metadata.get("author", ""),
                "producer": metadata.get("producer", ""),
            },
            "page_audit": page_audit,
        }
    finally:
        document.close()


def validate_docx(path: str | Path) -> dict[str, Any]:
    from xml.etree import ElementTree

    artifact = Path(path)
    namespaces = {
        "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
        "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    }
    header_parts = 0
    marks = 0
    with ZipFile(artifact) as package:
        for name in package.namelist():
            if not name.startswith("word/header") or not name.endswith(".xml"):
                continue
            header_parts += 1
            root = ElementTree.fromstring(package.read(name))
            text = "".join(node.text or "" for node in root.findall(".//w:t", namespaces))
            if public_identity()["document_header"] not in text:
                raise GateFailure(f"Word页眉{name}缺少共创研究院标识")
            current = [node for node in root.findall(".//wp:docPr", namespaces) if node.get("name") == WATERMARK_NAME]
            if len(current) != 1:
                raise GateFailure(f"Word页眉{name}的品牌水印数量为{len(current)}，要求为1")
            marks += 1
    if not header_parts:
        raise GateFailure("Word未检测到页眉")
    return {"status": "passed", "path": str(artifact), "format": "docx", "header_parts": header_parts, "watermarks": marks}


def validate_xlsx(path: str | Path) -> dict[str, Any]:
    from openpyxl import load_workbook

    artifact = Path(path)
    workbook = load_workbook(artifact, keep_vba=artifact.suffix.lower() == ".xlsm")
    if XLSX_MARKER not in workbook.defined_names:
        raise GateFailure("Excel缺少统一尺寸水印标记")
    visible = [sheet for sheet in workbook.worksheets if sheet.sheet_state == "visible"]
    if not visible:
        raise GateFailure("Excel没有可见工作表")
    for sheet in visible:
        if len(sheet._images) != 1:
            raise GateFailure(f"Excel工作表{sheet.title}的品牌水印数量为{len(sheet._images)}，要求为1")
        if public_identity()["document_header"] not in (sheet.oddHeader.right.text or ""):
            raise GateFailure(f"Excel工作表{sheet.title}缺少共创研究院页眉")
    return {"status": "passed", "path": str(artifact), "format": artifact.suffix.lower().lstrip("."), "worksheets": len(visible)}


def validate_html(path: str | Path) -> dict[str, Any]:
    artifact = Path(path)
    source = artifact.read_text(encoding="utf-8")
    if 'id="gongchuang-public-brand-style"' not in source:
        raise GateFailure("HTML缺少共创研究院品牌样式")
    if 'class="gongchuang-document-header"' not in source or public_identity()["document_header"] not in source:
        raise GateFailure("HTML缺少共创研究院页眉")
    has_cover = bool(re.search(r'(?:class|id)\s*=\s*["\'][^"\']*(?:cover|title-page|封面)[^"\']*["\']', source, re.I))
    if has_cover and 'class="gongchuang-cover-signature"' not in source:
        raise GateFailure("HTML存在封面但缺少共创研究院封面署名")
    return {"status": "passed", "path": str(artifact), "format": "html", "cover": has_cover}


def validate_artifact(
    path: str | Path,
    *,
    check_stamp: bool = True,
    expected_pages: int | None = None,
    expected_author: str | None = None,
    expected_title_contains: str | None = None,
) -> dict[str, Any]:
    del check_stamp
    artifact = Path(path)
    suffix = artifact.suffix.lower()
    if suffix == ".pdf":
        return validate_pdf(
            artifact,
            expected_pages=expected_pages,
            expected_author=expected_author,
            expected_title_contains=expected_title_contains,
        )
    if suffix == ".docx":
        return validate_docx(artifact)
    if suffix in {".xlsx", ".xlsm"}:
        return validate_xlsx(artifact)
    if suffix in {".html", ".htm"}:
        return validate_html(artifact)
    raise GateFailure(f"便携品牌运行时不支持该格式：{suffix}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--expected-pages", type=int)
    parser.add_argument("--expected-author")
    parser.add_argument("--expected-title-contains")
    parser.add_argument("--audit-json", type=Path)
    args = parser.parse_args()
    try:
        result = validate_artifact(
            args.artifact,
            expected_pages=args.expected_pages,
            expected_author=args.expected_author,
            expected_title_contains=args.expected_title_contains,
        )
    except Exception as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    if args.audit_json:
        args.audit_json.parent.mkdir(parents=True, exist_ok=True)
        args.audit_json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
