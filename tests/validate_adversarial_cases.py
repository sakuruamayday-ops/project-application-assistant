#!/usr/bin/env python3
"""校验对抗题库结构、数量和答案隔离。"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROMPTS_PATH = ROOT / "tests" / "adversarial-prompts.jsonl"
EXPECTED_PATH = ROOT / "tests" / "adversarial-expected.json"
SKILLS_ROOT = ROOT / "skills"
EXPECTED_CATEGORIES = {
    "base": 21,
    "typo": 21,
    "negation": 21,
    "multi-domain": 21,
    "stale-policy": 24,
}


def main() -> int:
    errors = []
    prompts = [
        json.loads(line)
        for line in PROMPTS_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    expected_doc = json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))
    answers = expected_doc.get("answers", [])
    prompt_ids = [item.get("case_id") for item in prompts]
    answer_ids = [item.get("case_id") for item in answers]
    if len(prompts) != 108:
        errors.append(f"题目数量应为108，实际{len(prompts)}")
    if len(set(prompt_ids)) != len(prompt_ids):
        errors.append("题目case_id重复")
    if set(prompt_ids) != set(answer_ids):
        errors.append("题目与隐藏答案case_id不一致")
    counts = Counter(item.get("category") for item in prompts)
    if dict(counts) != EXPECTED_CATEGORIES:
        errors.append(f"分类数量错误:{dict(counts)}")
    forbidden_prompt_keys = {
        "expected_primary_skill",
        "required_skills",
        "forbidden_skills",
        "expected_policy_status",
    }
    for item in prompts:
        leaked = forbidden_prompt_keys.intersection(item)
        if leaked:
            errors.append(f"{item.get('case_id')}:题目泄漏答案字段:{sorted(leaked)}")
        if not str(item.get("prompt", "")).strip():
            errors.append(f"{item.get('case_id')}:题目为空")
    for item in answers:
        skill = item.get("expected_primary_skill")
        if not (SKILLS_ROOT / str(skill) / "SKILL.md").is_file():
            errors.append(f"{item.get('case_id')}:主技能不存在:{skill}")
        for required in item.get("required_skills", []):
            if not (SKILLS_ROOT / required / "SKILL.md").is_file():
                errors.append(f"{item.get('case_id')}:必需技能不存在:{required}")
        if item.get("category") == "stale-policy":
            if item.get("expected_policy_status") != "stale":
                errors.append(f"{item.get('case_id')}:过期政策答案未标stale")
            if not item.get("claims_must_be_limited"):
                errors.append(f"{item.get('case_id')}:过期政策答案未限制结论")
    report = {
        "status": "pass" if not errors else "fail",
        "case_count": len(prompts),
        "category_counts": dict(counts),
        "answer_separation": "pass" if not errors else "check-errors",
        "errors": errors,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    sys.exit(main())
