#!/usr/bin/env python3
"""Render the branded Version B advisory PDF without an unbranded disk intermediate."""

import argparse
import base64
import os
from pathlib import Path
import shutil
import subprocess


HERE = Path(__file__).resolve().parent
SKILLS_ROOT = Path(__file__).resolve().parents[2]
BRANDING_SCRIPTS = SKILLS_ROOT / "_runtime" / "gongchuang-branding" / "scripts"


def npm_root() -> str:
    result = subprocess.run(
        ["npm", "root", "-g"], check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def render_pdf_bytes(html_path: Path) -> bytes:
    node = shutil.which("node")
    if not node:
        raise RuntimeError("node executable not found")
    env = os.environ.copy()
    global_modules = npm_root()
    existing = env.get("NODE_PATH", "")
    env["NODE_PATH"] = global_modules if not existing else global_modules + os.pathsep + existing
    result = subprocess.run(
        [node, str(HERE / "render_pdf_bytes.js"), str(html_path.resolve())],
        check=True,
        capture_output=True,
        env=env,
    )
    return base64.b64decode(result.stdout, validate=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if not args.html.is_file():
        raise FileNotFoundError(args.html)
    args.out.parent.mkdir(parents=True, exist_ok=True)

    raw_pdf = render_pdf_bytes(args.html)
    if not BRANDING_SCRIPTS.is_dir():
        raise RuntimeError(f"shared branding runtime missing: {BRANDING_SCRIPTS}")
    import sys

    sys.path.insert(0, str(BRANDING_SCRIPTS))
    from pdf_two_pass import brand_pdf_bytes

    audit = brand_pdf_bytes(raw_pdf, args.out)
    print(f"WROTE {args.out.resolve()} pages={len(audit)} bytes={args.out.stat().st_size}")


if __name__ == "__main__":
    main()
