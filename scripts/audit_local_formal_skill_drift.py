#!/usr/bin/env python3
"""Audit every visible local skill against the formal-suite inventory policy."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ALLOWED_STATUSES = {
    "merged_into",
    "retained_local_extension",
    "shared_runtime",
    "administrator_tool",
    "external_capability",
    "system_skill",
    "excluded",
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def discover(root: Path, *, recursive: bool = False) -> dict[str, list[str]]:
    if not root.is_dir():
        return {}
    skill_files = root.rglob("SKILL.md") if recursive else (
        path / "SKILL.md" for path in root.iterdir() if path.is_dir()
    )
    discovered: dict[str, list[str]] = {}
    for skill_file in skill_files:
        if not skill_file.is_file():
            continue
        discovered.setdefault(skill_file.parent.name, []).append(str(skill_file.parent))
    return {name: sorted(paths) for name, paths in discovered.items()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skills-root", type=Path, required=True)
    parser.add_argument("--local-root", type=Path, action="append", default=[])
    parser.add_argument("--candidate-skill-dir", type=Path, action="append", default=[])
    args = parser.parse_args()

    skills_root = args.skills_root.expanduser().resolve()
    manifest = load(skills_root / "suite-manifest.json")
    ledger = load(skills_root / "local-skill-reconciliation.json")
    formal_list = manifest.get("skills") or []
    formal = set(formal_list)
    entries = dict(ledger.get("entries") or {})
    root_policies = list(ledger.get("root_policies") or [])
    shared_paths = set(manifest.get("shared_paths") or [])
    errors: list[str] = []

    candidate_names: set[str] = set()
    for raw_candidate in args.candidate_skill_dir:
        candidate = raw_candidate.expanduser().resolve()
        if candidate.parent != skills_root or not (candidate / "SKILL.md").is_file():
            errors.append(
                f"candidate skill must be a direct source child with SKILL.md: {candidate}"
            )
            continue
        if candidate.name not in formal:
            errors.append(f"candidate skill is not declared formal: {candidate.name}")
            continue
        candidate_names.add(candidate.name)

    if not formal_list or len(formal_list) != len(formal):
        errors.append("suite-manifest formal skill list is empty or duplicated")

    for name, item in sorted(entries.items()):
        status = item.get("status")
        target = item.get("formal_target")
        targets = item.get("formal_targets")
        runtime_target = item.get("runtime_target")
        reason = str(item.get("reason") or "").strip()
        if status not in ALLOWED_STATUSES:
            errors.append(f"{name}: invalid status {status!r}")
        if not reason:
            errors.append(f"{name}: missing reason")
        for field in ("source", "owner", "package_policy"):
            if not str(item.get(field) or "").strip():
                errors.append(f"{name}: missing {field}")
        if item.get("package_policy") != "exclude_from_suite":
            errors.append(f"{name}: non-formal skill must be excluded from suite packaging")
        if targets is not None and (
            not isinstance(targets, list)
            or not targets
            or not all(isinstance(item, str) and item in formal for item in targets)
        ):
            errors.append(f"{name}: formal_targets must be non-empty declared formal skills")
        resolved_targets = set(targets or ([] if target is None else [target]))
        if status in {"merged_into", "retained_local_extension"} and (
            not resolved_targets or not resolved_targets.issubset(formal)
        ):
            errors.append(f"{name}: formal targets {sorted(resolved_targets)!r} are not declared")
        if status == "shared_runtime" and runtime_target not in shared_paths:
            errors.append(f"{name}: shared runtime {runtime_target!r} is not declared")
        if status in {"administrator_tool", "external_capability", "system_skill", "excluded"} and (
            target or targets or runtime_target
        ):
            errors.append(f"{name}: {status} entry must not declare a formal target")
        if name in formal:
            errors.append(
                f"{name}: manifest skill cannot be duplicated in the non-formal ledger"
            )

    explicit_roots = args.local_root or [
        Path.home() / ".codex" / "skills",
        Path.home() / ".agents" / "skills",
    ]
    root_specs: list[dict[str, object]] = [
        {
            "path": root.expanduser().resolve(),
            "recursive": False,
            "classification": None,
            "requires_entry": True,
        }
        for root in explicit_roots
    ]
    for policy in root_policies:
        if not isinstance(policy, dict):
            errors.append("root policy must be an object")
            continue
        status = policy.get("status")
        path_value = str(policy.get("path") or "").strip()
        reason = str(policy.get("reason") or "").strip()
        if status not in {"external_capability", "system_skill"}:
            errors.append(f"root policy has invalid status {status!r}")
            continue
        if not path_value or not reason:
            errors.append("root policy is missing path or reason")
            continue
        root_specs.append(
            {
                "path": Path(path_value).expanduser().resolve(),
                "recursive": bool(policy.get("recursive")),
                "classification": status,
                "requires_entry": False,
            }
        )

    discovered_by_root: dict[str, dict[str, object]] = {}
    discovered_paths: dict[str, list[dict[str, object]]] = {}
    discovered: set[str] = set()
    for spec in root_specs:
        root = Path(spec["path"])
        skills = discover(root, recursive=bool(spec["recursive"]))
        discovered.update(skills)
        discovered_by_root[str(root)] = {
            "recursive": bool(spec["recursive"]),
            "classification": spec["classification"],
            "skills": skills,
        }
        for name, paths in skills.items():
            for path in paths:
                discovered_paths.setdefault(name, []).append(
                    {
                        "path": path,
                        "classification": spec["classification"],
                        "requires_entry": bool(spec["requires_entry"]),
                    }
                )

    unregistered = sorted(
        name
        for name in discovered - formal - set(entries)
        if any(item["requires_entry"] for item in discovered_paths[name])
        or not all(item["classification"] for item in discovered_paths[name])
    )
    if unregistered:
        errors.append("unregistered local skills: " + ", ".join(unregistered))

    missing_formal = sorted(formal - discovered - candidate_names)
    if missing_formal:
        errors.append("formal skills missing from local roots: " + ", ".join(missing_formal))

    payload = {
        "status": "pass" if not errors else "fail",
        "formal_skill_count": len(formal),
        "formal_skills": sorted(formal),
        "local_roots": discovered_by_root,
        "skill_inventory": {
            name: {
                "classification": (
                    "formal"
                    if name in formal
                    else str(entries[name]["status"])
                    if name in entries
                    else next(
                        str(item["classification"] or "unregistered")
                        for item in discovered_paths[name]
                    )
                ),
                "package_policy": (
                    "include_from_suite_manifest"
                    if name in formal
                    else str(entries[name].get("package_policy"))
                    if name in entries
                    else "exclude_from_suite"
                ),
                "locations": sorted(item["path"] for item in discovered_paths[name]),
            }
            for name in sorted(discovered)
        },
        "discovered_skill_count": len(discovered),
        "registered_non_formal_skills": sorted(entries),
        "unregistered_local_skills": unregistered,
        "missing_formal_skills": missing_formal,
        "candidate_skills_pending_local_sync": sorted(candidate_names - discovered),
        "package_input": "suite-manifest.json:skills",
        "errors": errors,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
