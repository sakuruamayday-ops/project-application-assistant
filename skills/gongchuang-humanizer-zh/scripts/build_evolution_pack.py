#!/usr/bin/env python3
"""Build a review-only evolution pack from de-identified feedback."""

import argparse
import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path


DEFAULT_INPUT = (
    Path(os.environ.get("GONGCHUANG_SKILL_DATA_DIR", Path.home() / ".config" / "gongchuang-skills"))
    / "gongchuang-humanizer-zh"
    / "evolution-feedback.jsonl"
)


def load_entries(path: Path) -> list[dict]:
    entries = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"第 {line_number} 行不是有效 JSON") from exc
    return entries


def main() -> None:
    parser = argparse.ArgumentParser(description="汇总去 AI 味技能进化信号")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        entries = load_entries(args.input)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    issues = Counter(issue for entry in entries for issue in entry.get("issues", []))
    gate_failures = Counter(
        gate
        for entry in entries
        for gate, passed in entry.get("hard_gates", {}).items()
        if not passed
    )
    winner_scores = []
    for entry in entries:
        scores = {candidate.get("name"): candidate.get("score") for candidate in entry.get("candidates", [])}
        score = scores.get(entry.get("winner"))
        if isinstance(score, (int, float)):
            winner_scores.append(float(score))

    repeated = [name for name, count in issues.items() if count >= 2]
    high_risk = list(gate_failures)
    candidates = []
    if repeated:
        candidates.append("针对重复失误提出一条最小规则变更，并用保留样本回归")
    if high_risk:
        candidates.append("优先修复硬门禁失败，修复前禁止应用其他风格优化")
    if not candidates:
        candidates.append("当前信号不足以固化永久规则，继续收集真实同样本盲测")

    lines = [
        "# 去 AI 味技能进化候选包",
        "",
        f"生成时间：{datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"样本数：{len(entries)}",
        f"胜出版本平均分：{sum(winner_scores) / len(winner_scores):.1f}" if winner_scores else "胜出版本平均分：暂无",
        "",
        "## 失误信号",
        "",
    ]
    lines.extend([f"- {name}：{count} 次" for name, count in issues.most_common()] or ["- 暂无"])
    lines.extend(["", "## 硬门禁失败", ""])
    lines.extend([f"- {name}：{count} 次" for name, count in gate_failures.most_common()] or ["- 暂无"])
    lines.extend(["", "## 候选动作", ""])
    lines.extend(f"- {item}" for item in candidates)
    lines.extend([
        "",
        "## 应用门禁",
        "",
        "- 候选规则必须与现行版进行盲测对比",
        "- 使用未参与规则设计的保留样本回归",
        "- 政府申报样本不得出现事实锁或必要叙事失败",
        "- 主人明确确认后才可修改 SKILL.md",
        "",
        "本文件是本地统计汇总，不代表已完成 GEPA 或外部模型优化。",
    ])

    output = args.output or Path.cwd() / f"humanizer-evolution-pack-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"已生成进化候选包：{output}")


if __name__ == "__main__":
    main()
