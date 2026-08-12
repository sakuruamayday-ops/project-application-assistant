#!/usr/bin/env python3
"""Audit local jiaotang-* skills against the formal suite reconciliation ledger."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ALLOWED_STATUSES = {"formal", "merged_into", "retained_local_extension", "excluded"}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skills-root", type=Path, required=True)
    parser.add_argument("--local-root", type=Path, action="append", default=[])
    args = parser.parse_args()

    skills_root = args.skills_root.expanduser().resolve()
    manifest = load(skills_root / "suite-manifest.json")
    ledger = load(skills_root / "local-skill-reconciliation.json")
    formal = set(manifest.get("skills") or [])
    entries = dict(ledger.get("entries") or {})
    errors: list[str] = []

    for name, item in sorted(entries.items()):
        status = item.get("status")
        target = item.get("formal_target")
        reason = str(item.get("reason") or "").strip()
        if status not in ALLOWED_STATUSES:
            errors.append(f"{name}: invalid status {status!r}")
        if not reason:
            errors.append(f"{name}: missing reason")
        if status == "formal" and (name not in formal or target != name):
            errors.append(f"{name}: formal entry must exist under the same manifest name")
        if status in {"merged_into", "retained_local_extension"} and target not in formal:
            errors.append(f"{name}: formal target {target!r} is not declared")
        if status == "excluded" and target:
            errors.append(f"{name}: excluded entry must not declare a formal target")

    local_roots = args.local_root or [Path.home() / ".codex" / "skills"]
    discovered: set[str] = set()
    for root in local_roots:
        root = root.expanduser().resolve()
        if not root.is_dir():
            continue
        discovered.update(
            path.name
            for path in root.iterdir()
            if path.is_dir() and path.name.startswith("jiaotang-")
        )

    unregistered = sorted(discovered - set(entries))
    if unregistered:
        errors.append("unregistered local skills: " + ", ".join(unregistered))

    payload = {
        "status": "pass" if not errors else "fail",
        "formal_skill_count": len(formal),
        "local_jiaotang_skills": sorted(discovered),
        "registered_local_skills": sorted(entries),
        "unregistered_local_skills": unregistered,
        "errors": errors,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
