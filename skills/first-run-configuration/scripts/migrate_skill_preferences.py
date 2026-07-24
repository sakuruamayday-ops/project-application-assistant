#!/usr/bin/env python3
"""Convert safe direct SKILL.md edits into the structured personal preference overlay."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import stat
from datetime import datetime, timezone
from difflib import ndiff
from pathlib import Path


DEFAULT_CONFIG_DIR = Path.home() / ".config" / "project-assistant"
DIRECT_EDIT_STATUSES = {
    "检测到用户直接修改SKILL.md",
    "用户直改与官方更新冲突",
}
BLOCKED_TERMS = (
    "token",
    "api key",
    "密码",
    "凭据",
    "cookie",
    "绕过",
    "关闭核验",
    "无需核验",
    "不附来源",
    "保证获批",
    "一定符合",
    "编造",
    "伪造",
    "关闭四问",
    "忽略安全",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON顶层必须是对象：{path}")
    return payload


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.chmod(stat.S_IRUSR | stat.S_IWUSR)
    temporary.replace(path)


def skill_body(text: str) -> str:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2]
    return text


def normalize_instruction(line: str) -> str:
    normalized = line.strip()
    normalized = re.sub(r"^(?:[-*+]\s+|\d+[.、]\s*)", "", normalized)
    return normalized.strip()


def added_lines(baseline: str, modified: str) -> list[str]:
    additions: list[str] = []
    for line in ndiff(skill_body(baseline).splitlines(), skill_body(modified).splitlines()):
        if not line.startswith("+ "):
            continue
        normalized = normalize_instruction(line[2:])
        if (
            len(normalized) < 4
            or normalized.startswith(("#", "```", "---", "|"))
            or normalized in additions
        ):
            continue
        additions.append(normalized)
    return additions


def infer_global_preferences(line: str) -> dict[str, object]:
    inferred: dict[str, object] = {}
    region_match = re.search(r"(?:默认(?:政策)?地区|常用地区)[：:为是\s]*([^，。；\n]{2,30})", line)
    if region_match:
        region = region_match.group(1).strip()
        province = re.search(r"[^省市]{2,12}(?:省|自治区)", region)
        city = re.search(r"[^省市]{2,12}市", region)
        inferred["region"] = {
            "province": province.group(0) if province else "",
            "city": city.group(0) if city else "",
        }
    if re.search(r"(?:默认|输出).*(?:尽可能详细|详细版|详细程度.*详细)", line):
        inferred.setdefault("output", {})["detail_level"] = "detailed"
    elif re.search(r"(?:默认|输出).*(?:精简版|简洁|精简)", line):
        inferred.setdefault("output", {})["detail_level"] = "concise"
    if re.search(r"(?:默认|输出).*顾问式", line):
        inferred.setdefault("output", {})["tone"] = "consultative"
    elif re.search(r"(?:默认|输出).*正式", line):
        inferred.setdefault("output", {})["tone"] = "formal"
    elif re.search(r"(?:默认|输出).*直接", line):
        inferred.setdefault("output", {})["tone"] = "direct"
    if re.search(r"(?:默认|输出).*(?:先给结论|结论优先)", line):
        inferred.setdefault("output", {})["conclusion_first"] = True
    format_match = re.search(r"(?:默认|输出).*\b(markdown|word|pdf|html)\b", line, re.IGNORECASE)
    if format_match:
        inferred.setdefault("output", {})["format"] = format_match.group(1).lower()
    if re.search(r"默认.*不自动归档", line):
        inferred.setdefault("workflow", {})["auto_archive"] = False
    elif re.search(r"默认.*自动归档", line):
        inferred.setdefault("workflow", {})["auto_archive"] = True
    return inferred


def merge_mapping(target: dict[str, object], updates: dict[str, object]) -> None:
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            merge_mapping(target[key], value)
        else:
            target[key] = value


def latest_upgrade_report(config_dir: Path) -> Path:
    reports = sorted((config_dir / "upgrade-reports").glob("*.json"))
    if not reports:
        raise FileNotFoundError("未找到升级继承报告，请先运行升级工具")
    return reports[-1]


def migrate_report(report_path: Path, preference_file: Path, output_dir: Path) -> Path:
    upgrade_report = read_json(report_path)
    preference_payload = read_json(preference_file) or {
        "schema_version": 1,
        "revision": 0,
        "preferences": {},
        "_meta": {},
    }
    preferences = preference_payload.setdefault("preferences", {})
    if not isinstance(preferences, dict):
        raise ValueError("偏好文件中的preferences必须是对象")
    skill_preferences = preferences.setdefault("skill_preferences", {})
    if not isinstance(skill_preferences, dict):
        raise ValueError("skill_preferences必须是对象")
    migrated: list[dict[str, object]] = []
    blocked: list[dict[str, str]] = []
    unresolved: list[dict[str, str]] = []
    remaining_custom_chars = 20000
    for raw_item in upgrade_report.get("items", []):
        if not isinstance(raw_item, dict) or raw_item.get("status") not in DIRECT_EDIT_STATUSES:
            continue
        skill = str(raw_item.get("skill") or "").strip()
        backup = Path(str(raw_item.get("backup") or "")) / "SKILL.md"
        old_baseline = Path(str(raw_item.get("old_baseline") or ""))
        if not skill or not backup.is_file() or not old_baseline.is_file():
            unresolved.append({"skill": skill or "未知Skill", "line": "缺少旧官方基线，无法安全自动迁移"})
            continue
        additions = added_lines(
            old_baseline.read_text(encoding="utf-8"),
            backup.read_text(encoding="utf-8"),
        )
        safe_custom: list[str] = []
        global_updates: dict[str, object] = {}
        for line in additions:
            lowered = line.lower()
            if any(term in lowered for term in BLOCKED_TERMS):
                blocked.append({"skill": skill, "line": line})
                continue
            inferred = infer_global_preferences(line)
            if inferred:
                merge_mapping(global_updates, inferred)
                continue
            if len(line) <= 300 and len(safe_custom) < 20 and len(line) <= remaining_custom_chars:
                safe_custom.append(line)
                remaining_custom_chars -= len(line)
            else:
                unresolved.append({"skill": skill, "line": line})
        if global_updates:
            merge_mapping(preferences, global_updates)
        if safe_custom:
            current = skill_preferences.setdefault(skill, {})
            if not isinstance(current, dict):
                current = {}
                skill_preferences[skill] = current
            existing = current.get("custom_instructions", [])
            if not isinstance(existing, list):
                existing = []
            current["custom_instructions"] = list(dict.fromkeys([*existing, *safe_custom]))[:20]
        if global_updates or safe_custom:
            migrated.append(
                {
                    "skill": skill,
                    "global_preferences": global_updates,
                    "custom_instructions": safe_custom,
                }
            )
    meta = preference_payload.setdefault("_meta", {})
    if isinstance(meta, dict) and migrated:
        meta["dirty"] = True
        meta["changed_at"] = now_iso()
        meta["migration_source"] = str(report_path)
    if migrated:
        write_json(preference_file, preference_payload)
    migration_report = {
        "created_at": now_iso(),
        "upgrade_report": str(report_path),
        "preference_file": str(preference_file),
        "migrated": migrated,
        "blocked": blocked,
        "unresolved": unresolved,
        "status": "completed" if migrated and not blocked and not unresolved else "review-required",
    }
    output_path = output_dir / f"{report_path.stem}.preference-migration.json"
    write_json(output_path, migration_report)
    return output_path


def sync_preferences(script_dir: Path, preference_file: Path) -> int:
    if (
        not os.environ.get("JIAOTANG_KB_ENDPOINT")
        or not os.environ.get("JIAOTANG_KB_TOKEN")
        or not os.environ.get("JIAOTANG_KB_DEVICE_ID")
    ):
        print("未检测到云端凭据，偏好已保存在本机；首次配置后再同步。")
        return 0
    module_path = script_dir / "manage_preferences.py"
    specification = importlib.util.spec_from_file_location(
        "jiaotang_manage_preferences",
        module_path,
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("无法加载偏好同步模块")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    parser = module.parser()
    args = parser.parse_args(["--file", str(preference_file), "push", "--summary", "旧Skill个人习惯迁移"])
    return module.command_push(args)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--sync", action="store_true")
    args = parser.parse_args()
    config_dir = args.config_dir.expanduser().resolve()
    try:
        report_path = args.report.expanduser().resolve() if args.report else latest_upgrade_report(config_dir)
        output = migrate_report(
            report_path,
            config_dir / "preferences.json",
            config_dir / "preference-migration-reports",
        )
        result = read_json(output)
        print(f"偏好迁移完成：{len(result.get('migrated', []))}个Skill；报告：{output}")
        if result.get("blocked") or result.get("unresolved"):
            print("存在无法自动接收的内容，已保留在报告中等待确认。")
        if args.sync:
            return sync_preferences(Path(__file__).parent, config_dir / "preferences.json")
        return 0
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError, RuntimeError) as error:
        print(f"迁移失败：{error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
