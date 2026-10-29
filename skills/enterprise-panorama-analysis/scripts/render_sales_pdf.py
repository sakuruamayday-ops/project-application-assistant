#!/usr/bin/env python3
"""Render the owner-approved unwatermarked white-background sales report."""

import argparse
import sys
import re
import unicodedata
from pathlib import Path

if __name__ == "__main__":
    # Fixed CLI PDF work uses the classic engine; preserve any caller-loaded ML modules.
    sys.modules.setdefault("pymupdf.layout", None)
    sys.modules.setdefault("pymupdf4llm", None)

import pymupdf as fitz

from render_html_report import render_pdf_bytes


AUTHOR = "共创知识产权"
VISIBLE_BYLINE = re.compile(r"报告(?:人\s*[:：]\s*共创知识产权|机构\s*[:：]\s*共创知识产权(?=\s|$))")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--title", required=True)
    args = parser.parse_args()

    if not args.html.is_file():
        raise FileNotFoundError(args.html)
    raw_pdf = render_pdf_bytes(args.html)
    document = fitz.open(stream=raw_pdf, filetype="pdf")
    visible_text = unicodedata.normalize("NFKC", document[0].get_text("text"))
    if not VISIBLE_BYLINE.search(visible_text):
        document.close()
        raise ValueError("版本A必须在首页显示：报告机构：共创知识产权或报告人：共创知识产权")
    metadata = document.metadata or {}
    metadata.update({
        "title": args.title,
        "author": AUTHOR,
        "creator": AUTHOR,
        "producer": "GCIP Sales Report Renderer",
    })
    document.set_metadata(metadata)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    document.save(args.out, garbage=4, deflate=True)
    document.close()
    print(f"WROTE {args.out.resolve()} author={AUTHOR} watermark=disabled-by-owner-profile")


if __name__ == "__main__":
    main()
