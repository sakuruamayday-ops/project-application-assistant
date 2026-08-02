#!/usr/bin/env python3
"""阻断历史专精评分引擎重新进入活动 Skills 包。"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ACTIVE_SKILL = REPOSITORY_ROOT / "skills" / "sme-score-preassessment"
REMOVED_ACTIVE_PATHS = (
    "scripts/run_score.sh",
    "scripts/score_core.mjs",
    "scripts/score_engine.mjs",
    "scripts/nbs_fetch.mjs",
    "scripts/zhejiang_fetch.mjs",
    "assets/专精特新与小巨人前期评分预评估模板.xlsx",
    "assets/专精特新与小巨人客户评分_三年财务底表模板.xlsx",
)
REQUIRED_CURRENT_MARKERS = {
    "skills/sme-score-preassessment/SKILL.md": (
        "2026 年政策",
        "pending-platform-evaluation",
        "不得生成估算总分",
        "内部二十二项百分制",
    ),
    "skills/sme-score-preassessment/references/current-policy-baseline-2026.md": (
        "2026 年新办法",
        "待平台评价",
        "2026 年小巨人复核过渡规则",
    ),
    "skills/sme-development-projects/SKILL.md": (
        "活动技能只保留 2026 政策分支",
        "不能扩展到新申报或未来年度",
    ),
}
FORBIDDEN_ACTIVE_MARKERS = (
    "--task-type full-score",
    "三档总分唯一来源",
    "固定22项、满分100分",
    "2022-transition-for-2026-review",
)
OLD_POLICY_MARKERS = (
    "工信部企业〔2022〕63号",
    "2022年评价标准",
    "2022年评分表",
    "2022年标准",
)
HISTORY_OR_DENIAL_MARKERS = (
    "历史事实",
    "曾按",
    "不得",
    "禁止",
    "不构成",
    "不再",
)


def line_has_active_old_policy_semantics(line: str) -> bool:
    normalized = re.sub(r"\s+", "", line)
    if not any(marker in normalized for marker in OLD_POLICY_MARKERS):
        return False
    if any(marker in normalized for marker in HISTORY_OR_DENIAL_MARKERS):
        return False
    return any(action in normalized for action in ("使用", "执行", "适用", "计算", "评分"))


def validate_repository(root: Path = REPOSITORY_ROOT) -> dict[str, object]:
    errors: list[str] = []
    checked: list[str] = []
    active_skill = root / "skills" / "sme-score-preassessment"
    for relative in REMOVED_ACTIVE_PATHS:
        path = active_skill / relative
        if path.exists():
            errors.append(f"历史评分资产仍在活动技能中：{path.relative_to(root)}")
        checked.append(str(path.relative_to(root)))

    for relative, markers in REQUIRED_CURRENT_MARKERS.items():
        path = root / relative
        if not path.is_file():
            errors.append(f"缺少受控文件：{relative}")
            continue
        checked.append(relative)
        text = path.read_text(encoding="utf-8")
        for marker in markers:
            if marker not in text:
                errors.append(f"{relative}缺少2026边界：{marker}")
        for marker in FORBIDDEN_ACTIVE_MARKERS:
            if marker in text:
                errors.append(f"{relative}重新启用历史评分：{marker}")

    archive = root / "docs/archive/sme-score-preassessment-legacy-before-v1.5.0"
    if not (archive / "README.md").is_file():
        errors.append("历史评分工具缺少可恢复审计归档")

    return {
        "status": "pass" if not errors else "fail",
        "checked_files": checked,
        "errors": errors,
    }


def main() -> int:
    result = validate_repository()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
    sys.exit(main())
