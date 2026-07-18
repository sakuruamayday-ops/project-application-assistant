#!/usr/bin/env python3
"""Validate enterprise panorama PDF output using bundled relative assets."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from typing import Any

import fitz


SKILL_ROOT = Path(__file__).resolve().parent.parent
ASSET_DIR = SKILL_ROOT / "assets"


class ValidationError(RuntimeError):
    pass


def watermark_alpha_hashes() -> set[str]:
    hashes: set[str] = set()
    for path in ASSET_DIR.glob("brand-*.png"):
        pixmap = fitz.Pixmap(str(path))
        if pixmap.alpha:
            hashes.add(hashlib.sha256(bytes(pixmap.samples[pixmap.n - 1 :: pixmap.n])).hexdigest())
    return hashes


def validate_pdf(path: str | Path, *, require_watermark: bool = False) -> dict[str, Any]:
    pdf_path = Path(path)
    if not pdf_path.is_file():
        raise FileNotFoundError(pdf_path)
    document = fitz.open(pdf_path)
    if document.page_count == 0:
        document.close()
        raise ValidationError("PDF没有页面")

    alpha_hashes = watermark_alpha_hashes()
    watermark_count = 0
    for page_number, page in enumerate(document, start=1):
        page_marks = []
        for image in page.get_images(full=True):
            xref, soft_mask = image[0], image[1]
            if not soft_mask:
                continue
            alpha = fitz.Pixmap(document, soft_mask)
            if hashlib.sha256(alpha.samples).hexdigest() in alpha_hashes:
                page_marks.extend(page.get_image_rects(xref))
        if require_watermark and len(page_marks) != 1:
            document.close()
            raise ValidationError(f"PDF第{page_number}页品牌水印数量为{len(page_marks)}，要求为1")
        for mark in page_marks:
            if abs((mark.x0 + mark.x1) / 2 - page.rect.width / 2) > 0.75:
                document.close()
                raise ValidationError(f"PDF第{page_number}页水印未水平居中")
            if abs((mark.y0 + mark.y1) / 2 - page.rect.height / 2) > 0.75:
                document.close()
                raise ValidationError(f"PDF第{page_number}页水印未垂直居中")
        watermark_count += len(page_marks)

    result = {
        "status": "passed",
        "path": str(pdf_path),
        "pages": document.page_count,
        "watermarks": watermark_count,
    }
    document.close()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--require-watermark", action="store_true")
    args = parser.parse_args()
    print(validate_pdf(args.pdf, require_watermark=args.require_watermark))


if __name__ == "__main__":
    main()
