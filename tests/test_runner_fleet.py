from __future__ import annotations

import importlib.util
import os
import pwd
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "check_runner_fleet.py"
SPEC = importlib.util.spec_from_file_location("check_runner_fleet", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def runner(name: str, label: str, status: str = "online") -> dict[str, object]:
    return {
        "name": name,
        "status": status,
        "busy": False,
        "labels": [
            {"name": "self-hosted"},
            {"name": "workbuddy"},
            {"name": label},
        ],
    }


def test_fleet_status_is_case_insensitive_and_requires_both_hosts() -> None:
    rows, failures = MODULE.fleet_status(
        {
            "runners": [
                runner("mac", "macOS"),
                runner("windows", "Windows"),
            ]
        }
    )
    assert not failures
    assert "mac | online" in "\n".join(rows)
    assert "windows | online" in "\n".join(rows)

    _, failures = MODULE.fleet_status(
        {"runners": [runner("mac", "macOS")]}
    )
    assert failures == ["windows: matched=0, online=0"]


def test_gh_environment_uses_service_account_home(monkeypatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "workflow-token")
    monkeypatch.setenv("GITHUB_TOKEN", "workflow-token")
    monkeypatch.setenv("HOME", "/tmp/actions-runner-home")
    monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/actions-xdg")
    monkeypatch.setenv("GH_CONFIG_DIR", "/tmp/actions-gh")

    environment = MODULE.gh_environment()

    assert "GH_TOKEN" not in environment
    assert "GITHUB_TOKEN" not in environment
    assert "XDG_CONFIG_HOME" not in environment
    service_home = pwd.getpwuid(os.getuid()).pw_dir
    assert environment["HOME"] == service_home
    assert environment["GH_CONFIG_DIR"] == str(Path(service_home) / ".config" / "gh")
