from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any


SUPPORTED_PLATFORMS = ("codex", "claude-code", "hermes")


def platform_home(platform: str, config: dict[str, Any]) -> Path:
    discovery = config.get("discovery", {})
    key = "user_skills_install_dir" if platform == "hermes" else "skills_install_dir"
    raw = discovery.get(key)
    defaults = {
        "codex": Path.home() / ".codex" / "skills",
        "claude-code": Path.home() / ".claude" / "skills",
        "hermes": Path.home() / ".hermes" / "skills",
    }
    if not raw:
        return defaults[platform]
    expanded = os.path.expandvars(os.path.expanduser(str(raw)))
    if "${" in expanded:
        return defaults[platform]
    return Path(expanded)


def command_status(platform: str) -> tuple[bool, str]:
    command = {
        "codex": "codex",
        "claude-code": "claude",
        "hermes": "hermes",
    }[platform]
    path = shutil.which(command)
    return (bool(path), path or "未发现")


def install_skills(source: Path, destination: Path, mode: str, force: bool) -> list[str]:
    if mode not in {"copy", "symlink"}:
        raise ValueError("安装模式必须是 copy 或 symlink")
    if not source.is_dir():
        raise FileNotFoundError(f"技能源目录不存在：{source}")

    destination.mkdir(parents=True, exist_ok=True)
    installed: list[str] = []
    for skill_dir in sorted(path for path in source.iterdir() if (path / "SKILL.md").is_file()):
        target = destination / skill_dir.name
        if target.exists() or target.is_symlink():
            if not force:
                continue
            if target.is_symlink() or target.is_file():
                target.unlink()
            else:
                shutil.rmtree(target)
        if mode == "symlink":
            target.symlink_to(skill_dir.resolve(), target_is_directory=True)
        else:
            shutil.copytree(skill_dir, target)
        installed.append(skill_dir.name)
    return installed
