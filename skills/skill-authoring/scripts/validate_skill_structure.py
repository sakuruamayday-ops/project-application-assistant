#!/usr/bin/env python3
"""对技能目录执行轻量结构检查。"""
import argparse, json, re
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("skill_dir")
args = parser.parse_args()
root = Path(args.skill_dir)
skill_file = root / "SKILL.md"
errors = []
if not skill_file.is_file():
    errors.append("缺少SKILL.md")
else:
    text = skill_file.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not match:
        errors.append("YAML前置区不存在")
    else:
        front = match.group(1)
        if not re.search(r"^name:\s*[a-z0-9-]+\s*$", front, re.M):
            errors.append("name缺失或不合规")
        if not re.search(r"^description:\s*.+$", front, re.M):
            errors.append("description缺失")
        extra = [line.split(":", 1)[0] for line in front.splitlines() if ":" in line and not line.startswith(("name:", "description:"))]
        if extra:
            errors.append("前置区含额外字段:" + ",".join(extra))
print(json.dumps({"status": "pass" if not errors else "fail", "errors": errors}, ensure_ascii=False, indent=2))
raise SystemExit(0 if not errors else 2)
