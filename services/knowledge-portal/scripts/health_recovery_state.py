#!/usr/bin/env python3
"""Persist the portal health-recovery circuit breaker state atomically."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


SCHEMA = "jiaotang-health-recovery/v1"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_time(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def empty_state() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "consecutive_failures": 0,
        "restart_timestamps": [],
        "circuit_open_until": None,
        "last_event": None,
        "last_event_at": None,
        "last_action": "none",
    }


def normalize_state(payload: object) -> dict[str, Any]:
    state = empty_state()
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        return state
    try:
        state["consecutive_failures"] = max(
            0, int(payload.get("consecutive_failures") or 0)
        )
    except (TypeError, ValueError):
        state["consecutive_failures"] = 0
    restart_timestamps = []
    for item in payload.get("restart_timestamps") or []:
        try:
            parsed = parse_time(str(item))
        except (TypeError, ValueError):
            continue
        if parsed is not None:
            restart_timestamps.append(parsed)
    state["restart_timestamps"] = restart_timestamps
    try:
        state["circuit_open_until"] = parse_time(
            str(payload.get("circuit_open_until") or "")
        )
    except (TypeError, ValueError):
        state["circuit_open_until"] = None
    state["last_event"] = payload.get("last_event")
    state["last_event_at"] = payload.get("last_event_at")
    state["last_action"] = str(payload.get("last_action") or "none")
    return state


def transition(
    payload: object,
    *,
    event: str,
    now: datetime,
    failure_threshold: int,
    max_restarts: int,
    restart_window_seconds: int,
    circuit_cooldown_seconds: int,
) -> dict[str, Any]:
    if event not in {"success", "failure"}:
        raise ValueError("event must be success or failure")
    if min(
        failure_threshold,
        max_restarts,
        restart_window_seconds,
        circuit_cooldown_seconds,
    ) <= 0:
        raise ValueError("health recovery limits must be positive")
    now = now.astimezone(timezone.utc)
    state = normalize_state(payload)
    window_start = now - timedelta(seconds=restart_window_seconds)
    restarts = sorted(
        timestamp
        for timestamp in state["restart_timestamps"]
        if window_start <= timestamp <= now
    )
    circuit_open_until = state["circuit_open_until"]
    if circuit_open_until is not None and circuit_open_until <= now:
        circuit_open_until = None

    action = "healthy"
    if event == "success":
        consecutive_failures = 0
        circuit_open_until = None
    else:
        consecutive_failures = int(state["consecutive_failures"]) + 1
        if circuit_open_until is not None:
            action = "circuit_open"
            consecutive_failures = 0
        elif consecutive_failures < failure_threshold:
            action = "wait_for_consecutive_failure"
        elif len(restarts) >= max_restarts:
            action = "circuit_opened"
            consecutive_failures = 0
            circuit_open_until = now + timedelta(
                seconds=circuit_cooldown_seconds
            )
        else:
            action = "restart"
            consecutive_failures = 0
            restarts.append(now)

    return {
        "schema": SCHEMA,
        "consecutive_failures": consecutive_failures,
        "restart_timestamps": [format_time(item) for item in restarts],
        "restart_count_in_window": len(restarts),
        "circuit_open_until": format_time(circuit_open_until),
        "last_event": event,
        "last_event_at": format_time(now),
        "last_action": action,
        "action": action,
        "limits": {
            "failure_threshold": failure_threshold,
            "max_restarts": max_restarts,
            "restart_window_seconds": restart_window_seconds,
            "circuit_cooldown_seconds": circuit_cooldown_seconds,
        },
    }


def load_state(path: Path) -> object:
    if not path.is_file():
        return empty_state()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_state()


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    )
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary, 0o640)
    os.replace(temporary, path)


def update_state(
    path: Path,
    *,
    event: str,
    now: datetime,
    failure_threshold: int,
    max_restarts: int,
    restart_window_seconds: int,
    circuit_cooldown_seconds: int,
) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    with lock_path.open("a+", encoding="utf-8") as lock:
        # The health probe runs as jiaotang while the recovery unit runs as
        # root:jiaotang. Both must be able to reuse the same serialization lock.
        os.chmod(lock_path, 0o660)
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        result = transition(
            load_state(path),
            event=event,
            now=now,
            failure_threshold=failure_threshold,
            max_restarts=max_restarts,
            restart_window_seconds=restart_window_seconds,
            circuit_cooldown_seconds=circuit_cooldown_seconds,
        )
        atomic_write(path, result)
        return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("event", choices=("success", "failure"))
    parser.add_argument("--state-file", type=Path, required=True)
    parser.add_argument("--failure-threshold", type=int, default=2)
    parser.add_argument("--max-restarts", type=int, default=3)
    parser.add_argument("--restart-window-seconds", type=int, default=1800)
    parser.add_argument("--circuit-cooldown-seconds", type=int, default=3600)
    parser.add_argument("--now", help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> None:
    arguments = parse_args()
    now = parse_time(arguments.now) if arguments.now else utc_now()
    assert now is not None
    result = update_state(
        arguments.state_file,
        event=arguments.event,
        now=now,
        failure_threshold=arguments.failure_threshold,
        max_restarts=arguments.max_restarts,
        restart_window_seconds=arguments.restart_window_seconds,
        circuit_cooldown_seconds=arguments.circuit_cooldown_seconds,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
