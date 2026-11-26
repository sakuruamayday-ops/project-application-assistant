#!/usr/bin/env python3
"""Render the owner-approved unwatermarked white-background standard analysis report."""

import argparse
import sys
from pathlib import Path

if __name__ == "__main__":
    # Fixed CLI PDF work uses the classic engine; preserve any caller-loaded ML modules.
    sys.modules.setdefault("pymupdf.layout", None)
    sys.modules.setdefault("pymupdf4llm", None)

import pymupdf as fitz

from render_html_report import render_pdf_bytes
from build_standard_html import render_standard_html
from outline_pdf_text import outline_pdf_text


AUTHOR = ""



def main() -> None:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--html", type=Path, help="已有 HTML 报告")
    source.add_argument("--input", type=Path, help="按标准分析版母版回填的业务 JSON")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--title", required=True)
    args = parser.parse_args()

    if args.input is not None:
        raw_pdf = render_pdf_bytes(None, contents=render_standard_html(args.input).encode("utf-8"))
    else:
        if not args.html.is_file():
            raise FileNotFoundError(args.html)
        raw_pdf = render_pdf_bytes(args.html)
    document = fitz.open(stream=raw_pdf, filetype="pdf")
    metadata = document.metadata or {}
    metadata.update({
        "title": args.title,
        "author": AUTHOR,
        "creator": AUTHOR,
        "producer": "Standard Analysis Report Renderer",
    })
    document.set_metadata(metadata)
    outline_pdf_text(document)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    document.save(args.out, garbage=4, deflate=True)
    document.close()
    print(f"WROTE {args.out.resolve()} author={AUTHOR} watermark=disabled-by-owner-profile")


if __name__ == "__main__":
    main()
