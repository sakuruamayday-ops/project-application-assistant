from __future__ import annotations

import json
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

    for variable in ("JIAOTANG_KB_ENDPOINT", "JIAOTANG_KB_TOKEN", "QCC_API_KEY"):
        checks.append(_env_check(variable))

    config_dir = Path(os.environ.get("PROJECT_ASSISTANT_CONFIG_DIR", Path.home() / ".config" / "project-assistant"))
    capability_path = config_dir / "capabilities.json"
    if not capability_path.is_file():
        checks.append(Check("unified_onboarding", "warning", "尚未运行 first-run-configuration"))
        return checks
    try:
        report = json.loads(capability_path.read_text(encoding="utf-8"))
        capabilities = report.get("capabilities", {})
        for name, item in capabilities.items():
            if isinstance(item, dict):
                status = str(item.get("status") or "warning")
                normalized = "ok" if status in {"ready", "configured"} else status
                checks.append(Check(f"capability_{name}", normalized, str(item.get("detail") or "")))
    except (OSError, json.JSONDecodeError, AttributeError):
        checks.append(Check("unified_onboarding", "error", "能力报告损坏，请重新运行统一向导"))
    return checks
