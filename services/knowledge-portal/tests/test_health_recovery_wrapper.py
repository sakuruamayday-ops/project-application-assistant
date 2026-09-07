from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("active", "response", "curl_status", "alert_only"),
    [
        (True, {"status": "ok", "checks": {"portal_database": True, "knowledge_index": True}}, 0, True),
        (True, {"status": "ok", "checks": {"portal_database": False, "knowledge_index": True}}, 0, False),
        (True, {"status": "error"}, 22, False),
        (True, "malformed", 0, False),
        (True, {"status": "ok"}, 0, False),
        (False, {"status": "ok"}, 0, False),
    ],
)
def test_live_readiness_controls_restart_without_clearing_alerts(
    tmp_path, active, response, curl_status, alert_only
):
    app = tmp_path / "app"
    (app / ".venv/bin").mkdir(parents=True)
    (app / ".venv/bin/python").symlink_to(sys.executable)
    (app / "scripts").symlink_to(ROOT / "scripts", target_is_directory=True)
    commands = tmp_path / "bin"
    commands.mkdir()
    scripts = {
        "systemctl": '#!/bin/sh\ncase "$1" in is-active) [ -f "$CALL_LOG.restarted" ] && exit 0; exit "$ACTIVE_STATUS";; restart) echo restart >> "$CALL_LOG"; touch "$CALL_LOG.restarted";; esac\n',
        "curl": '#!/bin/sh\nprintf "%s" "$READY_JSON"\nexit "$CURL_STATUS"\n',
        "logger": '#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALL_LOG"\n',
    }
    for name, body in scripts.items():
        path = commands / name
        path.write_text(body)
        path.chmod(0o755)
    state = tmp_path / "health-recovery-state.json"
    alert = tmp_path / "health-status.json"
    alert.write_text('{"status":"异常","disk_percent":92}')
    env = {
        **os.environ,
        "PATH": f"{commands}:{os.environ['PATH']}",
        "JIAOTANG_APP_DIR": str(app),
        "JIAOTANG_DATA_DIR": str(tmp_path),
        "JIAOTANG_HEALTH_RECOVERY_STATE": str(state),
        "ACTIVE_STATUS": "0" if active else "3",
        "READY_JSON": response if isinstance(response, str) else json.dumps(response),
        "CURL_STATUS": str(curl_status),
        "CALL_LOG": str(tmp_path / "calls"),
    }
    if alert_only:
        subprocess.run([
            sys.executable, str(ROOT / "scripts/health_recovery_state.py"),
            "failure", "--state-file", str(state),
        ], check=True, capture_output=True)
    for _ in range(2):
        subprocess.run(["bash", str(ROOT / "deploy/health-recovery.sh")], env=env, check=True, capture_output=True)
    calls = (tmp_path / "calls").read_text().splitlines()
    assert ("restart" in calls) is not alert_only
    assert state.exists()
    assert json.loads(alert.read_text()) == {"status": "异常", "disk_percent": 92}
    if alert_only:
        assert all("action=alert_only" in line for line in calls)
        assert json.loads(state.read_text())["consecutive_failures"] == 0
        assert json.loads(state.read_text())["restart_count_in_window"] == 0
    else:
        assert json.loads(state.read_text())["restart_count_in_window"] == 1
