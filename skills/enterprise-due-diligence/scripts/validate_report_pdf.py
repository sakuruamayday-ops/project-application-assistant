#!/usr/bin/env python3
"""Validate enterprise panorama PDF output with the shared portable runtime."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

if __name__ == "__main__":
    # Fixed CLI PDF work uses the classic engine; preserve any caller-loaded ML modules.
    sys.modules.setdefault("pymupdf.layout", None)
    sys.modules.setdefault("pymupdf4llm", None)

import pymupdf as fitz

from outline_pdf_text import ValidationError, validate_page_content

def validate_pdf(path: str | Path) -> dict[str, Any]:
    with fitz.open(path) as document:
        return {"format": "pdf", "count": validate_page_content(document)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    args = parser.parse_args()
    try:
        print(validate_pdf(args.pdf))
    except ValidationError as error:
        parser.exit(2, f"{error}\n")


if __name__ == "__main__":
    main()
