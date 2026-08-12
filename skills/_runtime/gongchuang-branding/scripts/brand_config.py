#!/usr/bin/env python3
"""Shared centered brand-layout decisions for document generators."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SKILL_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = SKILL_ROOT / "references" / "brand_config.json"
ASSET_DIR = SKILL_ROOT / "assets"


def load_config() -> dict[str, Any]:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    style_sets = [config["styles"], *config.get("variants", {}).values()]
    for styles in style_sets:
        for style in styles.values():
            for key in ("light_asset", "dark_asset"):
                path = ASSET_DIR / style[key]
                if not path.exists():
                    raise FileNotFoundError(f"Brand asset missing: {path}")
    return config


def public_identity() -> dict[str, str]:
    """Return the single public-facing brand contract used by all renderers."""
    identity = load_config().get("public_identity")
    if not isinstance(identity, dict):
        raise ValueError("Public brand identity is missing")
    required = {
        "display_name",
        "product_name",
        "document_header",
        "cover_signature",
        "artifact_slug",
        "marketplace_name",
        "plugin_name",
        "mcp_name",
    }
    missing = sorted(required - set(identity))
    if missing:
        raise ValueError("Public brand identity fields missing: " + ", ".join(missing))
    return {key: str(identity[key]) for key in required}


def estimate_density(content: Any) -> float:
    """Estimate layout density from Markdown text or structured content blocks."""
    if isinstance(content, str):
        text_score = min(len(content) / 9000.0, 0.72)
        table_score = min(content.count("|") / 180.0, 0.38)
        heading_relief = min(content.count("\n#") / 30.0, 0.08)
        return round(max(0.0, min(1.0, text_score + table_score - heading_relief)), 4)

    if not isinstance(content, list):
        return 0.35

    score = 0.0
    for item in content:
        if not isinstance(item, dict):
            continue
        kind = item.get("type", "body")
        if kind == "table":
            cells = len(item.get("headers", [])) * max(1, len(item.get("rows", [])))
            score += min(0.45, cells / 100.0)
        elif kind in {"image", "figure", "chart", "flowchart"}:
            score += 0.18
        else:
            score += min(len(str(item.get("text", ""))) / 4500.0, 0.12)
    return round(max(0.0, min(1.0, score)), 4)


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    channels = []
    for value in rgb:
        c = max(0, min(255, value)) / 255.0
        channels.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def choose_style(
    density: float,
    background_luminance: float = 1.0,
    target: str = "pdf",
    occupied_regions: dict[str, float] | None = None,
    variant: str | None = None,
) -> dict[str, Any]:
    config = load_config()
    if target not in config["scope"]:
        raise ValueError(f"Branding is not enabled for format: {target}")

    density = max(0.0, min(1.0, float(density)))
    thresholds = config["density_thresholds"]
    band = "low" if density <= thresholds["low_max"] else "medium"
    if density > thresholds["medium_max"]:
        band = "high"

    dark = background_luminance < config["dark_background_luminance_threshold"]
    if variant is not None and variant not in config.get("variants", {}):
        raise ValueError(f"Unknown brand asset variant: {variant}")
    styles = config.get("variants", {}).get(variant, config["styles"])
    style = styles[band]
    asset_name = style["dark_asset" if dark else "light_asset"]
    return {
        "density": density,
        "density_band": band,
        "dark_background": dark,
        "asset_path": str(ASSET_DIR / asset_name),
        "scale": style[f"{target}_scale"],
        "position": config["policy"]["position"],
        "variant": variant or "default",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--density", type=float, default=0.35)
    parser.add_argument("--luminance", type=float, default=1.0)
    parser.add_argument("--target", choices=["pdf", "pptx", "docx", "xlsx"], default="pdf")
    parser.add_argument("--variant", choices=["gold"])
    parser.add_argument("--identity", action="store_true")
    args = parser.parse_args()
    result = public_identity() if args.identity else choose_style(
        args.density, args.luminance, args.target, variant=args.variant
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
