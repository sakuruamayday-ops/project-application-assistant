#!/usr/bin/env python3
"""Validate enterprise panorama PDF output with the shared portable runtime."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

SKILLS_ROOT = Path(__file__).resolve().parents[2]
BRANDING_SCRIPTS = SKILLS_ROOT / "_runtime" / "jiaotang-branding" / "scripts"
if not BRANDING_SCRIPTS.is_dir():
    raise RuntimeError(f"shared branding runtime missing: {BRANDING_SCRIPTS}")
sys.path.insert(0, str(BRANDING_SCRIPTS))
from delivery_gate import GateFailure, validate_pdf as validate_branded_pdf  # noqa: E402


class ValidationError(GateFailure):
    pass


def validate_pdf(path: str | Path, *, require_watermark: bool = False) -> dict[str, Any]:
    if not require_watermark:
        raise ValidationError(
            "B版验证必须显式使用--require-watermark；A版由销售版生成器单独校验"
        )
    return validate_branded_pdf(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--require-watermark", action="store_true")
    args = parser.parse_args()
    print(validate_pdf(args.pdf, require_watermark=args.require_watermark))


if __name__ == "__main__":
    main()
