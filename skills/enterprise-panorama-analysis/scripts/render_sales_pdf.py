#!/usr/bin/env python3
"""Render the owner-approved unwatermarked white-background sales report."""

import argparse
from pathlib import Path

import fitz

from render_html_report import render_pdf_bytes


AUTHOR = "共创知识产权"
VISIBLE_BYLINES = ("报告人：共创知识产权", "报告人: 共创知识产权")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--title", required=True)
    args = parser.parse_args()

    if not args.html.is_file():
        raise FileNotFoundError(args.html)
    html = args.html.read_text(encoding="utf-8")
    if not any(byline in html for byline in VISIBLE_BYLINES):
        raise ValueError("版本A必须在页面中显示：报告人：共创知识产权")

    raw_pdf = render_pdf_bytes(args.html)
    document = fitz.open(stream=raw_pdf, filetype="pdf")
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
