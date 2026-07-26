#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


def build_plan(payload):
    features = payload.get("features") or []
    return {
        "purpose": payload.get("purpose", "未指定"),
        "jurisdictions": payload.get("jurisdictions") or [],
        "cutoff_date": payload.get("cutoff_date"),
        "features": [
            {
                "feature": feature,
                "keywords": [],
                "synonyms": [],
                "ipc_candidates": [],
                "cpc_candidates": [],
            }
            for feature in features
        ],
        "query_rounds": ["宽检索", "区别特征收窄", "分类号交叉", "引证与同族扩展"],
        "evidence_log": [],
    }


def main():
    parser = argparse.ArgumentParser(description="生成专利检索计划JSON")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    payload = json.loads(arguments.input.read_text(encoding="utf-8"))
    arguments.output.write_text(json.dumps(build_plan(payload), ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
