#!/usr/bin/env python3
"""依据release-manifest.json校验技能安装完整性。"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "release-manifest.json"
IGNORED = {".DS_Store"}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def skill_name() -> str | None:
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return None
    for line in match.group(1).splitlines():
        if line.startswith("name:"):
            return line.split(":", 1)[1].strip().strip("'\"")
    return None


def main() -> int:
    errors = []
    warnings = []
    if not MANIFEST.is_file():
        errors.append("缺少release-manifest.json")
        manifest = {}
    else:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    actual_name = skill_name()
    if actual_name != manifest.get("skill_name") or actual_name != ROOT.name:
        errors.append("技能目录名、SKILL.md名称和发布清单名称不一致")
    for relative in manifest.get("required_paths", []):
        if not (ROOT / relative).exists():
            errors.append(f"缺少必需路径：{relative}")
    declared = manifest.get("files", {})
    integrity_excludes = set(
        manifest.get("integrity_excludes", ["release-manifest.json"])
    )
    for relative, expected in declared.items():
        path = ROOT / relative
        if not path.is_file():
            errors.append(f"缺少文件：{relative}")
        elif digest(path) != expected:
            errors.append(f"文件哈希不一致：{relative}")
    mutable_paths = manifest.get("mutable_paths", [])

    def is_mutable(relative: str) -> bool:
        return any(
            relative == prefix or relative.startswith(prefix.rstrip("/") + "/")
            for prefix in mutable_paths
        )

    actual = set()
    for path in ROOT.rglob("*"):
        if (
            not path.is_file()
            or path.name in IGNORED
            or "__pycache__" in path.parts
            or path.suffix == ".pyc"
        ):
            continue
        relative = path.relative_to(ROOT).as_posix()
        if relative not in integrity_excludes and not is_mutable(relative):
            actual.add(relative)
    extra = sorted(actual - set(declared))
    if extra:
        warnings.append("存在清单外文件：" + "、".join(extra))
    result = {
        "status": "pass" if not errors else "fail",
        "skill": actual_name,
        "release_tag": manifest.get("release_tag"),
        "checked_files": len(declared),
        "mutable_paths": mutable_paths,
        "errors": errors,
        "warnings": warnings,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    sys.exit(main())
