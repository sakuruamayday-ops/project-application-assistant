#!/usr/bin/env python3
"""Aggregate correction signals and emit a gated batch-evolution manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def normalized_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def signal_id(signal: dict[str, Any]) -> str:
    explicit = str(signal.get("id") or "").strip()
    if explicit:
        return explicit
    payload = "|".join(
        normalized_text(signal.get(key))
        for key in ("task_id", "skill", "rule_key", "category", "summary")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def load_jsonl(paths: list[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in paths:
        if not path.is_file():
            continue
        for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not raw.strip():
                continue
            try:
                item = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number} 不是有效JSONL") from exc
            if not isinstance(item, dict):
                continue
            item_id = signal_id(item)
            if item_id in seen:
                continue
            seen.add(item_id)
            item["_id"] = item_id
            records.append(item)
    return records


def load_policy(config_path: Path) -> dict[str, Any]:
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    policy = data.get("evolution", {}).get("correction_batch", {})
    return {
        "min_signal_count": int(policy.get("min_signal_count", 3)),
        "min_distinct_tasks": int(policy.get("min_distinct_tasks", 2)),
        "max_batch_skills": int(policy.get("max_batch_skills", 2)),
        "cooldown_days": int(policy.get("cooldown_days", 7)),
        "require_verified": bool(policy.get("require_verified", True)),
    }


def eligible(signal: dict[str, Any], require_verified: bool) -> tuple[bool, str]:
    required = ("skill", "rule_key", "task_id", "summary")
    if any(not str(signal.get(field) or "").strip() for field in required):
        return False, "missing_required_field"
    if bool(signal.get("sensitive", False)):
        return False, "sensitive"
    if require_verified and not bool(signal.get("verified", False)):
        return False, "unverified"
    return True, "eligible"


def aggregate(records: list[dict[str, Any]], policy: dict[str, Any], state: dict[str, Any], now: datetime) -> dict[str, Any]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    excluded: dict[str, int] = defaultdict(int)
    for record in records:
        ok, reason = eligible(record, policy["require_verified"])
        if not ok:
            excluded[reason] += 1
            continue
        skill = str(record["skill"]).strip()
        rule_key = str(record["rule_key"]).strip()
        groups[(skill, rule_key)].append(record)

    candidates: list[dict[str, Any]] = []
    group_summaries: list[dict[str, Any]] = []
    for (skill, rule_key), signals in groups.items():
        tasks = sorted({str(item["task_id"]).strip() for item in signals})
        summary = {
            "skill": skill,
            "rule_key": rule_key,
            "signal_count": len(signals),
            "distinct_tasks": len(tasks),
            "needed_signals": max(0, policy["min_signal_count"] - len(signals)),
            "needed_tasks": max(0, policy["min_distinct_tasks"] - len(tasks)),
            "status": "waiting",
        }
        if len(signals) < policy["min_signal_count"] or len(tasks) < policy["min_distinct_tasks"]:
            group_summaries.append(summary)
            continue
        last_planned = parse_time((state.get("last_planned_at_by_skill") or {}).get(skill))
        cooldown_until = last_planned + timedelta(days=policy["cooldown_days"]) if last_planned else None
        if cooldown_until and now < cooldown_until:
            excluded["cooldown"] += len(signals)
            summary["status"] = "cooldown"
            summary["cooldown_until"] = cooldown_until.isoformat()
            group_summaries.append(summary)
            continue
        summary["status"] = "ready"
        group_summaries.append(summary)
        candidates.append(
            {
                "skill": skill,
                "rule_key": rule_key,
                "signal_count": len(signals),
                "distinct_tasks": len(tasks),
                "task_ids": tasks,
                "signal_ids": sorted(str(item["_id"]) for item in signals),
                "severity": sorted({str(item.get("severity") or "medium") for item in signals}),
                "summaries": sorted({str(item["summary"]).strip() for item in signals}),
            }
        )
    candidates.sort(key=lambda item: (-int(item["signal_count"]), -int(item["distinct_tasks"]), str(item["skill"]), str(item["rule_key"])))

    selected_skills: list[str] = []
    selected: list[dict[str, Any]] = []
    for candidate in candidates:
        skill = str(candidate["skill"])
        if skill not in selected_skills:
            if len(selected_skills) >= policy["max_batch_skills"]:
                continue
            selected_skills.append(skill)
        selected.append(candidate)

    return {
        "schema_version": 1,
        "generated_at": now.isoformat(),
        "policy": policy,
        "input_signal_count": len(records),
        "eligible_group_count": len(groups),
        "excluded": dict(sorted(excluded.items())),
        "groups": sorted(group_summaries, key=lambda item: (str(item["skill"]), str(item["rule_key"]))),
        "ready": bool(selected),
        "selected_skills": selected_skills,
        "candidates": selected,
        "deferred_candidate_count": max(0, len(candidates) - len(selected)),
        "governance": {
            "mode": "dry_run",
            "requires_impact_graph": True,
            "requires_snapshot": True,
            "requires_human_approval": True,
            "automatic_skill_write": False,
            "automatic_gepa_run": False,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="聚合高频纠正并生成批量进化候选清单")
    default_root = Path(__file__).resolve().parents[3]
    parser.add_argument("--root", type=Path, default=default_root)
    parser.add_argument("--input", action="append", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--now", help="测试或回放使用的ISO时间")
    parser.add_argument("--mark-planned", action="store_true", help="批次开始处理后写入冷却状态")
    args = parser.parse_args()

    root = args.root.resolve()
    config_path = args.config or root / "config" / "common.yaml"
    output_dir = args.output_dir or root / ".project-assistant" / "evolution"
    state_path = args.state or output_dir / "evolution-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
    now = parse_time(args.now) if args.now else datetime.now(timezone.utc)
    if now is None:
        raise SystemExit("--now 必须是ISO时间")
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    policy = load_policy(config_path)
    records = load_jsonl([path.resolve() for path in args.input])
    result = aggregate(records, policy, state, now)
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.mark_planned and result["ready"]:
        planned = dict(state.get("last_planned_at_by_skill") or {})
        for skill in result["selected_skills"]:
            planned[str(skill)] = now.isoformat()
        state["last_planned_at_by_skill"] = planned
        state["last_batch_skills"] = result["selected_skills"]
        state["last_batch_at"] = now.isoformat()
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary_path = output_dir / "correction-summary.json"
    batch_path = output_dir / "evolution-batch.json"
    summary_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    batch_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": str(summary_path), "batch": str(batch_path), "state": str(state_path) if args.mark_planned else None, "ready": result["ready"], "skills": result["selected_skills"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
