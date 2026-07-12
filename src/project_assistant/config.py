from __future__ import annotations

import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


ENV_PATTERN = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")


class ConfigError(ValueError):
    pass


def expand_environment(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: expand_environment(item) for key, item in value.items()}
    if isinstance(value, list):
        return [expand_environment(item) for item in value]
    if not isinstance(value, str):
        return value

    def replace(match: re.Match[str]) -> str:
        return os.environ.get(match.group(1), match.group(0))

    return ENV_PATTERN.sub(replace, value)


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(f"配置文件不存在：{path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML解析失败：{path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"配置文件顶层必须是对象：{path}")
    return data


def load_config(project_root: Path, platform: str) -> dict[str, Any]:
    common_path = project_root / "config" / "common.yaml"
    platform_path = project_root / "config" / "platforms" / f"{platform}.yaml"
    common = load_yaml(common_path)
    platform_config = load_yaml(platform_path)
    config = expand_environment(deep_merge(common, platform_config))
    config["_meta"] = {
        "project_root": str(project_root.resolve()),
        "common_config": str(common_path.resolve()),
        "platform_config": str(platform_path.resolve()),
    }
    return config


def unresolved_environment(config: Any) -> list[str]:
    unresolved: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, str):
            unresolved.update(ENV_PATTERN.findall(value))

    visit(config)
    return sorted(unresolved)

