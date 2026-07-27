#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn


def unique_cells(row):
    seen = set()
    for cell in row.cells:
        key = id(cell._tc)
        if key not in seen:
            seen.add(key)
            yield cell


def iter_paragraphs(document):
    yield from document.paragraphs
    for table in document.tables:
        for row in table.rows:
            for cell in unique_cells(row):
                yield from cell.paragraphs


def main():
    parser = argparse.ArgumentParser(description="Audit a high-tech enterprise application DOCX.")
    parser.add_argument("docx", type=Path)
    parser.add_argument("--font", default="宋体")
    parser.add_argument("--size", type=float, default=12.0)
    args = parser.parse_args()

    document = Document(args.docx)
    font_issues = []
    placeholders = []

    for paragraph in iter_paragraphs(document):
        if "XXX" in paragraph.text or "待企业核定" in paragraph.text or "拟定指标" in paragraph.text:
            placeholders.append(paragraph.text.strip())
        for run in paragraph.runs:
            if not run.text.strip():
                continue
            east_asia = None
            if run._element.rPr is not None and run._element.rPr.rFonts is not None:
                east_asia = run._element.rPr.rFonts.get(qn("w:eastAsia"))
            size = run.font.size.pt if run.font.size is not None else None
            if args.font not in {run.font.name, east_asia} or size is None or abs(size - args.size) > 0.01:
                font_issues.append(
                    {"text": run.text[:40], "font": run.font.name, "eastAsia": east_asia, "size": size}
                )

    innovation = {}
    labels = {
        "知识产权对企业竞争力的作用",
        "科技成果转化情况",
        "研究开发与技术创新组织管理情况",
        "管理与科技人员情况",
    }
    for table in document.tables:
        for row in table.rows:
            cells = list(unique_cells(row))
            if len(cells) >= 2:
                label = "".join(cells[0].text.split())
                if label in labels:
                    innovation[label] = len(cells[1].text.replace("\n", ""))

    result = {
        "file": str(args.docx),
        "tables": len(document.tables),
        "font_issue_count": len(font_issues),
        "font_issue_sample": font_issues[:20],
        "innovation_capability_lengths": innovation,
        "innovation_below_390": {k: v for k, v in innovation.items() if v < 390},
        "placeholder_count": len(placeholders),
        "placeholder_sample": placeholders[:20],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(1 if font_issues or result["innovation_below_390"] else 0)


if __name__ == "__main__":
    main()
