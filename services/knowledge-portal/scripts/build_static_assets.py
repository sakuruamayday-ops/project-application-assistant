#!/usr/bin/env python3
from __future__ import annotations

import colorsys
import hashlib
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
TEMPLATES = ROOT / "templates"
SOURCES = (
    ("base", "style.css"),
    ("console", "console.css"),
    ("theme", "atelier.css"),
    ("theme", "skill-center.css"),
)

# 颜色门禁：红色系令牌不得进入最终 CSS。
# 判定规则：色相落在红区（<=15° 或 >=345°）、饱和度 >0.35、亮度 <0.75，
# 可放行青铜、咖啡等暗暖色，仅拦截视觉可辨的红。确需红色时显式加入白名单并注明理由。
RED_WHITELIST: set[str] = set()
HEX_TOKEN = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b")
RGB_TOKEN = re.compile(r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})")


def _is_red(r: int, g: int, b: int) -> bool:
    hue, lightness, saturation = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    degrees = hue * 360
    return saturation > 0.35 and lightness < 0.75 and (degrees <= 15 or degrees >= 345)


def find_red_tokens(css: str) -> list[str]:
    offenders: set[str] = set()
    for token in HEX_TOKEN.findall(css):
        value = token.lstrip("#").lower()
        expanded = "".join(ch * 2 for ch in value) if len(value) == 3 else value
        r, g, b = (int(expanded[i : i + 2], 16) for i in (0, 2, 4))
        if _is_red(r, g, b) and f"#{value}" not in RED_WHITELIST:
            offenders.add(f"#{value}")
    for r, g, b in RGB_TOKEN.findall(css):
        key = f"rgb({r},{g},{b})"
        if _is_red(int(r), int(g), int(b)) and key not in RED_WHITELIST:
            offenders.add(key)
    return sorted(offenders)


def main() -> int:
    sections = ["@layer base, console, theme;\n"]
    for layer, name in SOURCES:
        content = (STATIC / name).read_text(encoding="utf-8").strip()
        sections.append(f"@layer {layer} {{\n{content}\n}}\n")
    combined = "\n".join(sections)
    offenders = find_red_tokens(combined)
    if offenders:
        print("颜色门禁拦截：检测到未经白名单批准的红色令牌：")
        for token in offenders:
            print(f"  - {token}")
        return 1
    target = STATIC / "app.css"
    target.write_text(combined, encoding="utf-8")
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
