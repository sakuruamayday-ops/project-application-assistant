#!/usr/bin/env python3
"""Portable PDF delivery gate for the shared Jiaotang branding runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import fitz


RUNTIME_ROOT = Path(__file__).resolve().parent.parent
ASSET_DIR = RUNTIME_ROOT / "assets"


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

    alpha_hashes = _asset_alpha_hashes()
    document = fitz.open(pdf_path)
    try:
        if not document.page_count:
            raise GateFailure("PDF没有页面")
        if expected_pages is not None and document.page_count != expected_pages:
            raise GateFailure(
                f"PDF页数为{document.page_count}，要求为{expected_pages}"
            )

        metadata = document.metadata or {}
        if expected_author and metadata.get("author") != expected_author:
            raise GateFailure(
                f"PDF作者元数据为{metadata.get('author')!r}，要求为{expected_author!r}"
            )
        if expected_title_contains and expected_title_contains not in (
            metadata.get("title") or ""
        ):
            raise GateFailure(
                f"PDF标题元数据未包含{expected_title_contains!r}"
            )

        sizes: list[tuple[float, float]] = []
        page_audit: list[dict[str, Any]] = []
        for page_number, page in enumerate(document, start=1):
            marks: list[fitz.Rect] = []
            for image in page.get_images(full=True):
                xref, soft_mask = image[0], image[1]
                if not soft_mask:
                    continue
                alpha = fitz.Pixmap(document, soft_mask)
                if hashlib.sha256(alpha.samples).hexdigest() in alpha_hashes:
                    marks.extend(page.get_image_rects(xref))
            if len(marks) != 1:
                raise GateFailure(
                    f"PDF第{page_number}页品牌水印数量为{len(marks)}，要求为1"
                )

            mark = marks[0]
            if abs((mark.x0 + mark.x1) / 2 - page.rect.width / 2) > 0.75:
                raise GateFailure(f"PDF第{page_number}页水印未水平居中")
            if abs((mark.y0 + mark.y1) / 2 - page.rect.height / 2) > 0.75:
                raise GateFailure(f"PDF第{page_number}页水印未垂直居中")
            size = (round(mark.width, 3), round(mark.height, 3))
            sizes.append(size)
            page_audit.append(
                {
                    "page": page_number,
                    "watermarks": 1,
                    "size": list(size),
                    "centered": True,
                }
            )

        base_width, base_height = sizes[0]
        for page_number, (width, height) in enumerate(sizes[1:], start=2):
            if abs(width - base_width) > 0.25 or abs(height - base_height) > 0.25:
                raise GateFailure(
                    f"PDF第{page_number}页水印尺寸为{width}×{height}，"
                    f"基准为{base_width}×{base_height}"
                )

        return {
            "status": "passed",
            "path": str(pdf_path),
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


def validate_artifact(
    path: str | Path,
    *,
    check_stamp: bool = True,
    expected_pages: int | None = None,
    expected_author: str | None = None,
    expected_title_contains: str | None = None,
) -> dict[str, Any]:
    del check_stamp
    pdf_path = Path(path)
    if pdf_path.suffix.lower() != ".pdf":
        raise GateFailure(f"便携品牌运行时只校验PDF：{pdf_path.suffix}")
    return validate_pdf(
        pdf_path,
        expected_pages=expected_pages,
        expected_author=expected_author,
        expected_title_contains=expected_title_contains,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--expected-pages", type=int)
    parser.add_argument("--expected-author")
    parser.add_argument("--expected-title-contains")
    parser.add_argument("--audit-json", type=Path)
    args = parser.parse_args()
    try:
        result = validate_pdf(
            args.pdf,
            expected_pages=args.expected_pages,
            expected_author=args.expected_author,
            expected_title_contains=args.expected_title_contains,
        )
    except Exception as exc:
        print(
            json.dumps(
                {"status": "blocked", "error": str(exc)},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    if args.audit_json:
        args.audit_json.parent.mkdir(parents=True, exist_ok=True)
        args.audit_json.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
