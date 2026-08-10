#!/usr/bin/env python3
"""审计并修复已发布技能包的阶段元数据路径。

默认只读。只有显式传入 ``--apply`` 才会写入数据库；写入前会生成同目录
备份。此脚本只改元数据，不移动、删除或覆盖任何包文件。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from publish_skill_release import _artifact_name, _ensure_stage_table, sha256


def _final_path(release_directory: Path, version: str, target: str) -> Path:
    return release_directory / _artifact_name(version, target)


def _check_final(path: Path, expected_sha: str) -> tuple[bool, str]:
    if not path.is_file() or path.is_symlink():
        return False, "正式根目录缺少普通文件"
    actual = sha256(path)
    if actual != expected_sha:
        return False, f"正式文件哈希不匹配：{actual}"
    return True, ""


def audit(
    database: Path,
    release_directory: Path,
    versions: set[str] | None = None,
) -> dict[str, object]:
    findings: list[dict[str, object]] = []
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        _ensure_stage_table(connection)
        stage_artifacts = connection.execute(
            "SELECT version,target,file_path,sha256 FROM skill_release_stage_artifacts"
        ).fetchall()
        for row in stage_artifacts:
            version = str(row["version"])
            if versions is not None and version not in versions:
                continue
            target = str(row["target"])
            final_path = _final_path(release_directory, version, target)
            valid, error = _check_final(final_path, str(row["sha256"]))
            if not valid:
                findings.append(
                    {
                        "kind": "stage_artifact_unrepairable",
                        "version": version,
                        "target": target,
                        "stored_path": str(row["file_path"]),
                        "expected_path": str(final_path),
                        "reason": error,
                    }
                )
            elif str(row["file_path"]) != str(final_path):
                findings.append(
                    {
                        "kind": "stage_artifact_path",
                        "version": version,
                        "target": target,
                        "stored_path": str(row["file_path"]),
                        "expected_path": str(final_path),
                        "sha256": str(row["sha256"]),
                        "repairable": True,
                    }
                )
        artifact_stages = connection.execute(
            "SELECT version,target,file_path,sha256 FROM skill_release_artifact_stages"
        ).fetchall()
        for row in artifact_stages:
            version = str(row["version"])
            if versions is not None and version not in versions:
                continue
            target = str(row["target"])
            final_path = _final_path(release_directory, version, target)
            valid, error = _check_final(final_path, str(row["sha256"]))
            if not valid:
                findings.append(
                    {
                        "kind": "artifact_stage_unrepairable",
                        "version": version,
                        "target": target,
                        "stored_path": str(row["file_path"]),
                        "expected_path": str(final_path),
                        "reason": error,
                    }
                )
            elif str(row["file_path"]) != str(final_path):
                findings.append(
                    {
                        "kind": "artifact_stage_path",
                        "version": version,
                        "target": target,
                        "stored_path": str(row["file_path"]),
                        "expected_path": str(final_path),
                        "sha256": str(row["sha256"]),
                        "repairable": True,
                    }
                )
        releases = connection.execute(
            "SELECT id,version,file_name,file_path,sha256 FROM skill_releases"
        ).fetchall()
        for row in releases:
            version = str(row["version"])
            if versions is not None and version not in versions:
                continue
            final_path = _final_path(release_directory, version, "generic")
            valid, error = _check_final(final_path, str(row["sha256"]))
            if not valid:
                findings.append(
                    {
                        "kind": "skill_release_unrepairable",
                        "version": version,
                        "target": "generic",
                        "release_id": int(row["id"]),
                        "stored_path": str(row["file_path"]),
                        "expected_path": str(final_path),
                        "reason": error,
                    }
                )
            elif (
                str(row["file_path"]) != str(final_path)
                or str(row["file_name"]) != final_path.name
            ):
                findings.append(
                    {
                        "kind": "skill_release_path",
                        "version": version,
                        "target": "generic",
                        "release_id": int(row["id"]),
                        "stored_path": str(row["file_path"]),
                        "expected_path": str(final_path),
                        "sha256": str(row["sha256"]),
                        "repairable": True,
                    }
                )
        release_artifacts = connection.execute(
            """
            SELECT artifact.release_id,release.version,artifact.target,
                   artifact.file_name,artifact.file_path,artifact.sha256
            FROM skill_release_artifacts artifact
            JOIN skill_releases release ON release.id=artifact.release_id
            """
        ).fetchall()
        for row in release_artifacts:
            version = str(row["version"])
            if versions is not None and version not in versions:
                continue
            target = str(row["target"])
            final_path = _final_path(release_directory, version, target)
            valid, error = _check_final(final_path, str(row["sha256"]))
            if not valid:
                findings.append(
                    {
                        "kind": "skill_release_artifact_unrepairable",
                        "version": version,
                        "target": target,
                        "release_id": int(row["release_id"]),
                        "stored_path": str(row["file_path"]),
                        "expected_path": str(final_path),
                        "reason": error,
                    }
                )
            elif (
                str(row["file_path"]) != str(final_path)
                or str(row["file_name"]) != final_path.name
            ):
                findings.append(
                    {
                        "kind": "skill_release_artifact_path",
                        "version": version,
                        "target": target,
                        "release_id": int(row["release_id"]),
                        "stored_path": str(row["file_path"]),
                        "expected_path": str(final_path),
                        "sha256": str(row["sha256"]),
                        "repairable": True,
                    }
                )
        stages = connection.execute(
            """
            SELECT version,generic_path,generic_sha256,workbuddy_path,workbuddy_sha256
            FROM skill_release_stages WHERE status='published'
            """
        ).fetchall()
        for row in stages:
            version = str(row["version"])
            if versions is not None and version not in versions:
                continue
            for target, path_field, hash_field in (
                ("generic", "generic_path", "generic_sha256"),
                ("workbuddy", "workbuddy_path", "workbuddy_sha256"),
            ):
                stored_path = str(row[path_field] or "")
                expected_sha = str(row[hash_field] or "")
                if not stored_path or not expected_sha:
                    continue
                final_path = _final_path(release_directory, version, target)
                valid, error = _check_final(final_path, expected_sha)
                if not valid:
                    findings.append(
                        {
                            "kind": "release_stage_unrepairable",
                            "version": version,
                            "target": target,
                            "stored_path": stored_path,
                            "expected_path": str(final_path),
                            "reason": error,
                        }
                    )
                elif stored_path != str(final_path):
                    findings.append(
                        {
                            "kind": "release_stage_path",
                            "version": version,
                            "target": target,
                            "stored_path": stored_path,
                            "expected_path": str(final_path),
                            "sha256": expected_sha,
                            "repairable": True,
                        }
                    )
    return {
        "schema": "jiaotang-release-metadata-reconciliation/v1",
        "database": str(database),
        "release_directory": str(release_directory),
        "versions": sorted(versions) if versions is not None else None,
        "checked_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "repairable": sum(1 for item in findings if item.get("repairable")),
        "unrepairable": sum(1 for item in findings if not item.get("repairable")),
        "findings": findings,
    }


def apply_repairs(database: Path, report: dict[str, object]) -> str | None:
    repairable = [
        item for item in report.get("findings", [])
        if isinstance(item, dict) and item.get("repairable")
    ]
    if not repairable:
        return None
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = database.with_name(f"{database.name}.before-reconcile-{timestamp}")
    shutil.copy2(database, backup)
    with sqlite3.connect(database) as connection:
        for item in repairable:
            version = str(item["version"])
            target = str(item["target"])
            expected_path = str(item["expected_path"])
            if item["kind"] == "stage_artifact_path":
                connection.execute(
                    "UPDATE skill_release_stage_artifacts SET file_path=? WHERE version=? AND target=?",
                    (expected_path, version, target),
                )
            elif item["kind"] == "artifact_stage_path":
                connection.execute(
                    "UPDATE skill_release_artifact_stages SET file_path=? WHERE version=? AND target=?",
                    (expected_path, version, target),
                )
            elif item["kind"] == "release_stage_path":
                field = "generic_path" if target == "generic" else "workbuddy_path"
                connection.execute(
                    f"UPDATE skill_release_stages SET {field}=? WHERE version=?",
                    (expected_path, version),
                )
            elif item["kind"] == "skill_release_path":
                connection.execute(
                    "UPDATE skill_releases SET file_name=?,file_path=? WHERE id=?",
                    (Path(expected_path).name, expected_path, int(item["release_id"])),
                )
            elif item["kind"] == "skill_release_artifact_path":
                connection.execute(
                    """
                    UPDATE skill_release_artifacts SET file_name=?,file_path=?
                    WHERE release_id=? AND target=?
                    """,
                    (
                        Path(expected_path).name,
                        expected_path,
                        int(item["release_id"]),
                        target,
                    ),
                )
        connection.commit()
    return str(backup)


def main() -> int:
    data_dir = Path(os.environ.get("JIAOTANG_DATA_DIR", "/var/lib/jiaotang-kb"))
    parser = argparse.ArgumentParser(description="审计并修复技能发布阶段元数据路径")
    parser.add_argument("--database", type=Path, default=data_dir / "knowledge.db")
    parser.add_argument(
        "--release-directory",
        type=Path,
        default=Path(os.environ.get("JIAOTANG_SKILL_RELEASE_DIR", data_dir / "skill-releases")),
    )
    parser.add_argument("--apply", action="store_true", help="写入可修复路径，默认只读")
    parser.add_argument(
        "--version",
        action="append",
        dest="versions",
        help="只审计指定版本，可重复；不传时审计全部历史版本",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    versions = (
        {str(version).removeprefix("V") for version in args.versions}
        if args.versions
        else None
    )
    report = audit(
        args.database.expanduser().resolve(),
        args.release_directory.expanduser().resolve(),
        versions,
    )
    backup = apply_repairs(args.database.expanduser().resolve(), report) if args.apply else None
    report["mode"] = "apply" if args.apply else "audit"
    if backup:
        report["database_backup"] = backup
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if not report["unrepairable"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
