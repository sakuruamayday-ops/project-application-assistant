"""Internal-test diagnostics: resumable files, daily review, and scoped expiry."""
from __future__ import annotations

import base64
import json
import os
import re
import sqlite3
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field
from uuid import UUID

SHANGHAI = ZoneInfo("Asia/Shanghai")
CHUNK_BYTES = 1024 * 1024


class DiagnosticChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file_id: UUID
    name: str = Field(min_length=1, max_length=255)
    size: int = Field(ge=0, le=256 * 1024 * 1024)
    offset: int = Field(ge=0)
    data: str = Field(max_length=1_398_104)


def initialize(connection: sqlite3.Connection) -> None:
    connection.executescript("""
    CREATE TABLE IF NOT EXISTS client_diagnostic_files (
        report_id INTEGER NOT NULL REFERENCES client_error_reports(feedback_id),
        file_id TEXT NOT NULL, name TEXT NOT NULL, size INTEGER NOT NULL,
        received INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(report_id,file_id)
    );
    CREATE TABLE IF NOT EXISTS client_diagnostic_reviews (
        report_id INTEGER PRIMARY KEY REFERENCES client_error_reports(feedback_id),
        reviewed_at TEXT NOT NULL, day TEXT NOT NULL, review_json TEXT NOT NULL,
        purged_at TEXT
    );
    CREATE TABLE IF NOT EXISTS client_diagnostic_days (
        day TEXT PRIMARY KEY, created_at TEXT NOT NULL, document TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS client_diagnostic_job_runs (
        id INTEGER PRIMARY KEY, kind TEXT NOT NULL, finished_at TEXT NOT NULL,
        result_json TEXT NOT NULL
    );
    """)


def file_path(root: Path, report_id: int, file_id: str) -> Path:
    return root / str(int(report_id)) / str(UUID(file_id))


def receive_chunk(connection: sqlite3.Connection, root: Path, report_id: int,
                  chunk: DiagnosticChunk) -> dict:
    """One writer transaction owns the persisted byte offset; retransmits are harmless."""
    try:
        data = base64.b64decode(chunk.data, validate=True)
    except ValueError as error:
        raise ValueError("Invalid attachment encoding") from error
    if len(data) > CHUNK_BYTES or chunk.offset + len(data) > chunk.size:
        raise ValueError("Invalid attachment chunk size")
    if not data and chunk.size:
        raise ValueError("Empty attachment chunk")
    if "/" in chunk.name or "\\" in chunk.name or any(ord(c) < 32 for c in chunk.name):
        raise ValueError("Invalid attachment display name")
    connection.execute("BEGIN IMMEDIATE")
    try:
        if connection.execute("SELECT 1 FROM client_diagnostic_reviews WHERE report_id=? AND purged_at IS NOT NULL", (report_id,)).fetchone():
            raise ValueError("Diagnostic has expired")
        row = connection.execute("SELECT name,size,received FROM client_diagnostic_files WHERE report_id=? AND file_id=?", (report_id, str(chunk.file_id))).fetchone()
        if row is None:
            count, total = connection.execute("SELECT COUNT(*),COALESCE(SUM(size),0) FROM client_diagnostic_files WHERE report_id=?", (report_id,)).fetchone()
            if count >= 32 or total + chunk.size > 512 * 1024 * 1024:
                raise ValueError("Diagnostic attachment capacity exceeded")
            reserved = connection.execute("SELECT COALESCE(SUM(size),0) FROM client_diagnostic_files").fetchone()[0]
            root.mkdir(mode=0o700, parents=True, exist_ok=True)
            if reserved + chunk.size > 10 * 1024**3 or shutil.disk_usage(root).free < chunk.size + 2 * 1024**3:
                raise ValueError("Diagnostic storage capacity reached; original client files are retained")
            connection.execute("INSERT INTO client_diagnostic_files(report_id,file_id,name,size) VALUES (?,?,?,?)", (report_id, str(chunk.file_id), chunk.name, chunk.size))
            received = 0
        else:
            if row[0] != chunk.name or row[1] != chunk.size:
                raise ValueError("Attachment identity changed")
            received = row[2]
        if chunk.offset != received:
            connection.commit()
            return {"next_offset": received, "complete": received == chunk.size}
        path = file_path(root, report_id, str(chunk.file_id))
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.is_symlink():
            raise ValueError("Invalid attachment storage")
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "r+b") as stream:
            if os.fstat(stream.fileno()).st_size < received:
                raise ValueError("Attachment storage is incomplete")
            stream.seek(received)
            stream.write(data)
            stream.truncate(received + len(data))
            stream.flush()
            os.fsync(stream.fileno())
        received += len(data)
        connection.execute("UPDATE client_diagnostic_files SET received=? WHERE report_id=? AND file_id=?", (received, report_id, str(chunk.file_id)))
        connection.commit()
        return {"next_offset": received, "complete": received == chunk.size}
    except Exception:
        connection.rollback()
        raise


def _errors(value: object) -> list[str]:
    found: list[str] = []
    def walk(item: object) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                if key in {"error", "message", "code", "text", "reason"} and isinstance(child, str) and child:
                    found.append(child[:1500])
                elif isinstance(child, (dict, list)):
                    walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)
    if isinstance(value, dict) and isinstance(value.get('events'), list):
        if value.get('failure_stage') == 'report-preparation':
            found.append('错误上报准备失败：report-preparation')
            walk(value.get('error'))
        if value.get('module') == 'enterprise-trash' and value.get('failure_stage') in {'workspace-deletion', 'conversation-deletion'}:
            found.append('企业空间或对话删除未完成：' + value['failure_stage'])
            walk(value.get('error'))
        for event in value['events']:
            if not isinstance(event, dict) or not isinstance(event.get('data'), dict):
                continue
            data = event['data']
            failed_turn = value.get('failed_turn')
            if isinstance(failed_turn, int) and data.get('turn') != failed_turn:
                continue
            message = data.get('message', {})
            reason = data.get('reason', {})
            if data.get('isError') is True or (isinstance(message, dict) and message.get('isError') is True):
                walk(data)
            elif event.get('type') == 'turn/end' and isinstance(reason, dict) and reason.get('kind') in {'error', 'blocked', 'interrupted', 'max-tokens'}:
                walk(reason)
                if not found:
                    found.append(reason['kind'])
    else:
        walk(value)
    return list(dict.fromkeys(found))[:20]


def _failure_analysis(context: object) -> dict | None:
    """Keep bounded client observations, never accept a client claim of a confirmed root cause."""
    value = context.get("failure_analysis") if isinstance(context, dict) else None
    if not isinstance(value, dict) or not isinstance(value.get("failures"), list):
        return None
    failed_turn = context.get("failed_turn")
    if isinstance(failed_turn, int) and value.get("turn") != failed_turn:
        return None

    def incident(item: object) -> dict | None:
        if not isinstance(item, dict) or not isinstance(item.get("event_seq"), int):
            return None
        if not isinstance(item.get("category"), str) or item["category"] not in {"runtime", "precondition", "waiting-user", "business-rejection", "outcome-unknown", "protection"}:
            return None
        if not isinstance(item.get("status"), str) or item["status"] not in {"unrecovered", "recovered", "expected-block", "outcome-unknown"}:
            return None
        result = {key: item[key][:2000] for key in ("tool", "operation", "stage", "code", "observed_reason") if isinstance(item.get(key), str)}
        result.update(event_seq=item["event_seq"], category=item["category"], status=item["status"], cause_status="observed-failure-only")
        condition_status = "recovered" if result["status"] == "recovered" else "expected-block"
        if result.get("code") == "GC-ACCOUNT-UPGRADE":
            result.update(stage="client-upgrade", category="precondition", status=condition_status)
        elif result.get("code") in {"MISSING_CREDENTIAL", "INVALID_CREDENTIAL"}:
            result.update(stage="model-credentials", category="precondition", status=condition_status)
        elif result.get("code") in {"QUOTA", "ACCOUNT_QUOTA"}:
            balance = re.search(r"insufficient\s+(?:balance|credits?)|余额不足|欠费|\bHTTP\s*402\b", result.get("observed_reason", ""), re.I)
            result.update(stage="model-balance" if balance else "model-quota", category="precondition", status=condition_status)
        for key in ("recovery_event_seq", "blocked_by_event_seq"):
            if isinstance(item.get(key), int):
                result[key] = item[key]
        page_recovery = item.get("page_recovery")
        if isinstance(page_recovery, dict):
            requested = page_recovery.get("requested_pages")
            covered = page_recovery.get("covered_pages")
            requested_valid = requested == "all" or isinstance(requested, list) and 0 < len(requested) <= 200 and all(type(page) is int and page > 0 for page in requested)
            covered_valid = isinstance(covered, list) and len(covered) <= 200 and all(type(page) is int and page > 0 for page in covered)
            if requested_valid and covered_valid and (requested == "all" or set(covered).issubset(requested)):
                result["page_recovery"] = dict(requested_pages=requested if requested == "all" else sorted(set(requested)), covered_pages=sorted(set(covered)))
        execution = item.get("execution")
        if isinstance(execution, dict):
            result["execution"] = {key: execution[key] for key in ("timedOut", "cancelled") if isinstance(execution.get(key), bool)}
            result["execution"].update({key: execution[key] for key in ("elapsedMs", "exitCode") if isinstance(execution.get(key), (int, float))})
            if isinstance(execution.get("timeoutStage"), str):
                result["execution"]["timeoutStage"] = execution["timeoutStage"][:60]
            stdout = execution.get("stdout")
            if isinstance(stdout, dict):
                result["execution"]["stdout"] = {key: stdout[key] for key in ("bytes", "json", "lossy")
                                                   if isinstance(stdout.get(key), (int, bool)) or key == "json" and isinstance(stdout.get(key), str) and stdout[key] in {"not-started", "empty", "invalid", "valid", "unknown"}}
            stderr = execution.get("stderr")
            if isinstance(stderr, dict):
                errors = stderr.get("errors")
                result["execution"]["stderr"] = {"bytes": stderr.get("bytes") if isinstance(stderr.get("bytes"), int) else None,
                    "errors": [item for item in errors[:9] if isinstance(item, str) and item in {"ModuleNotFoundError", "ImportError", "PermissionError", "FileNotFoundError", "UnicodeDecodeError", "UnicodeEncodeError", "MemoryError", "DLL load failed", "Access is denied"}] if isinstance(errors, list) else []}
        return result

    failures = [parsed for item in value["failures"][:34] if (parsed := incident(item)) is not None]
    if not failures and value.get("turn_result", "unknown") == "unknown" and not isinstance(value.get("outcome"), dict):
        return None
    primary = incident(value.get("primary_failure"))
    first = incident(value.get("first_failure"))
    # A primary observation must also belong to the supplied failure sequence.
    if primary not in failures:
        primary = None
    if first not in failures:
        first = None
    model_request = value.get("model_request")
    if not isinstance(model_request, dict) or not isinstance(model_request.get("event_seq"), int) or not all(isinstance(model_request.get(key), str) for key in ("provider", "model")):
        model_request = None
        for index, event in enumerate(context.get("events", []) if isinstance(context.get("events"), list) else []):
            if not isinstance(event, dict) or event.get("type") != "request/header" or not isinstance(event.get("data"), dict):
                continue
            data = event["data"]
            if data.get("turn") != value.get("turn"):
                continue
            header = data.get("header", {})
            config = header.get("config", {}) if isinstance(header, dict) else {}
            if isinstance(config, dict) and all(isinstance(config.get(key), str) for key in ("provider", "model")):
                model_request = dict(event_seq=event.get("seq") if isinstance(event.get("seq"), int) else index,
                                     provider=config["provider"], model=config["model"])
    if model_request:
        model_request = dict(event_seq=model_request["event_seq"], provider=model_request["provider"][:100], model=model_request["model"][:240])
    return {"turn": value.get("turn") if isinstance(value.get("turn"), int) else None,
            "turn_result": str(value.get("turn_result", "unknown"))[:60],
            "delivery_result": str(value.get("delivery_result", "unknown"))[:60],
            "first_failure": first, "primary_failure": primary, "failures": failures,
            "model_request": model_request,
            "omitted_failure_count": value.get("omitted_failure_count", 0) if isinstance(value.get("omitted_failure_count", 0), int) else 0}


def _turn_outcome(context: object, analysis: dict | None) -> dict:
    """Inspect final visible replies and Host file receipts; attachments and model claims are not receipts."""
    context = context if isinstance(context, dict) else {}
    operation = context.get('user_operation')
    if (context.get('module') == 'enterprise-trash' and isinstance(operation, dict)
            and operation.get('operation') in {'workspace', 'conversation'} and operation.get('result') == 'failed'
            and context.get('failure_stage') == operation['operation'] + '-deletion'):
        target = '删除企业空间' if operation['operation'] == 'workspace' else '删除历史对话'
        return dict(status='not-delivered', verification_scope='host-operation-only', requested_formats=[],
                    file_requested=False, user_request=dict(event_seq=0, text=target, truncated=False),
                    goal_request=None, structured_reply='not-requested', last_reply=None, files=[], unpublished_files=[])
    turn = context.get("failed_turn", (analysis or {}).get("turn"))
    supplied = context.get("failure_analysis", {})
    supplied = supplied.get("outcome") if isinstance(supplied, dict) and supplied.get("turn") == turn else None
    supplied = supplied if isinstance(supplied, dict) else {}
    files: dict[str, dict] = {}
    targets: dict[str, dict] = {}
    request = None
    goal_request = None
    reply = None
    reply_text = ""
    calls = {}
    turn_result = (analysis or {}).get("turn_result", "unknown")
    delivery_result = (analysis or {}).get("delivery_result", "unknown")
    terminal_account_block = False

    def body(content):
        return "\n".join(item["text"] for item in content if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str)) if isinstance(content, list) else ""

    def excerpt(text, seq, **extra):
        return dict(event_seq=seq, text=text[:3000], truncated=len(text) > 3000, **extra)

    def publish(path, phase, seq, source):
        if not isinstance(path, str) or not path.strip() or "[已隐藏路径]" in path or "[REDACTED]" in path:
            return
        key = path.replace("\\", "/")
        name = key.rsplit("/", 1)[-1][:240]
        files[key] = dict(name=name, format=Path(name).suffix[1:].lower(), phase=phase, event_seq=seq, source=source)

    def absolute_receipt_path(path):
        return isinstance(path, str) and bool(re.match(r"^(?:/|[a-z]:[\\/]|\\\\)", path, re.I))

    events = context.get("events", [])
    for index, event in enumerate(events if isinstance(events, list) else []):
        if not isinstance(event, dict) or not isinstance(event.get("data"), dict):
            continue
        data = event["data"]
        kind = event.get("type")
        seq = event.get("seq") if isinstance(event.get("seq"), int) else index
        source = data.get("source", {})
        source = source if isinstance(source, dict) else {}
        if kind == "user/message" and source.get("kind") == "user":
            text = source["displayText"] if isinstance(source.get("displayText"), str) else body(data.get("content"))
            if text:
                request = excerpt(text, seq)
                if not re.fullmatch(r"\s*(?:继续|重试|再试一次|continue|retry)\s*[。.!！]?\s*", text, re.I):
                    goal_request = request
        delivery = source.get("delivery", {}) if source.get("kind") == "plugin:gongchuang-policy-gate" else {}
        delivery = delivery if isinstance(delivery, dict) else {}
        if isinstance(turn, int) and data.get("turn", delivery.get("turn")) != turn:
            continue
        if kind == "assistant/message":
            message = data.get("message", {})
            content = message.get("content", []) if isinstance(message, dict) else []
            text = body(content)
            if text:
                reply_text = text
                reply = excerpt(text, seq, final=not any(isinstance(item, dict) and item.get("type") == "tool-call" for item in content))
        if kind == "turn/end":
            reason = data.get("reason", {})
            if isinstance(reason, dict):
                turn_result = str(reason.get("kind", "unknown"))
                error = reason.get("error", {})
                terminal_account_block = isinstance(error, dict) and isinstance(error.get("code"), str) and error["code"] in {"GC-ACCOUNT-UPGRADE", "MISSING_CREDENTIAL", "INVALID_CREDENTIAL", "QUOTA", "ACCOUNT_QUOTA"}
            break
        if kind == "user/message" and delivery:
            delivery_result = str(delivery.get("phase", delivery_result))
            for file in delivery.get("files", []) if isinstance(delivery.get("files"), list) else []:
                if isinstance(file, dict):
                    publish(file.get("path"), str(file.get("phase", delivery_result)), seq, "professional-notice")
        if kind == "deliverables/presented":
            for file in data.get("files", []) if isinstance(data.get("files"), list) else []:
                if isinstance(file, dict):
                    publish(file.get("path"), "published", seq, kind)
        if kind == "tool/call" and isinstance(data.get("callId"), str):
            calls[data["callId"]] = (data.get("name"), data.get("arguments"))
        if kind not in {"tool/ptc-dispatch", "tool/result"}:
            continue
        result = data if kind == "tool/ptc-dispatch" else data.get("message", {})
        if not isinstance(result, dict):
            continue
        tool_source = result.get("source")
        call_id = tool_source.get("callId") if isinstance(tool_source, dict) and isinstance(tool_source.get("callId"), str) else result.get("toolCallId")
        name, args = (data.get("name"), data.get("arguments")) if kind == "tool/ptc-dispatch" else calls.get(call_id, (None, None)) if isinstance(call_id, str) else (None, None)
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = None
        if not isinstance(args, dict):
            continue
        output = args.get("outputPath")
        parameters = args.get("parameters")
        if isinstance(parameters, dict):
            output = parameters.get("output", output)
        if isinstance(output, str) and Path(output).suffix.lower() in {".pdf", ".docx", ".xlsx", ".pptx"}:
            key = output.replace("\\", "/")
            targets[key] = dict(name=key.rsplit("/", 1)[-1][:240], format=Path(output).suffix[1:].lower(), event_seq=seq)
        if result.get("isError") is not False:
            continue
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        if name in {"gongchuang_deliver_pdf", "gongchuang_publish_files"} and "paths" in meta:
            paths = meta["paths"]
            if isinstance(paths, list) and 0 < len(paths) <= 20 and all(absolute_receipt_path(path) for path in paths) and (name != "gongchuang_deliver_pdf" or len(paths) == 1):
                for path in paths:
                    publish(path, "published", seq, name)
        elif name == "gongchuang_artifact_probe":
            if "path" in meta:
                if absolute_receipt_path(meta["path"]):
                    publish(meta["path"], "published", seq, name)
            else:
                publish(args.get("artifactPath"), "published", seq, name)
        elif name == "gongchuang_publish_files" and isinstance(args.get("paths"), list):
            for path in args["paths"]:
                publish(path, "published", seq, name)

    # New clients compute this before event-size cropping, so their bounded observations survive omitted events.
    for key in ("user_request", "goal_request", "last_reply"):
        value = supplied.get(key)
        if isinstance(value, dict) and isinstance(value.get("event_seq"), int) and isinstance(value.get("text"), str):
            parsed = excerpt(value["text"], value["event_seq"])
            parsed["truncated"] = parsed["truncated"] or value.get("truncated") is True
            if key == "user_request":
                request = parsed
            elif key == "goal_request":
                goal_request = parsed
            else:
                reply = dict(parsed, final=value.get("final") is True)
                if not parsed["truncated"]:
                    reply_text = value["text"]
    if isinstance(supplied.get("files"), list):
        files = {}
        for file in supplied["files"][:32]:
            if isinstance(file, dict) and isinstance(file.get("name"), str) and isinstance(file.get("event_seq"), int) and isinstance(file.get("source"), str) and file["source"] in {"professional-notice", "deliverables/presented", "gongchuang_artifact_probe", "gongchuang_publish_files", "gongchuang_deliver_pdf"}:
                publish(file["name"], str(file.get("phase", "unknown"))[:30], file["event_seq"], file["source"])
    request_text = (goal_request or request or {}).get("text", "")
    json_requested = bool(re.search(r"(?:只|仅)(?:输出|返回)[^。！？；;\n]{0,12}JSON\s*对象", request_text, re.I))
    structured_reply = "absent" if json_requested else "not-requested"
    if json_requested and reply_text:
        try:
            structured_reply = "valid-object" if isinstance(json.loads(reply_text), dict) else "invalid"
        except ValueError:
            structured_reply = "invalid"
    structure = supplied.get("structured_reply")
    if json_requested and not reply_text and context.get("omitted_event_count") and isinstance(structure, str) and structure in {"valid-object", "invalid", "absent"}:
        structured_reply = structure
    direct_request = "" if re.search(r"(?:吗|么|[?？])\s*$", request_text) else re.sub(r"(?:不要|不用|无需|不必|别|不)(?:再|自动)?(?:生成|输出|导出|制作|交付|提供)[^。！？\n]{0,24}?(?:PDF|Word|DOCX)\b", "", request_text, flags=re.I | re.ASCII)
    formats = list(dict.fromkeys("pdf" if token.lower() == "pdf" else "docx" for token in re.findall(r"(?:生成|输出|导出|转成|转换成|转为|制作|交付|提供|给我)(?!看|读|分析|检查|介绍)[^。！？\n]{0,24}?(PDF|Word|DOCX)\b", direct_request, re.I | re.ASCII)))
    if isinstance(supplied.get("requested_formats"), list):
        formats = list(dict.fromkeys(item for item in supplied["requested_formats"] if isinstance(item, str) and item in {"pdf", "docx"}))
    report_requested = any(re.search(r"报告(?!中的|的|摘要|标题|目录|大纲|模板|模版|模块)", clause)
        and re.search(r"生成|撰写|出具|制作|交付|输出|出一份|出一版|出一个|给我一份|给我两份|给我一个|做一份|做一个|做一下|做下", clause)
        and not re.search(r"不要|不生成|不撰写|不输出|不用|无需|禁止", clause)
        for clause in re.split(r"[，,。！？；;\n]", request_text))
    shorthand_report = bool(re.fullmatch(
        r"\s*[\u4e00-\u9fffA-Za-z0-9·（）()]{2,}公司[，,\s]*"
        r"(?=[^。！？；;\n]*?(?:高企|高新技术企业|专精特新|研发中心))"
        r"[^。！？；;\n]*?(?:双报告|可行性(?:分析)?报告)\s*[。.!！]?\s*",
        request_text,
    )) and not re.search(
        r"阅读|解读|解释|查看|审核|审查|分析(?:这|该|已有|现有|提供|所附)|这份|该份|附件"
        r"|不要|不用|无需|不必|禁止|别|不生成|不做|不出|能否|能不能|能生成|能做|是否|支持|吗|么|[?？]",
        request_text,
    )
    report_requested = report_requested or shorthand_report
    if re.search(r"不(?:写|创建|生成)文件|只在对话中|只(?:输出|返回)[^。！？\n]{0,12}JSON", request_text, re.I) or re.search(r"^(?:请问)?(?:你)?(?:能否|能不能|能|会|支持)[^。！？\n]*报告(?:吗[?？]?|[?？])\s*$", request_text):
        report_requested = False
    file_requested = bool(formats or report_requested)
    if isinstance(supplied.get("file_requested"), bool):
        file_requested = supplied["file_requested"]
    if reply:
        reply["final"] = reply["final"] and turn_result == "completed"
    failures = (analysis or {}).get("failures", [])
    delivered = [file for file in files.values() if file["phase"] in {"published", "formal"}]
    account_block = any(item.get("stage") in {"client-upgrade", "model-credentials", "model-balance", "model-quota"} and item.get("status") != "recovered" for item in failures)
    unresolved_execution = any(item.get("status") == "unrecovered" and item.get("category") == "runtime" for item in failures)
    failed_file = any(item.get("status") == "unrecovered" and (item.get("stage", "").startswith("pdf-") or item.get("tool") in {"gongchuang_artifact_probe", "gongchuang_content_audit", "gongchuang_branding_gate", "gongchuang_visual_inspection"}) for item in failures)
    status = "unknown"
    if turn_result == "aborted":
        status = "cancelled"
    elif json_requested and not account_block and not terminal_account_block:
        status = "answered" if structured_reply == "valid-object" and not unresolved_execution and turn_result in {"completed", "blocked"} else "not-delivered" if turn_result in {"completed", "blocked", "error"} else "unknown"
    elif delivered:
        complete_formats = all(any(file["format"] == fmt for file in delivered) for fmt in formats)
        status = "not-delivered" if formats and not any(file["format"] in formats for file in delivered) else "delivered" if turn_result == "completed" and delivery_result not in {"draft", "failed", "waiting-user"} and complete_formats and not failed_file and len(delivered) == len(files) else "partial"
    elif files:
        status = "partial"
    elif file_requested and not account_block and not terminal_account_block and delivery_result != "waiting-user" and turn_result in {"completed", "blocked"} and (not context.get("omitted_event_count") or isinstance(supplied.get("file_requested"), bool) and isinstance(supplied.get("files"), list)):
        status = "not-delivered"
    elif account_block or terminal_account_block or delivery_result == "waiting-user" or turn_result == "blocked" and delivery_result == "draft" and not unresolved_execution:
        status = "blocked"
    elif failed_file or delivery_result == "failed" or turn_result == "blocked" and unresolved_execution or turn_result == "completed" and (formats or targets) and not context.get("omitted_event_count"):
        status = "not-delivered"
    elif not file_requested and not targets and turn_result == "completed" and reply and reply["final"]:
        status = "answered"
    unpublished = supplied.get("unpublished_files")
    unpublished = [dict(name=file["name"][:240], format=file["format"][:30], event_seq=file["event_seq"]) for file in unpublished[:32] if isinstance(file, dict) and isinstance(file.get("name"), str) and isinstance(file.get("format"), str) and isinstance(file.get("event_seq"), int)] if isinstance(unpublished, list) else [file for key, file in targets.items() if key not in files][:32]
    return dict(status=status, verification_scope="json-structure-only" if json_requested else "text-response-only" if status == "answered" else "file-delivery-only", requested_formats=formats, file_requested=file_requested,
                user_request=request, goal_request=goal_request, structured_reply=structured_reply,
                last_reply=reply, files=list(files.values())[:32], unpublished_files=unpublished)


def _outcome_lines(outcome: dict) -> list[str]:
    labels = {"delivered": "已记录实际文件交付", "partial": "部分文件已交付，整体尚未完成确认", "not-delivered": "目标结果未达成" if outcome.get("verification_scope") == "json-structure-only" else "目标文件未交付", "answered": "回复符合单一 JSON 对象结构" if outcome.get("verification_scope") == "json-structure-only" else "已记录最终文字回复", "blocked": "账号条件或用户确认阻塞", "cancelled": "用户取消", "unknown": "最终结果未知"}
    scope = "仅检查 JSON 结构，字段内容与计算是否正确仍需验收。" if outcome.get("verification_scope") == "json-structure-only" else "文件回执只证明交付，内容是否满足需求仍需验收。"
    if outcome.get("verification_scope") == "text-response-only":
        scope = "仅确认本轮已有文字回复；过程异常与恢复记录保留，内容是否准确完整仍需验收。"
    if outcome.get('verification_scope') == 'host-operation-only':
        labels['not-delivered'] = '目标操作未完成'
        scope = '宿主记录删除失败，修复后须重试并验收实际删除结果。'
    lines = ["最终结果：" + labels[outcome["status"]] + "。" + scope, ""]
    request = outcome.get("goal_request") or outcome["user_request"]
    if request:
        lines.extend(["用户目标：", "", "> " + request["text"].replace("\n", "\n> "), ""])
    if outcome.get("structured_reply") in {"invalid", "absent"}:
        lines.extend(["JSON-only 要求未满足：回复为空、夹杂说明或代码围栏，或不是可解析的单一 JSON 对象。", ""])
    if outcome["last_reply"]:
        reply = outcome["last_reply"]
        lines.extend(["最终可见回复：" if reply["final"] else "最后可见进度回复，不能当作完成：", "", "> " + reply["text"].replace("\n", "\n> "), ""])
    for file in outcome["files"]:
        lines.extend([f"- 文件：{file['name']}；格式 {file['format']}；状态 {file['phase']}；宿主事件 {file['event_seq']}。", ""])
    for file in outcome["unpublished_files"]:
        lines.extend([f"- 未取得发布回执：{file['name']}；格式 {file['format']}；事件 {file['event_seq']}。", ""])
    return lines


def _analysis_lines(analysis: dict) -> list[str]:
    categories = {"runtime": "执行故障", "precondition": "前置条件受阻", "waiting-user": "等待用户选择", "protection": "文件保护提示",
                  "business-rejection": "业务检查未通过", "outcome-unknown": "结果尚未确认"}
    statuses = {"unrecovered": "未记录同操作恢复", "recovered": "同操作已恢复", "expected-block": "规则拦截", "outcome-unknown": "结果未知"}
    lines = [f"客户端记录：轮次结束状态 {analysis['turn_result']}；专业交付状态 {analysis['delivery_result']}。", ""]
    model = analysis.get("model_request")
    if model:
        lines.extend([f"本轮最后一次实际模型请求：{model['provider']} / {model['model']}；宿主事件 {model['event_seq']}。不是设置页的默认模型。", ""])
    first = analysis.get("first_failure")
    if first:
        lines.extend([f"首个失败：事件 {first['event_seq']}，{first.get('operation') or first.get('tool', '未知操作')}；不能单独作为最终失败原因。", ""])
    primary = analysis["primary_failure"]
    lines.append(f"主要待排查失败：事件 {primary['event_seq']}，{primary.get('operation') or primary.get('tool', '未知操作')}，阶段 {primary.get('stage', '未知')}。"
                 if primary else "未记录主要未解决故障；仍需查看已恢复错误或规则拦截，不能据此宣称业务验收通过。")
    lines.extend(["", "失败与恢复顺序：", ""])
    for failure in analysis["failures"]:
        detail = f"事件 {failure['event_seq']}：{failure.get('operation') or failure.get('tool', '未知操作')}；阶段 {failure.get('stage', '未知')}；{categories[failure['category']]}；{statuses[failure['status']]}"
        if "recovery_event_seq" in failure:
            detail += f"；恢复于事件 {failure['recovery_event_seq']}"
        if "blocked_by_event_seq" in failure:
            detail += f"；同目标生成失败后的后续受阻，关联事件 {failure['blocked_by_event_seq']}"
        page_recovery = failure.get("page_recovery")
        if page_recovery:
            requested = page_recovery["requested_pages"]
            detail += "；OCR原请求为整份文件" if requested == "all" else f"；OCR后续成功页覆盖 {len(page_recovery['covered_pages'])}/{len(requested)} 页"
        lines.extend(["- " + detail, "", *["> " + line for line in failure.get("observed_reason", "未提供具体错误").splitlines()], ""])
        execution = failure.get("execution")
        if execution:
            lines.extend(["执行事实：`" + json.dumps(execution, ensure_ascii=False) + "`", ""])
    if analysis["omitted_failure_count"]:
        lines.extend([f"另有 {analysis['omitted_failure_count']} 条失败未纳入摘要，请查看原始诊断。", ""])
    return lines


def review_pending(connection: sqlite3.Connection, now: datetime) -> dict:
    """Create an evidence-based daily repair document; no inferred root cause is asserted."""
    day = now.astimezone(SHANGHAI).date().isoformat()
    stamp = now.astimezone(timezone.utc).isoformat()
    connection.execute("BEGIN IMMEDIATE")
    try:
        rows = connection.execute("""SELECT r.feedback_id,r.diagnostic_json,f.created_at
            FROM client_error_reports r JOIN feedback_messages f ON f.id=r.feedback_id
            LEFT JOIN client_diagnostic_reviews v ON v.report_id=r.feedback_id
            WHERE v.report_id IS NULL AND f.created_at<=? ORDER BY r.feedback_id""", (stamp,))
        for report_id, raw, received_at in rows:
            diagnostic = json.loads(raw)
            context = json.loads(diagnostic.get("conversation_context") or "{}")
            files = connection.execute("SELECT file_id,name,size,received FROM client_diagnostic_files WHERE report_id=?", (report_id,)).fetchall()
            # An interrupted upload is neither a complete review nor eligible for expiry.
            expected = context.get("diagnostic_files", []) if isinstance(context, dict) else []
            uploaded = {row[0] for row in files if row[2] == row[3]}
            incomplete = [item for item in expected if isinstance(item, dict) and item.get("status") == "pending" and item.get("file_id") not in uploaded]
            if incomplete and datetime.fromisoformat(received_at) > now - timedelta(hours=24):
                continue
            details = _errors(context)
            analysis = _failure_analysis(context)
            outcome = _turn_outcome(context, analysis)
            review = {"report_id": report_id, "received_at": received_at,
                      "occurred_at": diagnostic.get("occurred_at") if isinstance(diagnostic.get("occurred_at"), str) else None,
                      "code": diagnostic["code"], "client_version": diagnostic["client_version"],
                      "errors": details, "files": [dict(file_id=r[0], name=r[1], size=r[2]) for r in files],
                      "missing_files": [item for item in expected if isinstance(item, dict) and item.get("status") != "pending"] + incomplete,
                      "root_cause": "待复现，错误文本不能单独证明根因",
                      "next_action": "使用同版本、相关输入和工具参数复现，修复后验证原失败路径及相邻成功路径"}
            review["outcome"] = outcome
            if outcome["status"] == "blocked" and analysis and any(item.get("stage") in {"model-balance", "model-quota", "model-credentials", "client-upgrade"} for item in analysis["failures"]):
                review.update(root_cause="已观测账号或版本条件未满足，不等同于文件生成程序故障", next_action="按具体诊断处理余额、额度、模型密钥或客户端升级；条件恢复后验收原任务最终结果")
            elif outcome["status"] == "blocked" and any(re.search(r"GC-ACCOUNT-UPGRADE|MISSING_CREDENTIAL|INVALID_CREDENTIAL|Insufficient Balance|最低支持版本", detail, re.I) for detail in details):
                review.update(root_cause="已观测账号或版本条件未满足，不等同于文件生成程序故障", next_action="处理诊断记录的账号条件或升级要求，然后继续原任务；不能把拦截本身记为生成程序缺陷")
            elif outcome["status"] == "not-delivered" and outcome.get("file_requested") and analysis and analysis["delivery_result"] == "draft" and not analysis["failures"]:
                review.update(root_cause="专业流程在待完善状态停止，未取得目标报告的文件回执；这不单独证明程序崩溃", next_action="核对本轮报告意图、待完善原因及导出步骤；修复后验收实际文件，不能只以正常规则拦截关闭问题")
            if analysis is not None:
                review["failure_analysis"] = analysis
            connection.execute("INSERT INTO client_diagnostic_reviews(report_id,reviewed_at,day,review_json) VALUES (?,?,?,?)", (report_id, stamp, day, json.dumps(review, ensure_ascii=False)))
        reviews = [json.loads(row[0]) for row in connection.execute("SELECT review_json FROM client_diagnostic_reviews WHERE day=? ORDER BY report_id", (day,))]
        lines = [f"# 客户端错误复盘与修复清单 {day}", "", "说明：先检查用户目标、最终回复与实际文件交付，再分析失败阶段和同操作恢复。首条错误不代表最终失败原因；已观测失败不等于触发根因已确认。旧客户端未记录的信息标为未知。", ""]
        groups: dict[tuple[str, tuple[str, ...]], list[dict]] = {}
        for review in reviews:
            analysis = review.get("failure_analysis")
            signature = json.dumps({"turn_result": analysis["turn_result"], "delivery_result": analysis["delivery_result"],
                "model_request": analysis.get("model_request"),
                "failures": [{key: item.get(key) for key in ("tool", "operation", "stage", "code", "category", "status", "observed_reason")} for item in analysis["failures"]]}, sort_keys=True, ensure_ascii=False) if analysis else ""
            outcome_signature = json.dumps(review.get("outcome", {"status": "unknown"}), sort_keys=True, ensure_ascii=False)
            groups.setdefault((review["code"], tuple([signature, outcome_signature]) if signature else tuple(review["errors"] or ["未取得具体错误"]) + (outcome_signature,)), []).append(review)
        for index, ((code, errors), members) in enumerate(groups.items(), 1):
            lines.extend([f"## {index}. {code}", "", "报告编号：" + "、".join(str(m["report_id"]) for m in members),
                          "", "错误事实：", ""])
            for member in members:
                lines.extend([f"- #{member['report_id']} 客户端发生时间：{member.get('occurred_at') or '未记录'}；服务器接收时间：{member['received_at']}。", ""])
            lines.extend(_outcome_lines(members[0].get("outcome", {"status": "unknown", "files": [], "unpublished_files": [], "user_request": None, "last_reply": None})))
            if members[0].get("failure_analysis"):
                lines.extend(_analysis_lines(members[0]["failure_analysis"]))
            else:
                lines.extend(["未提供结构化对话失败阶段与恢复记录；可能是旧版上报或独立采集失败，以下保留原始错误事实。", ""])
                for error in members[0]["errors"]:
                    lines.extend([*["> " + line for line in error.splitlines()], ""])
            lines.extend(["根因：" + members[0]["root_cause"], "", "修复与验证：" + members[0]["next_action"], ""])
        if not reviews:
            lines.append("本批没有完成复盘的新错误；未传完附件的报告继续保留。")
        connection.execute("INSERT INTO client_diagnostic_days(day,created_at,document) VALUES (?,?,?) ON CONFLICT(day) DO UPDATE SET created_at=excluded.created_at,document=excluded.document", (day, stamp, "\n".join(lines)))
        result = {"day": day, "reviewed": len(reviews), "groups": len(groups)}
        connection.execute("INSERT INTO client_diagnostic_job_runs(kind,finished_at,result_json) VALUES ('review',?,?)", (stamp, json.dumps(result)))
        connection.commit()
        return result
    except Exception:
        connection.rollback()
        raise


def main() -> None:
    import argparse
    from contextlib import closing
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['review', 'purge'])
    args = parser.parse_args()
    # Reuse the service's configured database and data directory, not a second store.
    from app.main import database, DATA_DIR
    with closing(database()) as connection:
        initialize(connection)
        now = datetime.now(timezone.utc)
        result = review_pending(connection, now) if args.action == 'review' else purge_reviewed(connection, DATA_DIR / 'client-diagnostic-files', now)
    print(json.dumps(result, ensure_ascii=False))


def purge_reviewed(connection: sqlite3.Connection, root: Path, now: datetime) -> dict:
    """Permanently expire only resolved, reviewed, prior-day diagnostic copies."""
    midnight = now.astimezone(SHANGHAI).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).isoformat()
    stamp = now.astimezone(timezone.utc).isoformat()
    purged, reclaimed = [], 0
    connection.execute("BEGIN IMMEDIATE")
    try:
        rows = connection.execute("""SELECT r.feedback_id FROM client_error_reports r
            JOIN feedback_messages f ON f.id=r.feedback_id JOIN client_diagnostic_reviews v ON v.report_id=r.feedback_id
            WHERE f.created_at<? AND f.status IN ('resolved','closed') AND v.purged_at IS NULL""", (midnight,)).fetchall()
        for (report_id,) in rows:
            files = connection.execute("SELECT file_id,size,received FROM client_diagnostic_files WHERE report_id=?", (report_id,)).fetchall()
            if any(size != received for _, size, received in files):
                continue
            for file_id, size, received in files:
                path = file_path(root, report_id, file_id)
                if path.is_symlink():
                    raise ValueError("Refusing diagnostic storage symlink")
                if path.exists():
                    reclaimed += path.stat().st_size
                    path.unlink()  # Explicitly authorized expiry of server diagnostic copies only.
            connection.execute("DELETE FROM client_diagnostic_files WHERE report_id=?", (report_id,))
            connection.execute("UPDATE client_error_reports SET diagnostic_json=? WHERE feedback_id=?", (json.dumps({"expired": True, "report_id": report_id, "expired_at": stamp}), report_id))
            connection.execute("UPDATE client_diagnostic_reviews SET purged_at=? WHERE report_id=?", (stamp, report_id))
            purged.append(report_id)
        result = {"purged_report_ids": purged, "reclaimed_bytes": reclaimed, "cutoff": midnight}
        connection.execute("INSERT INTO client_diagnostic_job_runs(kind,finished_at,result_json) VALUES ('purge',?,?)", (stamp, json.dumps(result)))
        connection.commit()
        return result
    except Exception:
        connection.rollback()
        raise


if __name__ == '__main__':
    main()
