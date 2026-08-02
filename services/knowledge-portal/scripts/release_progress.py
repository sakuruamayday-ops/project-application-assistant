from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone


PROGRESS_PREFIX = "[release-progress] "


def utc_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def progress_interval_seconds() -> float:
    raw = os.environ.get("JIAOTANG_RELEASE_PROGRESS_INTERVAL_SECONDS", "5")
    try:
        return max(float(raw), 0.2)
    except ValueError:
        return 5.0


def emit_progress(
    stage: str,
    status: str,
    *,
    item: str | None = None,
    bytes_processed: int | None = None,
    total_bytes: int | None = None,
    elapsed_seconds: float | None = None,
) -> None:
    payload: dict[str, object] = {
        "at": utc_timestamp(),
        "stage": stage,
        "status": status,
    }
    if item:
        payload["item"] = item
    if bytes_processed is not None:
        payload["bytes_processed"] = max(int(bytes_processed), 0)
    if total_bytes is not None:
        payload["total_bytes"] = max(int(total_bytes), 0)
        if total_bytes > 0 and bytes_processed is not None:
            payload["percent"] = round(
                min(max(bytes_processed / total_bytes * 100, 0), 100),
                1,
            )
    if elapsed_seconds is not None:
        payload["elapsed_seconds"] = round(max(elapsed_seconds, 0), 3)
    print(
        PROGRESS_PREFIX
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        file=sys.stderr,
        flush=True,
    )


class TransferProgress:
    def __init__(self, stage: str, item: str, total_bytes: int) -> None:
        self.stage = stage
        self.item = item
        self.total_bytes = max(int(total_bytes), 0)
        self.started = time.monotonic()
        self.last_emitted = 0.0
        self.last_bytes = 0
        self.last_status = ""
        self.interval = progress_interval_seconds()
        self._emit("started", 0)

    def _emit(self, status: str, consumed: int) -> None:
        now = time.monotonic()
        self.last_emitted = now
        self.last_bytes = max(int(consumed), 0)
        self.last_status = status
        emit_progress(
            self.stage,
            status,
            item=self.item,
            bytes_processed=self.last_bytes,
            total_bytes=self.total_bytes,
            elapsed_seconds=now - self.started,
        )

    def update(self, consumed: int, total: int | None = None) -> None:
        if total is not None and int(total) >= 0:
            self.total_bytes = int(total)
        now = time.monotonic()
        complete = self.total_bytes > 0 and consumed >= self.total_bytes
        if complete or now - self.last_emitted >= self.interval:
            self._emit("completed" if complete else "running", consumed)

    def finish(self, *, status: str = "completed") -> None:
        final_bytes = self.total_bytes if status == "completed" else self.last_bytes
        if self.last_status != status or self.last_bytes != final_bytes:
            self._emit(status, final_bytes)

    def __call__(self, consumed: int, total: int) -> None:
        self.update(consumed, total)
