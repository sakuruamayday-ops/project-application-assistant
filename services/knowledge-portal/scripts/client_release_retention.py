#!/usr/bin/env python3
"""Keep desktop artifacts for the current and previous production releases."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from release_retention import directory_reclaimable_bytes


VERSIONED_ASSET_PATTERN = re.compile(
    r"^Gongchuang-Enterprise-Assistant-(?P<version>\d+\.\d+\.\d+)-"
    r"(?:mac-(?:arm64|x64)\.(?:dmg|zip)(?:\.blockmap)?|"
    r"win-x64\.(?:exe|zip)(?:\.blockmap)?)$"
)
FIXED_MACOS_MANIFESTS = {
    "desktop-release-index.json",
    "desktop-release-index.sig",
}
FIXED_WINDOWS_MANIFEST = "latest.yml"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def default_database() -> Path:
    return Path(os.environ.get("JIAOTANG_DATA_DIR", "/var/lib/jiaotang-kb")) / (
        "knowledge.db"
    )


def default_release_root() -> Path:
    return Path(
        os.environ.get(
            "JIAOTANG_CLIENT_RELEASE_DIR",
            "/var/lib/jiaotang-kb/desktop-client-releases",
        )
    )


def require_regular_file(path: Path, description: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"{description}不是普通文件：{path}")
    return path.resolve(strict=True)


def client_cleanup_backlog(trash_root: Path) -> dict[str, Any]:
    targets: list[dict[str, Any]] = []
    try:
        children = sorted(trash_root.iterdir(), key=lambda item: item.name)
    except FileNotFoundError:
        children = []
    for child in children:
        if not child.name.startswith("desktop-client-v"):
            continue
        if child.is_symlink():
            state = "symlink_requires_manual_review"
            reclaimable = 0
        elif child.is_dir():
            state = "recoverable_client_release_trash"
            reclaimable = directory_reclaimable_bytes(child)
        else:
            state = "special_file_requires_manual_review"
            reclaimable = 0
        targets.append(
            {
                "path": str(child.resolve(strict=False)),
                "reclaimable_bytes": reclaimable,
                "state": state,
            }
        )
    plan = {
        "schema": "jiaotang-client-release-cleanup-plan/v1",
        "trash_root": str(trash_root.resolve(strict=False)),
        "targets": targets,
    }
    plan_sha256 = hashlib.sha256(
        json.dumps(
            plan,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        **plan,
        "required": bool(targets),
        "target_count": len(targets),
        "reclaimable_bytes": sum(
            int(item["reclaimable_bytes"]) for item in targets
        ),
        "plan_sha256": plan_sha256,
        "authorization_required": bool(targets),
        "permanent_delete_applied": False,
    }


def read_release_state(
    database: Path,
) -> tuple[list[dict[str, Any]], set[str]]:
    require_regular_file(database, "客户端发布数据库")
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        published = connection.execute(
            """
            SELECT id,version,status,published_at
            FROM client_releases
            WHERE status='published' AND published_at IS NOT NULL
            ORDER BY published_at DESC,id DESC
            """
        ).fetchall()
        if len(published) != 1:
            identities = [(row["id"], row["version"]) for row in published]
            raise RuntimeError(
                f"正式客户端记录数量不是1：{identities}"
            )
        current = published[0]
        previous = connection.execute(
            """
            SELECT id,version,status,published_at
            FROM client_releases
            WHERE status='retired' AND published_at IS NOT NULL
            ORDER BY published_at DESC,id DESC
            LIMIT 1
            """
        ).fetchone()
        retained_rows = [current] + ([previous] if previous is not None else [])
        retained: list[dict[str, Any]] = []
        for row in retained_rows:
            version = str(row["version"])
            if re.fullmatch(r"\d+\.\d+\.\d+", version) is None:
                raise RuntimeError(f"客户端版本不是规范语义版本：{version}")
            artifacts = connection.execute(
                """
                SELECT platform,architecture,file_kind,file_name,file_path,size_bytes
                FROM client_release_artifacts
                WHERE release_id=?
                ORDER BY platform,architecture,file_kind
                """,
                (int(row["id"]),),
            ).fetchall()
            if not artifacts:
                raise RuntimeError(f"客户端版本 {version} 没有制品记录")
            retained.append(
                {
                    **dict(row),
                    "artifacts": [dict(artifact) for artifact in artifacts],
                }
            )
        retired_versions = {
            str(row["version"])
            for row in connection.execute(
                """
                SELECT version FROM client_releases
                WHERE status='retired' AND published_at IS NOT NULL
                """
            ).fetchall()
        }
    finally:
        connection.close()
    return retained, retired_versions


def validate_retained_artifacts(
    retained: list[dict[str, Any]], release_root: Path
) -> None:
    for release in retained:
        version = str(release["version"])
        for artifact in release["artifacts"]:
            path = require_regular_file(
                Path(str(artifact["file_path"])),
                f"客户端 {version} 制品",
            )
            try:
                path.relative_to(release_root)
            except ValueError:
                raise RuntimeError(f"客户端制品不在正式发布根目录：{path}") from None
            if path.name != str(artifact["file_name"]):
                raise RuntimeError(f"客户端制品文件名与数据库不一致：{path}")
            match = VERSIONED_ASSET_PATTERN.fullmatch(path.name)
            if match is None or match.group("version") != version:
                raise RuntimeError(f"客户端制品版本身份不一致：{path.name}")
            if path.stat().st_size != int(artifact["size_bytes"]):
                raise RuntimeError(f"客户端制品体积与数据库不一致：{path}")


def validate_fixed_manifests(release_root: Path, current_version: str) -> None:
    macos_root = release_root / "v0.2" / "macos"
    windows_root = release_root / "v0.2" / "windows"
    manifest_path = require_regular_file(
        macos_root / "desktop-release-index.json",
        "macOS 更新清单",
    )
    require_regular_file(
        macos_root / "desktop-release-index.sig",
        "macOS 更新清单签名",
    )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("macOS 更新清单无法解析") from error
    if manifest.get("clientVersion") != current_version:
        raise RuntimeError("macOS 更新清单与当前正式客户端版本不一致")

    windows_manifest = require_regular_file(
        windows_root / FIXED_WINDOWS_MANIFEST,
        "Windows 更新清单",
    )
    try:
        windows_text = windows_manifest.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise RuntimeError("Windows 更新清单无法读取") from error
    version_lines = re.findall(r"(?m)^version:\s*([^\s]+)\s*$", windows_text)
    if version_lines != [current_version]:
        raise RuntimeError("Windows 更新清单与当前正式客户端版本不一致")


def plan_client_release_retention(
    database: Path,
    release_root: Path,
) -> dict[str, Any]:
    if release_root.is_symlink() or not release_root.is_dir():
        raise RuntimeError("客户端发布根目录必须是实体目录")
    release_root = release_root.resolve(strict=True)
    if release_root == Path("/"):
        raise RuntimeError("客户端发布根目录不得为系统根目录")
    retained, retired_versions = read_release_state(database)
    current_version = str(retained[0]["version"])
    retained_versions = {str(row["version"]) for row in retained}
    validate_retained_artifacts(retained, release_root)
    validate_fixed_manifests(release_root, current_version)

    candidates: list[dict[str, Any]] = []
    for platform_root in (
        release_root / "v0.2" / "macos",
        release_root / "v0.2" / "windows",
    ):
        if platform_root.is_symlink() or not platform_root.is_dir():
            raise RuntimeError(f"客户端平台发布目录必须是实体目录：{platform_root}")
        for child in sorted(platform_root.iterdir(), key=lambda item: item.name):
            if child.name in FIXED_MACOS_MANIFESTS | {FIXED_WINDOWS_MANIFEST}:
                continue
            match = VERSIONED_ASSET_PATTERN.fullmatch(child.name)
            if match is None:
                continue
            version = match.group("version")
            if version in retained_versions:
                continue
            if version not in retired_versions:
                raise RuntimeError(f"发现未退役版本的游离客户端制品：{child}")
            if child.is_symlink() or not child.is_file():
                raise RuntimeError(f"旧客户端制品不是普通文件：{child}")
            candidates.append(
                {
                    "path": str(child),
                    "version": version,
                    "bytes": child.stat().st_size,
                }
            )
    return {
        "schema": "jiaotang-client-release-retention/v1",
        "checked_at": utc_now(),
        "database": str(database.resolve(strict=True)),
        "release_root": str(release_root),
        "current": current_version,
        "previous": (
            str(retained[1]["version"]) if len(retained) > 1 else None
        ),
        "retained_versions": sorted(retained_versions),
        "candidates": candidates,
        "candidate_count": len(candidates),
        "candidate_bytes": sum(int(item["bytes"]) for item in candidates),
        "applied": False,
    }


def prune_client_release_artifacts(
    database: Path,
    release_root: Path,
    *,
    apply: bool,
    trash_root: Path | None = None,
) -> dict[str, Any]:
    report = plan_client_release_retention(database, release_root)
    release_root = Path(str(report["release_root"]))
    if trash_root is None:
        trash_root = release_root / ".Trash" / "files"
    trash_root = trash_root.expanduser()
    trashed: list[dict[str, Any]] = []
    if apply:
        if trash_root == Path("/") or trash_root.is_symlink():
            raise RuntimeError("客户端制品回收区不得为系统根目录或符号链接")
        trash_root.mkdir(parents=True, exist_ok=True)
        trash_root = trash_root.resolve(strict=True)
        if release_root.stat().st_dev != trash_root.stat().st_dev:
            raise RuntimeError("客户端制品与回收区不在同一文件系统")
        groups: dict[str, Path] = {}
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        for item in report["candidates"]:
            source = Path(str(item["path"]))
            version = str(item["version"])
            destination_root = groups.get(version)
            if destination_root is None:
                destination_root = trash_root / (
                    f"desktop-client-v{version}-{timestamp}-"
                    f"{os.getpid()}-{secrets.token_hex(4)}"
                )
                destination_root.mkdir(mode=0o700)
                groups[version] = destination_root
            destination = destination_root / source.name
            try:
                os.rename(source, destination)
            except FileNotFoundError:
                if source.exists() or source.is_symlink():
                    raise
                continue
            trashed.append({**item, "trash_path": str(destination)})
        report["applied"] = True
        report["delete_mode"] = "recoverable_system_trash"
        report["trash_root"] = str(trash_root)
    report["trashed"] = trashed
    report["trashed_count"] = len(trashed)
    report["trashed_bytes"] = sum(int(item["bytes"]) for item in trashed)
    report["cleanup_pending"] = client_cleanup_backlog(trash_root)
    report["completed_at"] = utc_now()
    return report


def atomic_write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    )
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="保留当前与上一版桌面客户端制品，其余移入服务器回收区"
    )
    parser.add_argument("--database", type=Path, default=default_database())
    parser.add_argument("--release-root", type=Path, default=default_release_root())
    parser.add_argument("--trash-root", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("/var/lib/jiaotang-kb/client-release-retention.json"),
    )
    args = parser.parse_args()
    report = prune_client_release_artifacts(
        args.database,
        args.release_root,
        apply=args.apply,
        trash_root=args.trash_root,
    )
    atomic_write_report(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
