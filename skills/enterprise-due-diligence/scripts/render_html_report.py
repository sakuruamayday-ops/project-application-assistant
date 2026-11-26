#!/usr/bin/env python3
"""Render the Version B deep analysis HTML as a PDF."""

import argparse
import sys
import base64
import os
from pathlib import Path
import shutil
import subprocess


if __name__ == "__main__":
    # Fixed CLI PDF work uses the classic engine; preserve any caller-loaded ML modules.
    sys.modules.setdefault("pymupdf.layout", None)
    sys.modules.setdefault("pymupdf4llm", None)

HERE = Path(__file__).resolve().parent




def npm_root() -> str:
    result = subprocess.run(
        ["npm", "root", "-g"], check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def render_pdf_bytes(html_path: Path | None, *, contents: bytes | None = None) -> bytes:
    node = shutil.which("node")
    if not node:
        raise RuntimeError("node executable not found")
    env = os.environ.copy()
    global_modules = npm_root()
    existing = env.get("NODE_PATH", "")
    env["NODE_PATH"] = global_modules if not existing else global_modules + os.pathsep + existing
    source = "-" if html_path is None or html_path == Path("-") else str(html_path.resolve())
    result = subprocess.run(
        [node, str(HERE / "render_pdf_bytes.js"), source],
        input=contents,
        capture_output=True,
        env=env,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip())
    return base64.b64decode(result.stdout, validate=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", required=True, type=Path, help="已有 HTML 文件，或用 - 读取自包含的 HTML 流")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if args.html != Path("-") and not args.html.is_file():
        raise FileNotFoundError(args.html)
    args.out.parent.mkdir(parents=True, exist_ok=True)

    import pymupdf as fitz
    from outline_pdf_text import validate_page_content

    raw_pdf = render_pdf_bytes(args.html)
    with fitz.open(stream=raw_pdf, filetype="pdf") as document:
        pages = validate_page_content(document)
    args.out.write_bytes(raw_pdf)
    print(f"WROTE {args.out.resolve()} pages={pages} bytes={args.out.stat().st_size}")


if __name__ == "__main__":
    main()
