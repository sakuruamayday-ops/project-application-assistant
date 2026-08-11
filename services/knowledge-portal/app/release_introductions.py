from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


DEFAULT_CATALOG_PATH = (
    Path(__file__).resolve().parents[1]
    / "references"
    / "release-function-introductions.json"
)


def normalize_release_version(value: str) -> str:
    return str(value or "").strip().removeprefix("V")


def _validated_feature_list(value: object, *, error: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item.strip() for item in value)
    ):
        raise ValueError(error)
    return [str(item).strip() for item in value]


@lru_cache(maxsize=4)
def load_release_introduction_catalog(
    catalog_path: str = str(DEFAULT_CATALOG_PATH),
) -> dict[str, object]:
    path = Path(catalog_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "gongchuang-release-function-introductions/v1":
        raise ValueError("功能简介目录 schema 不受支持")
    profiles = payload.get("core_profiles")
    releases = payload.get("releases")
    if not isinstance(profiles, dict) or not isinstance(releases, dict):
        raise ValueError("功能简介目录缺少 core_profiles 或 releases")
    carry_forward_policy = payload.get("carry_forward_policy")
    if not isinstance(carry_forward_policy, dict):
        raise ValueError("功能简介目录缺少上一版本重要功能继承策略")
    enabled_from = normalize_release_version(
        str(carry_forward_policy.get("enabled_from") or "")
    )
    if carry_forward_policy.get("mode") != "previous_release_important_features":
        raise ValueError("功能简介目录的上一版本重要功能继承模式不受支持")
    ordered_versions = tuple(str(version) for version in releases)
    if enabled_from not in ordered_versions:
        raise ValueError("功能简介目录的继承策略起始版本不存在")
    enabled_index = ordered_versions.index(enabled_from)
    for version, release in releases.items():
        if not isinstance(release, dict):
            raise ValueError(f"V{version} 功能简介必须是对象")
        _validated_feature_list(
            release.get("new_features"),
            error=f"V{version} 缺少本版本新增功能",
        )
        profile_name = str(release.get("core_profile") or "")
        profile = profiles.get(profile_name)
        _validated_feature_list(
            profile,
            error=f"V{version} 引用了无效的核心功能配置：{profile_name}",
        )
    for index in range(max(enabled_index - 1, 0), len(ordered_versions)):
        version = ordered_versions[index]
        release = releases[version]
        _validated_feature_list(
            release.get("important_features"),
            error=f"V{version} 缺少供下一版本继承的重要功能",
        )
    return payload


def release_function_introduction(
    version: str,
    fallback: str = "",
    *,
    catalog_path: Path = DEFAULT_CATALOG_PATH,
) -> str:
    normalized = normalize_release_version(version)
    catalog = load_release_introduction_catalog(str(catalog_path.resolve()))
    releases = catalog["releases"]
    profiles = catalog["core_profiles"]
    release = releases.get(normalized)
    if not isinstance(release, dict):
        return fallback
    profile = list(profiles[str(release["core_profile"])])
    ordered_versions = tuple(str(version) for version in releases)
    carry_forward_policy = catalog["carry_forward_policy"]
    enabled_from = normalize_release_version(
        str(carry_forward_policy["enabled_from"])
    )
    release_index = ordered_versions.index(normalized)
    carry_forward: list[str] = []
    if release_index >= ordered_versions.index(enabled_from) and release_index > 0:
        previous_release = releases[ordered_versions[release_index - 1]]
        carry_forward = _validated_feature_list(
            previous_release.get("important_features"),
            error=f"V{normalized} 的上一版本缺少重要功能",
        )
    core_features = list(dict.fromkeys([*carry_forward, *profile]))
    title = str(
        release.get("title")
        or f"共创研究院企业全生命周期助手 V{normalized} 功能简介"
    )
    lines = [
        f"# {title}",
        "",
        "## 一、本版本新增功能",
        "",
        *(f"- {item.strip()}" for item in release["new_features"]),
        "",
        "## 二、原有核心功能",
        "",
        *(f"- {item.strip()}" for item in core_features),
    ]
    return "\n".join(lines).strip() + "\n"


def release_introduction_versions(
    *,
    catalog_path: Path = DEFAULT_CATALOG_PATH,
) -> tuple[str, ...]:
    catalog = load_release_introduction_catalog(str(catalog_path.resolve()))
    return tuple(str(version) for version in catalog["releases"])
