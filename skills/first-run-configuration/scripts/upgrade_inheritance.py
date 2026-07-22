#!/usr/bin/env python3
"""Upgrade official Skills without overwriting the personal preference overlay."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_CONFIG_DIR = Path.home() / ".config" / "project-assistant"


def digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def read_json(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def classify(old_official: str | None, installed: str | None, incoming: str) -> str:
    if installed is None:
        return "新增"
    if old_official is None:
        return "未纳管的既有Skill"
    local_changed = installed != old_official
    official_changed = incoming != old_official
    if local_changed and official_changed:
        return "用户直改与官方更新冲突"
    if local_changed:
        return "检测到用户直接修改SKILL.md"
    if official_changed:
        return "仅官方更新"
    return "无变化"


def markdown_report(report: dict[str, object]) -> str:
    lines = [
        "# Skills升级继承报告",
        "",
        f"- 目标版本：{report['version']}",
        f"- 生成时间：{report['created_at']}",
        f"- 官方核心：已更新",
        f"- 个人覆盖层：已保留 `{report['preferences']}`",
        f"- 旧版备份：`{report['backup_root']}`",
        "",
        "| Skill | 识别结果 | 处理方式 |",
        "|---|---|---|",
    ]
    for item in report["items"]:
        handling = "安装新版官方核心"
        if item["status"] in {"检测到用户直接修改SKILL.md", "用户直改与官方更新冲突", "未纳管的既有Skill"}:
            handling = "旧文件已备份；需将有效习惯转成结构化偏好"
        lines.append(f"| {item['skill']} | {item['status']} | {handling} |")
    lines.extend(
        [
            "",
            "> 升级不会把用户直接修改的SKILL.md自动混入官方核心，避免旧规则覆盖新版质量门禁。",
        ]
    )
    return "\n".join(lines) + "\n"


def upgrade(source: Path, destination: Path, config_dir: Path, version: str) -> Path:
    skills_source = source / "skills" if (source / "skills").is_dir() else source
    if not skills_source.is_dir():
        raise FileNotFoundError(f"找不到Skills目录：{skills_source}")
    state_path = config_dir / "install-state.json"
    state = read_json(state_path)
    previous_skills = state.get("skills", {})
    if not isinstance(previous_skills, dict):
        previous_skills = {}
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_root = config_dir / "install-backups" / run_id
    baseline_root = config_dir / "official-baselines" / version
    destination.mkdir(parents=True, exist_ok=True)
    items = []
    next_skills = dict(previous_skills)
    for skill_dir in sorted(path for path in skills_source.iterdir() if (path / "SKILL.md").is_file()):
        target = destination / skill_dir.name
        incoming_hash = digest(skill_dir / "SKILL.md") or ""
        previous = previous_skills.get(skill_dir.name, {})
        old_hash = previous.get("official_hash") if isinstance(previous, dict) else None
        installed_hash = digest(target / "SKILL.md")
        status = classify(old_hash, installed_hash, incoming_hash)
        backup = None
        if target.exists() or target.is_symlink():
            backup_root.mkdir(parents=True, exist_ok=True)
            backup = backup_root / skill_dir.name
            target.rename(backup)
        shutil.copytree(skill_dir, target)
        baseline = baseline_root / skill_dir.name / "SKILL.md"
        baseline.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(skill_dir / "SKILL.md", baseline)
        next_skills[skill_dir.name] = {
            "official_hash": incoming_hash,
            "baseline": str(baseline),
            "version": version,
        }
        items.append(
            {
                "skill": skill_dir.name,
                "status": status,
                "old_official_hash": old_hash,
                "installed_hash": installed_hash,
                "incoming_hash": incoming_hash,
                "backup": str(backup) if backup else None,
            }
        )
    created_at = datetime.now(timezone.utc).isoformat()
    state.update(
        {
            "version": version,
            "updated_at": created_at,
            "destination": str(destination),
            "skills": next_skills,
        }
    )
    write_json(state_path, state)
    report = {
        "version": version,
        "created_at": created_at,
        "preferences": str(config_dir / "preferences.json"),
        "backup_root": str(backup_root),
        "items": items,
    }
    report_dir = config_dir / "upgrade-reports"
    json_path = report_dir / f"{run_id}.json"
    markdown_path = report_dir / f"{run_id}.md"
    write_json(json_path, report)
    markdown_path.write_text(markdown_report(report), encoding="utf-8")
    return markdown_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True, help="解压后的发布包或skills目录")
    parser.add_argument("--target", type=Path, required=True, help="Agent的Skills目录")
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    try:
        report = upgrade(
            args.source.expanduser().resolve(),
            args.target.expanduser().resolve(),
            args.config_dir.expanduser().resolve(),
            args.version,
        )
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"升级失败：{error}")
        return 2
    print(f"升级完成，继承报告：{report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
