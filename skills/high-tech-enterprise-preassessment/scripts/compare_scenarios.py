#!/usr/bin/env python3
"""Compare current/next-year high-tech enterprise scoring scenarios."""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path
from typing import Any


SCORE_KEYS = ("ip", "conversion", "organization")
LEVEL_KEYS = ("target", "conservative", "stress")
INTERNAL_BORDERLINE_MIN = 71
INTERNAL_BUFFER_MIN = 75
INPUT_EXAMPLE = {
    "scenarios": [{
        "name": "example",
        "revenue": [100, 110, 121],
        "net_assets": [100, 105, 110.25],
        "scores": {
            "ip": {"target": 25, "conservative": 22, "stress": 19},
            "conversion": {"target": 20, "conservative": 18, "stress": 15},
            "organization": {"target": 15, "conservative": 12, "stress": 10},
        },
    }],
}


def growth_rate(values: list[int | float | Decimal | str]) -> tuple[Fraction | None, str | None]:
    if len(values) != 3:
        raise ValueError("revenue and net_assets must each contain exactly three values")
    first, second, third = (Fraction(str(value)) for value in values)
    if first < 0 or second < 0:
        return None, "negative denominator requires specialist review; conservative score set to 0"
    if second == 0:
        return Fraction(0), "second-year denominator is 0; score set to 0"
    if first == 0:
        return third / second - 1, "first-year denominator is 0; calculated from the latter two years"
    return (second / first + third / second) / 2 - 1, None


def growth_band(rate: Fraction | None) -> tuple[int, int, str]:
    if rate is None or rate <= 0:
        return 0, 0, "≤0%"
    if rate >= Fraction(35, 100):
        return 9, 10, "≥35%"
    if rate >= Fraction(25, 100):
        return 7, 8, "≥25%"
    if rate >= Fraction(15, 100):
        return 5, 6, "≥15%"
    if rate >= Fraction(5, 100):
        return 3, 4, "≥5%"
    return 1, 2, ">0%"


def normalize_scores(raw: dict[str, Any]) -> dict[str, dict[str, float]]:
    normalized: dict[str, dict[str, float]] = {}
    maxima = {"ip": 30, "conversion": 30, "organization": 20}
    for key in SCORE_KEYS:
        if key not in raw:
            raise ValueError(f"missing scores.{key}")
        value = raw[key]
        if isinstance(value, dict) and "components" in value:
            components = value["components"]
            if not isinstance(components, list) or not components:
                raise ValueError(f"scores.{key}.components must be a non-empty list")
            totals = {level: Decimal(0) for level in LEVEL_KEYS}
            for index, component in enumerate(components):
                try:
                    levels = {level: Decimal(str(component[level])) for level in LEVEL_KEYS}
                except InvalidOperation as exc:
                    raise ValueError(f"scores.{key}.components[{index}] must contain numeric scores") from exc
                if not all(score.is_finite() for score in levels.values()):
                    raise ValueError(f"scores.{key}.components[{index}] must contain finite scores")
                if not (0 <= levels["stress"] <= levels["conservative"] <= levels["target"]):
                    raise ValueError(f"scores.{key}.components[{index}] must satisfy 0 <= stress <= conservative <= target")
                for level in LEVEL_KEYS:
                    totals[level] += levels[level]
            value = totals
        if isinstance(value, (int, float, Decimal)):
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
    revenue = scenario["revenue"]
    net_assets = scenario["net_assets"]
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
    elif totals["conservative"] >= INTERNAL_BUFFER_MIN:
        readiness = "原则上建议当年申报，仍须通过全部硬门槛"
    elif totals["conservative"] >= INTERNAL_BORDERLINE_MIN:
        readiness = "临界，只有真实证据补强形成安全边际后才建议申报"
    else:
        readiness = "不建议仅按当前保守分申报，需比较下一年度净改善"

    return {
        "name": name,
        "growth": {
            "revenue": {
                "rate": None if revenue_rate is None else float(round(revenue_rate, 6)),
                "percentage": None if revenue_rate is None else f"{float(revenue_rate * 100):.2f}%",
                "band": revenue_band,
                "score_range": [revenue_low, revenue_high],
                "note": revenue_note,
            },
            "net_assets": {
                "rate": None if asset_rate is None else float(round(asset_rate, 6)),
                "percentage": None if asset_rate is None else f"{float(asset_rate * 100):.2f}%",
                "band": asset_band,
                "score_range": [asset_low, asset_high],
                "note": asset_note,
            },
        },
        "nonfinancial_scores": scores,
        "totals": totals,
        "readiness": readiness,
        "internal_recommendation_thresholds": {
            "borderline_min_inclusive": INTERNAL_BORDERLINE_MIN,
            "borderline_max_exclusive": INTERNAL_BUFFER_MIN,
            "borderline_integer_score_range": [INTERNAL_BORDERLINE_MIN, INTERNAL_BUFFER_MIN - 1],
            "buffer_min_inclusive": INTERNAL_BUFFER_MIN,
            "basis": "内部申报建议区间，不是官方认定门槛，也不代表企业得分；小数分按下限包含、上限不包含判断。",
        },
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
        payload = json.loads(args.input.read_text(encoding="utf-8"), parse_float=Decimal)
        scenarios = payload["scenarios"]
        if not isinstance(scenarios, list) or not scenarios:
            raise ValueError("scenarios must be a non-empty list")
        result = {
            "schema_version": "high-tech-scenario-calculation-operation/v1",
            "scenarios": [analyze_scenario(item) for item in scenarios],
        }
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({
            "error": str(exc),
            "input_example": INPUT_EXAMPLE,
            "input_help": "Use three chronological annual values per financial array. Replace example scores with evidence-based target/conservative/stress assessments; do not reuse example facts or scores.",
        }, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
