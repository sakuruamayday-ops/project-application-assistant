from __future__ import annotations

import io
import sys
import time

from scripts.stream_to_command import stream, write_all


class PartialWriter:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.payload = bytearray()

    def write(self, data: bytes | memoryview) -> int:
        accepted = bytes(data[: self.limit])
        self.payload.extend(accepted)
        return len(accepted)


def test_write_all_preserves_bytes_across_partial_writes() -> None:
    destination = PartialWriter(limit=7)
    payload = b"gongchuang-release-stream" * 100

    written = write_all(destination, payload)

    assert written == len(payload)
    assert bytes(destination.payload) == payload


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


def test_stream_to_command_handles_consumer_backpressure() -> None:
    payload = b"jiaotang" * 500_000
    code = (
        "import sys,time; total=0; "
        "\nwhile data := sys.stdin.buffer.read(16384): "
        "total += len(data); time.sleep(0.001)\n"
        f"raise SystemExit(0 if total=={len(payload)} else 7)"
    )

    result = stream(
        io.BytesIO(payload),
        [sys.executable, "-c", code],
        label="backpressure-fixture",
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
