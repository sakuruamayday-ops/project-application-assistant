#!/usr/bin/env python3
"""Write clean PDF metadata without any watermark or brand overlay."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __name__ == "__main__":
    # Fixed CLI PDF work uses the classic engine; preserve any caller-loaded ML modules.
    sys.modules.setdefault("pymupdf.layout", None)
    sys.modules.setdefault("pymupdf4llm", None)

import pymupdf as fitz


def with_metadata(
    pdf_bytes: bytes,
    *,
    title: str,
    author: str,
    subject: str,
) -> tuple[bytes, int]:
    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    metadata = document.metadata or {}
    metadata.update(
        {
            "title": title,
            "author": author,
            "subject": subject,
            "creator": "manufacturing-tax-risk-analysis",
            "producer": "Portable Report Runtime",
            "keywords": "金税四期,财税风险",
        }
    )
    document.set_metadata(metadata)
    page_count = len(document)
    output = document.tobytes(garbage=3, deflate=True)
    document.close()
    return output, page_count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--audit-json", type=Path)
    parser.add_argument("--title", default="金税四期财务分析报告")
    parser.add_argument("--author", default="")
    parser.add_argument(
        "--subject",
        default="制造企业财务与税务风险内部分析",
    )
    args = parser.parse_args()
    data = sys.stdin.buffer.read()
    if not data.startswith(b"%PDF"):
        raise RuntimeError("stdin did not contain a PDF")
    clean_pdf, page_count = with_metadata(
        data,
        title=args.title,
        author=args.author,
        subject=args.subject,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(clean_pdf)
    audit = [{"page": idx + 1, "status": "clean"} for idx in range(page_count)]
    if args.audit_json:
        args.audit_json.write_text(
            json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(
        json.dumps(
            {"status": "ok", "pages": page_count, "output": str(args.output)},
            ensure_ascii=False,
        ),
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
