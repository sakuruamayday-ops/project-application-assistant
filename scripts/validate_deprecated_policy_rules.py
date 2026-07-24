#!/usr/bin/env python3
"""阻断已停用政策被重新写入当前申报、复核、评分或写作链。"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
OLD_POLICY_MARKERS = (
    "工信部企业〔2022〕63号",
    "2022年评价标准",
    "2022年评分表",
    "2022年标准",
    "旧标准",
    "旧评分表",
)
ACTIVE_ACTIONS = (
    "使用",
    "执行",
    "沿用",
    "适用",
    "核验",
    "计算",
    "评分",
    "补充",
    "提取",
)
DENIAL_OR_HISTORY = (
    "禁止",
    "不得",
    "不再",
    "只保留为历史",
    "仅用于历史",
    "只用于历史",
    "历史事实",
    "曾按",
    "已经结束",
    "不构成",
    "退出当前评价链",
)

ACTIVE_FILES = (
    "skills/sme-development-projects/SKILL.md",
    "skills/sme-development-projects/references/current-policy-baseline-2026.md",
    "services/knowledge-portal/app/main.py",
    "services/knowledge-portal/scripts/build_knowledge_content_index.py",
)

REQUIRED_RULES = {
    "skills/sme-development-projects/SKILL.md": (
        "不得用于当前或未来的新申报、复核、评分和材料写作",
        "不得补充现行标准没有规定的条件",
        "仅用于历史追溯",
    ),
    "skills/sme-development-projects/references/current-policy-baseline-2026.md": (
        "禁止使用2022年评分表计算当前分数",
        "禁止从旧标准提取现行标准没有规定的条件",
        "不得据此启动当前评价",
    ),
    "services/knowledge-portal/app/main.py": (
        "不得用于当前或未来的新申报、复核、评分和材料写作",
        "不得补充现行标准没有规定的条件",
        "不构成当前或以后年度的适用依据",
    ),
}

EXPLICITLY_FORBIDDEN = (
    "复核过渡情形可按旧标准",
    "复核仅在当期通知明确的过渡范围内继续使用旧标准",
)


def line_has_active_old_policy_semantics(line: str) -> bool:
    normalized = re.sub(r"\s+", "", line)
    if not any(marker in normalized for marker in OLD_POLICY_MARKERS):
        return False
    if not any(action in normalized for action in ACTIVE_ACTIONS):
        return False
    return not any(marker in normalized for marker in DENIAL_OR_HISTORY)


def validate_repository(root: Path = REPOSITORY_ROOT) -> dict[str, object]:
    errors: list[str] = []
    checked: list[str] = []

    for relative in ACTIVE_FILES:
        path = root / relative
        if not path.is_file():
            errors.append(f"缺少受控文件：{relative}")
            continue
        checked.append(relative)
        text = path.read_text(encoding="utf-8")
        for phrase in EXPLICITLY_FORBIDDEN:
            if phrase in text:
                errors.append(f"{relative}包含禁止表述：{phrase}")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if line_has_active_old_policy_semantics(line):
                errors.append(
                    f"{relative}:{line_number}疑似重新启用旧标准：{line.strip()}"
                )

    for relative, phrases in REQUIRED_RULES.items():
        path = root / relative
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for phrase in phrases:
            if phrase not in text:
                errors.append(f"{relative}缺少强制停用规则：{phrase}")

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
