#!/usr/bin/env python3
"""Generate deterministic host telemetry from a WorkBuddy session JSONL log."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MCP_PROXY_NAME = "DeferExecuteTool"
EXTERNAL_NETWORK_TOOLS = {"WebFetch", "WebSearch"}
SHELL_WRITE_PATTERN = re.compile(
    r"(?:^|[;&|]\s*)(?:cp|mv|mkdir|touch|tee|install|rsync)\b|"
    r"(?:^|[^>])>{1,2}\s*(?!/dev/null(?:\s|$))|"
    r"\b(?:write_text|write_bytes|open\s*\([^)]*[, ]\s*['\"](?:w|a|x))",
    re.IGNORECASE,
)


def shell_may_write(command: str) -> bool:
    without_null_redirects = re.sub(
        r"(?:\d*)>{1,2}\s*/dev/null(?:\s*2>&1)?",
        "",
        command,
    )
    return bool(SHELL_WRITE_PATTERN.search(without_null_redirects))


def load_json_lines(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"第{line_number}行不是有效JSON") from error
            if not isinstance(payload, dict):
                raise ValueError(f"第{line_number}行必须是JSON对象")
            events.append(payload)
    return events


def decoded_arguments(event: dict[str, Any]) -> dict[str, Any]:
    value = event.get("arguments") or {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def result_text(event: dict[str, Any] | None) -> str:
    if not event:
        return ""
    output = event.get("output")
    if isinstance(output, dict):
        value = output.get("text") or output.get("content") or output
    else:
        value = output
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def mcp_outcome(result: dict[str, Any] | None) -> str:
    text = result_text(result).lower()
    if "timed out" in text or "timeout" in text:
        return "timeout"
    if (
        "output has been saved to" in text
        or "full output saved to" in text
        or "<persisted-output>" in text
    ):
        return "usable_with_host_cache"
    if not result:
        return "missing_result_event"
    if result.get("status") not in {None, "completed"}:
        return "other_failure"
    if text.lstrip().startswith("error") or "error executing tool" in text:
        return "other_failure"
    return "success"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def generate_receipt(session_log: Path) -> dict[str, Any]:
    events = load_json_lines(session_log)
    calls = [event for event in events if event.get("type") == "function_call"]
    results_by_call_id = {
        str(event.get("callId")): event
        for event in events
        if event.get("type") == "function_call_result" and event.get("callId")
    }

    skill_calls: list[dict[str, str]] = []
    mcp_calls: list[dict[str, str]] = []
    external_calls: list[dict[str, str]] = []
    host_write_calls: list[dict[str, str]] = []
    unresolved_shell_write_risks: list[dict[str, str]] = []

    for call in calls:
        name = str(call.get("name") or "")
        call_id = str(call.get("callId") or "")
        arguments = decoded_arguments(call)
        if name == "Skill":
            skill_calls.append(
                {"call_id": call_id, "skill": str(arguments.get("skill") or "")}
            )

        tool_name = ""
        if name == MCP_PROXY_NAME:
            tool_name = str(arguments.get("toolName") or "")
        elif name.startswith("mcp__"):
            tool_name = name
        if tool_name:
            mcp_calls.append(
                {
                    "call_id": call_id,
                    "tool_name": tool_name,
                    "outcome": mcp_outcome(results_by_call_id.get(call_id)),
                }
            )

        if name in EXTERNAL_NETWORK_TOOLS:
            external_calls.append({"call_id": call_id, "tool_name": name})

        if name in {"Write", "Edit", "MultiEdit"}:
            path = str(arguments.get("file_path") or arguments.get("path") or "")
            host_write_calls.append(
                {"call_id": call_id, "tool_name": name, "path": path}
            )
        if name == "Bash":
            command = str(arguments.get("command") or "")
            if shell_may_write(command):
                unresolved_shell_write_risks.append(
                    {
                        "call_id": call_id,
                        "tool_name": name,
                        "reason": "shell-command-may-write",
                    }
                )

    tool_results_dir = session_log.with_suffix("") / "tool-results"
    # WorkBuddy stores tool-results beside the session log under a directory
    # named after the session id. Prefer the path encoded by the log layout.
    expected_session_dir = session_log.parent / session_log.stem / "tool-results"
    if expected_session_dir.is_dir():
        tool_results_dir = expected_session_dir
    cache_files = sorted(
        str(path.resolve())
        for path in tool_results_dir.glob("*")
        if path.is_file()
    ) if tool_results_dir.is_dir() else []

    tool_counts = Counter(item["tool_name"] for item in mcp_calls)
    outcome_counts = Counter(item["outcome"] for item in mcp_calls)
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "source": {
            "session_log": str(session_log.resolve()),
            "session_log_sha256": sha256_file(session_log),
            "event_count": len(events),
        },
        "host_activated_skills": {
            "observable_skill_call_count": len(skill_calls),
            "calls": skill_calls,
            "implicit_activation_verifiable": bool(skill_calls),
            "note": (
                "Only actual Skill events are observable; behavior alone does not prove activation."
            ),
        },
        "mcp_tool_calls": {
            "total_attempts": len(mcp_calls),
            "distinct_tools": len(tool_counts),
            "by_tool": dict(sorted(tool_counts.items())),
            "by_outcome": dict(sorted(outcome_counts.items())),
            "calls": mcp_calls,
        },
        "external_network_calls": {
            "total": len(external_calls),
            "calls": external_calls,
        },
        "file_write_events": {
            "explicit_host_write_calls": host_write_calls,
            "automatic_tool_result_cache_count": len(cache_files),
            "automatic_tool_result_cache_files": cache_files,
            "unresolved_shell_write_risks": unresolved_shell_write_risks,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-log", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    receipt = generate_receipt(options.session_log.expanduser().resolve())
    output = options.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
