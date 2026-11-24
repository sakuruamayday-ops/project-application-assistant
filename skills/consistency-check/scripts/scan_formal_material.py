#!/usr/bin/env python3
"""对已提取的正式正文做括号与待核验标记初筛。"""

import argparse
import json
import re
from pathlib import Path

from cross_chapter_fields import field_findings, text_observations, validate_observations


def _reconcile_blackboard(blackboard_path: Path, text: str) -> dict:
    payload = json.loads(blackboard_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("--blackboard 须指向 JSON 对象")
    compact = re.sub(r"\s+", "", text)
    pending, resolved = [], []
    for item in payload.get("estimatedMetrics", []):
        if not isinstance(item, dict) or item.get("origin", "ai_design_target") != "ai_design_target":
            continue
        snippet = re.sub(r"\s+", "", str(item.get("snippet", "")))
        suggested = re.sub(r"\s+", "", str(item.get("suggestedValue", "")))
        present = bool((snippet and snippet in compact) or (suggested and suggested in compact))
        entry = dict(item)
        if present:
            entry["status"] = "pending"
            entry["checkup_note"] = "该数值源自初稿行业设计目标，尚未见企业实测原件，提交前请核对工艺单或检测报告。"
            pending.append(entry)
        else:
            entry["status"] = "resolved"
            resolved.append(entry)
    return {
        "company_name": payload.get("company_name", ""),
        "pending_count": len(pending),
        "resolved_count": len(resolved),
        "pending_estimates": pending,
        "resolved_estimates": resolved,
    }


def main():
    parser = argparse.ArgumentParser(description="对正式材料正文做括号、占位符、跨章数字及黑板估算回查")
    parser.add_argument("text_file", type=Path)
    parser.add_argument("--fields", type=Path, help="同一任务的章节和表格字段记录")
    parser.add_argument("--blackboard", type=Path, help="可选：企业事实黑板 JSON，自动回查并销项行业设计目标")
    parser.add_argument("--strict", action="store_true", help="严格模式：发现任何问题时返回退出码 2")
    args = parser.parse_args()
    try:
        text = args.text_file.read_text(encoding="utf-8-sig")
        if not text.strip():
            raise ValueError("未提供可核查的材料正文")
        fields = validate_observations(json.loads(args.fields.read_text(encoding="utf-8"))) if args.fields else []
        reconciliation = _reconcile_blackboard(args.blackboard, text) if args.blackboard else None
    except (OSError, ValueError) as error:
        print(json.dumps({"status": "fail", "errors": [str(error)]}, ensure_ascii=False))
        return 2
    findings = []
    for token, label in (("(", "英文左括号"), (")", "英文右括号"), ("（", "中文左括号"), ("）", "中文右括号")):
        count = text.count(token)
        if count:
            findings.append({"rule": "parentheses", "token": token, "label": label, "count": count})
    for token in ("待核验", "待补充", "TBD", "TODO"):
        count = text.count(token)
        if count:
            findings.append({"rule": "placeholder", "token": token, "count": count})
    observations = [*text_observations(text, args.text_file.stem), *fields]
    findings.extend(field_findings(observations))
    output = {
        "status": "pass" if not findings else "review",
        "findings": findings,
        "observations": observations,
    }
    if reconciliation is not None:
        output["estimated_metrics_reconciliation"] = reconciliation
    print(json.dumps(output, ensure_ascii=False, indent=2))
    if args.strict and findings:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
