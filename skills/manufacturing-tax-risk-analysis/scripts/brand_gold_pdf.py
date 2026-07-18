#!/usr/bin/env python3
"""Apply the bundled centered gold watermark to a PDF received on stdin."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SKILLS_ROOT = Path(__file__).resolve().parents[2]
BRANDING_SCRIPTS = SKILLS_ROOT / "enterprise-panorama-analysis" / "scripts"
sys.path.insert(0, str(BRANDING_SCRIPTS))
from pdf_two_pass import brand_pdf_bytes  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--audit-json", type=Path)
    args = parser.parse_args()
    data = sys.stdin.buffer.read()
    if not data.startswith(b"%PDF"):
        raise RuntimeError("stdin did not contain a PDF")
    audit = brand_pdf_bytes(data, args.output, variant="gold")
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
