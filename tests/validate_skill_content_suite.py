#!/usr/bin/env python3
"""验证21个增强技能的结构、引用、案例和关键依赖。"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
CASES = json.loads((ROOT / "tests" / "skill_content_cases.json").read_text(encoding="utf-8"))
EXPECTED = set(CASES)
SCRIPT_REQUIRED = {
    "application-version-diff",
    "consistency-check",
    "evidence-ledger",
    "green-development-projects",
    "investment-subsidy-projects",
    "ip-assessment",
    "patent-router",
    "project-memory",
    "regional-special-projects",
    "skill-authoring",
    "talent-projects",
    "trade-and-open-economy-projects",
}
CASE_TYPES = {"positive", "boundary", "missing", "routing"}


def main():
    errors = []
    for skill in sorted(EXPECTED):
        folder = SKILLS / skill
        path = folder / "SKILL.md"
        if not path.is_file():
            errors.append(f"{skill}:缺少SKILL.md")
            continue
        text = path.read_text(encoding="utf-8")
        tail = text.split("<!-- END MANAGED PORTABLE SKILL RUNTIME -->", 1)[-1]
        if len([line for line in tail.splitlines() if line.strip()]) < 10:
            errors.append(f"{skill}:业务正文仍过薄")
        refs = [item for item in (folder / "references").glob("*") if item.is_file() and item.name != "portable-runtime-protocol.md"]
        if not refs:
            errors.append(f"{skill}:没有领域参考文件")
        if skill in SCRIPT_REQUIRED:
            scripts = [item for item in (folder / "scripts").glob("*.py") if item.name not in {"portable_skill_runtime.py", "verify_skill_installation.py"}]
            if not scripts:
                errors.append(f"{skill}:缺少确定性业务脚本")
        for relative in re.findall(r"`((?:references|scripts)/[^`]+)`", tail):
            if not (folder / relative).is_file():
                errors.append(f"{skill}:引用缺失:{relative}")
        if set(CASES[skill]) != CASE_TYPES:
            errors.append(f"{skill}:案例类型不完整")
    manifest = json.loads((SKILLS / "suite-manifest.json").read_text(encoding="utf-8"))
    dependencies = manifest.get("dependencies", {})
    for skill in ("application-writing", "industry-positioning", "intellectual-property-projects", "patent-router", "regional-special-projects"):
        if skill not in dependencies:
            errors.append(f"suite-manifest:缺少依赖声明:{skill}")
    router = (SKILLS / "project-task-router" / "references" / "domain-routing-matrix.md")
    if not router.is_file():
        errors.append("project-task-router:缺少领域路由矩阵")
    report = {
        "status": "pass" if not errors else "fail",
        "skills": len(EXPECTED),
        "functional_cases": len(EXPECTED) * 3,
        "routing_cases": len(EXPECTED),
        "total_cases": len(EXPECTED) * 4,
        "errors": errors,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    sys.exit(main())
