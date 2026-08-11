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
    for version, release in releases.items():
        if not isinstance(release, dict):
            raise ValueError(f"V{version} 功能简介必须是对象")
        features = release.get("new_features")
        profile_name = str(release.get("core_profile") or "")
        if (
            not isinstance(features, list)
            or not features
            or not all(isinstance(item, str) and item.strip() for item in features)
        ):
            raise ValueError(f"V{version} 缺少本版本新增功能")
        profile = profiles.get(profile_name)
        if (
            not isinstance(profile, list)
            or not profile
            or not all(isinstance(item, str) and item.strip() for item in profile)
        ):
            raise ValueError(f"V{version} 引用了无效的核心功能配置：{profile_name}")
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
    profile = profiles[str(release["core_profile"])]
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
        *(f"- {item.strip()}" for item in profile),
    ]
    return "\n".join(lines).strip() + "\n"


def release_introduction_versions(
    *,
    catalog_path: Path = DEFAULT_CATALOG_PATH,
) -> tuple[str, ...]:
    catalog = load_release_introduction_catalog(str(catalog_path.resolve()))
    return tuple(str(version) for version in catalog["releases"])
