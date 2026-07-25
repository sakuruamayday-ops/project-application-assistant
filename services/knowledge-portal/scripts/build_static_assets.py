#!/usr/bin/env python3
from __future__ import annotations

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
TEMPLATES = ROOT / "templates"
SOURCES = (
    ("base", "style.css"),
    ("console", "console.css"),
    ("theme", "atelier.css"),
)


def main() -> int:
    sections = ["@layer base, console, theme;\n"]
    for layer, name in SOURCES:
        content = (STATIC / name).read_text(encoding="utf-8").strip()
        sections.append(f"@layer {layer} {{\n{content}\n}}\n")
    target = STATIC / "app.css"
    target.write_text("\n".join(sections), encoding="utf-8")
    css_digest = hashlib.sha256(target.read_bytes()).hexdigest()[:16]
    js_digest = hashlib.sha256((STATIC / "portal.js").read_bytes()).hexdigest()[:16]
    (TEMPLATES / "_static_assets.html").write_text(
        f'<link rel="stylesheet" href="/static/app.css?v={css_digest}">\n'
        f'<script src="/static/portal.js?v={js_digest}" defer></script>\n',
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
