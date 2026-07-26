#!/usr/bin/env python3
"""Publish an already-signed generic + WorkBuddy release to the portal."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_members(archive: zipfile.ZipFile) -> list[str]:
    names: list[str] = []
    for info in archive.infolist():
        name = info.filename
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name:
            raise ValueError(f"ZIP 包含不安全路径：{name}")
        names.append(name)
    return names


def _single_json(archive: zipfile.ZipFile, suffix: str) -> dict[str, object]:
    matches = [name for name in _safe_members(archive) if name.endswith(suffix)]
    if len(matches) != 1:
        raise ValueError(f"ZIP 中应且仅应包含一个 {suffix}，实际 {len(matches)} 个")
    value = json.loads(archive.read(matches[0]).decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{suffix} 必须是 JSON 对象")
    return value


def validate_packages(generic: Path, workbuddy: Path, version: str) -> dict[str, object]:
    release_tag = f"V{version}"
    semantic_version = f"{version}.0"
    with zipfile.ZipFile(generic) as archive:
        suite = _single_json(archive, "/skills/suite-manifest.json")
        release = suite.get("release")
        if not isinstance(release, dict):
            raise ValueError("通用包 suite-manifest 缺少 release")
        if release.get("tag") != release_tag or release.get("version") != semantic_version:
            raise ValueError("通用包版本与发布版本不一致")
        skills = suite.get("skills")
        if (
            not isinstance(skills, list)
            or not skills
            or not all(isinstance(name, str) and name.strip() for name in skills)
            or len(set(skills)) != len(skills)
        ):
            raise ValueError("通用包技能清单必须为非空、无重复的字符串数组")
    with zipfile.ZipFile(workbuddy) as archive:
        marketplace = _single_json(archive, "/.codebuddy-plugin/marketplace.json")
        plugin = _single_json(archive, "/.codebuddy-plugin/plugin.json")
        suite = _single_json(archive, "/skills/suite-manifest.json")
        plugins = marketplace.get("plugins")
        marketplace_version = plugins[0].get("version") if isinstance(plugins, list) and plugins else None
        if marketplace_version != semantic_version or plugin.get("version") != semantic_version:
            raise ValueError("WorkBuddy 市场清单或插件版本与发布版本不一致")
        release = suite.get("release")
        if not isinstance(release, dict) or release.get("tag") != release_tag:
            raise ValueError("WorkBuddy 技能清单与发布版本不一致")
        workbuddy_skills = suite.get("skills")
        if workbuddy_skills != skills:
            raise ValueError("WorkBuddy 与通用包的技能清单不一致")
    return {
        "version": version,
        "skill_count": len(skills),
        "generic_sha256": sha256(generic),
        "workbuddy_sha256": sha256(workbuddy),
    }


def _install_file(source: Path, target: Path) -> None:
    if target.exists():
        if sha256(target) == sha256(source):
            return
        raise RuntimeError(f"目标文件已存在且内容不同：{target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _ensure_stage_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS skill_release_stages(
            version TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            generic_path TEXT NOT NULL,
            generic_sha256 TEXT NOT NULL,
            workbuddy_path TEXT NOT NULL,
            workbuddy_sha256 TEXT NOT NULL,
            release_notes TEXT NOT NULL,
            git_commit TEXT NOT NULL,
            github_url TEXT NOT NULL,
            staged_at TEXT NOT NULL,
            promoted_at TEXT
        )
        """
    )


def stage(
    database_path: Path,
    release_directory: Path,
    generic_package: Path,
    workbuddy_package: Path,
    version: str,
    release_notes: str,
    git_commit: str,
    github_url: str,
) -> dict[str, object]:
    validation = validate_packages(generic_package, workbuddy_package, version)
    stage_directory = release_directory / ".staging" / f"V{version}"
    generic_target = stage_directory / f"企业全生命周期助手-V{version}.zip"
    workbuddy_target = (
        stage_directory / f"企业全生命周期助手-V{version}-WorkBuddy.zip"
    )
    release_directory.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        _ensure_stage_table(connection)
        if connection.execute(
            "SELECT 1 FROM skill_releases WHERE version=?", (version,)
        ).fetchone():
            raise RuntimeError(f"版本 {version} 已正式发布，不能重新进入发布中")
        existing = connection.execute(
            "SELECT * FROM skill_release_stages WHERE version=?", (version,)
        ).fetchone()
        if existing is not None:
            if (
                str(existing["status"]) == "releasing"
                and str(existing["generic_sha256"]) == validation["generic_sha256"]
                and str(existing["workbuddy_sha256"])
                == validation["workbuddy_sha256"]
                and Path(str(existing["generic_path"])).is_file()
                and Path(str(existing["workbuddy_path"])).is_file()
                and sha256(Path(str(existing["generic_path"])))
                == str(existing["generic_sha256"])
                and sha256(Path(str(existing["workbuddy_path"])))
                == str(existing["workbuddy_sha256"])
            ):
                return {
                    **validation,
                    "status": "already-staged",
                    "release_state": "releasing",
                    "github_url": str(existing["github_url"]),
                }
            raise RuntimeError(f"版本 {version} 已有不同内容的发布中记录")
        _install_file(generic_package, generic_target)
        _install_file(workbuddy_package, workbuddy_target)
        staged_at = datetime.now(timezone.utc).isoformat()
        connection.execute(
            """
            INSERT INTO skill_release_stages(
                version,status,generic_path,generic_sha256,
                workbuddy_path,workbuddy_sha256,release_notes,
                git_commit,github_url,staged_at,promoted_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,NULL)
            """,
            (
                version,
                "releasing",
                str(generic_target),
                validation["generic_sha256"],
                str(workbuddy_target),
                validation["workbuddy_sha256"],
                release_notes.strip(),
                git_commit.strip(),
                github_url.strip(),
                staged_at,
            ),
        )
        connection.commit()
    return {
        **validation,
        "status": "staged",
        "release_state": "releasing",
        "github_url": github_url.strip(),
        "staged_at": staged_at,
    }


def publish(
    database_path: Path,
    release_directory: Path,
    generic_package: Path,
    workbuddy_package: Path,
    version: str,
    release_notes: str,
) -> dict[str, object]:
    validation = validate_packages(generic_package, workbuddy_package, version)
    generic_target = release_directory / f"企业全生命周期助手-V{version}.zip"
    workbuddy_target = release_directory / f"企业全生命周期助手-V{version}-WorkBuddy.zip"
    release_directory.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        existing = connection.execute(
            "SELECT * FROM skill_releases WHERE version=?", (version,)
        ).fetchone()
        if existing is not None:
            if (
                str(existing["sha256"]) == validation["generic_sha256"]
                and Path(str(existing["file_path"])).is_file()
                and workbuddy_target.is_file()
                and sha256(workbuddy_target) == validation["workbuddy_sha256"]
            ):
                return {**validation, "release_id": int(existing["id"]), "status": "already-published"}
            raise RuntimeError(f"版本 {version} 已存在，但发布文件或哈希不一致")

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = database_path.with_name(f"{database_path.name}.before-v{version}-{timestamp}")
        with sqlite3.connect(backup_path) as backup:
            connection.backup(backup)

        _install_file(generic_package, generic_target)
        _install_file(workbuddy_package, workbuddy_target)
        published_at = datetime.now(timezone.utc).isoformat()
        cursor = connection.execute(
            """
            INSERT INTO skill_releases(
                version,file_name,file_path,sha256,release_notes,published_at
            ) VALUES (?,?,?,?,?,?)
            """,
            (
                version,
                generic_target.name,
                str(generic_target),
                validation["generic_sha256"],
                release_notes.strip(),
                published_at,
            ),
        )
        connection.commit()
    return {
        **validation,
        "release_id": int(cursor.lastrowid),
        "status": "published",
        "database_backup": str(backup_path),
        "generic_path": str(generic_target),
        "workbuddy_path": str(workbuddy_target),
    }


def promote(
    database_path: Path,
    release_directory: Path,
    version: str,
) -> dict[str, object]:
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        _ensure_stage_table(connection)
        staged = connection.execute(
            "SELECT * FROM skill_release_stages WHERE version=?", (version,)
        ).fetchone()
    if staged is None or str(staged["status"]) != "releasing":
        raise RuntimeError(f"版本 {version} 未处于正式发布中，禁止确认发布")
    generic_package = Path(str(staged["generic_path"]))
    workbuddy_package = Path(str(staged["workbuddy_path"]))
    if not generic_package.is_file() or not workbuddy_package.is_file():
        raise RuntimeError("正式发布中的候选包缺失")
    if (
        sha256(generic_package) != str(staged["generic_sha256"])
        or sha256(workbuddy_package) != str(staged["workbuddy_sha256"])
    ):
        raise RuntimeError("正式发布中的候选包哈希发生变化")
    result = publish(
        database_path,
        release_directory,
        generic_package,
        workbuddy_package,
        version,
        str(staged["release_notes"]),
    )
    promoted_at = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            UPDATE skill_release_stages
            SET status='published',promoted_at=?
            WHERE version=? AND status='releasing'
            """,
            (promoted_at, version),
        )
        connection.commit()
    return {
        **result,
        "release_state": "published",
        "promoted_at": promoted_at,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="两阶段发布已签名的通用与 WorkBuddy 技能包"
    )
    parser.add_argument("--mode", choices=("stage", "promote"), required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--generic-package", type=Path)
    parser.add_argument("--workbuddy-package", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--release-notes-file", type=Path)
    parser.add_argument("--git-commit", default="")
    parser.add_argument("--github-url", default="")
    arguments = parser.parse_args()
    if arguments.mode == "stage":
        if (
            arguments.generic_package is None
            or arguments.workbuddy_package is None
            or arguments.release_notes_file is None
            or not arguments.git_commit.strip()
            or not arguments.github_url.strip()
        ):
            parser.error(
                "stage模式必须提供候选包、发布说明、git提交和GitHub预发布地址"
            )
        result = stage(
            arguments.database,
            arguments.release_dir,
            arguments.generic_package,
            arguments.workbuddy_package,
            arguments.version,
            arguments.release_notes_file.read_text(encoding="utf-8"),
            arguments.git_commit,
            arguments.github_url,
        )
    else:
        result = promote(
            arguments.database,
            arguments.release_dir,
            arguments.version,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
