#!/usr/bin/env python3
"""Compare current/next-year high-tech enterprise scoring scenarios."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


SCORE_KEYS = ("ip", "conversion", "organization")
LEVEL_KEYS = ("target", "conservative", "stress")


def growth_rate(values: list[float]) -> tuple[float | None, str | None]:
    if len(values) != 3:
        raise ValueError("revenue and net_assets must each contain exactly three values")
    first, second, third = values
    if first < 0 or second < 0:
        return None, "negative denominator requires specialist review; conservative score set to 0"
    if second == 0:
        return 0.0, "second-year denominator is 0; score set to 0"
    if first == 0:
        return third / second - 1, "first-year denominator is 0; calculated from the latter two years"
    return 0.5 * (second / first + third / second) - 1, None


def growth_band(rate: float | None) -> tuple[int, int, str]:
    if rate is None or rate <= 0:
        return 0, 0, "≤0%"
    if rate >= 0.35:
        return 9, 10, "≥35%"
    if rate >= 0.25:
        return 7, 8, "≥25%"
    if rate >= 0.15:
        return 5, 6, "≥15%"
    if rate >= 0.05:
        return 3, 4, "≥5%"
    return 1, 2, ">0%"


def normalize_scores(raw: dict[str, Any]) -> dict[str, dict[str, float]]:
    normalized: dict[str, dict[str, float]] = {}
    maxima = {"ip": 30, "conversion": 30, "organization": 20}
    for key in SCORE_KEYS:
        if key not in raw:
            raise ValueError(f"missing scores.{key}")
        value = raw[key]
        if isinstance(value, (int, float)):
            levels = {level: float(value) for level in LEVEL_KEYS}
        elif isinstance(value, dict):
            levels = {level: float(value[level]) for level in LEVEL_KEYS}
        else:
            raise ValueError(f"scores.{key} must be a number or an object")
        if not (levels["stress"] <= levels["conservative"] <= levels["target"]):
            raise ValueError(f"scores.{key} must satisfy stress <= conservative <= target")
        if levels["stress"] < 0 or levels["target"] > maxima[key]:
            raise ValueError(f"scores.{key} is outside 0..{maxima[key]}")
        normalized[key] = levels
    return normalized


def analyze_scenario(scenario: dict[str, Any]) -> dict[str, Any]:
    name = str(scenario.get("name", "scenario"))
    revenue = [float(v) for v in scenario["revenue"]]
    net_assets = [float(v) for v in scenario["net_assets"]]
    scores = normalize_scores(scenario["scores"])

    revenue_rate, revenue_note = growth_rate(revenue)
    asset_rate, asset_note = growth_rate(net_assets)
    revenue_low, revenue_high, revenue_band = growth_band(revenue_rate)
    asset_low, asset_high, asset_band = growth_band(asset_rate)

    nonfinancial = {
        level: sum(scores[key][level] for key in SCORE_KEYS) for level in LEVEL_KEYS
    }
    totals = {
        "target": nonfinancial["target"] + revenue_high + asset_high,
        "conservative": nonfinancial["conservative"] + revenue_low + asset_low,
        "stress": nonfinancial["stress"] + revenue_low + asset_low,
    }

    if revenue_rate is None or asset_rate is None:
        readiness = "存在负分母或特殊财务口径，须专项复核后才能形成申报年度建议"
    elif totals["conservative"] >= 75:
        readiness = "原则上建议当年申报，仍须通过全部硬门槛"
    elif totals["conservative"] >= 71:
        readiness = "临界，只有真实证据补强形成安全边际后才建议申报"
    else:
        readiness = "不建议仅按当前保守分申报，需比较下一年度净改善"

    return {
        "name": name,
        "growth": {
            "revenue": {
                "rate": None if revenue_rate is None else round(revenue_rate, 6),
                "band": revenue_band,
                "score_range": [revenue_low, revenue_high],
                "note": revenue_note,
            },
            "net_assets": {
                "rate": None if asset_rate is None else round(asset_rate, 6),
                "band": asset_band,
                "score_range": [asset_low, asset_high],
                "note": asset_note,
            },
        },
        "nonfinancial_scores": scores,
        "totals": totals,
        "readiness": readiness,
        "warning": "75 分是内部保守缓冲线，不是官方政策门槛。",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Calculate growth bands and target/conservative/stress totals.",
        epilog=(
            'Input: {"scenarios":[{"name":"今年","revenue":[100,90,110],'
            '"net_assets":[100,95,100],"scores":{"ip":{"target":29,'
            '"conservative":27,"stress":24},"conversion":{"target":29,'
            '"conservative":25,"stress":19},"organization":{"target":19,'
            '"conservative":17,"stress":14}}}]}'
        ),
    )
    parser.add_argument("input", type=Path, help="JSON input file")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        scenarios = payload["scenarios"]
        if not isinstance(scenarios, list) or not scenarios:
            raise ValueError("scenarios must be a non-empty list")
        result = {"scenarios": [analyze_scenario(item) for item in scenarios]}
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
