#!/usr/bin/env python3
"""Calculate observable-only weighted scores and public-evidence confidence."""

import argparse
import json
from pathlib import Path


def calculate(payload):
    indicators = payload["indicators"]
    observed = [item for item in indicators if item.get("score") is not None]
    if not observed:
        raise ValueError("at least one indicator must have an observed score")

    denominator = sum(float(item["weight"]) for item in observed)
    if denominator <= 0:
        raise ValueError("observed weights must sum to a positive number")
    numerator = sum(float(item["score"]) * float(item["weight"]) for item in observed)
    score = numerator / denominator

    public_fields = payload.get("public_evidence", [])
    if public_fields:
        evidence_weight = sum(float(item.get("weight", 1)) for item in public_fields)
        found_weight = sum(
            float(item.get("weight", 1)) for item in public_fields if item.get("found") is True
        )
        coverage = 100 * found_weight / evidence_weight if evidence_weight else 0
        confidence = "高" if coverage >= 80 else "中" if coverage >= 50 else "低"
    else:
        coverage = None
        confidence = "未计算"

    return {
        "score": round(score, 1),
        "score_rounded": round(score),
        "observed_weight": denominator,
        "excluded_indicators": [item["name"] for item in indicators if item.get("score") is None],
        "public_evidence_coverage": None if coverage is None else round(coverage, 1),
        "confidence": confidence,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, help="JSON input path")
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    print(json.dumps(calculate(payload), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
