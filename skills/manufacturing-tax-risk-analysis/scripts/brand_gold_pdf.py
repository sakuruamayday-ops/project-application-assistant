#!/usr/bin/env python3
"""Apply the portable centered gold watermark to a PDF received on stdin."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import fitz

SKILLS_ROOT = Path(__file__).resolve().parents[2]
BRANDING_SCRIPTS = SKILLS_ROOT / "_runtime" / "gongchuang-branding" / "scripts"
if not BRANDING_SCRIPTS.is_dir():
    raise RuntimeError(f"shared branding runtime missing: {BRANDING_SCRIPTS}")
sys.path.insert(0, str(BRANDING_SCRIPTS))
from pdf_two_pass import brand_pdf_bytes  # noqa: E402


def with_metadata(
    pdf_bytes: bytes,
    *,
    title: str,
    author: str,
    subject: str,
) -> bytes:
    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    metadata = document.metadata or {}
    metadata.update(
        {
            "title": title,
            "author": author,
            "subject": subject,
            "creator": "manufacturing-tax-risk-analysis",
            "producer": "Gongchuang Research Institute Portable Report Runtime",
            "keywords": "金税四期,财税风险,共创知识产权",
        }
    )
    document.set_metadata(metadata)
    output = document.tobytes(garbage=3, deflate=True)
    document.close()
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--audit-json", type=Path)
    parser.add_argument("--title", default="金税四期财务分析报告")
    parser.add_argument("--author", default="共创知识产权")
    parser.add_argument(
        "--subject",
        default="制造企业财务与税务风险内部分析",
    )
    args = parser.parse_args()
    data = sys.stdin.buffer.read()
    if not data.startswith(b"%PDF"):
        raise RuntimeError("stdin did not contain a PDF")
    branded_input = with_metadata(
        data,
        title=args.title,
        author=args.author,
        subject=args.subject,
    )
    audit = brand_pdf_bytes(branded_input, args.output, variant="gold")
    if args.audit_json:
        args.audit_json.write_text(
            json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(
        json.dumps(
            {"status": "ok", "pages": len(audit), "output": str(args.output)},
            ensure_ascii=False,
        ),
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
