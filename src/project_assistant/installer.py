from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .skill_integrity import (
    freeze_managed_path,
    freeze_signed_skill,
    load_json,
    sha256_file,
    tree_hashes,
    verify_skill_directory,
)


def file_hash(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def load_install_state(config_dir: Path) -> dict[str, object]:
    path = config_dir / "install-state.json"
    if not path.is_file():
        return {"skills": {}}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {"skills": {}}


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def append_json_line(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, encoded)
    finally:
        os.close(descriptor)


def classify_skill_change(
    old_official: str | None,
    installed: str | None,
    incoming: str,
) -> str:
    if installed is None:
        return "new"
    if old_official is None:
        return "unmanaged-existing"
    local_changed = installed != old_official
    official_changed = incoming != old_official
    if local_changed and official_changed:
        return "both-changed-conflict"
    if local_changed:
        return "local-only"
    if official_changed:
        return "upstream-only"
    return "unchanged"


def _contains(parent: Path, child: Path) -> bool:
    return child == parent or parent in child.parents


def validate_role_separation(source: Path, destination: Path) -> None:
    source_resolved = source.expanduser().resolve()
    destination_resolved = destination.expanduser().resolve()
    if _contains(source_resolved, destination_resolved) or _contains(
        destination_resolved, source_resolved
    ):
        raise ValueError("开发源、正式发布源和实际安装目录不得相同或相互嵌套")
    known_install_roots = (
        Path.home() / ".codex" / "skills",
        Path.home() / ".agents" / "skills",
    )
    for root in known_install_roots:
        resolved_root = root.expanduser().resolve()
        if _contains(resolved_root, source_resolved):
            raise ValueError(
                f"拒绝把已安装目录作为开发或发布源：{source_resolved}"
            )


def _safe_relative(value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValueError(f"套件共享路径不安全：{value}")
    return relative


def _managed_entries(source: Path) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    skill_dirs = sorted(
        path for path in source.iterdir() if (path / "SKILL.md").is_file()
    )
    entries: list[dict[str, Any]] = [
        {
            "name": skill_dir.name,
            "relative": Path(skill_dir.name),
            "source": skill_dir,
            "kind": "skill",
            "signed": (skill_dir / "release-manifest.json").is_file(),
        }
        for skill_dir in skill_dirs
    ]
    suite_manifest_path = source / "suite-manifest.json"
    if not suite_manifest_path.is_file():
        return entries, None
    suite_manifest = load_json(suite_manifest_path)
    declared = [str(value) for value in suite_manifest.get("skills", [])]
    actual = [path.name for path in skill_dirs]
    if declared != actual:
        raise ValueError(
            "suite-manifest.json声明的Skills与发布源目录不一致"
        )
    shared_paths = ["suite-manifest.json"]
    shared_paths.extend(
        str(value) for value in suite_manifest.get("shared_paths", [])
    )
    for value in shared_paths:
        relative = _safe_relative(value)
        shared_source = source / relative
        if not shared_source.exists():
            raise FileNotFoundError(f"套件共享路径不存在：{shared_source}")
        entries.append(
            {
                "name": relative.as_posix(),
                "relative": relative,
                "source": shared_source,
                "kind": "shared",
                "signed": False,
            }
        )
    return entries, suite_manifest


def _copy_entry(source: Path, target: Path, mode: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if mode == "symlink":
        target.symlink_to(source.resolve(), target_is_directory=source.is_dir())
    elif source.is_dir():
        shutil.copytree(
            source,
            target,
            ignore=shutil.ignore_patterns(
                "__pycache__", "*.pyc", "*.pyo", ".DS_Store", "._*"
            ),
        )
    else:
        shutil.copy2(source, target)


def _item_report(
    entry: dict[str, Any],
    *,
    action: str,
    change: str | None,
    old_official_hash: str | None,
    installed_hash: str | None,
    incoming_hash: str | None,
    backup: Path | None,
    reason: str | None = None,
) -> dict[str, object]:
    return {
        "entry": entry["name"],
        "kind": entry["kind"],
        "action": action,
        "reason": reason,
        "status": change,
        "old_official_hash": old_official_hash,
        "installed_hash": installed_hash,
        "incoming_hash": incoming_hash,
        "backup": str(backup) if backup else None,
    }


def install_skills(
    source: Path,
    destination: Path,
    mode: str,
    force: bool,
    config_dir: Path | None = None,
    version: str = "unknown",
    *,
    command: list[str] | None = None,
    report_out: dict[str, Any] | None = None,
    require_signatures: bool = False,
) -> list[str]:
    if mode not in {"copy", "symlink"}:
        raise ValueError("安装模式必须是 copy 或 symlink")
    source = source.expanduser().resolve()
    destination = destination.expanduser().resolve()
    config_dir = (
        config_dir or Path.home() / ".config" / "project-assistant"
    ).expanduser().resolve()
    run_id = timestamp()
    created_at = datetime.now(timezone.utc).isoformat()
    report_path = config_dir / "upgrade-reports" / f"{run_id}.json"
    execution_log = config_dir / "install-executions.jsonl"
    execution_root = config_dir / "install-evidence" / run_id
    staging_root = config_dir / "install-staging" / run_id
    backup_root = config_dir / "install-backups" / run_id
    rollback_root = config_dir / "install-rollbacks" / run_id
    invocation = {
        "run_id": run_id,
        "created_at": created_at,
        "process_id": os.getpid(),
        "cwd": str(Path.cwd()),
        "command": list(command or []),
        "source": str(source),
        "destination": str(destination),
        "config_dir": str(config_dir),
        "mode": mode,
        "force": force,
        "version": version,
        "require_signatures": require_signatures,
    }
    if report_out is not None:
        report_out.update(
            {
                "run_id": run_id,
                "report": str(report_path),
                "execution_log": str(execution_log),
            }
        )

    state: dict[str, object] = {"skills": {}}
    report_items: list[dict[str, object]] = []
    installed: list[str] = []
    transaction_status = "failed-before-staging"
    error: str | None = None
    moved_backups: list[tuple[Path, Path]] = []
    deployed_targets: list[tuple[Path, Path]] = []
    frozen: dict[str, dict[str, int]] = {}
    frozen_shared: dict[str, dict[str, int]] = {}
    suite_manifest: dict[str, Any] | None = None
    try:
        if not source.is_dir():
            raise FileNotFoundError(f"技能源目录不存在：{source}")
        validate_role_separation(source, destination)
        entries, suite_manifest = _managed_entries(source)
        if not entries:
            raise ValueError(f"技能源目录没有可安装Skill：{source}")
        signed_skills = [
            entry for entry in entries
            if entry["kind"] == "skill" and entry["signed"]
        ]
        if require_signatures:
            unsigned = [
                str(entry["name"])
                for entry in entries
                if entry["kind"] == "skill" and not entry["signed"]
            ]
            if unsigned:
                raise RuntimeError(
                    "正式部署源存在未签名Skill：" + "、".join(unsigned)
                )
        if mode == "symlink" and signed_skills:
            raise ValueError("已签名Skill禁止符号链接安装，必须使用原子复制")

        destination.mkdir(parents=True, exist_ok=True)
        config_dir.mkdir(parents=True, exist_ok=True)
        execution_root.mkdir(parents=True, exist_ok=True)
        state = load_install_state(config_dir)
        skill_state = state.get("skills", {})
        if not isinstance(skill_state, dict):
            skill_state = {}

        for entry in signed_skills:
            verify_skill_directory(
                entry["source"],
                evidence_dir=execution_root / "source-signatures",
                label=f"source-{entry['name']}",
                require_signature=True,
            )

        selected: list[dict[str, Any]] = []
        for entry in entries:
            target = destination / entry["relative"]
            previous = skill_state.get(entry["name"], {})
            old_official_hash = (
                previous.get("official_hash")
                if isinstance(previous, dict)
                else None
            )
            installed_hash = (
                file_hash(target / "SKILL.md")
                if entry["kind"] == "skill"
                else file_hash(target) if target.is_file() else None
            )
            incoming_hash = (
                file_hash(entry["source"] / "SKILL.md")
                if entry["kind"] == "skill"
                else file_hash(entry["source"])
                if entry["source"].is_file()
                else None
            )
            change = (
                classify_skill_change(
                    old_official_hash,
                    installed_hash,
                    incoming_hash or "",
                )
                if entry["kind"] == "skill"
                else None
            )
            exists = target.exists() or target.is_symlink()
            if exists and not force:
                report_items.append(
                    _item_report(
                        entry,
                        action="skipped",
                        reason="existing-target-without-force",
                        change=change,
                        old_official_hash=old_official_hash,
                        installed_hash=installed_hash,
                        incoming_hash=incoming_hash,
                        backup=None,
                    )
                )
                continue
            selected.append(
                {
                    **entry,
                    "target": target,
                    "old_official_hash": old_official_hash,
                    "installed_hash": installed_hash,
                    "incoming_hash": incoming_hash,
                    "change": change,
                    "exists": exists,
                }
            )

        staging_root.mkdir(parents=True, exist_ok=True)
        for entry in selected:
            staged = staging_root / entry["relative"]
            _copy_entry(entry["source"], staged, mode)
            entry["staged"] = staged
            if entry["kind"] == "skill" and entry["signed"]:
                verify_skill_directory(
                    staged,
                    evidence_dir=execution_root / "staged-signatures",
                    label=f"staged-{entry['name']}",
                    require_signature=True,
                )
        transaction_status = "staged-and-verified"

        for entry in selected:
            target = entry["target"]
            if entry["exists"]:
                backup = backup_root / entry["relative"]
                backup.parent.mkdir(parents=True, exist_ok=True)
                target.rename(backup)
                moved_backups.append((target, backup))
                entry["backup"] = backup
            else:
                entry["backup"] = None
        transaction_status = "previous-install-backed-up"

        for entry in selected:
            target = entry["target"]
            target.parent.mkdir(parents=True, exist_ok=True)
            entry["staged"].rename(target)
            deployed_targets.append((target, rollback_root / entry["relative"]))
        transaction_status = "new-install-swapped"

        for entry in selected:
            if entry["kind"] == "shared":
                source_path = entry["source"]
                target_path = entry["target"]
                if source_path.is_dir():
                    if tree_hashes(source_path) != tree_hashes(target_path):
                        raise RuntimeError(
                            f"共享路径安装后哈希不一致：{entry['name']}"
                        )
                elif sha256_file(source_path) != sha256_file(target_path):
                    raise RuntimeError(
                        f"共享文件安装后哈希不一致：{entry['name']}"
                    )
                frozen_shared[str(entry["name"])] = freeze_managed_path(
                    target_path
                )
                continue
            target = entry["target"]
            if entry["signed"]:
                verify_skill_directory(
                    target,
                    evidence_dir=execution_root / "installed-signatures",
                    label=f"installed-{entry['name']}",
                    require_signature=True,
                )
                frozen[str(entry["name"])] = freeze_signed_skill(target)
            baseline = (
                config_dir
                / "official-baselines"
                / version
                / str(entry["name"])
                / "SKILL.md"
            )
            baseline.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(entry["source"] / "SKILL.md", baseline)
            skill_state[str(entry["name"])] = {
                "official_hash": entry["incoming_hash"],
                "version": version,
                "baseline": str(baseline),
                "signed": bool(entry["signed"]),
                "read_only": bool(entry["signed"]),
            }
            installed.append(str(entry["name"]))
        transaction_status = "installed-and-verified"

        for entry in selected:
            report_items.append(
                _item_report(
                    entry,
                    action="installed",
                    change=entry["change"],
                    old_official_hash=entry["old_official_hash"],
                    installed_hash=entry["installed_hash"],
                    incoming_hash=entry["incoming_hash"],
                    backup=entry["backup"],
                )
            )
        if installed:
            state.update(
                {
                    "version": version,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "destination": str(destination),
                    "suite_release": (
                        suite_manifest.get("release")
                        if suite_manifest
                        else None
                    ),
                    "skills": skill_state,
                }
            )
            write_json(config_dir / "install-state.json", state)
        transaction_status = "committed"
    except Exception as exc:
        error = str(exc)
        if deployed_targets:
            for target, rollback in reversed(deployed_targets):
                if target.exists() or target.is_symlink():
                    rollback.parent.mkdir(parents=True, exist_ok=True)
                    target.rename(rollback)
            for target, backup in reversed(moved_backups):
                if backup.exists() or backup.is_symlink():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    backup.rename(target)
            transaction_status = "rolled-back"
        raise
    finally:
        completed_at = datetime.now(timezone.utc).isoformat()
        report = {
            "schema_version": 2,
            "run_id": run_id,
            "version": version,
            "created_at": created_at,
            "completed_at": completed_at,
            "status": "pass" if transaction_status == "committed" else "fail",
            "transaction_status": transaction_status,
            "error": error,
            "invocation": invocation,
            "official_core": (
                "installed"
                if installed
                else "not-installed"
            ),
            "personal_overlay": str(config_dir / "preferences.json"),
            "staging_root": str(staging_root),
            "backup_root": str(backup_root),
            "rollback_root": str(rollback_root),
            "items": report_items,
            "installed_skills": installed,
            "skipped_entries": [
                item["entry"]
                for item in report_items
                if item["action"] == "skipped"
            ],
            "direct_skill_edits": [
                item["entry"]
                for item in report_items
                if item["status"]
                in {
                    "local-only",
                    "both-changed-conflict",
                    "unmanaged-existing",
                }
            ],
            "read_only_signed_skills": frozen,
            "read_only_shared_paths": frozen_shared,
        }
        try:
            write_json(report_path, report)
            append_json_line(
                execution_log,
                {
                    **invocation,
                    "completed_at": completed_at,
                    "status": report["status"],
                    "transaction_status": transaction_status,
                    "error": error,
                    "report": str(report_path),
                    "installed_skills": installed,
                    "skipped_entries": report["skipped_entries"],
                },
            )
            if report_out is not None:
                report_out.update(
                    {
                        "status": report["status"],
                        "transaction_status": transaction_status,
                        "installed_skills": list(installed),
                        "skipped_entries": list(report["skipped_entries"]),
                    }
                )
        except OSError:
            if error is None:
                raise
    return installed
