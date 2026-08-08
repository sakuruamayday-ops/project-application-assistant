from __future__ import annotations

import io
import sys
import time

from scripts.stream_to_command import stream


def test_stream_to_command_delivers_complete_input() -> None:
    payload = b"jiaotang" * 200_000
    code = (
        "import sys; data=sys.stdin.buffer.read(); "
        f"raise SystemExit(0 if len(data)=={len(payload)} else 7)"
    )

    result = stream(
        io.BytesIO(payload),
        [sys.executable, "-c", code],
        label="fixture",
        stall_timeout_seconds=2,
        completion_timeout_seconds=2,
        report_interval_seconds=10,
    )

    assert result == 0


def test_stream_to_command_stops_a_stalled_consumer() -> None:
    started = time.monotonic()

    result = stream(
        io.BytesIO(b"x" * 4_000_000),
        [sys.executable, "-c", "import time; time.sleep(5)"],
        label="fixture",
        stall_timeout_seconds=0.2,
        completion_timeout_seconds=1,
        report_interval_seconds=10,
    )

    assert result == 124
    assert time.monotonic() - started < 3
