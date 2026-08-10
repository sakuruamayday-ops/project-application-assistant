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
PAGINATED_RETRIEVAL_TOOLS = {
    "authoritative_list_search",
    "public_list_search",
    "recognition_search",
}
UNPAGINATED_RETRIEVAL_TOOLS = {"knowledge_search"}
HOOK_RECEIPT_PATTERN = re.compile(
    r"<!-- BEGIN WORKBUDDY BEHAVIOR HOOK -->\s*(\{.*?\})\s*"
    r"<!-- END WORKBUDDY BEHAVIOR HOOK -->",
    re.DOTALL,
)
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


def json_result(event: dict[str, Any] | None) -> dict[str, Any]:
    text = result_text(event).strip()
    if not text.startswith("{"):
        return {}
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def hook_activation_receipt(event: dict[str, Any] | None) -> dict[str, Any]:
    match = HOOK_RECEIPT_PATTERN.search(result_text(event))
    if not match:
        return {}
    try:
        value = json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"无法读取Hook状态文件: {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"Hook状态文件必须是JSON对象: {path}")
    return value


def explicit_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def delivery_status(receipt: dict[str, Any] | None) -> str:
    if not receipt:
        return "unavailable"
    delivery_check_ok = explicit_bool(receipt.get("delivery_check_ok"))
    stop_event_seen = explicit_bool(receipt.get("stop_event_seen"))
    if delivery_check_ok is True and stop_event_seen is True:
        return "passed"
    if delivery_check_ok is False or stop_event_seen is False:
        return "failed"
    return "unavailable"


def aggregate_delivery_status(skill_calls: list[dict[str, Any]]) -> str:
    statuses = [str(item.get("delivery_check") or "unavailable") for item in skill_calls]
    if not statuses or all(status == "unavailable" for status in statuses):
        return "unavailable"
    if any(status == "failed" for status in statuses):
        return "failed"
    if all(status == "passed" for status in statuses):
        return "passed"
    return "partial"


def tool_basename(tool_name: str) -> str:
    return tool_name.rsplit("__", 1)[-1]


def assistant_message_text(event: dict[str, Any]) -> str:
    if event.get("type") != "message" or event.get("role") != "assistant":
        return ""
    chunks: list[str] = []
    for item in event.get("content", []):
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            chunks.append(item["text"])
    return "\n".join(chunks).strip()


def final_assistant_report(events: list[dict[str, Any]]) -> str:
    messages = [assistant_message_text(event) for event in events]
    messages = [message for message in messages if message]
    return messages[-1] if messages else ""


def ambiguous_entity_count_is_negated_example(
    report: str,
    match: re.Match[str],
) -> bool:
    """Ignore an explicitly negated example without hiding a real dual count."""
    prefix = report[max(0, match.start() - 24) : match.start()]
    suffix = report[match.end() : match.end() + 24]
    negated = re.search(
        r"(?:无|不存在|没有|未出现|未发生|并无)\s*[\"'`“‘「『]*\s*$",
        prefix,
    )
    described_as_problem = re.match(
        r"^\s*[\"'`”’」』]*\s*(?:式|这类|此类|这种|这样的)?\s*"
        r"(?:计数)?\s*(?:矛盾|冲突|问题)",
        suffix,
    )
    return bool(negated and described_as_problem)


def statement_conflicts(
    report: str,
    mcp_calls: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    detected: list[dict[str, str]] = []
    for match in re.finditer(r"(?<!\d)(\d+)\s*/\s*(\d+)\s*家", report):
        if ambiguous_entity_count_is_negated_example(report, match):
            continue
        detected.append(
            {
                "code": "AMBIGUOUS_ENTITY_COUNT",
                "evidence": match.group(0),
                "reason": "同一实体集合不能同时使用两个未解释的家数。",
            }
        )

    total_match = re.search(
        r"去重企业\s*(\d+)\s*家\s*=\s*verified\s*(\d+)\s*\+\s*"
        r"pending\s*(\d+)\s*\+\s*related\s*(\d+)\s*\+\s*noise\s*(\d+)",
        report,
        re.IGNORECASE,
    )
    if total_match:
        total, *parts = (int(value) for value in total_match.groups())
        if total != sum(parts):
            detected.append(
                {
                    "code": "CLASSIFICATION_TOTAL_MISMATCH",
                    "evidence": total_match.group(0),
                    "reason": f"分级合计为{sum(parts)}，与总计{total}不一致。",
                }
            )

    verification_claim = re.search(
        r"对\s*(\d+)\s*家[^。；\n]{0,100}(?:逐一|逐家)[^。；\n]{0,100}"
        r"(?:authoritative_list_search|权威名单)",
        report,
        re.IGNORECASE,
    )
    if verification_claim and mcp_calls is not None:
        claimed = int(verification_claim.group(1))
        actual = sum(
            tool_basename(str(item.get("tool_name") or ""))
            == "authoritative_list_search"
            for item in mcp_calls
        )
        if claimed != actual:
            detected.append(
                {
                    "code": "VERIFICATION_CALL_COUNT_MISMATCH",
                    "evidence": verification_claim.group(0),
                    "reason": f"报告声称逐一核验{claimed}家，真实名单核验调用为{actual}次。",
                }
            )

    declared_none = bool(
        re.search(
            r"statement[_\\ ]conflicts\s*(?:\*\*)?\s*(?:\||：|:|=)"
            r"\s*(?:\*\*|`)*\s*(?:无|0)",
            report,
            re.IGNORECASE,
        )
    )
    if declared_none and detected:
        detected.append(
            {
                "code": "CONFLICT_DECLARED_NONE",
                "evidence": "statement_conflicts=无",
                "reason": "报告声明无冲突，但确定性检查已发现冲突。",
            }
        )
    return {
        "status": "conflict" if detected else "none_observed",
        "declared_none": declared_none,
        "detected": detected,
    }


def retrieval_completeness(calls: list[dict[str, Any]]) -> dict[str, Any]:
    truncated_true = False
    unavailable_tools: set[str] = set()
    observed_pageable = 0
    coverage_incomplete = False
    coverage_observed = False

    for item in calls:
        if item.get("outcome") != "success":
            continue
        name = tool_basename(str(item.get("tool_name") or ""))
        payload = item.get("result_payload")
        payload = payload if isinstance(payload, dict) else {}
        if name in UNPAGINATED_RETRIEVAL_TOOLS:
            unavailable_tools.add(name)
        elif name in PAGINATED_RETRIEVAL_TOOLS:
            pagination = payload.get("pagination")
            if not isinstance(pagination, dict):
                unavailable_tools.add(name)
            else:
                observed_pageable += 1
                if pagination.get("has_more") is True or pagination.get("is_truncated") is True:
                    truncated_true = True

        coverage = payload.get("coverage")
        if isinstance(coverage, dict):
            coverage_observed = True
            if (
                coverage.get("is_complete") is False
                or coverage.get("completeness_claim_allowed") is False
                or str(coverage.get("status") or "").lower() == "incomplete"
            ):
                coverage_incomplete = True

    if truncated_true:
        truncation = {
            "status": "true",
            "reason": "至少一个已调用分页路径仍有下一页或明确返回截断。",
        }
    elif unavailable_tools:
        truncation = {
            "status": "unavailable",
            "reason": "存在不返回分页状态的已用检索路径。",
            "unobservable_tools": sorted(unavailable_tools),
        }
    elif observed_pageable:
        truncation = {
            "status": "false",
            "reason": "全部已调用分页路径均返回无下一页且未截断。",
        }
    else:
        truncation = {
            "status": "unavailable",
            "reason": "没有可观察的检索分页回执。",
        }

    coverage_status = (
        "false" if coverage_incomplete else "true" if coverage_observed else "unavailable"
    )
    return {
        "coverage_complete": {"status": coverage_status},
        "truncated": truncation,
    }


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


def generate_receipt(
    session_log: Path,
    hook_state_path: Path | None = None,
) -> dict[str, Any]:
    events = load_json_lines(session_log)
    hook_state: dict[str, Any] = {}
    delivery_receipt: dict[str, Any] = {}
    hook_state_source: dict[str, Any] | None = None
    if hook_state_path is not None:
        hook_state = load_json_object(hook_state_path)
        state_session_id = str(hook_state.get("session_id") or "")
        if state_session_id != session_log.stem:
            raise ValueError(
                "Hook状态session_id与WorkBuddy会话日志文件名不一致: "
                f"{state_session_id!r} != {session_log.stem!r}"
            )
        candidate = hook_state.get("delivery_receipt")
        delivery_receipt = candidate if isinstance(candidate, dict) else {}
        hook_state_source = {
            "path": str(hook_state_path.resolve()),
            "sha256": sha256_file(hook_state_path),
            "session_id": state_session_id,
            "turn_id": str(hook_state.get("turn_id") or ""),
        }
    calls = [event for event in events if event.get("type") == "function_call"]
    results_by_call_id = {
        str(event.get("callId")): event
        for event in events
        if event.get("type") == "function_call_result" and event.get("callId")
    }

    skill_calls: list[dict[str, Any]] = []
    mcp_calls: list[dict[str, Any]] = []
    external_calls: list[dict[str, str]] = []
    host_write_calls: list[dict[str, str]] = []
    unresolved_shell_write_risks: list[dict[str, str]] = []

    for call in calls:
        name = str(call.get("name") or "")
        call_id = str(call.get("callId") or "")
        arguments = decoded_arguments(call)
        if name == "Skill":
            activation = hook_activation_receipt(results_by_call_id.get(call_id))
            turn_id = str(activation.get("turn_id") or "")
            current_delivery = (
                delivery_receipt
                if turn_id
                and turn_id == str(hook_state.get("turn_id") or "")
                and turn_id == str(delivery_receipt.get("turn_id") or "")
                else {}
            )
            prompt_context_ok = explicit_bool(activation.get("prompt_context_ok"))
            prompt_hook_observable = explicit_bool(
                activation.get("prompt_hook_observable")
            )
            if prompt_hook_observable is None and prompt_context_ok is False:
                prompt_hook_observable = False
            skill_calls.append(
                {
                    "call_id": call_id,
                    "skill": str(arguments.get("skill") or ""),
                    "activation_ok": explicit_bool(activation.get("activation_ok")),
                    "hook_runtime_ok": explicit_bool(activation.get("hook_runtime_ok")),
                    "state_persisted": explicit_bool(activation.get("state_persisted")),
                    "turn_id": turn_id or None,
                    "state_origin": activation.get("state_origin"),
                    "prompt_context_ok": prompt_context_ok,
                    "prompt_hook_observable": prompt_hook_observable,
                    "prompt_context_source": activation.get("prompt_context_source"),
                    "delivery_check": delivery_status(current_delivery),
                    "stop_event_seen": explicit_bool(
                        current_delivery.get("stop_event_seen")
                    ),
                    "degraded_reason": (
                        None
                        if prompt_context_ok is True
                        else activation.get("error_code") or "PROMPT_CONTEXT_UNAVAILABLE"
                    ),
                }
            )

        tool_name = ""
        if name == MCP_PROXY_NAME:
            tool_name = str(arguments.get("toolName") or "")
        elif name.startswith("mcp__"):
            tool_name = name
        if tool_name:
            result_event = results_by_call_id.get(call_id)
            mcp_calls.append(
                {
                    "call_id": call_id,
                    "tool_name": tool_name,
                    "outcome": mcp_outcome(result_event),
                    "result_payload": json_result(result_event),
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
    completeness = retrieval_completeness(mcp_calls)
    report = final_assistant_report(events)
    return {
        "schema_version": 3,
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "source": {
            "session_log": str(session_log.resolve()),
            "session_log_sha256": sha256_file(session_log),
            "event_count": len(events),
            "hook_state": hook_state_source,
        },
        "host_activated_skills": {
            "observable_skill_call_count": len(skill_calls),
            "calls": skill_calls,
            "implicit_activation_verifiable": bool(skill_calls),
            "all_activations_ok": bool(skill_calls)
            and all(item.get("activation_ok") is True for item in skill_calls),
            "prompt_context_ok": bool(skill_calls)
            and all(item.get("prompt_context_ok") is True for item in skill_calls),
            "prompt_hook_observable": (
                True
                if skill_calls
                and all(item.get("prompt_hook_observable") is True for item in skill_calls)
                else False
                if any(item.get("prompt_hook_observable") is False for item in skill_calls)
                else None
            ),
            "delivery_check": aggregate_delivery_status(skill_calls),
            "note": (
                "Skill activation, prompt context, native prompt-hook observability, "
                "and Stop delivery are separate facts. SessionStart transcript recovery "
                "may provide valid prompt context while prompt_hook_observable remains false."
            ),
        },
        "mcp_tool_calls": {
            "total_attempts": len(mcp_calls),
            "distinct_tools": len(tool_counts),
            "by_tool": dict(sorted(tool_counts.items())),
            "by_outcome": dict(sorted(outcome_counts.items())),
            "calls": mcp_calls,
            **completeness,
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
        # Keep the canonical machine-readable completeness fields at the
        # receipt root as well as beside the MCP call ledger.  Consumers should
        # not need to know the nested implementation detail to enforce gates.
        "coverage_complete": completeness["coverage_complete"],
        "truncated": completeness["truncated"],
        "statement_conflicts": statement_conflicts(report, mcp_calls),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-log", type=Path, required=True)
    parser.add_argument("--hook-state", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    hook_state = (
        options.hook_state.expanduser().resolve()
        if options.hook_state is not None
        else None
    )
    receipt = generate_receipt(
        options.session_log.expanduser().resolve(),
        hook_state,
    )
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
