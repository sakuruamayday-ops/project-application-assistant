#!/usr/bin/env python3
"""Publish an already-signed generic + WorkBuddy release to the portal."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
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


def semantic_version(value: str) -> str:
    match = re.fullmatch(
        r"(\d+)\.(\d+)(?:\.(\d+))?(?:\.(\d+))?",
        value.strip(),
    )
    if not match:
        raise ValueError("版本必须形如 1.3、1.3.1 或 1.3.1.1")
    patch = match.group(3) or "0"
    hotfix = f".{match.group(4)}" if match.group(4) is not None else ""
    return f"{match.group(1)}.{match.group(2)}.{patch}{hotfix}"


ARTIFACT_TARGETS = ("generic", "macos", "windows")


def validate_release_packages(
    packages: dict[str, Path],
    version: str,
) -> dict[str, object]:
    """Validate any non-empty combination of independently released clients."""
    invalid = sorted(set(packages) - set(ARTIFACT_TARGETS))
    if invalid:
        raise ValueError("不支持的发布目标：" + "、".join(invalid))
    if not packages:
        raise ValueError("至少提供一个发布包")

    release_tag = f"V{version}"
    expected_version = semantic_version(version)
    canonical_skills: list[str] | None = None
    hashes: dict[str, str] = {}
    for target, package in packages.items():
        with zipfile.ZipFile(package) as archive:
            names = _safe_members(archive)
            suite = _single_json(archive, "/skills/suite-manifest.json")
            release = suite.get("release")
            if not isinstance(release, dict) or (
                release.get("tag") != release_tag
                or release.get("version") != expected_version
            ):
                raise ValueError(f"{target}包版本与发布版本不一致")
            skills = suite.get("skills")
            if (
                not isinstance(skills, list)
                or not skills
                or not all(
                    isinstance(name, str) and name.strip() for name in skills
                )
                or len(set(skills)) != len(skills)
            ):
                raise ValueError(f"{target}包技能清单不合规")
            if canonical_skills is None:
                canonical_skills = skills
            elif skills != canonical_skills:
                raise ValueError("各客户端包的技能清单不一致")

            if target != "generic":
                marketplace = _single_json(
                    archive, "/.codebuddy-plugin/marketplace.json"
                )
                plugin = _single_json(
                    archive, "/.codebuddy-plugin/plugin.json"
                )
                plugins = marketplace.get("plugins")
                marketplace_version = (
                    plugins[0].get("version")
                    if isinstance(plugins, list) and plugins
                    else None
                )
                if (
                    marketplace_version != expected_version
                    or plugin.get("version") != expected_version
                ):
                    raise ValueError(
                        f"{target}包的WorkBuddy插件版本不一致"
                    )
                if not any(
                    name.endswith("/.codebuddy-plugin/marketplace.json")
                    for name in names
                ):
                    raise ValueError(f"{target}包缺少WorkBuddy插件市场清单")
        hashes[target] = sha256(package)

    return {
        "version": version,
        "skill_count": len(canonical_skills or []),
        "targets": list(packages),
        "artifacts": {
            target: {
                "path": str(packages[target]),
                "sha256": hashes[target],
            }
            for target in packages
        },
    }


def validate_packages(generic: Path, workbuddy: Path, version: str) -> dict[str, object]:
    validated = validate_release_packages(
        {"generic": generic, "windows": workbuddy},
        version,
    )
    artifacts = validated["artifacts"]
    return {
        "version": version,
        "skill_count": validated["skill_count"],
        "generic_sha256": artifacts["generic"]["sha256"],
        "workbuddy_sha256": artifacts["windows"]["sha256"],
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
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS skill_release_stage_artifacts(
            version TEXT NOT NULL,
            target TEXT NOT NULL,
            file_path TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            PRIMARY KEY(version,target)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS skill_release_artifacts(
            release_id INTEGER NOT NULL,
            target TEXT NOT NULL,
            file_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            PRIMARY KEY(release_id,target)
        )
        """
    )


def _artifact_name(version: str, target: str) -> str:
    suffix = {
        "generic": "",
        "macos": "-WorkBuddy-macOS",
        "windows": "-WorkBuddy-Windows",
    }[target]
    return f"企业全生命周期助手-V{version}{suffix}.zip"


def stage_selective(
    database_path: Path,
    release_directory: Path,
    packages: dict[str, Path],
    version: str,
    release_notes: str,
    git_commit: str,
    github_url: str,
) -> dict[str, object]:
    validation = validate_release_packages(packages, version)
    stage_directory = release_directory / ".staging" / f"V{version}"
    release_directory.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        _ensure_stage_table(connection)
        if connection.execute(
            "SELECT 1 FROM skill_releases WHERE version=?", (version,)
        ).fetchone():
            raise RuntimeError(f"版本 {version} 已正式发布")
        existing = connection.execute(
            "SELECT * FROM skill_release_stages WHERE version=?", (version,)
        ).fetchone()
        if existing is not None:
            rows = connection.execute(
                """
                SELECT target,file_path,sha256
                FROM skill_release_stage_artifacts
                WHERE version=? ORDER BY target
                """,
                (version,),
            ).fetchall()
            existing_hashes = {
                str(row["target"]): str(row["sha256"]) for row in rows
            }
            expected_hashes = {
                target: str(data["sha256"])
                for target, data in validation["artifacts"].items()
            }
            if (
                str(existing["status"]) == "releasing"
                and existing_hashes == expected_hashes
                and all(
                    Path(str(row["file_path"])).is_file()
                    and sha256(Path(str(row["file_path"])))
                    == str(row["sha256"])
                    for row in rows
                )
            ):
                return {
                    **validation,
                    "status": "already-staged",
                    "release_state": "releasing",
                    "github_url": str(existing["github_url"]),
                }
            raise RuntimeError(f"版本 {version} 已有不同内容的发布中记录")

        installed: dict[str, Path] = {}
        for target, source in packages.items():
            destination = stage_directory / _artifact_name(version, target)
            _install_file(source, destination)
            installed[target] = destination
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
                str(installed.get("generic", "")),
                validation["artifacts"].get("generic", {}).get("sha256", ""),
                str(
                    installed.get("windows")
                    or installed.get("macos")
                    or ""
                ),
                validation["artifacts"].get(
                    "windows",
                    validation["artifacts"].get("macos", {}),
                ).get("sha256", ""),
                release_notes.strip(),
                git_commit.strip(),
                github_url.strip(),
                staged_at,
            ),
        )
        connection.executemany(
            """
            INSERT INTO skill_release_stage_artifacts(
                version,target,file_path,sha256
            ) VALUES (?,?,?,?)
            """,
            [
                (
                    version,
                    target,
                    str(installed[target]),
                    validation["artifacts"][target]["sha256"],
                )
                for target in packages
            ],
        )
        connection.commit()
    return {
        **validation,
        "status": "staged",
        "release_state": "releasing",
        "github_url": github_url.strip(),
        "staged_at": staged_at,
    }


def publish_selective(
    database_path: Path,
    release_directory: Path,
    packages: dict[str, Path],
    version: str,
    release_notes: str,
) -> dict[str, object]:
    validation = validate_release_packages(packages, version)
    release_directory.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        _ensure_stage_table(connection)
        existing = connection.execute(
            "SELECT * FROM skill_releases WHERE version=?", (version,)
        ).fetchone()
        if existing is not None:
            rows = connection.execute(
                """
                SELECT target,file_path,sha256
                FROM skill_release_artifacts
                WHERE release_id=? ORDER BY target
                """,
                (int(existing["id"]),),
            ).fetchall()
            existing_hashes = {
                str(row["target"]): str(row["sha256"]) for row in rows
            }
            expected_hashes = {
                target: str(data["sha256"])
                for target, data in validation["artifacts"].items()
            }
            if existing_hashes == expected_hashes and all(
                Path(str(row["file_path"])).is_file()
                and sha256(Path(str(row["file_path"])))
                == str(row["sha256"])
                for row in rows
            ):
                return {
                    **validation,
                    "release_id": int(existing["id"]),
                    "status": "already-published",
                }
            raise RuntimeError(f"版本 {version} 已存在，但目标或哈希不一致")

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = database_path.with_name(
            f"{database_path.name}.before-v{version}-{timestamp}"
        )
        with sqlite3.connect(backup_path) as backup:
            connection.backup(backup)
        installed: dict[str, Path] = {}
        for target, source in packages.items():
            destination = release_directory / _artifact_name(version, target)
            _install_file(source, destination)
            installed[target] = destination
        primary_target = next(
            target
            for target in ("generic", "windows", "macos")
            if target in installed
        )
        primary = installed[primary_target]
        published_at = datetime.now(timezone.utc).isoformat()
        cursor = connection.execute(
            """
            INSERT INTO skill_releases(
                version,file_name,file_path,sha256,release_notes,published_at
            ) VALUES (?,?,?,?,?,?)
            """,
            (
                version,
                primary.name,
                str(primary),
                validation["artifacts"][primary_target]["sha256"],
                release_notes.strip(),
                published_at,
            ),
        )
        release_id = int(cursor.lastrowid)
        connection.executemany(
            """
            INSERT INTO skill_release_artifacts(
                release_id,target,file_name,file_path,sha256
            ) VALUES (?,?,?,?,?)
            """,
            [
                (
                    release_id,
                    target,
                    installed[target].name,
                    str(installed[target]),
                    validation["artifacts"][target]["sha256"],
                )
                for target in packages
            ],
        )
        connection.commit()
    return {
        **validation,
        "release_id": release_id,
        "status": "published",
        "database_backup": str(backup_path),
    }


def promote_selective(
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
        rows = connection.execute(
            """
            SELECT target,file_path,sha256
            FROM skill_release_stage_artifacts
            WHERE version=? ORDER BY target
            """,
            (version,),
        ).fetchall()
    if staged is None or str(staged["status"]) != "releasing" or not rows:
        raise RuntimeError(f"版本 {version} 未处于可提升的正式发布中")
    packages = {
        str(row["target"]): Path(str(row["file_path"])) for row in rows
    }
    if any(
        not path.is_file()
        or sha256(path)
        != next(
            str(row["sha256"])
            for row in rows
            if str(row["target"]) == target
        )
        for target, path in packages.items()
    ):
        raise RuntimeError("正式发布中的候选包缺失或哈希发生变化")
    result = publish_selective(
        database_path,
        release_directory,
        packages,
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
    parser.add_argument("--workbuddy-macos-package", type=Path)
    parser.add_argument("--workbuddy-windows-package", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--release-notes-file", type=Path)
    parser.add_argument("--git-commit", default="")
    parser.add_argument("--github-url", default="")
    arguments = parser.parse_args()
    if arguments.mode == "stage":
        packages = {
            target: package
            for target, package in (
                ("generic", arguments.generic_package),
                (
                    "macos",
                    arguments.workbuddy_macos_package
                    or arguments.workbuddy_package,
                ),
                (
                    "windows",
                    arguments.workbuddy_windows_package
                    or arguments.workbuddy_package,
                ),
            )
            if package is not None
        }
        if (
            not packages
            or arguments.release_notes_file is None
            or not arguments.git_commit.strip()
            or not arguments.github_url.strip()
        ):
            parser.error(
                "stage模式必须至少提供一个客户端包，并提供发布说明、"
                "git提交和GitHub预发布地址"
            )
        result = stage_selective(
            arguments.database,
            arguments.release_dir,
            packages,
            arguments.version,
            arguments.release_notes_file.read_text(encoding="utf-8"),
            arguments.git_commit,
            arguments.github_url,
        )
    else:
        result = promote_selective(
            arguments.database,
            arguments.release_dir,
            arguments.version,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
