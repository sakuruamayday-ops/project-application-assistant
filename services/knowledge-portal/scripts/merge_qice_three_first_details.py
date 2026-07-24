#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="合并企策顾问三首项目采集快照并保留历史来源链接")
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def nonempty(value: Any) -> bool:
    return value not in (None, "", [], {})


def merge_dict(current: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    merged = dict(previous)
    for key, value in current.items():
        if nonempty(value):
            merged[key] = value
    return merged


def project_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item.get("projectId") or ""): item for item in payload.get("projects", [])}


def policy_key(policy: dict[str, Any]) -> str:
    meta = policy.get("policy") if isinstance(policy.get("policy"), dict) else policy
    return str(meta.get("indexId") or meta.get("id") or meta.get("policyId") or meta.get("title") or "")


def merge_policy(current: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    current_meta = current.get("policy") if isinstance(current.get("policy"), dict) else {}
    previous_meta = previous.get("policy") if isinstance(previous.get("policy"), dict) else {}
    merged = dict(previous)
    merged.update(current)
    merged["policy"] = merge_dict(current_meta, previous_meta)
    if not current.get("records") and previous.get("records"):
        merged["records"] = previous["records"]
    return merged


def main() -> None:
    args = parse_args()
    current = json.loads(args.current.read_text(encoding="utf-8"))
    previous = json.loads(args.previous.read_text(encoding="utf-8"))
    current_projects = project_map(current)
    previous_projects = project_map(previous)
    projects: list[dict[str, Any]] = []
    for project_id in sorted(set(current_projects) | set(previous_projects)):
        current_project = current_projects.get(project_id, {})
        previous_project = previous_projects.get(project_id, {})
        current_policies = {policy_key(item): item for item in current_project.get("policies", [])}
        previous_policies = {policy_key(item): item for item in previous_project.get("policies", [])}
        policies = []
        for key in sorted(set(current_policies) | set(previous_policies)):
            if key in current_policies and key in previous_policies:
                policies.append(merge_policy(current_policies[key], previous_policies[key]))
            else:
                policies.append(current_policies.get(key) or previous_policies[key])
        projects.append(
            {
                "projectId": project_id,
                "projectName": current_project.get("projectName") or previous_project.get("projectName") or "",
                "relatedPolicyCount": max(
                    int(current_project.get("relatedPolicyCount") or 0),
                    int(previous_project.get("relatedPolicyCount") or 0),
                ),
                "selectedPolicyCount": len(policies),
                "policies": policies,
            }
        )
    output = {
        "schema_version": 2,
        "merged_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "sources": [str(args.current), str(args.previous)],
        "projects": projects,
        "failures": [*current.get("failures", []), *previous.get("failures", [])],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "projects": len(projects),
                "policies": sum(len(item["policies"]) for item in projects),
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
