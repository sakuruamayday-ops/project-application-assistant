#!/usr/bin/env python3
"""Check the repository's macOS and Windows WorkBuddy runner fleet."""
from __future__ import annotations

import json
import os
import pwd
import subprocess
import sys


REQUIRED = {
    "macos": {"self-hosted", "workbuddy", "macos"},
    "windows": {"self-hosted", "workbuddy", "windows"},
}


def gh_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("GH_TOKEN", None)
    environment.pop("GITHUB_TOKEN", None)
    # Actions rewrites HOME to the runner work directory. Restore the service
    # account's real home so gh can use its existing macOS Keychain credential.
    environment["HOME"] = pwd.getpwuid(os.getuid()).pw_dir
    return environment


def fleet_status(payload: dict[str, object]) -> tuple[list[str], list[str]]:
    runners = payload.get("runners")
    if not isinstance(runners, list):
        raise RuntimeError("GitHub Runner 返回结构无效")
    rows: list[str] = []
    failures: list[str] = []
    for host, labels in REQUIRED.items():
        matches = []
        for runner in runners:
            actual = {
                str(label.get("name") or "").casefold()
                for label in runner.get("labels", [])
            }
            if labels <= actual:
                matches.append(runner)
        online = [runner for runner in matches if runner.get("status") == "online"]
        state = "online" if len(online) == 1 else "missing/offline"
        name = str(online[0]["name"]) if len(online) == 1 else "—"
        busy = (
            str(online[0].get("busy", "—")).lower()
            if len(online) == 1
            else "—"
        )
        rows.append(f"| {host} | {name} | {state} | {busy} |")
        if len(online) != 1:
            failures.append(
                f"{host}: matched={len(matches)}, online={len(online)}"
            )
    return rows, failures


def main() -> None:
    repository = os.environ.get(
        "GITHUB_REPOSITORY",
        "sakuruamayday-ops/project-application-assistant",
    )
    completed = subprocess.run(
        ["gh", "api", f"repos/{repository}/actions/runners"],
        check=False,
        capture_output=True,
        text=True,
        env=gh_environment(),
    )
    if completed.returncode != 0:
        raise SystemExit(
            "Runner API failed: "
            + (completed.stderr.strip() or f"exit {completed.returncode}")
        )
    rows, failures = fleet_status(json.loads(completed.stdout))
    report = (
        "## WorkBuddy Runner Fleet\n\n"
        "| Host | Runner | Status | Busy |\n"
        "|---|---|---|---|\n"
        + "\n".join(rows)
        + "\n"
    )
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as output:
            output.write(report)
    else:
        sys.stdout.write(report)
    if failures:
        raise SystemExit("Runner fleet unhealthy: " + "; ".join(failures))


if __name__ == "__main__":
    main()
