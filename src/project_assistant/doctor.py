from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import unresolved_environment
from .platforms import command_status, platform_home


@dataclass
class Check:
    name: str
    status: str
    detail: str


def _env_check(name: str) -> Check:
    return Check(name, "ok" if os.environ.get(name) else "optional", "已配置" if os.environ.get(name) else "未配置")


def run_checks(platform: str, config: dict[str, Any], project_root: Path) -> list[Check]:
    checks: list[Check] = []
    installed, command = command_status(platform)
    checks.append(Check("platform_command", "ok" if installed else "warning", command))

    skills_source = project_root / "skills"
    checks.append(Check("skills_source", "ok" if skills_source.is_dir() else "error", str(skills_source)))

    destination = platform_home(platform, config)
    checks.append(Check("skills_destination", "ok" if destination.parent.exists() else "warning", str(destination)))

    unresolved = unresolved_environment(config)
    checks.append(Check("environment_placeholders", "warning" if unresolved else "ok", ", ".join(unresolved) or "全部已解析"))

    for variable in ("QCC_MCP_TOKEN", "PADDLE_OCR_API_KEY", "AIQICE_USERNAME", "FEISHU_APP_ID"):
        checks.append(_env_check(variable))

    obsidian = config.get("providers", {}).get("obsidian", {})
    vault = obsidian.get("vault_path")
    if obsidian.get("enabled"):
        valid = bool(vault and Path(os.path.expanduser(str(vault))).is_dir())
        checks.append(Check("obsidian", "ok" if valid else "error", str(vault or "未设置Vault路径")))
    else:
        checks.append(Check("obsidian", "optional", "未启用"))
    return checks

