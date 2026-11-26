#!/usr/bin/env python3
"""Self-review gate for six-chapter material checkup reports.

Scans a generated checkup report (markdown/text) for the 8 mandatory items.
Exit 0 = all pass; exit 2 = something missing (re-run the missing stage and regenerate).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

CHECKS: list[tuple[str, str, list[str]]] = [
    ("base_year", "已标注基准年与适用政策版本", [r"基准年", r"Y\s*[=＝]\s*20\d\d|20\d\d\s*年为基准"]),
    ("hard_gates", "壹章刚性指标核查表并给出判定", [r"壹", r"(硬性|刚性)指标", r"(达标|未达标|红灯|绿灯|黄灯|通过|不通过)"]),
    ("finance_penetration", "贰章财务表内比例与绝对值穿透比对", [r"贰", r"(穿透|推导比例|复算)"]),
    ("cross_form_ip", "叁章跨表单一致性与知识产权关联", [r"叁", r"(一致性|跨表)", r"(知识产权|专利)"]),
    ("dual_positioning", "肆章重点产业链与工业六基双维定位", [r"肆", r"产业链", r"六基"]),
    ("four_narratives", "伍章四大文字板块均完成字数与匿名诊断", [r"伍", r"主导产品", r"补短板", r"(产学研|研究领域已获得成果)", r"(企业简介|企业总体情况)", r"\d+\s*字"]),
    ("tiered_actions", "陆章红黄绿三级整改清单", [r"陆", r"(必须修改|🔴)", r"(建议补强|🟡)"]),
    ("tone", "口吻客观温和，无过激用词", []),
]
HARSH_WORDS = ["致命", "瞎写", "严重造假", "不可饶恕", "胡编", "垃圾"]


def review(text: str) -> dict:
    results = []
    for key, label, patterns in CHECKS:
        if key == "tone":
            harsh = [w for w in HARSH_WORDS if w in text]
            results.append({"item": key, "label": label, "pass": not harsh, "detail": harsh})
            continue
        missing = [p for p in patterns if not re.search(p, text)]
        results.append({"item": key, "label": label, "pass": not missing, "detail": missing})
    failed = [r for r in results if not r["pass"]]
    return {"ok": not failed, "checked": len(results), "failed": failed, "results": results}


def main() -> int:
    ap = argparse.ArgumentParser(description="六大章材料体检报告交稿前自检（8项）")
    ap.add_argument("report", type=Path)
    args = ap.parse_args()
    if not args.report.exists():
        print(json.dumps({"ok": False, "error": f"报告不存在：{args.report}"}, ensure_ascii=False))
        return 2
    res = review(args.report.read_text(encoding="utf-8", errors="ignore"))
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
