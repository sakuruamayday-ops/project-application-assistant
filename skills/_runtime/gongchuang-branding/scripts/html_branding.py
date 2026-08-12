#!/usr/bin/env python3
"""Apply 共创研究院 page header, cover signature, and watermark to printable HTML."""

from __future__ import annotations

import argparse
import base64
import html as html_module
import re
from pathlib import Path

from brand_config import load_config, public_identity


STYLE_ID = "gongchuang-public-brand-style"
HEADER_CLASS = "gongchuang-document-header"
COVER_CLASS = "gongchuang-cover-signature"


def brand_html_text(source: str, *, has_cover: bool | None = None) -> str:
    config = load_config()
    identity = public_identity()
    if has_cover is None:
        has_cover = bool(
            re.search(
                r"""(?:class|id)\s*=\s*["'][^"']*(?:cover|title-page|封面)[^"']*["']""",
                source,
                re.IGNORECASE,
            )
        )
    asset = Path(__file__).resolve().parent.parent / "assets" / "brand-red-07.png"
    if not asset.is_file():
        raise FileNotFoundError(f"Brand asset missing: {asset}")
    asset_data = base64.b64encode(asset.read_bytes()).decode("ascii")
    header = html_module.escape(identity["document_header"])
    signature = html_module.escape(identity["cover_signature"])
    color = html_module.escape(str(config["policy"]["header_color"]))
    font_size = float(config["policy"]["header_font_size_pt"])
    style = f"""<style id="{STYLE_ID}">
.{HEADER_CLASS} {{
  position: fixed; top: 8mm; left: 16mm; right: 16mm; z-index: 2147483646;
  text-align: right; color: {color}; font: 500 {font_size}pt/1.2 "Microsoft YaHei", sans-serif;
}}
body::before {{
  content: ""; position: fixed; inset: 0; z-index: 2147483000; pointer-events: none;
  background: url(data:image/png;base64,{asset_data}) center center / 34% auto no-repeat;
}}
.{COVER_CLASS} {{
  color: {color}; text-align: right; margin: 12mm 16mm 0; font: 600 10pt/1.2 "Microsoft YaHei", sans-serif;
}}
@media print {{ .{HEADER_CLASS} {{ position: fixed; }} }}
</style>"""
    if f'id="{STYLE_ID}"' not in source:
        source = re.sub(r"</head\s*>", style + "\n</head>", source, count=1, flags=re.I)
        if f'id="{STYLE_ID}"' not in source:
            source = style + "\n" + source
    prefix = f'<div class="{HEADER_CLASS}" data-public-brand="共创研究院">{header}</div>'
    if has_cover:
        prefix += f'<div class="{COVER_CLASS}" data-cover-brand="共创研究院">{signature}</div>'
    if f'class="{HEADER_CLASS}"' not in source:
        source = re.sub(r"(<body\b[^>]*>)", r"\1\n" + prefix, source, count=1, flags=re.I)
        if f'class="{HEADER_CLASS}"' not in source:
            source = prefix + "\n" + source
    return source


def brand_html_file(path: str | Path, *, has_cover: bool | None = None) -> Path:
    path = Path(path)
    branded = brand_html_text(path.read_text(encoding="utf-8"), has_cover=has_cover)
    path.write_text(branded, encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path")
    parser.add_argument("--has-cover", action="store_true")
    args = parser.parse_args()
    print(brand_html_file(args.path, has_cover=True if args.has_cover else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
