#!/usr/bin/env python3
"""Validate real DOCX/PDF/XLSX/PPTX grounded-citation fixtures."""

from __future__ import annotations

import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

from docx import Document
from PIL import Image, ImageChops
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "tests" / "fixtures" / "grounded-citations" / "real"


def document_text(path: Path) -> str:
    document = Document(path)
    return "\n".join(paragraph.text for paragraph in document.paragraphs)


def pdf_text(path: Path) -> str:
    return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)


def archive_text(path: Path) -> str:
    chunks: list[str] = []
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if name.endswith((".xml", ".rels")):
                chunks.append(archive.read(name).decode("utf-8", errors="replace"))
    return "\n".join(chunks)


def ppt_slide_text(path: Path, number: int) -> str:
    with zipfile.ZipFile(path) as archive:
        raw = archive.read(f"ppt/slides/slide{number}.xml").decode("utf-8", errors="replace")
    return "".join(re.findall(r"<a:t>(.*?)</a:t>", raw))


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def visible_pixel_ratio(path: Path) -> float:
    """Return the share of pixels that differ from pure white."""
    with Image.open(path) as source:
        image = source.convert("RGB")
        difference = ImageChops.difference(image, Image.new("RGB", image.size, "white")).convert("L")
        histogram = difference.histogram()
        total = image.width * image.height
        return (total - histogram[0]) / total if total else 0.0


def has_no_missing_glyphs(text: str) -> bool:
    return not any(marker in text for marker in ("\ufffd", "\u25a1", "\u25a0"))


def main() -> int:
    report_docx = BASE / "grounded-analysis-report.docx"
    report_pdf = BASE / "render-report" / "grounded-analysis-report.pdf"
    standard_docx = BASE / "Q-JT-001-2026-grounded-standard.docx"
    source_docx = BASE / "Q-JT-001-2026-grounded-standard-source-explanation.docx"
    workbook = BASE / "xlsx" / "grounded-market-share.xlsx"
    deck = BASE / "pptx" / "grounded-citations.pptx"
    required = [report_docx, report_pdf, standard_docx, source_docx, workbook, deck]
    errors: list[str] = []
    for path in required:
        if not path.exists() or path.stat().st_size == 0:
            errors.append(f"missing-or-empty:{path.relative_to(ROOT)}")
    if errors:
        print(json.dumps({"status": "fail", "errors": errors}, ensure_ascii=False, indent=2))
        return 2

    report_word = document_text(report_docx)
    report_pdf_text = pdf_text(report_pdf)
    standard = document_text(standard_docx)
    source_memo = document_text(source_docx)
    workbook_xml = archive_text(workbook)
    deck_xml = archive_text(deck)
    rendered_pages = [
        BASE / "render-report" / "page-1.png",
        BASE / "render-standard" / "page-1.png",
        BASE / "render-standard-source" / "page-1.png",
        *(BASE / "xlsx" / f"{name}.png" for name in ("分析结果", "计算底稿", "数据来源")),
        *(BASE / "pptx" / f"slide-{number:02d}.png" for number in (1, 2, 3)),
    ]
    render_ratios = {
        str(path.relative_to(ROOT)): round(visible_pixel_ratio(path), 6)
        for path in rendered_pages
        if path.is_file()
    }

    checks = {
        "report_sources_after_conclusion": report_word.rfind("Data Sources") > report_word.find("Conclusion"),
        "report_pdf_sources_after_conclusion": report_pdf_text.rfind("Data Sources") > report_pdf_text.find("Conclusion"),
        "report_pdf_has_no_missing_glyphs": has_no_missing_glyphs(report_pdf_text),
        "report_no_internal_path": "client-dossier" not in report_word + report_pdf_text,
        "standard_preserves_normative_references": "Normative references" in standard,
        "standard_has_no_report_source_section": "Data Sources" not in standard and "数据来源" not in standard,
        "standard_has_no_evidence_markers": "[1]" not in standard and "[2]" not in standard,
        "standard_source_memo_is_separate": "Standard Source Explanation" in source_memo,
        "standard_source_memo_hides_internal_path": "knowledge/internal" not in source_memo,
        "xlsx_has_final_source_sheet": workbook_xml.find("分析结果") < workbook_xml.find("计算底稿") < workbook_xml.find("数据来源"),
        "xlsx_hides_internal_path": "client-dossier" not in workbook_xml and "knowledge/internal" not in workbook_xml,
        "pptx_has_three_slides": len(re.findall(r"ppt/slides/slide\d+\.xml", "\n".join(zipfile.ZipFile(deck).namelist()))) == 3,
        "pptx_final_slide_is_sources": "数据来源" in ppt_slide_text(deck, 3),
        "pptx_hides_internal_path": "client-dossier" not in deck_xml and "knowledge/internal" not in deck_xml,
        "all_docx_pages_rendered": all((BASE / folder / "page-1.png").exists() for folder in ("render-report", "render-standard", "render-standard-source")),
        "all_xlsx_sheets_rendered": all((BASE / "xlsx" / f"{name}.png").exists() for name in ("分析结果", "计算底稿", "数据来源")),
        "all_pptx_slides_rendered": all((BASE / "pptx" / f"slide-{number:02d}.png").exists() for number in (1, 2, 3)),
        "all_rendered_artifacts_have_visible_content": len(render_ratios) == len(rendered_pages) and all(ratio >= 0.001 for ratio in render_ratios.values()),
    }
    failures = [name for name, passed in checks.items() if not passed]
    manifest = {
        "schema_version": 1,
        "status": "pass" if not failures else "fail",
        "checks": checks,
        "files": {str(path.relative_to(ROOT)): {"sha256": sha256(path), "bytes": path.stat().st_size} for path in required},
        "render_nonwhite_ratios": render_ratios,
        "errors": failures,
    }
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
