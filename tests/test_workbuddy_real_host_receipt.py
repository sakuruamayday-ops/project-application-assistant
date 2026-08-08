from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "generate_workbuddy_real_host_receipt.py"
SPEC = importlib.util.spec_from_file_location("workbuddy_receipt", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def write_jsonl(path: Path, events: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events),
        encoding="utf-8",
    )


def test_receipt_counts_failed_mcp_attempts_and_all_host_caches(tmp_path: Path):
    session_id = "session-1"
    log = tmp_path / f"{session_id}.jsonl"
    cache_dir = tmp_path / session_id / "tool-results"
    cache_dir.mkdir(parents=True)
    (cache_dir / "large-result.txt").write_text("cached", encoding="utf-8")
    events = [
        {
            "type": "function_call",
            "name": "Skill",
            "callId": "skill-1",
            "arguments": json.dumps({"skill": "local-knowledge-retrieval"}),
        },
        {
            "type": "function_call",
            "name": "DeferExecuteTool",
            "callId": "mcp-1",
            "arguments": json.dumps(
                {"toolName": "mcp__jiaotang-kb__knowledge_search", "params": {}}
            ),
        },
        {
            "type": "function_call_result",
            "name": "Skill",
            "callId": "skill-1",
            "status": "completed",
            "output": {
                "type": "text",
                "text": (
                    "<!-- BEGIN WORKBUDDY BEHAVIOR HOOK -->\n"
                    '{"activation_ok":true,"state_persisted":true,'
                    '"state_origin":"activation_fallback","prompt_context_ok":false,'
                    '"error_code":"PROMPT_CONTEXT_UNAVAILABLE"}\n'
                    "<!-- END WORKBUDDY BEHAVIOR HOOK -->"
                ),
            },
        },
        {
            "type": "function_call_result",
            "name": "DeferExecuteTool",
            "callId": "mcp-1",
            "status": "completed",
            "output": {"type": "text", "text": "{\"results\": []}"},
        },
        {
            "type": "function_call",
            "name": "DeferExecuteTool",
            "callId": "mcp-2",
            "arguments": json.dumps(
                {"toolName": "mcp__jiaotang-kb__knowledge_search", "params": {}}
            ),
        },
        {
            "type": "function_call_result",
            "name": "DeferExecuteTool",
            "callId": "mcp-2",
            "status": "completed",
            "output": {"type": "text", "text": "Error: MCP request timed out"},
        },
        {
            "type": "function_call",
            "name": "DeferExecuteTool",
            "callId": "mcp-3",
            "arguments": json.dumps(
                {"toolName": "mcp__jiaotang-kb__knowledge_document", "params": {}}
            ),
        },
        {
            "type": "function_call_result",
            "name": "DeferExecuteTool",
            "callId": "mcp-3",
            "status": "completed",
            "output": {
                "type": "text",
                "text": "Error: result too large. Output has been saved to cache.txt",
            },
        },
        {
            "type": "function_call",
            "name": "Write",
            "callId": "write-1",
            "arguments": json.dumps({"file_path": "/tmp/memory.md"}),
        },
    ]
    write_jsonl(log, events)

    receipt = MODULE.generate_receipt(log)

    assert receipt["host_activated_skills"]["observable_skill_call_count"] == 1
    assert receipt["host_activated_skills"]["all_activations_ok"] is True
    assert receipt["host_activated_skills"]["prompt_hook_observable"] is False
    assert receipt["host_activated_skills"]["delivery_check"] == "unavailable"
    assert receipt["mcp_tool_calls"]["total_attempts"] == 3
    assert receipt["mcp_tool_calls"]["by_tool"] == {
        "mcp__jiaotang-kb__knowledge_document": 1,
        "mcp__jiaotang-kb__knowledge_search": 2,
    }
    assert receipt["mcp_tool_calls"]["by_outcome"] == {
        "success": 1,
        "timeout": 1,
        "usable_with_host_cache": 1,
    }
    assert receipt["file_write_events"]["automatic_tool_result_cache_count"] == 1
    assert len(receipt["file_write_events"]["explicit_host_write_calls"]) == 1


def test_receipt_reports_unavailable_truncation_and_detects_statement_conflict(tmp_path: Path):
    log = tmp_path / "session-report.jsonl"
    write_jsonl(
        log,
        [
            {
                "type": "function_call",
                "name": "DeferExecuteTool",
                "callId": "search-1",
                "arguments": json.dumps(
                    {"toolName": "mcp__jiaotang-kb__knowledge_search", "params": {}}
                ),
            },
            {
                "type": "function_call_result",
                "name": "DeferExecuteTool",
                "callId": "search-1",
                "status": "completed",
                "output": {"type": "text", "text": '{"results":[]}'},
            },
            {
                "type": "function_call",
                "name": "DeferExecuteTool",
                "callId": "recognition-1",
                "arguments": json.dumps(
                    {"toolName": "mcp__jiaotang-kb__recognition_search", "params": {}}
                ),
            },
            {
                "type": "function_call_result",
                "name": "DeferExecuteTool",
                "callId": "recognition-1",
                "status": "completed",
                "output": {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "pagination": {"is_truncated": False},
                            "coverage": {"is_complete": False},
                        }
                    ),
                },
            },
            {
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": (
                            "对 8 家候选逐一执行 authoritative_list_search。"
                            "statement_conflicts | 无。pending 中仅 6/5 家逐一核验。"
                        ),
                    }
                ],
            },
        ],
    )

    receipt = MODULE.generate_receipt(log)

    assert receipt["mcp_tool_calls"]["coverage_complete"]["status"] == "false"
    assert receipt["mcp_tool_calls"]["truncated"]["status"] == "unavailable"
    assert receipt["statement_conflicts"]["status"] == "conflict"
    assert {
        item["code"] for item in receipt["statement_conflicts"]["detected"]
    } == {
        "AMBIGUOUS_ENTITY_COUNT",
        "VERIFICATION_CALL_COUNT_MISMATCH",
        "CONFLICT_DECLARED_NONE",
    }


def test_receipt_does_not_infer_implicit_skill_activation(tmp_path: Path):
    log = tmp_path / "session-2.jsonl"
    write_jsonl(
        log,
        [
            {
                "type": "function_call",
                "name": "DeferExecuteTool",
                "callId": "mcp-1",
                "arguments": json.dumps(
                    {"toolName": "mcp__jiaotang-kb__recognition_search", "params": {}}
                ),
            }
        ],
    )

    receipt = MODULE.generate_receipt(log)

    assert receipt["host_activated_skills"]["observable_skill_call_count"] == 0
    assert receipt["host_activated_skills"]["implicit_activation_verifiable"] is False


def test_negated_ambiguous_entity_count_example_is_not_a_conflict():
    report = (
        "verified 0 + related 0 + pending 15 + noise 0 = 15 家，"
        "无‘6/5 家’式矛盾。**statement_conflicts=`无`**。"
    )

    result = MODULE.statement_conflicts(report, [])

    assert result == {
        "status": "none_observed",
        "declared_none": True,
        "detected": [],
    }


def test_shell_null_redirection_is_not_reported_as_a_write_risk():
    assert MODULE.shell_may_write("ls /tmp 2>/dev/null || echo missing") is False
    assert MODULE.shell_may_write("printf result > /tmp/result.txt") is True
