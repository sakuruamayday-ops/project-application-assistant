#!/usr/bin/env python3
"""Keep the compact portable-runtime notice identical across every skill."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


START = "<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->"
END = "<!-- END MANAGED PORTABLE SKILL RUNTIME -->"
BLOCK = f"""{START}
## 便携运行门禁

每次触发时，从宿主提供或当前已读取的 `SKILL.md` 实际路径定位本技能目录，并运行其 `scripts/portable_skill_runtime.py prepare`。不得假设特定宿主变量或猜测路径。

宿主若只暴露 `run_code`，`skill`、`read`、`web_search`、校验器等工具均须在其中以 `await tools.<name>(...)` 调用，不得根级调用隐藏工具。先按 `SKILL.md` 或参考文档执行命令；不得为理解用法预读脚本、模板、示例或测试，只有真实命令报错且契约不明确时才读取直接相关源码。

`fail` 表示签名、发布者身份或完整性失败，必须停用受影响副本；`limited` 表示已验签副本的依赖或偏好读写受限，仅在任务所需能力仍满足时继续并说明边界。只应用返回的 `active_preferences`；临时要求不持久化，明确授权的长期习惯才按协议保存。偏好不得覆盖真实性、安全、验签和质量门禁。完整规则见[便携运行协议](references/portable-runtime-protocol.md)。
{END}"""


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
