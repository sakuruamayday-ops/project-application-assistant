#!/usr/bin/env python3
"""Validate the readable PDF or Word artifact in an unbranded package."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def validate_artifact(path: Path, expected_pages: int | None = None) -> dict:
    if path.suffix.lower() == ".pdf":
        import pymupdf as fitz

        with fitz.open(path) as document:
            if not document.is_pdf or document.needs_pass or not document.page_count:
                raise ValueError("报告须为可读的非空 PDF")
            if expected_pages is not None and document.page_count != expected_pages:
                raise ValueError(f"PDF 实际页数为 {document.page_count}，应为 {expected_pages}")
            for number, page in enumerate(document, start=1):
                if not page.get_text().strip():
                    raise ValueError(f"PDF 第 {number} 页缺少可读正文")
            return {"format": "pdf", "pages": document.page_count}

    if path.suffix.lower() == ".docx":
        from docx import Document

        if expected_pages is not None:
            raise ValueError("--expected-pages 适用于 PDF")
        document = Document(path)
        texts = [paragraph.text for paragraph in document.paragraphs]
        texts.extend(cell.text for table in document.tables for row in table.rows for cell in row.cells)
        if not any(text.strip() for text in texts):
            raise ValueError("Word 缺少可读正文或表格内容")
        return {"format": "docx", "paragraphs": len(document.paragraphs), "tables": len(document.tables)}

    raise ValueError("报告格式须为 PDF 或 DOCX")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--expected-pages", type=int)
    parser.add_argument("--audit-json", type=Path)
    args = parser.parse_args()
    try:
        result = {"status": "passed", "path": str(args.artifact),
                  **validate_artifact(args.artifact, args.expected_pages)}
        output = json.dumps(result, ensure_ascii=False, indent=2)
        if args.audit_json:
            args.audit_json.parent.mkdir(parents=True, exist_ok=True)
            args.audit_json.write_text(output + "\n", encoding="utf-8")
    except Exception as error:
        print(json.dumps({"status": "blocked", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
