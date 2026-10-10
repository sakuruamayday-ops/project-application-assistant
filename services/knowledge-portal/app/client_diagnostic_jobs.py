"""Internal-test diagnostics: resumable files, daily review, and scoped expiry."""
from __future__ import annotations

import base64
import json
import os
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
        if not isinstance(item.get("category"), str) or item["category"] not in {"runtime", "precondition", "waiting-user", "business-rejection", "outcome-unknown"}:
            return None
        if not isinstance(item.get("status"), str) or item["status"] not in {"unrecovered", "recovered", "expected-block", "outcome-unknown"}:
            return None
        result = {key: item[key][:2000] for key in ("tool", "operation", "stage", "code", "observed_reason") if isinstance(item.get(key), str)}
        result.update(event_seq=item["event_seq"], category=item["category"], status=item["status"], cause_status="observed-failure-only")
        for key in ("recovery_event_seq", "blocked_by_event_seq"):
            if isinstance(item.get(key), int):
                result[key] = item[key]
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
    if not failures:
        return None
    primary = incident(value.get("primary_failure"))
    first = incident(value.get("first_failure"))
    # A primary observation must also belong to the supplied failure sequence.
    if primary not in failures:
        primary = None
    if first not in failures:
        first = None
    return {"turn": value.get("turn") if isinstance(value.get("turn"), int) else None,
            "turn_result": str(value.get("turn_result", "unknown"))[:60],
            "delivery_result": str(value.get("delivery_result", "unknown"))[:60],
            "first_failure": first, "primary_failure": primary, "failures": failures,
            "omitted_failure_count": value.get("omitted_failure_count", 0) if isinstance(value.get("omitted_failure_count", 0), int) else 0}


def _analysis_lines(analysis: dict) -> list[str]:
    categories = {"runtime": "执行故障", "precondition": "前置条件受阻", "waiting-user": "等待用户选择",
                  "business-rejection": "业务检查未通过", "outcome-unknown": "结果尚未确认"}
    statuses = {"unrecovered": "未记录同操作恢复", "recovered": "同操作已恢复", "expected-block": "规则拦截", "outcome-unknown": "结果未知"}
    lines = [f"客户端记录：轮次结束状态 {analysis['turn_result']}；专业交付状态 {analysis['delivery_result']}。", ""]
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
            review = {"report_id": report_id, "received_at": received_at,
                      "code": diagnostic["code"], "client_version": diagnostic["client_version"],
                      "errors": details, "files": [dict(file_id=r[0], name=r[1], size=r[2]) for r in files],
                      "missing_files": [item for item in expected if isinstance(item, dict) and item.get("status") != "pending"] + incomplete,
                      "root_cause": "待复现，错误文本不能单独证明根因",
                      "next_action": "使用同版本、相关输入和工具参数复现，修复后验证原失败路径及相邻成功路径"}
            if analysis is not None:
                review["failure_analysis"] = analysis
            connection.execute("INSERT INTO client_diagnostic_reviews(report_id,reviewed_at,day,review_json) VALUES (?,?,?,?)", (report_id, stamp, day, json.dumps(review, ensure_ascii=False)))
        reviews = [json.loads(row[0]) for row in connection.execute("SELECT review_json FROM client_diagnostic_reviews WHERE day=? ORDER BY report_id", (day,))]
        lines = [f"# 客户端错误复盘与修复清单 {day}", "", "说明：优先使用客户端记录的失败阶段、同操作恢复与交付状态。首条错误不代表最终失败原因；已观测失败不等于触发根因已确认。旧客户端未记录的信息标为未知。", ""]
        groups: dict[tuple[str, tuple[str, ...]], list[dict]] = {}
        for review in reviews:
            analysis = review.get("failure_analysis")
            signature = json.dumps({"turn_result": analysis["turn_result"], "delivery_result": analysis["delivery_result"],
                "failures": [{key: item.get(key) for key in ("tool", "operation", "stage", "code", "category", "status", "observed_reason")} for item in analysis["failures"]]}, sort_keys=True, ensure_ascii=False) if analysis else ""
            groups.setdefault((review["code"], tuple([signature]) if signature else tuple(review["errors"] or ["未取得具体错误"])), []).append(review)
        for index, ((code, errors), members) in enumerate(groups.items(), 1):
            lines.extend([f"## {index}. {code}", "", "报告编号：" + "、".join(str(m["report_id"]) for m in members),
                          "", "错误事实：", ""])
            if members[0].get("failure_analysis"):
                lines.extend(_analysis_lines(members[0]["failure_analysis"]))
            else:
                lines.extend(["未提供结构化对话失败阶段与恢复记录；可能是旧版上报或独立采集失败，以下保留原始错误事实。", ""])
                for error in errors:
                    lines.extend([*["> " + line for line in error.splitlines()], ""])
            lines.extend(["根因：待复现。", "", "修复与验证：使用关联诊断、附件和失败成品复现；修复后回归同类失败及成功路径。", ""])
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
