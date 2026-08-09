from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPOSITORY = Path(__file__).resolve().parents[1]
RUNTIME = REPOSITORY / "runtime/workbuddy"
WINDOWS_SOURCE = RUNTIME / "windows_hook"


def test_windows_hook_registration_uses_deterministic_marketplace_root():
    payload = json.loads((RUNTIME / "windows-hooks.json").read_text("utf-8"))
    assert set(payload["hooks"]) == {
        "SessionStart",
        "UserPromptSubmit",
        "Stop",
    }
    for groups in payload["hooks"].values():
        command = groups[0]["hooks"][0]["command"]
        assert command.startswith(
            '"$HOME/.workbuddy/plugins/marketplaces/jiaotang/plugins/'
            'jiaotang-workbuddy-skills/scripts/'
            'workbuddy_behavior_hook_windows.exe" '
        )
        assert "${CODEBUDDY_PLUGIN_ROOT}" not in command
        assert "powershell" not in command.casefold()
        assert ".cmd" not in command.casefold()
        assert "python" not in command.casefold()


def test_windows_hook_source_contains_truthful_activation_recovery():
    main = (WINDOWS_SOURCE / "main.go").read_text("utf-8")
    events = (WINDOWS_SOURCE / "events.go").read_text("utf-8")
    state = (WINDOWS_SOURCE / "state.go").read_text("utf-8")
    assert 'runtimeVersion = "1.6.2"' in main
    assert 'case "session-start"' in main
    assert '"skill_activation_recovery"' in events
    assert '"session_transcript"' in events
    assert "ACTIVATION_TRANSCRIPT_AMBIGUOUS" in events
    assert "PromptEventID" in state


def test_versioned_windows_hook_go_suite_passes():
    go_binary = os.environ.get("JIAOTANG_GO", "").strip() or shutil.which("go")
    if not go_binary:
        pytest.skip("Go toolchain unavailable")
    subprocess.run(
        [go_binary, "test", "./..."],
        cwd=WINDOWS_SOURCE,
        check=True,
        env={**os.environ, "CGO_ENABLED": "0"},
    )
