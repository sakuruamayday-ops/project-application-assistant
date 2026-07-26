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
        if not isinstance(skills, list) or len(skills) != 56:
            raise ValueError("通用包必须完整包含 56 个技能")
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
    return {
        "version": version,
        "generic_sha256": sha256(generic),
        "workbuddy_sha256": sha256(workbuddy),
    }


def validate_host_evidence(path: Path, version: str) -> dict[str, object]:
    evidence = json.loads(path.read_text(encoding="utf-8"))
    if evidence.get("schema") != "jiaotang-workbuddy-host-matrix/v1":
        raise ValueError("双宿主证据格式不受支持")
    if evidence.get("status") != "pass" or evidence.get("release_tag") != f"V{version}":
        raise ValueError("双宿主证据状态或版本不一致")
    hosts = evidence.get("hosts")
    if not isinstance(hosts, dict):
        raise ValueError("双宿主证据缺少 hosts")
    for host in ("macos", "windows"):
        item = hosts.get(host)
        if not isinstance(item, dict) or item.get("status") != "pass":
            raise ValueError(f"双宿主证据缺少成功的 {host} 实机任务")
    return evidence


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


def publish(
    database_path: Path,
    release_directory: Path,
    generic_package: Path,
    workbuddy_package: Path,
    version: str,
    release_notes: str,
    host_evidence: Path | None = None,
) -> dict[str, object]:
    validation = validate_packages(generic_package, workbuddy_package, version)
    evidence = validate_host_evidence(host_evidence, version) if host_evidence else None
    generic_target = release_directory / f"企业全生命周期助手-V{version}.zip"
    workbuddy_target = release_directory / f"企业全生命周期助手-V{version}-WorkBuddy.zip"
    evidence_target = (
        release_directory / f"企业全生命周期助手-V{version}-WorkBuddy-host-evidence.json"
    )
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
                and (
                    host_evidence is None
                    or (
                        evidence_target.is_file()
                        and validate_host_evidence(evidence_target, version) == evidence
                    )
                )
            ):
                return {**validation, "release_id": int(existing["id"]), "status": "already-published"}
            raise RuntimeError(f"版本 {version} 已存在，但发布文件或哈希不一致")

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = database_path.with_name(f"{database_path.name}.before-v{version}-{timestamp}")
        with sqlite3.connect(backup_path) as backup:
            connection.backup(backup)

        _install_file(generic_package, generic_target)
        _install_file(workbuddy_package, workbuddy_target)
        if host_evidence is not None:
            _install_file(host_evidence, evidence_target)
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
        "host_evidence_path": str(evidence_target) if host_evidence else "",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="发布已签名的通用与 WorkBuddy 技能包")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--generic-package", type=Path, required=True)
    parser.add_argument("--workbuddy-package", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--release-notes-file", type=Path, required=True)
    parser.add_argument("--host-evidence", type=Path)
    arguments = parser.parse_args()
    result = publish(
        arguments.database,
        arguments.release_dir,
        arguments.generic_package,
        arguments.workbuddy_package,
        arguments.version,
        arguments.release_notes_file.read_text(encoding="utf-8"),
        arguments.host_evidence,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
