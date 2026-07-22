from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


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
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def classify_skill_change(old_official: str | None, installed: str | None, incoming: str) -> str:
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


def install_skills(
    source: Path,
    destination: Path,
    mode: str,
    force: bool,
    config_dir: Path | None = None,
    version: str = "unknown",
) -> list[str]:
    if mode not in {"copy", "symlink"}:
        raise ValueError("安装模式必须是 copy 或 symlink")
    if not source.is_dir():
        raise FileNotFoundError(f"技能源目录不存在：{source}")

    destination.mkdir(parents=True, exist_ok=True)
    config_dir = (config_dir or Path.home() / ".config" / "project-assistant").expanduser()
    state = load_install_state(config_dir)
    skill_state = state.get("skills", {})
    if not isinstance(skill_state, dict):
        skill_state = {}
    run_id = timestamp()
    backup_root = config_dir / "install-backups" / run_id
    baseline_root = config_dir / "official-baselines" / version
    report_items: list[dict[str, object]] = []
    installed: list[str] = []
    for skill_dir in sorted(path for path in source.iterdir() if (path / "SKILL.md").is_file()):
        target = destination / skill_dir.name
        incoming_hash = file_hash(skill_dir / "SKILL.md")
        previous = skill_state.get(skill_dir.name, {})
        old_official_hash = previous.get("official_hash") if isinstance(previous, dict) else None
        installed_hash = file_hash(target / "SKILL.md")
        change = classify_skill_change(old_official_hash, installed_hash, incoming_hash or "")
        if target.exists() or target.is_symlink():
            if not force:
                continue
            backup_root.mkdir(parents=True, exist_ok=True)
            backup = backup_root / skill_dir.name
            target.rename(backup)
        if mode == "symlink":
            target.symlink_to(skill_dir.resolve(), target_is_directory=True)
        else:
            shutil.copytree(skill_dir, target)
        baseline = baseline_root / skill_dir.name / "SKILL.md"
        baseline.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(skill_dir / "SKILL.md", baseline)
        skill_state[skill_dir.name] = {
            "official_hash": incoming_hash,
            "version": version,
            "baseline": str(baseline),
        }
        report_items.append(
            {
                "skill": skill_dir.name,
                "status": change,
                "old_official_hash": old_official_hash,
                "installed_hash": installed_hash,
                "incoming_hash": incoming_hash,
                "backup": str(backup_root / skill_dir.name) if installed_hash else None,
            }
        )
        installed.append(skill_dir.name)
    if installed:
        state.update(
            {
                "version": version,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "destination": str(destination),
                "skills": skill_state,
            }
        )
        write_json(config_dir / "install-state.json", state)
        report = {
            "version": version,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "official_core": "installed",
            "personal_overlay": str(config_dir / "preferences.json"),
            "backup_root": str(backup_root),
            "items": report_items,
            "direct_skill_edits": [
                item["skill"]
                for item in report_items
                if item["status"] in {"local-only", "both-changed-conflict", "unmanaged-existing"}
            ],
        }
        write_json(config_dir / "upgrade-reports" / f"{run_id}.json", report)
    return installed
