from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/health_recovery_state.py"
SPEC = importlib.util.spec_from_file_location("health_recovery_state", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


LIMITS = {
    "failure_threshold": 2,
    "max_restarts": 3,
    "restart_window_seconds": 1800,
    "circuit_cooldown_seconds": 3600,
}


def apply(payload, event: str, now: datetime):
    return MODULE.transition(payload, event=event, now=now, **LIMITS)


def test_two_consecutive_failures_restart_and_success_resets_counter():
    started = datetime(2026, 8, 1, tzinfo=timezone.utc)
    first = apply(MODULE.empty_state(), "failure", started)
    assert first["action"] == "wait_for_consecutive_failure"
    assert first["consecutive_failures"] == 1

    second = apply(first, "failure", started + timedelta(minutes=1))
    assert second["action"] == "restart"
    assert second["consecutive_failures"] == 0
    assert second["restart_count_in_window"] == 1

    next_failure = apply(second, "failure", started + timedelta(minutes=2))
    recovered = apply(next_failure, "success", started + timedelta(minutes=3))
    assert recovered["action"] == "healthy"
    assert recovered["consecutive_failures"] == 0
    assert recovered["restart_count_in_window"] == 1
    assert recovered["circuit_open_until"] is None


def test_fourth_restart_attempt_opens_circuit_and_cooldown_is_bounded():
    started = datetime(2026, 8, 1, tzinfo=timezone.utc)
    state = MODULE.empty_state()
    for minute in range(6):
        state = apply(state, "failure", started + timedelta(minutes=minute))
    assert state["action"] == "restart"
    assert state["restart_count_in_window"] == 3

    state = apply(state, "failure", started + timedelta(minutes=6))
    state = apply(state, "failure", started + timedelta(minutes=7))
    assert state["action"] == "circuit_opened"
    assert state["restart_count_in_window"] == 3
    assert state["circuit_open_until"] == "2026-08-01T01:07:00Z"

    suppressed = apply(state, "failure", started + timedelta(minutes=8))
    assert suppressed["action"] == "circuit_open"
    assert suppressed["restart_count_in_window"] == 3

    after_cooldown = apply(
        suppressed, "failure", started + timedelta(minutes=68)
    )
    assert after_cooldown["action"] == "wait_for_consecutive_failure"
    assert after_cooldown["restart_count_in_window"] == 0
    assert after_cooldown["circuit_open_until"] is None


def test_update_state_persists_atomic_machine_readable_state(tmp_path: Path):
    state_file = tmp_path / "health-recovery-state.json"
    now = datetime(2026, 8, 1, tzinfo=timezone.utc)
    result = MODULE.update_state(
        state_file,
        event="failure",
        now=now,
        **LIMITS,
    )
    assert state_file.is_file()
    assert (state_file.stat().st_mode & 0o777) == 0o640
    assert result["action"] == "wait_for_consecutive_failure"
    loaded = MODULE.load_state(state_file)
    assert loaded["schema"] == MODULE.SCHEMA
    assert loaded["last_event"] == "failure"
    assert not list(tmp_path.glob(".*.tmp"))
