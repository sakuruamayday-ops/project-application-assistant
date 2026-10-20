"""Original files explicitly uploaded by client users; retained apart from reports and knowledge."""
from __future__ import annotations

import hashlib
import os
import sqlite3
from datetime import timezone
from pathlib import Path
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from app import client_reports
from app.client_reports import ReportChunk as AttachmentChunk


class AttachmentConflict(ValueError):
    """An upload request was reused with different metadata."""


class AttachmentNotFound(LookupError):
    """An original attachment is unavailable to this member."""


class AttachmentMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    filename: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(ge=0, le=2**53 - 1, strict=True)
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    uploaded_at: AwareDatetime
    client_version: str = Field(min_length=1, max_length=64)
    session_id: str | None = Field(default=None, min_length=1, max_length=200)
    task_title: str | None = Field(default=None, max_length=300)

    @field_validator("filename")
    @classmethod
    def basename_only(cls, value: str) -> str:
        if value in {".", ".."} or "/" in value or "\\" in value or any(ord(c) < 32 for c in value):
            raise ValueError("filename must be a display name without a local path")
        # User attachments follow the real upload entrypoints, not the final-report extension list.
        return value

    @field_validator("sha256")
    @classmethod
    def lowercase_digest(cls, value: str) -> str:
        return value.lower()

    @field_validator("session_id")
    @classmethod
    def session_identifier_only(cls, value: str | None) -> str | None:
        if value is not None and ("/" in value or "\\" in value or any(ord(c) < 32 for c in value)):
            raise ValueError("session_id must be an identifier without a local path")
        return value

    @model_validator(mode="after")
    def valid_empty_file(self) -> AttachmentMetadata:
        if self.size_bytes == 0 and self.sha256 != hashlib.sha256(b"").hexdigest():
            raise ValueError("an empty file requires its actual SHA-256")
        return self


def initialize(connection: sqlite3.Connection) -> None:
    connection.execute("""
        CREATE TABLE IF NOT EXISTS client_attachments (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            request_id TEXT NOT NULL,
            filename TEXT NOT NULL, size_bytes INTEGER NOT NULL, sha256 TEXT NOT NULL,
            uploaded_at TEXT NOT NULL, client_version TEXT NOT NULL,
            session_id TEXT, task_title TEXT,
            received_bytes INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL, completed_at TEXT,
            UNIQUE(user_id,request_id)
        )
    """)


def create_attachment(connection: sqlite3.Connection, root: Path, user_id: int, metadata: AttachmentMetadata) -> dict:
    values = metadata.model_dump(mode="json")
    values["uploaded_at"] = metadata.uploaded_at.astimezone(timezone.utc).isoformat()
    connection.execute("BEGIN IMMEDIATE")
    try:
        row = connection.execute(
            "SELECT * FROM client_attachments WHERE user_id=? AND request_id=?",
            (user_id, str(metadata.request_id)),
        ).fetchone()
        if row is not None:
            if any(row[key] != value for key, value in values.items()):
                raise AttachmentConflict("同一 request_id 的附件元数据不同，请为新上传使用新的 request_id")
        else:
            fields = ["user_id", *values, "created_at"]
            cursor = connection.execute(
                "INSERT INTO client_attachments(" + ",".join(fields) + ") VALUES (" + ",".join("?" for _ in fields) + ")",
                (user_id, *values.values(), client_reports.timestamp()),
            )
            row = connection.execute("SELECT * FROM client_attachments WHERE id=?", (cursor.lastrowid,)).fetchone()
        if metadata.size_bytes == 0 and row["completed_at"] is None:
            client_reports.write_file_chunk(root, row["id"], 0, row["sha256"], 0, b"")
            connection.execute("UPDATE client_attachments SET completed_at=? WHERE id=?", (client_reports.timestamp(), row["id"]))
            row = connection.execute("SELECT * FROM client_attachments WHERE id=?", (row["id"],)).fetchone()
        connection.commit()
        return {"attachment_id": row["id"], **client_reports.receipt(row)}
    except Exception:
        connection.rollback()
        raise


def owned_attachment(connection: sqlite3.Connection, attachment_id: int, user_id: int | None = None) -> sqlite3.Row:
    row = connection.execute("SELECT * FROM client_attachments WHERE id=?", (attachment_id,)).fetchone()
    if row is None or user_id is not None and row["user_id"] != user_id:
        raise AttachmentNotFound("附件不存在")
    return row


def receive_chunk(connection: sqlite3.Connection, root: Path, attachment_id: int,
                  user_id: int, chunk: AttachmentChunk) -> dict:
    data = client_reports.decode_file_chunk(chunk)
    connection.execute("BEGIN IMMEDIATE")
    try:
        row = owned_attachment(connection, attachment_id, user_id)
        if row["completed_at"] is not None or chunk.offset != row["received_bytes"]:
            connection.commit()
            return client_reports.receipt(row)
        received, mismatch = client_reports.write_file_chunk(
            root, attachment_id, row["size_bytes"], row["sha256"], chunk.offset, data,
        )
        complete = received == row["size_bytes"]
        connection.execute(
            "UPDATE client_attachments SET received_bytes=?,completed_at=? WHERE id=?",
            (received, client_reports.timestamp() if complete else None, attachment_id),
        )
        connection.commit()
        if mismatch:
            raise ValueError("附件 SHA-256 不匹配，已重置为 offset=0，请重传")
        return {"next_offset": received, "complete": complete}
    except Exception:
        connection.rollback()
        raise


def list_attachments(connection: sqlite3.Connection, *, user_id: int | None = None,
                     limit: int = 50, offset: int = 0) -> list[dict]:
    rows = connection.execute(
        "SELECT attachment.*,users.username AS member_username,COALESCE(NULLIF(users.real_name,''),users.username) AS member_name "
        "FROM client_attachments attachment JOIN users ON users.id=attachment.user_id"
        + (" WHERE attachment.user_id=?" if user_id is not None else "")
        + " ORDER BY attachment.id DESC LIMIT ? OFFSET ?",
        (*((user_id,) if user_id is not None else ()), limit, offset),
    ).fetchall()
    attachments = []
    for row in rows:
        attachment = dict(row)
        attachment["attachment_id"] = attachment.pop("id")
        attachments.append(attachment)
    return attachments


def completed_file(connection: sqlite3.Connection, root: Path, attachment_id: int,
                   user_id: int | None = None) -> tuple[sqlite3.Row, Path]:
    row = owned_attachment(connection, attachment_id, user_id)
    path = client_reports.file_path(root, attachment_id)
    if row["completed_at"] is None or root.is_symlink() or path.parent.is_symlink() or path.is_symlink() or not path.is_file():
        raise AttachmentNotFound("附件尚未收齐或文件不可用")
    with path.open("rb") as stream:
        if os.fstat(stream.fileno()).st_size != row["size_bytes"] or hashlib.file_digest(stream, "sha256").hexdigest() != row["sha256"]:
            raise ValueError("附件文件完整性校验失败")
    return row, path
