#!/usr/bin/env python3
"""Keep the compact portable-runtime notice identical across every skill."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


START = "<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->"
END = "<!-- END MANAGED PORTABLE SKILL RUNTIME -->"
# Canonical authoring source, also consumed by the release-manager patch.
NOTICE = Path(__file__).resolve().parents[1] / "toolchain-candidates/skill-release-manager/references/portable-runtime-notice.md"
BLOCK = NOTICE.read_text(encoding="utf-8").rstrip()



def replace_block(path: Path, *, check: bool) -> bool:
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(re.escape(START) + r"[\s\S]*?" + re.escape(END))
    matches = pattern.findall(text)
    if len(matches) != 1:
        raise RuntimeError(f"托管便携运行区块缺失或重复：{path}")
    updated = pattern.sub(BLOCK, text)
    changed = updated != text
    if changed and not check:
        path.write_text(updated, encoding="utf-8")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description="同步全部技能的托管便携运行说明")
    parser.add_argument(
        "--skills-root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "skills",
    )
    parser.add_argument("--check", action="store_true")
    options = parser.parse_args()

    paths = sorted(options.skills_root.glob("*/SKILL.md"))
    changed = [path for path in paths if replace_block(path, check=options.check)]
    if options.check and changed:
        print("便携运行说明未同步：")
        for path in changed:
            print(f"- {path}")
        return 1
    print(f"已检查 {len(paths)} 项技能，变更 {len(changed)} 项。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
