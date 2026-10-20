"""Member-owned final business reports, separate from diagnostics and knowledge indexes."""
from __future__ import annotations

import base64
import hashlib
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from app.client_diagnostic_jobs import CHUNK_BYTES

REPORT_EXTENSIONS = {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".pdf", ".html", ".htm"}


class ReportConflict(ValueError):
    """An idempotency key was reused with different file metadata."""


class ReportNotFound(LookupError):
    """The requested report is unavailable to this member."""


class ReportMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    filename: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(ge=1, le=256 * 1024 * 1024, strict=True)
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    generated_at: AwareDatetime
    title: str = Field(min_length=1, max_length=300)
    company_name: str | None = Field(default=None, max_length=200)
    skill_name: str | None = Field(default=None, max_length=100)
    skill_version: str | None = Field(default=None, max_length=64)
    client_version: str = Field(min_length=1, max_length=64)
    report_kind: Literal["business-analysis"]
    stage: Literal["final"]
    final_reason: str = Field(min_length=1, max_length=300)

    @field_validator("filename")
    @classmethod
    def basename_only(cls, value: str) -> str:
        if value in {".", ".."} or "/" in value or "\\" in value or any(ord(c) < 32 for c in value):
            raise ValueError("filename must be a display name without a local path")
        if Path(value).suffix.lower() not in REPORT_EXTENSIONS:
            raise ValueError("only PDF, Word, Excel, PowerPoint and HTML finals are collected")
        return value

    @field_validator("sha256")
    @classmethod
    def lowercase_digest(cls, value: str) -> str:
        return value.lower()


class ReportChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")
    offset: int = Field(ge=0, strict=True)
    content_base64: str = Field(min_length=1, max_length=1_398_104)


def initialize(connection: sqlite3.Connection) -> None:
    connection.execute("""
        CREATE TABLE IF NOT EXISTS client_reports (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            request_id TEXT NOT NULL,
            filename TEXT NOT NULL, size_bytes INTEGER NOT NULL, sha256 TEXT NOT NULL,
            generated_at TEXT NOT NULL, title TEXT NOT NULL, company_name TEXT,
            skill_name TEXT, skill_version TEXT, client_version TEXT NOT NULL,
            report_kind TEXT NOT NULL CHECK(report_kind='business-analysis'),
            stage TEXT NOT NULL CHECK(stage='final'), final_reason TEXT NOT NULL,
            received_bytes INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL, completed_at TEXT, downloaded_at TEXT,
            cleanup_requested_at TEXT, cleaned_at TEXT,
            UNIQUE(user_id,request_id)
        )
    """)
    columns = {row[1] for row in connection.execute("PRAGMA table_info(client_reports)")}
    for column in ("cleanup_requested_at", "cleaned_at"):
        if column not in columns:
            connection.execute("ALTER TABLE client_reports ADD COLUMN " + column + " TEXT")


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def file_path(root: Path, report_id: int) -> Path:
    return root / str(int(report_id)) / "content"


def receipt(row: sqlite3.Row) -> dict:
    return {"next_offset": row["received_bytes"], "complete": row["completed_at"] is not None}


def create_report(connection: sqlite3.Connection, user_id: int, metadata: ReportMetadata) -> dict:
    values = metadata.model_dump(mode="json")
    values["generated_at"] = metadata.generated_at.astimezone(timezone.utc).isoformat()
    connection.execute("BEGIN IMMEDIATE")
    try:
        row = connection.execute(
            "SELECT * FROM client_reports WHERE user_id=? AND request_id=?",
            (user_id, str(metadata.request_id)),
        ).fetchone()
        if row is not None:
            if any(row[key] != value for key, value in values.items()):
                raise ReportConflict("同一 request_id 的报告元数据不同，请为新定稿版本使用新的 request_id")
        else:
            fields = ["user_id", *values, "created_at"]
            cursor = connection.execute(
                "INSERT INTO client_reports(" + ",".join(fields) + ") VALUES (" + ",".join("?" for _ in fields) + ")",
                (user_id, *values.values(), timestamp()),
            )
            row = connection.execute("SELECT * FROM client_reports WHERE id=?", (cursor.lastrowid,)).fetchone()
        connection.commit()
        return {"report_id": row["id"], **receipt(row)}
    except Exception:
        connection.rollback()
        raise


def owned_report(connection: sqlite3.Connection, report_id: int, user_id: int | None = None) -> sqlite3.Row:
    row = connection.execute("SELECT * FROM client_reports WHERE id=?", (report_id,)).fetchone()
    if row is None or user_id is not None and row["user_id"] != user_id:
        raise ReportNotFound("报告不存在")
    return row


def decode_file_chunk(chunk: ReportChunk) -> bytes:
    try:
        data = base64.b64decode(chunk.content_base64, validate=True)
    except ValueError as error:
        raise ValueError("文件分块编码无效") from error
    if not data or len(data) > CHUNK_BYTES:
        raise ValueError("文件分块必须包含 1 至 1048576 字节")
    return data


def write_file_chunk(root: Path, file_id: int, size_bytes: int, sha256: str,
                     offset: int, data: bytes) -> tuple[int, bool]:
    """Persist shared report/attachment transport bytes; each caller owns its table and lifecycle."""
    if offset + len(data) > size_bytes:
        raise ValueError("文件分块超过声明大小")
    path = file_path(root, file_id)
    if root.is_symlink() or path.parent.is_symlink() or path.is_symlink():
        raise ValueError("文件存储目录无效")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.mkdir(mode=0o700, exist_ok=True)
    if shutil.disk_usage(root).free < len(data) + 2 * 1024**3:
        raise ValueError("文件存储空间不足，请保留客户端文件稍后重试")
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    mismatch = False
    received = offset + len(data)
    with os.fdopen(descriptor, "r+b") as stream:
        if os.fstat(stream.fileno()).st_size < offset:
            raise ValueError("文件已保存的分块不完整")
        stream.seek(offset)
        stream.write(data)
        stream.truncate(received)
        stream.flush()
        os.fsync(stream.fileno())
        if received == size_bytes:
            stream.seek(0)
            if hashlib.file_digest(stream, "sha256").hexdigest() != sha256:
                # Keep the file identity and retry from zero; never expose corrupt bytes.
                stream.seek(0)
                stream.truncate(0)
                stream.flush()
                os.fsync(stream.fileno())
                received = 0
                mismatch = True
    return received, mismatch


def receive_chunk(connection: sqlite3.Connection, root: Path, report_id: int, user_id: int, chunk: ReportChunk) -> dict:
    data = decode_file_chunk(chunk)
    connection.execute("BEGIN IMMEDIATE")
    try:
        row = owned_report(connection, report_id, user_id)
        if row["completed_at"] is not None or chunk.offset != row["received_bytes"]:
            connection.commit()
            return receipt(row)
        received, mismatch = write_file_chunk(
            root, report_id, row["size_bytes"], row["sha256"], chunk.offset, data,
        )
        complete = received == row["size_bytes"]
        connection.execute(
            "UPDATE client_reports SET received_bytes=?,completed_at=? WHERE id=?",
            (received, timestamp() if complete else None, report_id),
        )
        connection.commit()
        if mismatch:
            raise ValueError("报告 SHA-256 不匹配，已重置为 offset=0，请重传")
        return {"next_offset": received, "complete": complete}
    except Exception:
        connection.rollback()
        raise


def list_reports(connection: sqlite3.Connection, *, user_id: int | None = None,
                 undownloaded_only: bool = False, completed_only: bool = False,
                 limit: int = 50, offset: int = 0) -> list[dict]:
    filters = []
    args: list = []
    if user_id is not None:
        filters.append("report.user_id=?")
        args.append(user_id)
    if completed_only or undownloaded_only:
        filters.append("report.completed_at IS NOT NULL")
    if undownloaded_only:
        filters.append("report.downloaded_at IS NULL")
    where = " WHERE " + " AND ".join(filters) if filters else ""
    rows = connection.execute(
        "SELECT report.*,COALESCE(NULLIF(users.real_name,''),users.username) AS member_name "
        "FROM client_reports report JOIN users ON users.id=report.user_id" + where
        + " ORDER BY report.id LIMIT ? OFFSET ?", (*args, limit, offset),
    ).fetchall()
    reports = []
    for row in rows:
        report = dict(row)
        report["report_id"] = report.pop("id")
        reports.append(report)
    return reports


def completed_file(connection: sqlite3.Connection, root: Path, report_id: int,
                   user_id: int | None = None) -> tuple[sqlite3.Row, Path]:
    row = owned_report(connection, report_id, user_id)
    path = file_path(root, report_id)
    if row["completed_at"] is None or row["cleaned_at"] is not None or root.is_symlink() or path.parent.is_symlink() or path.is_symlink() or not path.is_file():
        raise ReportNotFound("报告尚未收齐或文件不可用")
    with path.open("rb") as stream:
        if os.fstat(stream.fileno()).st_size != row["size_bytes"] or hashlib.file_digest(stream, "sha256").hexdigest() != row["sha256"]:
            raise ValueError("报告文件完整性校验失败")
    return row, path


def acknowledge_download(connection: sqlite3.Connection, report_id: int) -> dict:
    row = owned_report(connection, report_id)
    if row["completed_at"] is None or row["received_bytes"] != row["size_bytes"]:
        raise ReportConflict("报告尚未完整上传")
    if row["cleaned_at"] is not None and row["downloaded_at"] is None:
        raise ReportConflict("报告尚未完成下载确认")
    downloaded_at = row["downloaded_at"] or timestamp()
    connection.execute("UPDATE client_reports SET downloaded_at=? WHERE id=?", (downloaded_at, report_id))
    connection.commit()
    return {"report_id": report_id, "downloaded_at": downloaded_at}


def cleanup_report(connection: sqlite3.Connection, root: Path, report_id: int, *, dry_run: bool = False) -> dict:
    """Release one explicitly confirmed copy; retain metadata and a durable retryable cleanup intent."""
    database_path = next((row[2] for row in connection.execute("PRAGMA database_list") if row[1] == "main"), "")
    expected_root = Path(database_path).parent / "client-reports"
    if not database_path or root.is_symlink() or root.resolve() != expected_root.resolve():
        raise ReportConflict("清理目录不是此数据库的独立定稿报告目录")
    row = owned_report(connection, report_id)
    if row["completed_at"] is None or row["received_bytes"] != row["size_bytes"] or row["downloaded_at"] is None:
        raise ReportConflict("仅可清理已完整上传且已核对下载的报告副本")
    if row["cleaned_at"] is not None:
        return {"report_id": report_id, "cleaned_at": row["cleaned_at"], "deleted": 0, **({"dry_run": True} if dry_run else {})}
    path = file_path(root, report_id)
    if path.parent.is_symlink() or path.is_symlink():
        raise ReportConflict("报告副本路径无效")
    if path.exists() and not path.is_file():
        raise ReportConflict("报告副本不是普通文件")
    present = path.is_file()
    if not present and row["cleanup_requested_at"] is None:
        raise ReportNotFound("未找到可核对的原报告副本")
    if dry_run:
        return {"report_id": report_id, "cleaned_at": None, "deleted": 0, "dry_run": True}
    # Commit intent before crossing the file/SQLite boundary so a lost response or process exit is retryable.
    connection.execute("UPDATE client_reports SET cleanup_requested_at=COALESCE(cleanup_requested_at,?) WHERE id=?", (timestamp(), report_id))
    connection.commit()
    deleted = 0
    if present:
        try:
            path.unlink()
            deleted = 1
        except FileNotFoundError:
            pass  # Another explicit cleanup may have removed the same confirmed copy after intent committed.
    connection.execute("UPDATE client_reports SET cleaned_at=COALESCE(cleaned_at,?) WHERE id=?", (timestamp(), report_id))
    connection.commit()
    cleaned_at = connection.execute("SELECT cleaned_at FROM client_reports WHERE id=?", (report_id,)).fetchone()[0]
    return {"report_id": report_id, "cleaned_at": cleaned_at, "deleted": deleted}
