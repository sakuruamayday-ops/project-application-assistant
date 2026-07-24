#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


PROFILES = {
    "application-evidence",
    "policy-corpus",
    "ip-evidence",
    "client-dossier",
}
PRIVACY = {"restricted", "internal", "public"}


def atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temp_name = handle.name
    os.replace(temp_name, path)


def graphify_version() -> str:
    executable = shutil.which("graphify")
    if executable:
        try:
            result = subprocess.run(
                [executable, "--version"],
                text=True,
                capture_output=True,
                timeout=5,
                check=False,
            )
            parts = result.stdout.strip().split()
            if len(parts) >= 2 and parts[0] == "graphify":
                return parts[1]
        except (OSError, subprocess.SubprocessError):
            pass
    return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize a project-scoped Jiaotang Graphify profile.")
    parser.add_argument("project_root", type=Path)
    parser.add_argument("--profile", required=True, choices=sorted(PROFILES))
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--client-name", default="")
    parser.add_argument("--privacy", choices=sorted(PRIVACY), default="restricted")
    parser.add_argument("--review-version", default="")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    root = args.project_root.expanduser().resolve()
    if root in {Path("/"), Path.home().resolve()}:
        raise SystemExit("refusing broad scan root; choose a single project directory")
    root.mkdir(parents=True, exist_ok=True)
    target = root / ".jiaotang-graphify.json"
    if target.exists() and not args.force:
        raise SystemExit(f"profile already exists: {target}")

    profile = {
        "schema_version": "1.0",
        "profile": args.profile,
        "project_name": args.project_name,
        "client_name": args.client_name,
        "privacy": args.privacy,
        "review_version": args.review_version,
        "project_root": str(root),
        "created_at": datetime.now().astimezone().isoformat(),
        "graphify_version": graphify_version(),
        "external_backend_authorized": False,
    }
    atomic_json(target, profile)
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
