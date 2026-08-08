from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"


def load_script(name: str):
    path = SCRIPT_DIR / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_request(tmp_path: Path, *, release_mode: str = "code"):
    module = load_script("run_application_deployment.py")
    deployment_id = "20260803T200000Z-123456789abc-deadbeef"
    runtime = tmp_path / "runtime"
    release_root = tmp_path / "releases"
    previous = release_root / "previous-release"
    release = release_root / deployment_id
    runtime.mkdir()
    previous.mkdir(parents=True)
    release.mkdir()
    for relative in (
        "app/main.py",
        ".venv/bin/python",
        "scripts/migrate_first_public_release.py",
        "scripts/verify_authenticated_portal.py",
        "scripts/refresh_index_from_oss.py",
    ):
        path = release / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("pass\n", encoding="utf-8")
    (runtime / "current").symlink_to(previous)
    (runtime / "previous").symlink_to(previous)
    expected_build = {
        key: f"new-{key}" for key in module.BUILD_KEYS
    }
    expected_build["deployment_id"] = deployment_id
    previous_build = {
        key: f"old-{key}" for key in module.BUILD_KEYS
    }
    candidate_ops_env = tmp_path / f"{deployment_id}.candidate-ops.env"
    candidate_app_env = tmp_path / f"{deployment_id}.candidate-app.env"
    candidate_ops_env.write_text("OPS=true\n", encoding="utf-8")
    candidate_app_env.write_text("APP=true\n", encoding="utf-8")
    request = {
        "schema": module.REQUEST_SCHEMA,
        "deployment_id": deployment_id,
        "release_mode": release_mode,
        "runtime_root": str(runtime),
        "release_root": str(release_root),
        "release_dir": str(release),
        "previous_release_dir": str(previous),
        "expected_build": expected_build,
        "previous_build": previous_build,
        "candidate_ops_env": str(candidate_ops_env),
        "candidate_app_env": str(candidate_app_env),
        "created_at": "2026-08-03T20:00:00+00:00",
    }
    request_path = tmp_path / "request.json"
    state_path = tmp_path / "state.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    return module, request, request_path, state_path, runtime, release, previous


def install_success_fakes(monkeypatch, module, expected_build):
    commands: list[list[str]] = []

    def fake_run(command: list[str], *, timeout: int = 180):
        commands.append(command)

    def fake_fetch(url: str, *, timeout: int = 20):
        if url.endswith("/build"):
            return expected_build
        return {"status": "ok"}

    monkeypatch.setattr(module, "run_checked", fake_run)
    monkeypatch.setattr(module, "fetch_json", fake_fetch)
    monkeypatch.setattr(module, "verify_public_routes", lambda _host: None)
    monkeypatch.setattr(module, "install_candidate_environment", lambda _request: None)
    monkeypatch.setattr(
        module,
        "parse_env",
        lambda _path: {
            "JIAOTANG_DATA_DIR": "/var/lib/jiaotang-kb",
            "JIAOTANG_SKILL_RELEASE_DIR": "/srv/jiaotang/skill-releases",
            "JIAOTANG_PUBLIC_HOST": "example.invalid",
        },
    )
    monkeypatch.setattr(module, "restore_previous_build", lambda _build: None)
    monkeypatch.setattr(module, "configure_index_verifier", lambda _env: "test.timer")
    return commands


def test_server_transaction_completes_and_records_phase_history(tmp_path, monkeypatch):
    module, request, request_path, state_path, runtime, release, _ = make_request(
        tmp_path
    )
    commands = install_success_fakes(
        monkeypatch, module, request["expected_build"]
    )
    stale = Path(request["release_root"]) / "stale-release"
    stale.mkdir()
    (stale / "payload.bin").write_bytes(b"stale")
    trash = tmp_path / "trash"
    monkeypatch.setenv("JIAOTANG_RELEASE_TRASH_ROOT", str(trash))

    assert module.execute(request_path, state_path) == 0

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["phase"] == "completed"
    assert state["terminal"] is True
    assert state["success"] is True
    assert state["retention_cleanup"]["removed_count"] == 1
    assert not stale.exists()
    assert len(list(trash.iterdir())) == 1
    assert (runtime / "current").resolve() == release
    phases = [item["phase"] for item in state["history"]]
    assert phases == [
        "accepted",
        "switched",
        "service_ready",
        "migration_complete",
        "portal_verified",
        "routes_verified",
        "completed",
    ]
    assert not any("refresh_index_from_oss.py" in part for cmd in commands for part in cmd)


def test_candidate_environment_is_activated_atomically_with_fixed_modes(tmp_path):
    module, request, _, _, _, _, _ = make_request(tmp_path)
    ops_target = tmp_path / "active-ops.env"
    app_target = tmp_path / "active-app.env"

    module.install_candidate_environment(
        request,
        state_dir=tmp_path,
        ops_target=ops_target,
        app_target=app_target,
        owner_id=os.getuid(),
        ops_group_id=os.getgid(),
        app_group_id=os.getgid(),
    )

    assert ops_target.read_text(encoding="utf-8") == "OPS=true\n"
    assert app_target.read_text(encoding="utf-8") == "APP=true\n"
    assert ops_target.stat().st_mode & 0o777 == 0o600
    assert app_target.stat().st_mode & 0o777 == 0o640


def test_code_transaction_failure_rolls_back_without_index_operation(
    tmp_path, monkeypatch
):
    module, request, request_path, state_path, runtime, _, previous = make_request(
        tmp_path
    )
    commands = install_success_fakes(
        monkeypatch, module, request["expected_build"]
    )
    original_runner = module.run_checked

    def fail_portal(command: list[str], *, timeout: int = 180):
        if any("verify_authenticated_portal.py" in part for part in command):
            raise subprocess.CalledProcessError(1, command)
        original_runner(command, timeout=timeout)

    monkeypatch.setattr(module, "run_checked", fail_portal)

    with pytest.raises(subprocess.CalledProcessError):
        module.execute(request_path, state_path)

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["phase"] == "rolled_back"
    assert state["rollback"] == "completed"
    assert (runtime / "current").resolve() == previous
    assert not any("refresh_index_from_oss.py" in part for cmd in commands for part in cmd)


def test_index_transaction_failure_rolls_back_index_once(tmp_path, monkeypatch):
    module, request, request_path, state_path, _, _, _ = make_request(
        tmp_path, release_mode="index"
    )
    commands = install_success_fakes(
        monkeypatch, module, request["expected_build"]
    )
    original_runner = module.run_checked

    def fail_portal(command: list[str], *, timeout: int = 180):
        if any("verify_authenticated_portal.py" in part for part in command):
            raise subprocess.CalledProcessError(1, command)
        original_runner(command, timeout=timeout)

    monkeypatch.setattr(module, "run_checked", fail_portal)

    with pytest.raises(subprocess.CalledProcessError):
        module.execute(request_path, state_path)

    rollback_commands = [
        command
        for command in commands
        if any("refresh_index_from_oss.py" in part for part in command)
    ]
    assert len(rollback_commands) == 1
    assert rollback_commands[0][-1] == "--rollback"


def test_completed_transaction_revalidates_without_restarting(tmp_path, monkeypatch):
    module, request, request_path, state_path, runtime, release, _ = make_request(
        tmp_path
    )
    (runtime / "current").unlink()
    (runtime / "current").symlink_to(release)
    state_path.write_text(
        json.dumps(
            {
                "schema": module.STATE_SCHEMA,
                "deployment_id": request["deployment_id"],
                "phase": "completed",
            }
        ),
        encoding="utf-8",
    )
    commands = install_success_fakes(
        monkeypatch, module, request["expected_build"]
    )

    assert module.execute(request_path, state_path) == 0
    assert commands == []


def test_receipt_polling_recovers_after_transport_disconnect():
    module = load_script("wait_for_application_deployment.py")
    deployment_id = "20260803T200000Z-123456789abc-deadbeef"
    responses = [
        subprocess.CalledProcessError(255, ["ssh"]),
        {
            "schema": module.STATE_SCHEMA,
            "deployment_id": deployment_id,
            "phase": "service_ready",
        },
        {
            "schema": module.STATE_SCHEMA,
            "deployment_id": deployment_id,
            "phase": "completed",
            "success": True,
        },
    ]
    now = [0.0]

    def fetcher():
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    state, failures = module.wait_for_terminal_state(
        fetcher,
        deployment_id=deployment_id,
        timeout_seconds=30,
        poll_seconds=1,
        clock=lambda: now[0],
        sleeper=lambda seconds: now.__setitem__(0, now[0] + seconds),
    )

    assert state["phase"] == "completed"
    assert failures == 1
