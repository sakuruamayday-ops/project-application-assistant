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
        for event in value['events']:
            if not isinstance(event, dict) or not isinstance(event.get('data'), dict):
                continue
            data = event['data']
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
            review = {"report_id": report_id, "received_at": received_at,
                      "code": diagnostic["code"], "client_version": diagnostic["client_version"],
                      "errors": details, "files": [dict(file_id=r[0], name=r[1], size=r[2]) for r in files],
                      "missing_files": [item for item in expected if isinstance(item, dict) and item.get("status") != "pending"] + incomplete,
                      "root_cause": "待复现，错误文本不能单独证明根因",
                      "next_action": "使用同版本、相关输入和工具参数复现，修复后验证原失败路径及相邻成功路径"}
            connection.execute("INSERT INTO client_diagnostic_reviews(report_id,reviewed_at,day,review_json) VALUES (?,?,?,?)", (report_id, stamp, day, json.dumps(review, ensure_ascii=False)))
        reviews = [json.loads(row[0]) for row in connection.execute("SELECT review_json FROM client_diagnostic_reviews WHERE day=? ORDER BY report_id", (day,))]
        lines = [f"# 客户端错误复盘与修复清单 {day}", "", "说明：以下为程序提取的错误事实，根因尚须复现验证。", ""]
        groups: dict[tuple[str, str], list[dict]] = {}
        for review in reviews:
            groups.setdefault((review["code"], (review["errors"] or ["未取得具体错误"])[0]), []).append(review)
        for index, ((code, error), members) in enumerate(groups.items(), 1):
            lines.extend([f"## {index}. {code}", "", "报告编号：" + "、".join(str(m["report_id"]) for m in members),
                          "", "错误事实：", "", *["> " + line for line in error.splitlines()], "",
                          "根因：待复现。", "", "修复与验证：使用关联诊断、附件和失败成品复现；修复后回归同类失败及成功路径。", ""])
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
