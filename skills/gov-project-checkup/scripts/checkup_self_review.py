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

CHAPTER_HEADINGS: list[tuple[str, str]] = [
    ("ch1", r"(?:^|\n)\s*#*\s*壹[、.\s]"),
    ("ch2", r"(?:^|\n)\s*#*\s*贰[、.\s]"),
    ("ch3", r"(?:^|\n)\s*#*\s*叁[、.\s]"),
    ("ch4", r"(?:^|\n)\s*#*\s*肆[、.\s]"),
    ("ch5", r"(?:^|\n)\s*#*\s*伍[、.\s]"),
    ("ch6", r"(?:^|\n)\s*#*\s*陆[、.\s]"),
]

# (item_key, label, chapter_scope_or_none, required_patterns, min_chapter_chars)
CHECKS: list[tuple[str, str, str | None, list[str], int]] = [
    ("base_year", "已标注基准年与适用政策版本", None, [r"基准年", r"Y\s*[=＝]\s*20\d\d|20\d\d\s*年为基准"], 0),
    ("hard_gates", "壹章刚性指标核查表并给出判定", "ch1", [r"(硬性|刚性)指标", r"(达标|未达标|红灯|绿灯|黄灯|通过|不通过)"], 20),
    ("finance_penetration", "贰章财务表内比例与绝对值穿透比对", "ch2", [r"(穿透|推导比例|复算|比例)"], 20),
    ("cross_form_ip", "叁章跨表单一致性与知识产权关联", "ch3", [r"(一致性|跨表)", r"(知识产权|专利)"], 20),
    ("dual_positioning", "肆章重点产业链与工业六基双维定位", "ch4", [r"产业链", r"六基"], 20),
    ("four_narratives", "伍章四大文字板块均完成字数与匿名诊断", "ch5", [r"主导产品", r"补短板", r"(产学研|研究领域已获得成果)", r"(企业简介|企业总体情况)", r"\d+\s*字"], 30),
    ("tiered_actions", "陆章红黄绿三级整改清单", "ch6", [r"(必须修改|🔴)", r"(建议补强|🟡)"], 20),
    ("tone", "口吻客观温和，无过激用词", None, [], 0),
]
HARSH_WORDS = ["致命", "瞎写", "严重造假", "不可饶恕", "胡编", "垃圾"]


def _split_chapters(text: str) -> dict[str, str]:
    marks: list[tuple[int, str]] = []
    for key, pat in CHAPTER_HEADINGS:
        m = re.search(pat, text)
        if m:
            marks.append((m.start(), key))
    marks.sort()
    chapters: dict[str, str] = {}
    for idx, (pos, key) in enumerate(marks):
        end = marks[idx + 1][0] if idx + 1 < len(marks) else len(text)
        chapters[key] = text[pos:end].strip()
    return chapters


def review(text: str) -> dict:
    chapters = _split_chapters(text)
    results = []
    for key, label, scope, patterns, min_chars in CHECKS:
        if key == "tone":
            harsh = [w for w in HARSH_WORDS if w in text]
            results.append({"item": key, "label": label, "pass": not harsh, "detail": harsh})
            continue
        target_text = chapters.get(scope, "") if scope else text
        issues = []
        if scope and not target_text:
            issues.append(f"缺少对应章节({scope})")
        else:
            if min_chars:
                # Strip first heading line before measuring actual chapter body substance
                body_lines = target_text.splitlines()[1:]
                body_len = len(re.sub(r"\s+", "", "\n".join(body_lines)))
                if body_len < min_chars:
                    issues.append(f"章节内容过空（正文仅{body_len}字，低于最低实质要求{min_chars}字）")
            missing = [p for p in patterns if not re.search(p, target_text)]
            issues.extend(missing)
        results.append({"item": key, "label": label, "pass": not issues, "detail": issues})
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
