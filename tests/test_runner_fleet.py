from __future__ import annotations

import importlib.util
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
