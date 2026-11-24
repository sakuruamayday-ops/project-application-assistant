#!/usr/bin/env python3
"""Apply the product, project and batch comparison rules to sourced candidates."""

import argparse
import json
from pathlib import Path


FORMAL_STAGES = {"认定", "认定名单", "正式认定", "已认定", "正式公布", "公布", "复核通过"}
PROPOSED_STAGES = {
    "拟认定", "拟认定名单", "拟认定公示", "公示拟认定", "拟认定/公示", "拟复核通过", "公示", "公示名单",
}
DECISION_GROUPS = {"exclude": "排除", "background": "背景组", "needs-evidence": "待补证"}


def classify(target, candidates):
    results = []
    for candidate in candidates:
        relation = candidate.get("product_relation")
        if relation == "different":
            decision, reason = "exclude", "产品交付形态不同"
        elif relation == "broader":
            decision, reason = "background", "来源覆盖更宽的产品范围"
        elif relation != "same" or not candidate.get("product_source"):
            decision, reason = "needs-evidence", "缺同一细分产品证据"
        elif any(candidate.get(key) and candidate[key] != target[key] for key in ("project", "batch")):
            decision, reason = "background", "项目或认定批次不同"
        elif not all(candidate.get(key) for key in ("project", "batch", "recognition_source")):
            decision, reason = "needs-evidence", "缺同项目、同批次认定原件"
        else:
            decision, reason = "include", "同细分产品、同项目、同认定批次均有来源"
        stage = str(candidate.get("recognition_stage") or "").strip()
        if decision != "include":
            group = DECISION_GROUPS[decision]
        elif stage in PROPOSED_STAGES:
            group = "拟认定/公示"
        elif stage in FORMAL_STAGES:
            group = "直接组"
        else:
            group = stage or "认定阶段未标注"
        results.append({**candidate, "decision": decision, "group": group,
                        "group_label": (stage or group) if decision == "include" else group, "reason": reason})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        target, candidates = payload["target"], payload["candidates"]
        if (not all(isinstance(target.get(key), str) and target[key].strip() for key in ("project", "batch"))
                or not isinstance(candidates, list) or any(not isinstance(row, dict) for row in candidates)):
            raise ValueError("填写目标项目、认定批次和候选记录")
        results = classify(target, candidates)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        print(json.dumps({"status": "fail", "errors": [str(error)]}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "pass", "candidates": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
