from __future__ import annotations

import hashlib
import html
import json
import os
import re
import secrets
import shutil
import sqlite3
import threading
import urllib.error
import urllib.request
import zipfile
from contextlib import closing
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Cookie, Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from markupsafe import Markup
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("JIAOTANG_DATA_DIR", BASE_DIR / "data"))
DATABASE_PATH = DATA_DIR / "knowledge.db"
INDEX_DIR = Path(
    os.environ.get(
        "JIAOTANG_INDEX_DIR",
        DATA_DIR / "knowledge-index",
    )
)
CONTENT_DATABASE_PATH = INDEX_DIR / "knowledge_content.sqlite3"
KNOWLEDGE_FILES_DIR = Path(os.environ.get("JIAOTANG_KNOWLEDGE_FILES_DIR", DATA_DIR / "knowledge-files"))
SKILL_RELEASE_DIR = Path(os.environ.get("JIAOTANG_SKILL_RELEASE_DIR", DATA_DIR / "skill-releases"))
INDEX_SNAPSHOT_DIR = Path(os.environ.get("JIAOTANG_INDEX_SNAPSHOT_DIR", DATA_DIR / "index-snapshots"))
MEMBER_COMPANY = os.environ.get("JIAOTANG_MEMBER_COMPANY", "共创集团").strip()
SESSION_COOKIE = "jiaotang_session"
SESSION_HOURS = int(os.environ.get("JIAOTANG_SESSION_HOURS", "12"))
REMEMBER_SESSION_DAYS = 7
SECURE_COOKIES = os.environ.get("JIAOTANG_SECURE_COOKIES", "true").lower() == "true"
HEALTH_STATUS_PATH = DATA_DIR / "health-status.json"
BACKUP_STATUS_PATH = DATA_DIR / "backup-status.json"
DEPLOYED_USER_GUIDE_PATH = BASE_DIR / "docs" / "user-guide" / "项目申报助手用户使用手册.md"
SOURCE_USER_GUIDE_PATH = BASE_DIR.parents[1] / "docs" / "user-guide" / "项目申报助手用户使用手册.md"
USER_GUIDE_PATH = Path(
    os.environ.get(
        "JIAOTANG_USER_GUIDE_PATH",
        DEPLOYED_USER_GUIDE_PATH if DEPLOYED_USER_GUIDE_PATH.is_file() else SOURCE_USER_GUIDE_PATH,
    )
)
AI_API_BASE = os.environ.get("JIAOTANG_AI_API_BASE", "").strip()
AI_API_KEY = os.environ.get("JIAOTANG_AI_API_KEY", "").strip()
AI_MODEL = os.environ.get("JIAOTANG_AI_MODEL", "").strip()
AI_TIMEOUT_SECONDS = int(os.environ.get("JIAOTANG_AI_TIMEOUT_SECONDS", "45"))


def render_guide_markdown(source: str) -> Markup:
    def inline(value: str) -> str:
        escaped = html.escape(value)
        escaped = re.sub(
            r"`(https?://[^`]+)`",
            lambda match: f'<a href="{match.group(1)}" rel="noreferrer">{match.group(1)}</a>',
            escaped,
        )
        escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
        return escaped

    output: list[str] = []
    paragraph: list[str] = []
    list_type: str | None = None
    code_lines: list[str] = []
    in_code = False

    def flush_paragraph() -> None:
        if paragraph:
            output.append(f"<p>{inline(' '.join(paragraph))}</p>")
            paragraph.clear()

    def close_list() -> None:
        nonlocal list_type
        if list_type:
            output.append(f"</{list_type}>")
            list_type = None

    for raw_line in source.splitlines():
        line = raw_line.rstrip()
        if line.startswith("```"):
            flush_paragraph()
            close_list()
            if in_code:
                output.append(f"<pre><code>{html.escape(chr(10).join(code_lines))}</code></pre>")
                code_lines.clear()
            in_code = not in_code
            continue
        if in_code:
            code_lines.append(line)
            continue
        if not line.strip():
            flush_paragraph()
            close_list()
            continue
        heading = re.match(r"^(#{1,4})\s+(.+)$", line)
        if heading:
            flush_paragraph()
            close_list()
            level = len(heading.group(1))
            output.append(f"<h{level}>{inline(heading.group(2))}</h{level}>")
            continue
        ordered = re.match(r"^\d+\.\s+(.+)$", line)
        unordered = re.match(r"^-\s+(.+)$", line)
        item = ordered or unordered
        if item:
            flush_paragraph()
            target = "ol" if ordered else "ul"
            if list_type != target:
                close_list()
                output.append(f"<{target}>")
                list_type = target
            output.append(f"<li>{inline(item.group(1))}</li>")
            continue
        close_list()
        paragraph.append(line.strip())

    flush_paragraph()
    close_list()
    if in_code:
        output.append(f"<pre><code>{html.escape(chr(10).join(code_lines))}</code></pre>")
    return Markup("\n".join(output))

password_hasher = PasswordHasher()
MIN_PASSWORD_LENGTH = 9
ACCOUNT_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{2,31}$")
REAL_NAME_PATTERN = re.compile(r"^[\u3400-\u4dbf\u4e00-\u9fff·]{2,20}$")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
public_host = os.environ.get("JIAOTANG_PUBLIC_HOST", "localhost").strip()
knowledge_mcp = FastMCP(
    "项目申报助手知识库",
    instructions="使用个人访问凭据检索团队知识库。先搜索，再按文档编号读取原文。",
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
    transport_security=TransportSecuritySettings(
        allowed_hosts=[public_host, f"{public_host}:443", "127.0.0.1:8100", "localhost:8100", "testserver"],
        allowed_origins=[f"https://{public_host}"],
    ),
)


@asynccontextmanager
async def lifespan(application: FastAPI):
    del application
    init_database()
    async with knowledge_mcp.session_manager.run():
        yield


app = FastAPI(title="项目申报助手知识库", docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=8, ge=1, le=20)


class SearchResult(BaseModel):
    document_id: int
    title: str
    excerpt: str
    source: str | None
    document_role: str
    index_layer: str = "content"
    updated_at: str


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]


class DocumentResponse(BaseModel):
    document_id: int
    title: str
    content: str
    source: str
    document_role: str
    updated_at: str


class UsageEndpoint(BaseModel):
    endpoint: str
    calls: int


class UsageCall(BaseModel):
    endpoint: str
    method: str
    called_at: str


class UsageResponse(BaseModel):
    total_calls: int
    calls_last_30_days: int
    by_endpoint: list[UsageEndpoint]
    recent_calls: list[UsageCall]


class SkillLatestResponse(BaseModel):
    available: bool
    version: str | None = None
    file_name: str | None = None
    sha256: str | None = None
    file_size: int | None = None
    release_notes: str | None = None
    published_at: str | None = None
    download_url: str | None = None


SUPPORTED_UPLOAD_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".doc",
    ".xlsx",
    ".xls",
    ".pptx",
    ".ppt",
    ".txt",
    ".md",
    ".html",
    ".htm",
    ".wps",
}
INDEX_UPDATE_LOCK = threading.Lock()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat()


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_account_name(value: str) -> str:
    normalized = value.strip().lower()
    if not ACCOUNT_NAME_PATTERN.fullmatch(normalized):
        raise ValueError("登录账号须使用3至32位英文字母，可包含数字、点、下划线或连字符。")
    return normalized


def normalize_real_name(value: str) -> str:
    normalized = value.strip()
    if (
        not REAL_NAME_PATTERN.fullmatch(normalized)
        or normalized.startswith("·")
        or normalized.endswith("·")
        or "··" in normalized
    ):
        raise ValueError("请输入中文真实姓名，少数民族姓名可使用间隔号。")
    return normalized


def read_status_file(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def database() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 10000")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def read_only_database(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise HTTPException(status_code=503, detail=f"知识库索引未就绪：{path.name}")
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection


def content_database() -> sqlite3.Connection:
    return read_only_database(CONTENT_DATABASE_PATH)


def fts_expression(query: str) -> str:
    terms = [term for term in re.split(r"\s+", query.strip()) if term]
    return " AND ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms)


def query_terms(query: str) -> list[str]:
    return [term for term in re.split(r"\s+", query.strip()) if term]


def pagination_window(current_page: int, total_pages: int) -> list[int | None]:
    visible = {1, total_pages}
    visible.update(range(max(1, current_page - 2), min(total_pages, current_page + 2) + 1))
    ordered = sorted(visible)
    result: list[int | None] = []
    previous = 0
    for page_number in ordered:
        if previous and page_number - previous > 1:
            result.append(None)
        result.append(page_number)
        previous = page_number
    return result


def company_verified(company_name: str) -> bool:
    return secrets.compare_digest(
        company_name.strip().encode("utf-8"), MEMBER_COMPANY.encode("utf-8")
    )


def safe_file_name(file_name: str) -> str:
    name = Path(file_name).name
    cleaned = re.sub(r"[^0-9A-Za-z._\-\u4e00-\u9fff（）()]+", "-", name).strip(".-")
    return cleaned or "upload.bin"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def save_upload(upload: UploadFile, directory: Path) -> tuple[Path, str, int]:
    directory.mkdir(parents=True, exist_ok=True)
    temporary = directory / f"upload-{secrets.token_hex(12)}.tmp"
    with temporary.open("wb") as target:
        shutil.copyfileobj(upload.file, target)
    digest = sha256_file(temporary)
    file_name = safe_file_name(upload.filename or "upload.bin")
    final_path = directory / f"{digest[:16]}-{file_name}"
    if final_path.exists():
        final_path = directory / f"{digest[:16]}-{secrets.token_hex(4)}-{file_name}"
    temporary.replace(final_path)
    return final_path, digest, final_path.stat().st_size


def knowledge_index_stats() -> dict[str, object]:
    if not CONTENT_DATABASE_PATH.is_file():
        return {"connected": False, "documents": 0, "characters": 0, "updated_at": None}
    try:
        with closing(content_database()) as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS documents, COALESCE(SUM(length(content)), 0) AS characters, MAX(updated_at) AS updated_at FROM documents"
            ).fetchone()
        return {
            "connected": True,
            "documents": int(row["documents"]),
            "characters": int(row["characters"]),
            "updated_at": row["updated_at"],
        }
    except (sqlite3.Error, HTTPException):
        return {"connected": False, "documents": 0, "characters": 0, "updated_at": None}


def snapshot_content_database(job_id: int | str) -> Path:
    if not CONTENT_DATABASE_PATH.is_file():
        raise RuntimeError("知识库全文索引不存在")
    INDEX_SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    snapshot = INDEX_SNAPSHOT_DIR / f"job-{job_id}-{utc_now().strftime('%Y%m%dT%H%M%SZ')}.sqlite3"
    with closing(sqlite3.connect(CONTENT_DATABASE_PATH)) as source:
        with closing(sqlite3.connect(snapshot)) as target:
            source.backup(target)
    return snapshot


def add_document_to_index(
    path: Path,
    digest: str,
    original_name: str,
    text: str,
    document_role: str,
    job_id: int,
) -> tuple[int, Path]:
    from scripts.build_knowledge_content_index import enterprise_mentions, iter_chunks

    snapshot = snapshot_content_database(job_id)
    temporary = CONTENT_DATABASE_PATH.with_name(
        f"{CONTENT_DATABASE_PATH.stem}.job-{job_id}.tmp.sqlite3"
    )
    shutil.copy2(CONTENT_DATABASE_PATH, temporary)
    try:
        with closing(sqlite3.connect(temporary)) as connection:
            existing = connection.execute(
                "SELECT id FROM documents WHERE sha256 = ? OR source_key = ?",
                (digest, digest),
            ).fetchone()
            if existing:
                return int(existing[0]), snapshot
            source = f"80_管理员增量上传/{path.name}"
            updated_at = isoformat(utc_now())
            cursor = connection.execute(
                """
                INSERT INTO documents(
                    source_key,title,content,source,cloud_path,document_role,
                    sensitivity,sha256,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    digest,
                    original_name,
                    text,
                    source,
                    source,
                    document_role,
                    "internal",
                    digest,
                    updated_at,
                ),
            )
            document_id = int(cursor.lastrowid)
            connection.execute(
                "INSERT INTO documents_fts(rowid,title,content,source,document_role) VALUES (?,?,?,?,?)",
                (document_id, original_name, text, source, document_role),
            )
            connection.execute(
                "INSERT INTO documents_fts_trigram(rowid,title,content,source,document_role) VALUES (?,?,?,?,?)",
                (document_id, original_name, text, source, document_role),
            )
            for chunk_number, chunk in iter_chunks(text):
                connection.execute(
                    "INSERT INTO document_chunks(document_id,chunk_number,content) VALUES (?,?,?)",
                    (document_id, chunk_number, chunk),
                )
                connection.execute(
                    "INSERT INTO document_chunks_fts(document_id,chunk_number,title,content,source) VALUES (?,?,?,?,?)",
                    (document_id, chunk_number, original_name, chunk, source),
                )
            for enterprise_name, sequence_no, context in enterprise_mentions(text):
                connection.execute(
                    "INSERT OR IGNORE INTO enterprise_mentions(document_id,enterprise_name,sequence_no,context) VALUES (?,?,?,?)",
                    (document_id, enterprise_name, sequence_no, context),
                )
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise RuntimeError(f"增量索引完整性检查失败：{integrity}")
            connection.commit()
        os.replace(temporary, CONTENT_DATABASE_PATH)
        return document_id, snapshot
    finally:
        if temporary.exists():
            failed_directory = INDEX_SNAPSHOT_DIR / "failed-builds"
            failed_directory.mkdir(parents=True, exist_ok=True)
            temporary.replace(failed_directory / temporary.name)


def restore_content_snapshot(snapshot: Path, job_id: int) -> None:
    if not snapshot.is_file():
        raise RuntimeError("回滚快照不存在")
    temporary = CONTENT_DATABASE_PATH.with_name(
        f"{CONTENT_DATABASE_PATH.stem}.rollback-{job_id}.tmp.sqlite3"
    )
    shutil.copy2(snapshot, temporary)
    with closing(sqlite3.connect(temporary)) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise RuntimeError(f"回滚快照完整性检查失败：{integrity}")
    os.replace(temporary, CONTENT_DATABASE_PATH)


def search_knowledge(query: str, limit: int = 8) -> dict[str, object]:
    normalized_query = query.strip()
    if not normalized_query:
        raise HTTPException(status_code=422, detail="检索词不能为空")
    bounded_limit = max(1, min(int(limit), 20))
    with closing(content_database()) as connection:
        rows = []
        try:
            rows = connection.execute(
                """
                SELECT documents.id, documents.title,
                       snippet(documents_fts_trigram, 1, '<mark>', '</mark>', '…', 36) AS excerpt,
                       documents.source, documents.document_role, documents.updated_at
                FROM documents_fts_trigram
                JOIN documents ON documents.id = documents_fts_trigram.rowid
                WHERE documents_fts_trigram MATCH ?
                ORDER BY bm25(documents_fts_trigram)
                LIMIT ?
                """,
                (fts_expression(normalized_query), bounded_limit),
            ).fetchall()
        except sqlite3.OperationalError:
            pass
        if not rows:
            conditions = []
            parameters: list[object] = []
            for term in query_terms(normalized_query):
                escaped = term.replace("%", "\\%").replace("_", "\\_")
                value = f"%{escaped}%"
                conditions.append(
                    "(title LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\' OR source LIKE ? ESCAPE '\\')"
                )
                parameters.extend((value, value, value))
            parameters.append(bounded_limit)
            rows = connection.execute(
                f"""
                SELECT id, title, substr(content, 1, 600) AS excerpt, source,
                       document_role, updated_at
                FROM documents
                WHERE {' AND '.join(conditions)}
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                parameters,
            ).fetchall()
    return {
        "query": normalized_query,
        "results": [
            {
                "document_id": int(row["id"]),
                "title": row["title"],
                "excerpt": row["excerpt"],
                "source": row["source"],
                "document_role": row["document_role"],
                "index_layer": "content",
                "updated_at": row["updated_at"],
            }
            for row in rows
        ],
    }


def assistant_chat_url() -> str:
    base = AI_API_BASE.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def answer_with_knowledge(question: str, results: list[dict[str, object]]) -> tuple[str, str]:
    clean_results = []
    for result in results:
        clean_results.append(
            {
                "title": str(result["title"]),
                "excerpt": re.sub(r"<[^>]+>", "", str(result["excerpt"])),
                "source": str(result.get("source") or ""),
            }
        )
    if not (AI_API_BASE and AI_API_KEY and AI_MODEL):
        if not clean_results:
            return "当前团队知识库未命中相关资料。请补充企业、地区、项目名称或年份后再试。", "knowledge-search"
        lines = ["当前以免费知识库检索模式返回最相关资料："]
        for index, result in enumerate(clean_results[:4], start=1):
            excerpt = result["excerpt"].strip().replace("\n", " ")
            lines.append(f"{index}. {result['title']}：{excerpt[:220]}")
        lines.append("需要形成正式结论时，请在 Agent 中调用项目申报助手，并核验原文件与当期官方通知。")
        return "\n".join(lines), "knowledge-search"

    context = "\n\n".join(
        f"资料{index}｜{result['title']}\n{result['excerpt']}\n来源：{result['source']}"
        for index, result in enumerate(clean_results[:5], start=1)
    )
    payload = {
        "model": AI_MODEL,
        "temperature": 0.2,
        "messages": [
            {
                "role": "system",
                "content": "你是项目申报助手网站答疑员。只依据提供的团队知识片段回答，先给结论，再给依据；资料不足时明确说明，不承诺企业一定符合或项目一定获批。",
            },
            {"role": "user", "content": f"问题：{question}\n\n团队知识片段：\n{context or '当前未命中资料'}"},
        ],
    }
    request = urllib.request.Request(
        assistant_chat_url(),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {AI_API_KEY}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=AI_TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode("utf-8"))
        return str(body["choices"][0]["message"]["content"]).strip(), "language-model"
    except (urllib.error.URLError, urllib.error.HTTPError, KeyError, IndexError, json.JSONDecodeError) as error:
        if clean_results:
            fallback, _ = answer_with_knowledge_without_model(clean_results)
            return f"大模型暂不可用，已切换知识库检索模式。\n\n{fallback}", "knowledge-search"
        raise HTTPException(status_code=502, detail=f"智能答疑服务暂不可用：{type(error).__name__}") from error


def answer_with_knowledge_without_model(results: list[dict[str, str]]) -> tuple[str, str]:
    lines = ["当前以免费知识库检索模式返回最相关资料："]
    for index, result in enumerate(results[:4], start=1):
        excerpt = result["excerpt"].strip().replace("\n", " ")
        lines.append(f"{index}. {result['title']}：{excerpt[:220]}")
    return "\n".join(lines), "knowledge-search"


def get_knowledge_document(document_id: int) -> dict[str, object]:
    with closing(content_database()) as connection:
        row = connection.execute(
            """
            SELECT id, title, content, source, document_role, updated_at
            FROM documents
            WHERE id = ?
            """,
            (document_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="知识库文件不存在")
    return {
        "document_id": int(row["id"]),
        "title": row["title"],
        "content": row["content"],
        "source": row["source"],
        "document_role": row["document_role"],
        "updated_at": row["updated_at"],
    }


def get_knowledge_document_payload(document_id: int) -> dict[str, object]:
    with closing(content_database()) as connection:
        row = connection.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="知识库文件不存在")
    return dict(row)


def move_document_index_to_trash(document_id: int, trash_id: int) -> Path:
    snapshot = snapshot_content_database(f"trash-{trash_id}")
    temporary = CONTENT_DATABASE_PATH.with_name(
        f"{CONTENT_DATABASE_PATH.stem}.trash-{trash_id}.tmp.sqlite3"
    )
    shutil.copy2(CONTENT_DATABASE_PATH, temporary)
    try:
        with closing(sqlite3.connect(temporary)) as connection:
            connection.row_factory = sqlite3.Row
            document = connection.execute(
                "SELECT * FROM documents WHERE id = ?", (document_id,)
            ).fetchone()
            if document is None:
                raise RuntimeError("知识库文件不存在")
            for table in ("documents_fts", "documents_fts_trigram"):
                connection.execute(
                    f"INSERT INTO {table}({table},rowid,title,content,source,document_role) VALUES ('delete',?,?,?,?,?)",
                    (
                        document_id,
                        document["title"],
                        document["content"],
                        document["source"],
                        document["document_role"],
                    ),
                )
            connection.execute("DELETE FROM document_chunks_fts WHERE document_id = ?", (document_id,))
            connection.execute("DELETE FROM document_chunks WHERE document_id = ?", (document_id,))
            connection.execute("DELETE FROM enterprise_mentions WHERE document_id = ?", (document_id,))
            connection.execute("DELETE FROM documents WHERE id = ?", (document_id,))
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise RuntimeError(f"知识库回收站完整性检查失败：{integrity}")
            connection.commit()
        os.replace(temporary, CONTENT_DATABASE_PATH)
        return snapshot
    finally:
        if temporary.exists():
            failed_directory = INDEX_SNAPSHOT_DIR / "failed-builds"
            failed_directory.mkdir(parents=True, exist_ok=True)
            temporary.replace(failed_directory / temporary.name)


def restore_document_index_from_trash(payload: dict[str, object], trash_id: int) -> Path:
    from scripts.build_knowledge_content_index import enterprise_mentions, iter_chunks

    document_id = int(payload["id"])
    snapshot = snapshot_content_database(f"trash-restore-{trash_id}")
    temporary = CONTENT_DATABASE_PATH.with_name(
        f"{CONTENT_DATABASE_PATH.stem}.trash-restore-{trash_id}.tmp.sqlite3"
    )
    shutil.copy2(CONTENT_DATABASE_PATH, temporary)
    try:
        with closing(sqlite3.connect(temporary)) as connection:
            if connection.execute(
                "SELECT 1 FROM documents WHERE id = ? OR source_key = ?",
                (document_id, payload["source_key"]),
            ).fetchone():
                raise RuntimeError("原编号或来源键已被占用，无法恢复")
            columns = (
                "id", "source_key", "title", "content", "source", "cloud_path",
                "document_role", "sensitivity", "sha256", "updated_at",
            )
            connection.execute(
                f"INSERT INTO documents({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                tuple(payload[column] for column in columns),
            )
            for table in ("documents_fts", "documents_fts_trigram"):
                connection.execute(
                    f"INSERT INTO {table}(rowid,title,content,source,document_role) VALUES (?,?,?,?,?)",
                    (
                        document_id,
                        payload["title"],
                        payload["content"],
                        payload["source"],
                        payload["document_role"],
                    ),
                )
            for chunk_number, chunk in iter_chunks(str(payload["content"])):
                connection.execute(
                    "INSERT INTO document_chunks(document_id,chunk_number,content) VALUES (?,?,?)",
                    (document_id, chunk_number, chunk),
                )
                connection.execute(
                    "INSERT INTO document_chunks_fts(document_id,chunk_number,title,content,source) VALUES (?,?,?,?,?)",
                    (document_id, chunk_number, payload["title"], chunk, payload["source"]),
                )
            for enterprise_name, sequence_no, context in enterprise_mentions(str(payload["content"])):
                connection.execute(
                    "INSERT OR IGNORE INTO enterprise_mentions(document_id,enterprise_name,sequence_no,context) VALUES (?,?,?,?)",
                    (document_id, enterprise_name, sequence_no, context),
                )
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise RuntimeError(f"知识库恢复完整性检查失败：{integrity}")
            connection.commit()
        os.replace(temporary, CONTENT_DATABASE_PATH)
        return snapshot
    finally:
        if temporary.exists():
            failed_directory = INDEX_SNAPSHOT_DIR / "failed-builds"
            failed_directory.mkdir(parents=True, exist_ok=True)
            temporary.replace(failed_directory / temporary.name)


def update_document_index(
    document_id: int,
    title: str,
    content: str,
    source: str,
    document_role: str,
    revision_id: int,
) -> Path:
    from scripts.build_knowledge_content_index import enterprise_mentions, iter_chunks

    snapshot = snapshot_content_database(f"revision-{revision_id}")
    temporary = CONTENT_DATABASE_PATH.with_name(
        f"{CONTENT_DATABASE_PATH.stem}.revision-{revision_id}.tmp.sqlite3"
    )
    shutil.copy2(CONTENT_DATABASE_PATH, temporary)
    try:
        with closing(sqlite3.connect(temporary)) as connection:
            connection.row_factory = sqlite3.Row
            old = connection.execute(
                "SELECT title, content, source, document_role FROM documents WHERE id = ?",
                (document_id,),
            ).fetchone()
            if old is None:
                raise RuntimeError("知识库文件不存在")
            for table in ("documents_fts", "documents_fts_trigram"):
                connection.execute(
                    f"INSERT INTO {table}({table},rowid,title,content,source,document_role) VALUES ('delete',?,?,?,?,?)",
                    (document_id, old["title"], old["content"], old["source"], old["document_role"]),
                )
            connection.execute(
                """
                UPDATE documents
                SET title = ?, content = ?, source = ?, document_role = ?, updated_at = ?
                WHERE id = ?
                """,
                (title, content, source, document_role, isoformat(utc_now()), document_id),
            )
            for table in ("documents_fts", "documents_fts_trigram"):
                connection.execute(
                    f"INSERT INTO {table}(rowid,title,content,source,document_role) VALUES (?,?,?,?,?)",
                    (document_id, title, content, source, document_role),
                )
            connection.execute("DELETE FROM document_chunks_fts WHERE document_id = ?", (document_id,))
            connection.execute("DELETE FROM document_chunks WHERE document_id = ?", (document_id,))
            connection.execute("DELETE FROM enterprise_mentions WHERE document_id = ?", (document_id,))
            for chunk_number, chunk in iter_chunks(content):
                connection.execute(
                    "INSERT INTO document_chunks(document_id,chunk_number,content) VALUES (?,?,?)",
                    (document_id, chunk_number, chunk),
                )
                connection.execute(
                    "INSERT INTO document_chunks_fts(document_id,chunk_number,title,content,source) VALUES (?,?,?,?,?)",
                    (document_id, chunk_number, title, chunk, source),
                )
            for enterprise_name, sequence_no, context in enterprise_mentions(content):
                connection.execute(
                    "INSERT OR IGNORE INTO enterprise_mentions(document_id,enterprise_name,sequence_no,context) VALUES (?,?,?,?)",
                    (document_id, enterprise_name, sequence_no, context),
                )
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise RuntimeError(f"知识库修订完整性检查失败：{integrity}")
            connection.commit()
        os.replace(temporary, CONTENT_DATABASE_PATH)
        return snapshot
    finally:
        if temporary.exists():
            failed_directory = INDEX_SNAPSHOT_DIR / "failed-builds"
            failed_directory.mkdir(parents=True, exist_ok=True)
            temporary.replace(failed_directory / temporary.name)


def init_database() -> None:
    with closing(database()) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                company_name TEXT NOT NULL DEFAULT '共创集团',
                is_admin INTEGER NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                csrf_token TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS device_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                label TEXT NOT NULL,
                token_prefix TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                last_used_at TEXT,
                revoked_at TEXT
            );

            CREATE TABLE IF NOT EXISTS api_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                device_token_id INTEGER NOT NULL REFERENCES device_tokens(id) ON DELETE CASCADE,
                endpoint TEXT NOT NULL,
                method TEXT NOT NULL,
                called_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS api_usage_user_time_idx
            ON api_usage(user_id, called_at DESC);

            CREATE TABLE IF NOT EXISTS skill_releases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version TEXT NOT NULL UNIQUE,
                file_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                release_notes TEXT NOT NULL,
                published_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS knowledge_update_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_name TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                status TEXT NOT NULL,
                extraction_status TEXT,
                text_characters INTEGER NOT NULL DEFAULT 0,
                document_id INTEGER,
                snapshot_path TEXT,
                error_message TEXT,
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL,
                completed_at TEXT,
                rolled_back_at TEXT
            );

            CREATE INDEX IF NOT EXISTS knowledge_update_jobs_time_idx
            ON knowledge_update_jobs(created_at DESC);

            CREATE TABLE IF NOT EXISTS knowledge_document_revisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                old_payload TEXT NOT NULL,
                new_payload TEXT NOT NULL,
                snapshot_path TEXT,
                changed_by INTEGER NOT NULL REFERENCES users(id),
                changed_at TEXT NOT NULL,
                rolled_back_at TEXT
            );

            CREATE INDEX IF NOT EXISTS knowledge_document_revisions_time_idx
            ON knowledge_document_revisions(changed_at DESC);

            CREATE TABLE IF NOT EXISTS knowledge_document_trash (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                document_payload TEXT NOT NULL,
                snapshot_path TEXT,
                status TEXT NOT NULL DEFAULT 'processing',
                error_message TEXT,
                deleted_by INTEGER NOT NULL REFERENCES users(id),
                deleted_at TEXT NOT NULL,
                restored_at TEXT
            );

            CREATE INDEX IF NOT EXISTS knowledge_document_trash_time_idx
            ON knowledge_document_trash(deleted_at DESC);

            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_key TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                source TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
                title,
                content,
                content='documents',
                content_rowid='id',
                tokenize='unicode61'
            );

            CREATE TRIGGER IF NOT EXISTS documents_ai AFTER INSERT ON documents BEGIN
                INSERT INTO documents_fts(rowid, title, content)
                VALUES (new.id, new.title, new.content);
            END;

            CREATE TRIGGER IF NOT EXISTS documents_ad AFTER DELETE ON documents BEGIN
                INSERT INTO documents_fts(documents_fts, rowid, title, content)
                VALUES ('delete', old.id, old.title, old.content);
            END;

            CREATE TRIGGER IF NOT EXISTS documents_au AFTER UPDATE ON documents BEGIN
                INSERT INTO documents_fts(documents_fts, rowid, title, content)
                VALUES ('delete', old.id, old.title, old.content);
                INSERT INTO documents_fts(rowid, title, content)
                VALUES (new.id, new.title, new.content);
            END;
            """
        )
        user_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(users)").fetchall()
        }
        if "company_name" not in user_columns:
            connection.execute(
                "ALTER TABLE users ADD COLUMN company_name TEXT NOT NULL DEFAULT '共创集团'"
            )
        connection.commit()


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if SECURE_COOKIES:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


def user_count() -> int:
    with closing(database()) as connection:
        return int(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0])


def session_user(session_token: str | None) -> tuple[sqlite3.Row, sqlite3.Row] | None:
    if not session_token:
        return None
    with closing(database()) as connection:
        row = connection.execute(
            """
            SELECT users.*, sessions.csrf_token, sessions.expires_at
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token_hash = ? AND users.active = 1
            """,
            (token_hash(session_token),),
        ).fetchone()
        if row is None or datetime.fromisoformat(row["expires_at"]) <= utc_now():
            return None
        return row, row


def require_web_user(
    jiaotang_session: Annotated[str | None, Cookie()] = None,
) -> sqlite3.Row:
    result = session_user(jiaotang_session)
    if result is None:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})
    return result[0]


def authenticate_api_token(authorization: str | None, endpoint: str, method: str) -> sqlite3.Row:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="缺少用户访问凭据")
    raw_token = authorization.removeprefix("Bearer ").strip()
    with closing(database()) as connection:
        row = connection.execute(
            """
            SELECT users.id, users.username, device_tokens.id AS device_token_id
            FROM device_tokens
            JOIN users ON users.id = device_tokens.user_id
            WHERE device_tokens.token_hash = ?
              AND device_tokens.revoked_at IS NULL
              AND users.active = 1
            """,
            (token_hash(raw_token),),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=401, detail="用户访问凭据无效或已吊销")
        connection.execute(
            "UPDATE device_tokens SET last_used_at = ? WHERE id = ?",
            (isoformat(utc_now()), row["device_token_id"]),
        )
        connection.execute(
            """
            INSERT INTO api_usage(user_id, device_token_id, endpoint, method, called_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                row["id"],
                row["device_token_id"],
                endpoint,
                method,
                isoformat(utc_now()),
            ),
        )
        connection.commit()
        return row


def require_api_user(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> sqlite3.Row:
    return authenticate_api_token(authorization, request.url.path, request.method)


class MCPBearerMiddleware:
    def __init__(self, application):
        self.application = application

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.application(scope, receive, send)
            return
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        try:
            authenticate_api_token(
                headers.get("authorization"),
                "/mcp",
                scope.get("method", "POST"),
            )
        except HTTPException as error:
            response = JSONResponse({"detail": error.detail}, status_code=error.status_code)
            await response(scope, receive, send)
            return
        await self.application(scope, receive, send)


def validate_csrf(user: sqlite3.Row, supplied: str) -> None:
    if not secrets.compare_digest(user["csrf_token"], supplied):
        raise HTTPException(status_code=403, detail="请求校验失败")


def require_admin(user: sqlite3.Row) -> None:
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="仅管理员可执行此操作")


def portal_payload(
    request: Request,
    user: sqlite3.Row,
    new_token: str | None = None,
    message: str | None = None,
    error: str | None = None,
) -> dict[str, object]:
    with closing(database()) as connection:
        device_tokens = connection.execute(
            """
            SELECT device_tokens.id, device_tokens.label, device_tokens.token_prefix,
                   device_tokens.created_at, device_tokens.last_used_at,
                   device_tokens.revoked_at, COUNT(api_usage.id) AS call_count
            FROM device_tokens
            LEFT JOIN api_usage ON api_usage.device_token_id = device_tokens.id
            WHERE device_tokens.user_id = ?
            GROUP BY device_tokens.id
            ORDER BY device_tokens.id DESC
            """,
            (user["id"],),
        ).fetchall()
        recent_calls = connection.execute(
            """
            SELECT api_usage.endpoint, api_usage.method, api_usage.called_at,
                   device_tokens.label
            FROM api_usage
            JOIN device_tokens ON device_tokens.id = api_usage.device_token_id
            WHERE api_usage.user_id = ?
            ORDER BY api_usage.id DESC
            LIMIT 12
            """,
            (user["id"],),
        ).fetchall()
        usage_total = int(
            connection.execute(
                "SELECT COUNT(*) FROM api_usage WHERE user_id = ?", (user["id"],)
            ).fetchone()[0]
        )
        users = []
        update_jobs = []
        releases = []
        admin_health: dict[str, object] = {}
        if user["is_admin"]:
            users = connection.execute(
                "SELECT id, username, company_name, is_admin, active, created_at FROM users ORDER BY id"
            ).fetchall()
            update_jobs = connection.execute(
                """
                SELECT id, original_name, status, extraction_status, text_characters,
                       document_id, error_message, created_at, completed_at,
                       rolled_back_at, snapshot_path
                FROM knowledge_update_jobs
                ORDER BY id DESC
                LIMIT 20
                """
            ).fetchall()
            releases = connection.execute(
                """
                SELECT id, version, file_name, sha256, release_notes, published_at
                FROM skill_releases
                ORDER BY published_at DESC, id DESC
                LIMIT 20
                """
            ).fetchall()
            since_24_hours = isoformat(utc_now() - timedelta(hours=24))
            admin_health = {
                "active_users": int(
                    connection.execute("SELECT COUNT(*) FROM users WHERE active = 1").fetchone()[0]
                ),
                "active_tokens": int(
                    connection.execute(
                        "SELECT COUNT(*) FROM device_tokens WHERE revoked_at IS NULL"
                    ).fetchone()[0]
                ),
                "calls_24h": int(
                    connection.execute(
                        "SELECT COUNT(*) FROM api_usage WHERE called_at >= ?", (since_24_hours,)
                    ).fetchone()[0]
                ),
                "failed_updates": int(
                    connection.execute(
                        "SELECT COUNT(*) FROM knowledge_update_jobs WHERE status = 'failed'"
                    ).fetchone()[0]
                ),
                "runtime": read_status_file(HEALTH_STATUS_PATH),
                "backup": read_status_file(BACKUP_STATUS_PATH),
            }
        latest_release = connection.execute(
            """
            SELECT id, version, file_name, sha256, release_notes, published_at
            FROM skill_releases
            ORDER BY published_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
    return {
        "request": request,
        "user": user,
        "device_tokens": device_tokens,
        "recent_calls": recent_calls,
        "usage_total": usage_total,
        "users": users,
        "update_jobs": update_jobs,
        "releases": releases,
        "latest_release": latest_release,
        "knowledge_stats": knowledge_index_stats(),
        "new_token": new_token,
        "message": message,
        "error": error,
        "admin_health": admin_health,
        "assistant_mode": "大模型增强" if AI_API_BASE and AI_API_KEY and AI_MODEL else "免费知识检索",
        "public_endpoint": str(request.base_url).rstrip("/"),
    }


@app.get("/health")
def health() -> dict[str, object]:
    index = knowledge_index_stats()
    database_ready = DATABASE_PATH.is_file()
    status_value = "ok" if database_ready and index["connected"] else "degraded"
    return {
        "status": status_value,
        "database": database_ready,
        "index": index,
    }


@app.get("/")
def home():
    return RedirectResponse("/login", status_code=303)


@app.get("/guide", response_class=HTMLResponse)
def user_guide(request: Request):
    if not USER_GUIDE_PATH.is_file():
        raise HTTPException(status_code=503, detail="用户使用手册暂不可用")
    source = USER_GUIDE_PATH.read_text(encoding="utf-8")
    return templates.TemplateResponse(
        request,
        "user_guide.html",
        {"guide_html": render_guide_markdown(source)},
    )


@app.get("/setup", response_class=HTMLResponse)
def setup_page(request: Request):
    if user_count() > 0:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(request, "setup.html", {"error": None})


@app.post("/setup", response_class=HTMLResponse)
def setup_submit(
    request: Request,
    setup_key: Annotated[str, Form()],
    username: Annotated[str, Form(min_length=3, max_length=64)],
    password: Annotated[str, Form(min_length=MIN_PASSWORD_LENGTH, max_length=256)],
):
    expected_key = os.environ.get("JIAOTANG_SETUP_KEY")
    if user_count() > 0:
        return RedirectResponse("/login", status_code=303)
    if not expected_key or not secrets.compare_digest(setup_key, expected_key):
        return templates.TemplateResponse(
            request, "setup.html", {"error": "初始化密钥不正确"}, status_code=403
        )
    try:
        normalized_username = normalize_account_name(username)
    except ValueError as exc:
        return templates.TemplateResponse(
            request, "setup.html", {"error": str(exc)}, status_code=400
        )
    with closing(database()) as connection:
        connection.execute(
            "INSERT INTO users(username, password_hash, is_admin, created_at) VALUES (?, ?, 1, ?)",
            (normalized_username, password_hasher.hash(password), isoformat(utc_now())),
        )
        connection.commit()
    return RedirectResponse("/login?initialized=1", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, initialized: int = 0, registered: int = 0):
    if user_count() == 0:
        return RedirectResponse("/setup", status_code=303)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"error": None, "initialized": initialized == 1, "registered": registered == 1},
    )


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    if user_count() == 0:
        return RedirectResponse("/setup", status_code=303)
    return templates.TemplateResponse(request, "register.html", {"error": None})


@app.post("/register", response_class=HTMLResponse)
def register_submit(
    request: Request,
    username: Annotated[str, Form(min_length=3, max_length=64)],
    company_name: Annotated[str, Form(min_length=2, max_length=100)],
    password: Annotated[str, Form(min_length=MIN_PASSWORD_LENGTH, max_length=256)],
    confirm_password: Annotated[str, Form(min_length=MIN_PASSWORD_LENGTH, max_length=256)],
):
    try:
        normalized_username = normalize_account_name(username)
    except ValueError as exc:
        return templates.TemplateResponse(
            request,
            "register.html",
            {"error": str(exc)},
            status_code=400,
        )
    if not company_verified(company_name):
        return templates.TemplateResponse(
            request,
            "register.html",
            {"error": "公司名称验证未通过，请填写完整公司名称。"},
            status_code=403,
        )
    if password != confirm_password:
        return templates.TemplateResponse(
            request,
            "register.html",
            {"error": "两次输入的密码不一致。"},
            status_code=400,
        )
    try:
        with closing(database()) as connection:
            connection.execute(
                """
                INSERT INTO users(username, password_hash, company_name, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    normalized_username,
                    password_hasher.hash(password),
                    MEMBER_COMPANY,
                    isoformat(utc_now()),
                ),
            )
            connection.commit()
    except sqlite3.IntegrityError:
        return templates.TemplateResponse(
            request,
            "register.html",
            {"error": "该用户名称已经注册。"},
            status_code=409,
        )
    return RedirectResponse("/login?registered=1", status_code=303)


@app.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    remember_me: Annotated[str | None, Form()] = None,
):
    with closing(database()) as connection:
        user = connection.execute(
            "SELECT * FROM users WHERE username = ? AND active = 1",
            (username.strip().lower(),),
        ).fetchone()
        valid = False
        if user is not None:
            try:
                valid = password_hasher.verify(user["password_hash"], password)
            except (VerifyMismatchError, InvalidHashError):
                valid = False
        if not valid:
            return templates.TemplateResponse(
                request,
                "login.html",
                {"error": "用户名称或密码错误", "initialized": False, "registered": False},
                status_code=401,
            )
        raw_session = secrets.token_urlsafe(48)
        csrf_token = secrets.token_urlsafe(32)
        created_at = utc_now()
        session_duration = (
            timedelta(days=REMEMBER_SESSION_DAYS)
            if remember_me == "7_days"
            else timedelta(hours=SESSION_HOURS)
        )
        connection.execute(
            "INSERT INTO sessions(token_hash, user_id, csrf_token, expires_at, created_at) VALUES (?, ?, ?, ?, ?)",
            (
                token_hash(raw_session),
                user["id"],
                csrf_token,
                isoformat(created_at + session_duration),
                isoformat(created_at),
            ),
        )
        connection.commit()
    response = RedirectResponse("/portal", status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        raw_session,
        httponly=True,
        secure=SECURE_COOKIES,
        samesite="strict",
        max_age=int(session_duration.total_seconds()),
    )
    return response


@app.post("/logout")
def logout(
    csrf_token: Annotated[str, Form()],
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
    jiaotang_session: Annotated[str | None, Cookie()] = None,
):
    validate_csrf(user, csrf_token)
    if jiaotang_session:
        with closing(database()) as connection:
            connection.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(jiaotang_session),))
            connection.commit()
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response


@app.get("/portal", response_class=HTMLResponse)
def portal(request: Request, user: Annotated[sqlite3.Row, Depends(require_web_user)]):
    return templates.TemplateResponse(request, "portal.html", portal_payload(request, user))


@app.post("/assistant/answer")
def assistant_answer(
    question: Annotated[str, Form(min_length=2, max_length=500)],
    csrf_token: Annotated[str, Form()],
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
):
    validate_csrf(user, csrf_token)
    search_result = search_knowledge(question, 5)
    answer, mode = answer_with_knowledge(question, search_result["results"])
    return JSONResponse(
        {
            "answer": answer,
            "mode": mode,
            "sources": [
                {
                    "document_id": item["document_id"],
                    "title": item["title"],
                    "source": item["source"],
                }
                for item in search_result["results"]
            ],
        }
    )


@app.get("/admin/health/{section}", response_class=HTMLResponse)
def admin_health_detail(
    request: Request,
    section: str,
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
):
    require_admin(user)
    runtime = read_status_file(HEALTH_STATUS_PATH)
    backup = read_status_file(BACKUP_STATUS_PATH)
    index = knowledge_index_stats()
    with closing(database()) as connection:
        active_users = int(connection.execute("SELECT COUNT(*) FROM users WHERE active = 1").fetchone()[0])
        active_tokens = int(
            connection.execute("SELECT COUNT(*) FROM device_tokens WHERE revoked_at IS NULL").fetchone()[0]
        )
        recent_calls = connection.execute(
            """
            SELECT api_usage.endpoint, api_usage.method, api_usage.called_at,
                   users.username, device_tokens.label
            FROM api_usage
            JOIN users ON users.id = api_usage.user_id
            JOIN device_tokens ON device_tokens.id = api_usage.device_token_id
            ORDER BY api_usage.id DESC LIMIT 30
            """
        ).fetchall()
        failed_updates = connection.execute(
            """
            SELECT id, original_name, status, error_message, created_at, completed_at
            FROM knowledge_update_jobs WHERE status = 'failed'
            ORDER BY id DESC LIMIT 30
            """
        ).fetchall()
        access_users = connection.execute(
            """
            SELECT users.id, users.username, users.company_name, users.is_admin, users.active,
                   users.created_at,
                   COUNT(DISTINCT device_tokens.id) AS token_count,
                   COUNT(DISTINCT CASE WHEN device_tokens.revoked_at IS NULL THEN device_tokens.id END) AS active_token_count,
                   COUNT(DISTINCT CASE WHEN device_tokens.revoked_at IS NOT NULL THEN device_tokens.id END) AS revoked_token_count,
                   COUNT(api_usage.id) AS call_count,
                   MAX(device_tokens.last_used_at) AS last_used_at
            FROM users
            LEFT JOIN device_tokens ON device_tokens.user_id = users.id
            LEFT JOIN api_usage ON api_usage.device_token_id = device_tokens.id
            GROUP BY users.id
            ORDER BY users.active DESC, users.is_admin DESC, users.id
            """
        ).fetchall()
        access_tokens = connection.execute(
            """
            SELECT device_tokens.id, users.username, device_tokens.label,
                   device_tokens.token_prefix, device_tokens.created_at,
                   device_tokens.last_used_at, device_tokens.revoked_at,
                   COUNT(api_usage.id) AS call_count
            FROM device_tokens
            JOIN users ON users.id = device_tokens.user_id
            LEFT JOIN api_usage ON api_usage.device_token_id = device_tokens.id
            GROUP BY device_tokens.id
            ORDER BY device_tokens.id DESC
            LIMIT 100
            """
        ).fetchall()
    sections = {
        "runtime": ("应用服务", [("状态", runtime.get("status", "待采集")), ("检查时间", runtime.get("checked_at", "待采集")), ("公开地址", os.environ.get("JIAOTANG_PUBLIC_HOST", "未配置"))]),
        "index": ("全文索引", [("连接状态", "已连接" if index["connected"] else "未连接"), ("全文资料", index["documents"]), ("文本字符", index["characters"]), ("索引更新时间", index["updated_at"] or "待采集")]),
        "backup": ("最近备份", [("状态", backup.get("status", "待采集")), ("完成时间", backup.get("completed_at", "待采集")), ("备份位置", backup.get("backup_path", "由服务器备份任务管理"))]),
        "certificate": ("HTTPS 证书", [("证书状态", runtime.get("certificate_status", "待采集")), ("到期时间", runtime.get("certificate_expires", "待采集")), ("域名", os.environ.get("JIAOTANG_PUBLIC_HOST", "未配置"))]),
        "disk": ("磁盘使用", [("使用率", runtime.get("disk_percent", "待采集")), ("检查时间", runtime.get("checked_at", "待采集")), ("数据目录", str(DATA_DIR))]),
        "access": ("用户与凭据", [("有效用户", active_users), ("有效 Token", active_tokens), ("权限模式", "统一知识权限")]),
        "calls": ("调用记录", [("最近记录", len(recent_calls)), ("接口范围", "REST API 与 MCP")]),
        "updates": ("失败更新", [("待处理失败", len(failed_updates)), ("回滚机制", "成功更新均保留快照")]),
    }
    if section not in sections:
        raise HTTPException(status_code=404, detail="健康详情不存在")
    title, details = sections[section]
    return templates.TemplateResponse(
        request,
        "admin_health_detail.html",
        {
            "user": user,
            "section": section,
            "title": title,
            "details": details,
            "recent_calls": recent_calls if section == "calls" else [],
            "failed_updates": failed_updates if section == "updates" else [],
            "access_users": access_users if section == "access" else [],
            "access_tokens": access_tokens if section == "access" else [],
        },
    )


@app.get("/admin/knowledge", response_class=HTMLResponse)
def admin_knowledge(
    request: Request,
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
    query: str = "",
    document_role: str = "",
    page: int = 1,
):
    require_admin(user)
    page = max(1, page)
    page_size = 30
    conditions = ["1 = 1"]
    parameters: list[object] = []
    if query.strip():
        escaped_query = query.strip().replace("%", "\\%").replace("_", "\\_")
        value = f"%{escaped_query}%"
        conditions.append("(title LIKE ? ESCAPE '\\' OR source LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\')")
        parameters.extend((value, value, value))
    if document_role.strip():
        conditions.append("document_role = ?")
        parameters.append(document_role.strip())
    where = " AND ".join(conditions)
    with closing(content_database()) as connection:
        total = int(connection.execute(f"SELECT COUNT(*) FROM documents WHERE {where}", parameters).fetchone()[0])
        rows = connection.execute(
            f"""
            SELECT id, title, source, document_role, updated_at, length(content) AS characters
            FROM documents WHERE {where}
            ORDER BY id ASC LIMIT ? OFFSET ?
            """,
            [*parameters, page_size, (page - 1) * page_size],
        ).fetchall()
        roles = connection.execute(
            "SELECT document_role, COUNT(*) AS count FROM documents GROUP BY document_role ORDER BY document_role"
        ).fetchall()
    with closing(database()) as connection:
        revisions = connection.execute(
            """
            SELECT knowledge_document_revisions.id, knowledge_document_revisions.document_id,
                   knowledge_document_revisions.changed_at, knowledge_document_revisions.rolled_back_at,
                   users.username
            FROM knowledge_document_revisions
            JOIN users ON users.id = knowledge_document_revisions.changed_by
            ORDER BY knowledge_document_revisions.id DESC LIMIT 20
            """
        ).fetchall()
        trash_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM knowledge_document_trash WHERE status = 'trashed' AND restored_at IS NULL"
            ).fetchone()[0]
        )
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, total_pages)
    if rows == [] and total and page > 1:
        return RedirectResponse(
            f"/admin/knowledge?query={query}&document_role={document_role}&page={total_pages}",
            status_code=303,
        )
    return templates.TemplateResponse(
        request,
        "admin_knowledge.html",
        {
            "user": user,
            "documents": rows,
            "roles": roles,
            "revisions": revisions,
            "query": query,
            "selected_role": document_role,
            "page": page,
            "pages": total_pages,
            "page_links": pagination_window(page, total_pages),
            "total": total,
            "trash_count": trash_count,
        },
    )


@app.get("/admin/knowledge-trash", response_class=HTMLResponse)
def admin_knowledge_trash(
    request: Request,
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
):
    require_admin(user)
    with closing(database()) as connection:
        rows = connection.execute(
            """
            SELECT knowledge_document_trash.*, users.username
            FROM knowledge_document_trash
            JOIN users ON users.id = knowledge_document_trash.deleted_by
            ORDER BY knowledge_document_trash.id DESC
            """
        ).fetchall()
    trash_items = []
    for row in rows:
        payload = json.loads(row["document_payload"])
        trash_items.append({**dict(row), "title": payload.get("title", "未命名资料")})
    return templates.TemplateResponse(
        request,
        "admin_knowledge_trash.html",
        {"user": user, "trash_items": trash_items},
    )


@app.get("/admin/knowledge/{document_id}", response_class=HTMLResponse)
def admin_knowledge_edit(
    request: Request,
    document_id: int,
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
):
    require_admin(user)
    document = get_knowledge_document(document_id)
    return templates.TemplateResponse(
        request,
        "admin_knowledge_edit.html",
        {"user": user, "document": document},
    )


@app.get("/admin/knowledge/{document_id}/trash", response_class=HTMLResponse)
def admin_knowledge_trash_confirm(
    request: Request,
    document_id: int,
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
):
    require_admin(user)
    document = get_knowledge_document(document_id)
    return templates.TemplateResponse(
        request,
        "admin_knowledge_trash_confirm.html",
        {"user": user, "document": document},
    )


@app.post("/admin/knowledge/{document_id}/trash")
def admin_knowledge_move_to_trash(
    document_id: int,
    csrf_token: Annotated[str, Form()],
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
):
    validate_csrf(user, csrf_token)
    require_admin(user)
    payload = get_knowledge_document_payload(document_id)
    with closing(database()) as connection:
        cursor = connection.execute(
            """
            INSERT INTO knowledge_document_trash(
                document_id, document_payload, status, deleted_by, deleted_at
            ) VALUES (?, ?, 'processing', ?, ?)
            """,
            (document_id, json.dumps(payload, ensure_ascii=False), user["id"], isoformat(utc_now())),
        )
        trash_id = int(cursor.lastrowid)
        connection.commit()
    try:
        with INDEX_UPDATE_LOCK:
            snapshot = move_document_index_to_trash(document_id, trash_id)
        with closing(database()) as connection:
            connection.execute(
                "UPDATE knowledge_document_trash SET status = 'trashed', snapshot_path = ? WHERE id = ?",
                (str(snapshot), trash_id),
            )
            connection.commit()
    except Exception as error:
        with closing(database()) as connection:
            connection.execute(
                "UPDATE knowledge_document_trash SET status = 'failed', error_message = ? WHERE id = ?",
                (str(error)[:2000], trash_id),
            )
            connection.commit()
        raise
    return RedirectResponse("/admin/knowledge-trash", status_code=303)


@app.post("/admin/knowledge-trash/{trash_id}/restore")
def admin_knowledge_restore_from_trash(
    trash_id: int,
    csrf_token: Annotated[str, Form()],
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
):
    validate_csrf(user, csrf_token)
    require_admin(user)
    with closing(database()) as connection:
        item = connection.execute(
            "SELECT * FROM knowledge_document_trash WHERE id = ?", (trash_id,)
        ).fetchone()
    if item is None:
        raise HTTPException(status_code=404, detail="回收站记录不存在")
    if item["status"] != "trashed" or item["restored_at"]:
        raise HTTPException(status_code=409, detail="该资料当前不可恢复")
    payload = json.loads(item["document_payload"])
    with INDEX_UPDATE_LOCK:
        restore_document_index_from_trash(payload, trash_id)
    with closing(database()) as connection:
        connection.execute(
            "UPDATE knowledge_document_trash SET status = 'restored', restored_at = ? WHERE id = ?",
            (isoformat(utc_now()), trash_id),
        )
        connection.commit()
    return RedirectResponse("/admin/knowledge-trash", status_code=303)


@app.post("/admin/knowledge/{document_id}")
def admin_knowledge_update(
    document_id: int,
    title: Annotated[str, Form(min_length=1, max_length=500)],
    content: Annotated[str, Form(min_length=1)],
    source: Annotated[str, Form(max_length=2000)],
    document_role: Annotated[str, Form(min_length=1, max_length=200)],
    csrf_token: Annotated[str, Form()],
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
):
    validate_csrf(user, csrf_token)
    require_admin(user)
    old = get_knowledge_document(document_id)
    new_payload = {
        "document_id": document_id,
        "title": title.strip(),
        "content": content.strip(),
        "source": source.strip(),
        "document_role": document_role.strip(),
    }
    with closing(database()) as connection:
        cursor = connection.execute(
            """
            INSERT INTO knowledge_document_revisions(
                document_id, old_payload, new_payload, changed_by, changed_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                document_id,
                json.dumps(old, ensure_ascii=False),
                json.dumps(new_payload, ensure_ascii=False),
                user["id"],
                isoformat(utc_now()),
            ),
        )
        revision_id = int(cursor.lastrowid)
        connection.commit()
    with INDEX_UPDATE_LOCK:
        snapshot = update_document_index(revision_id=revision_id, **new_payload)
    with closing(database()) as connection:
        connection.execute(
            "UPDATE knowledge_document_revisions SET snapshot_path = ? WHERE id = ?",
            (str(snapshot), revision_id),
        )
        connection.commit()
    return RedirectResponse(f"/admin/knowledge/{document_id}?saved=1", status_code=303)


@app.post("/admin/knowledge-revisions/{revision_id}/rollback")
def rollback_knowledge_revision(
    revision_id: int,
    csrf_token: Annotated[str, Form()],
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
):
    validate_csrf(user, csrf_token)
    require_admin(user)
    with closing(database()) as connection:
        revision = connection.execute(
            "SELECT snapshot_path, rolled_back_at FROM knowledge_document_revisions WHERE id = ?",
            (revision_id,),
        ).fetchone()
    if revision is None:
        raise HTTPException(status_code=404, detail="修订记录不存在")
    if revision["rolled_back_at"]:
        raise HTTPException(status_code=409, detail="该修订已经回滚")
    with INDEX_UPDATE_LOCK:
        restore_content_snapshot(Path(revision["snapshot_path"] or ""), revision_id)
    with closing(database()) as connection:
        connection.execute(
            "UPDATE knowledge_document_revisions SET rolled_back_at = ? WHERE id = ?",
            (isoformat(utc_now()), revision_id),
        )
        connection.commit()
    return RedirectResponse("/admin/knowledge", status_code=303)


@app.post("/device-tokens", response_class=HTMLResponse)
def create_device_token(
    request: Request,
    real_name: Annotated[str, Form(min_length=2, max_length=20)],
    company_name: Annotated[str, Form(min_length=2, max_length=100)],
    csrf_token: Annotated[str, Form()],
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
):
    validate_csrf(user, csrf_token)
    try:
        normalized_real_name = normalize_real_name(real_name)
    except ValueError as exc:
        return templates.TemplateResponse(
            request,
            "portal.html",
            portal_payload(request, user, error=str(exc)),
            status_code=400,
        )
    if not company_verified(company_name):
        return templates.TemplateResponse(
            request,
            "portal.html",
            portal_payload(request, user, error="公司名称验证未通过，未生成用户凭据。"),
            status_code=403,
        )
    raw_token = "jtk_" + secrets.token_urlsafe(36)
    prefix = raw_token[:12]
    with closing(database()) as connection:
        connection.execute(
            """
            INSERT INTO device_tokens(user_id, label, token_prefix, token_hash, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user["id"], normalized_real_name, prefix, token_hash(raw_token), isoformat(utc_now())),
        )
        connection.commit()
    return templates.TemplateResponse(
        request,
        "portal.html",
        portal_payload(request, user, new_token=raw_token, message="用户凭据已生成，请立即保存。"),
    )


@app.post("/device-tokens/{device_token_id}/revoke")
def revoke_device_token(
    device_token_id: int,
    csrf_token: Annotated[str, Form()],
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
):
    validate_csrf(user, csrf_token)
    with closing(database()) as connection:
        connection.execute(
            """
            UPDATE device_tokens SET revoked_at = ?
            WHERE id = ? AND user_id = ? AND revoked_at IS NULL
            """,
            (isoformat(utc_now()), device_token_id, user["id"]),
        )
        connection.commit()
    return RedirectResponse("/portal", status_code=303)


@app.post("/password")
def change_password(
    current_password: Annotated[str, Form()],
    new_password: Annotated[str, Form(min_length=MIN_PASSWORD_LENGTH, max_length=256)],
    csrf_token: Annotated[str, Form()],
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
):
    validate_csrf(user, csrf_token)
    try:
        valid = password_hasher.verify(user["password_hash"], current_password)
    except (VerifyMismatchError, InvalidHashError):
        valid = False
    if not valid:
        raise HTTPException(status_code=400, detail="当前密码不正确")
    with closing(database()) as connection:
        connection.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (password_hasher.hash(new_password), user["id"]),
        )
        connection.execute("DELETE FROM sessions WHERE user_id = ?", (user["id"],))
        connection.commit()
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response


@app.post("/users")
def create_user(
    username: Annotated[str, Form(min_length=3, max_length=64)],
    initial_password: Annotated[str, Form(min_length=MIN_PASSWORD_LENGTH, max_length=256)],
    csrf_token: Annotated[str, Form()],
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
):
    validate_csrf(user, csrf_token)
    require_admin(user)
    try:
        normalized_username = normalize_account_name(username)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        with closing(database()) as connection:
            connection.execute(
                "INSERT INTO users(username, password_hash, created_at) VALUES (?, ?, ?)",
                (normalized_username, password_hasher.hash(initial_password), isoformat(utc_now())),
            )
            connection.commit()
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="用户名称已存在") from exc
    return RedirectResponse("/portal", status_code=303)


@app.post("/users/{user_id}/toggle")
def toggle_user(
    user_id: int,
    csrf_token: Annotated[str, Form()],
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
):
    validate_csrf(user, csrf_token)
    require_admin(user)
    if user_id == user["id"]:
        raise HTTPException(status_code=400, detail="不能停用当前管理员账号")
    with closing(database()) as connection:
        connection.execute("UPDATE users SET active = 1 - active WHERE id = ?", (user_id,))
        connection.execute(
            "DELETE FROM sessions WHERE user_id = ? AND (SELECT active FROM users WHERE id = ?) = 0",
            (user_id, user_id),
        )
        connection.commit()
    return RedirectResponse("/portal", status_code=303)


@app.post("/admin/knowledge-updates", response_class=HTMLResponse)
def create_knowledge_update(
    request: Request,
    document_role: Annotated[str, Form(min_length=2, max_length=80)],
    csrf_token: Annotated[str, Form()],
    knowledge_file: Annotated[UploadFile, File()],
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
):
    validate_csrf(user, csrf_token)
    require_admin(user)
    original_name = safe_file_name(knowledge_file.filename or "upload.bin")
    extension = Path(original_name).suffix.lower()
    if extension not in SUPPORTED_UPLOAD_EXTENSIONS:
        return templates.TemplateResponse(
            request,
            "portal.html",
            portal_payload(request, user, error=f"暂不支持 {extension or '无扩展名'} 文件。"),
            status_code=400,
        )
    daily_directory = KNOWLEDGE_FILES_DIR / utc_now().strftime("%Y/%m/%d")
    stored_path, digest, file_size = save_upload(knowledge_file, daily_directory)
    with closing(database()) as connection:
        cursor = connection.execute(
            """
            INSERT INTO knowledge_update_jobs(
                original_name, stored_path, sha256, file_size, status,
                created_by, created_at
            ) VALUES (?, ?, ?, ?, 'processing', ?, ?)
            """,
            (
                original_name,
                str(stored_path),
                digest,
                file_size,
                user["id"],
                isoformat(utc_now()),
            ),
        )
        job_id = int(cursor.lastrowid)
        connection.commit()
    try:
        with INDEX_UPDATE_LOCK:
            with closing(content_database()) as connection:
                duplicate = connection.execute(
                    "SELECT id FROM documents WHERE sha256 = ? OR source_key = ?",
                    (digest, digest),
                ).fetchone()
            if duplicate:
                with closing(database()) as connection:
                    connection.execute(
                        """
                        UPDATE knowledge_update_jobs
                        SET status = 'duplicate', extraction_status = 'duplicate',
                            document_id = ?, completed_at = ?
                        WHERE id = ?
                        """,
                        (int(duplicate["id"]), isoformat(utc_now()), job_id),
                    )
                    connection.commit()
                return RedirectResponse("/portal#knowledge-admin", status_code=303)
            from scripts.build_knowledge_content_index import extract

            text, extraction_status = extract(stored_path, extension)
            if extraction_status == "ocr_required":
                extraction_status = "local_ocr_required"
            if extraction_status != "indexed":
                with closing(database()) as connection:
                    connection.execute(
                        """
                        UPDATE knowledge_update_jobs
                        SET status = 'waiting', extraction_status = ?,
                            text_characters = ?, completed_at = ?
                        WHERE id = ?
                        """,
                        (extraction_status, len(text), isoformat(utc_now()), job_id),
                    )
                    connection.commit()
                return RedirectResponse("/portal#knowledge-admin", status_code=303)
            document_id, snapshot = add_document_to_index(
                stored_path,
                digest,
                original_name,
                text,
                document_role,
                job_id,
            )
            with closing(database()) as connection:
                connection.execute(
                    """
                    UPDATE knowledge_update_jobs
                    SET status = 'indexed', extraction_status = 'indexed',
                        text_characters = ?, document_id = ?, snapshot_path = ?,
                        completed_at = ?
                    WHERE id = ?
                    """,
                    (
                        len(text),
                        document_id,
                        str(snapshot),
                        isoformat(utc_now()),
                        job_id,
                    ),
                )
                connection.commit()
    except Exception as error:
        with closing(database()) as connection:
            connection.execute(
                """
                UPDATE knowledge_update_jobs
                SET status = 'failed', error_message = ?, completed_at = ?
                WHERE id = ?
                """,
                (str(error)[:2000], isoformat(utc_now()), job_id),
            )
            connection.commit()
    return RedirectResponse("/portal#knowledge-admin", status_code=303)


@app.post("/admin/knowledge-updates/{job_id}/rollback")
def rollback_knowledge_update(
    job_id: int,
    csrf_token: Annotated[str, Form()],
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
):
    validate_csrf(user, csrf_token)
    require_admin(user)
    with closing(database()) as connection:
        job = connection.execute(
            """
            SELECT snapshot_path, status, rolled_back_at
            FROM knowledge_update_jobs
            WHERE id = ?
            """,
            (job_id,),
        ).fetchone()
    if job is None:
        raise HTTPException(status_code=404, detail="更新任务不存在")
    if job["status"] != "indexed" or job["rolled_back_at"]:
        raise HTTPException(status_code=409, detail="该任务当前不可回滚")
    snapshot = Path(job["snapshot_path"] or "")
    with INDEX_UPDATE_LOCK:
        restore_content_snapshot(snapshot, job_id)
    with closing(database()) as connection:
        connection.execute(
            "UPDATE knowledge_update_jobs SET status = 'rolled_back', rolled_back_at = ? WHERE id = ?",
            (isoformat(utc_now()), job_id),
        )
        connection.commit()
    return RedirectResponse("/portal#knowledge-admin", status_code=303)


@app.post("/admin/skill-releases", response_class=HTMLResponse)
def publish_skill_release(
    request: Request,
    version: Annotated[str, Form(min_length=1, max_length=40)],
    release_notes: Annotated[str, Form(min_length=1, max_length=4000)],
    csrf_token: Annotated[str, Form()],
    skill_package: Annotated[UploadFile, File()],
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
):
    validate_csrf(user, csrf_token)
    require_admin(user)
    normalized_version = version.strip().removeprefix("v")
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", normalized_version):
        return templates.TemplateResponse(
            request,
            "portal.html",
            portal_payload(request, user, error="版本号必须使用 1.2.3 格式。"),
            status_code=400,
        )
    with closing(database()) as connection:
        if connection.execute(
            "SELECT 1 FROM skill_releases WHERE version = ?", (normalized_version,)
        ).fetchone():
            return templates.TemplateResponse(
                request,
                "portal.html",
                portal_payload(request, user, error="该 Skills 版本已经存在。"),
                status_code=409,
            )
    if Path(skill_package.filename or "").suffix.lower() != ".zip":
        return templates.TemplateResponse(
            request,
            "portal.html",
            portal_payload(request, user, error="Skills 发布包必须是 ZIP 文件。"),
            status_code=400,
        )
    stored_path, digest, _ = save_upload(skill_package, SKILL_RELEASE_DIR)
    try:
        with zipfile.ZipFile(stored_path) as archive:
            skill_files = [name for name in archive.namelist() if name.endswith("/SKILL.md")]
            if not skill_files:
                raise ValueError("ZIP 中未找到任何 SKILL.md")
            bad_paths = [
                name
                for name in archive.namelist()
                if name.startswith("/") or ".." in Path(name).parts
            ]
            if bad_paths:
                raise ValueError("ZIP 包含不安全路径")
    except (zipfile.BadZipFile, ValueError) as error:
        rejected = SKILL_RELEASE_DIR / "rejected"
        rejected.mkdir(parents=True, exist_ok=True)
        stored_path.replace(rejected / stored_path.name)
        return templates.TemplateResponse(
            request,
            "portal.html",
            portal_payload(request, user, error=f"Skills 发布包校验失败：{error}"),
            status_code=400,
        )
    with closing(database()) as connection:
        connection.execute(
            """
            INSERT INTO skill_releases(
                version, file_name, file_path, sha256, release_notes, published_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                normalized_version,
                safe_file_name(skill_package.filename or stored_path.name),
                str(stored_path),
                digest,
                release_notes.strip(),
                isoformat(utc_now()),
            ),
        )
        connection.commit()
    return RedirectResponse("/portal#skill-admin", status_code=303)


@app.get("/skills/latest/download")
def web_download_latest_skills(user: Annotated[sqlite3.Row, Depends(require_web_user)]):
    del user
    release = latest_skill_release()
    if release is None:
        raise HTTPException(status_code=404, detail="尚未发布 Skills 版本")
    package_path = Path(release["file_path"])
    if not package_path.is_file():
        raise HTTPException(status_code=503, detail="最新版 Skills 文件暂不可用")
    return FileResponse(package_path, filename=release["file_name"], media_type="application/zip")


@app.get("/v1/me")
def api_me(user: Annotated[sqlite3.Row, Depends(require_api_user)]):
    return {"username": user["username"], "access": "unified"}


@app.post("/v1/search", response_model=SearchResponse)
def search(payload: SearchRequest, user: Annotated[sqlite3.Row, Depends(require_api_user)]):
    del user
    return SearchResponse.model_validate(search_knowledge(payload.query, payload.limit))


@app.get("/v1/documents/{document_id}", response_model=DocumentResponse)
def document_detail(
    document_id: int,
    user: Annotated[sqlite3.Row, Depends(require_api_user)],
):
    del user
    return DocumentResponse.model_validate(get_knowledge_document(document_id))


@app.get("/v1/usage", response_model=UsageResponse)
def usage(user: Annotated[sqlite3.Row, Depends(require_api_user)]):
    thirty_days_ago = isoformat(utc_now() - timedelta(days=30))
    with closing(database()) as connection:
        total_calls = int(
            connection.execute(
                "SELECT COUNT(*) FROM api_usage WHERE user_id = ?",
                (user["id"],),
            ).fetchone()[0]
        )
        calls_last_30_days = int(
            connection.execute(
                "SELECT COUNT(*) FROM api_usage WHERE user_id = ? AND called_at >= ?",
                (user["id"], thirty_days_ago),
            ).fetchone()[0]
        )
        endpoint_rows = connection.execute(
            """
            SELECT endpoint, COUNT(*) AS calls
            FROM api_usage
            WHERE user_id = ?
            GROUP BY endpoint
            ORDER BY calls DESC, endpoint
            """,
            (user["id"],),
        ).fetchall()
        recent_rows = connection.execute(
            """
            SELECT endpoint, method, called_at
            FROM api_usage
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT 20
            """,
            (user["id"],),
        ).fetchall()
    return UsageResponse(
        total_calls=total_calls,
        calls_last_30_days=calls_last_30_days,
        by_endpoint=[UsageEndpoint(endpoint=row["endpoint"], calls=row["calls"]) for row in endpoint_rows],
        recent_calls=[
            UsageCall(endpoint=row["endpoint"], method=row["method"], called_at=row["called_at"])
            for row in recent_rows
        ],
    )


def latest_skill_release() -> sqlite3.Row | None:
    with closing(database()) as connection:
        return connection.execute(
            """
            SELECT id, version, file_name, file_path, sha256, release_notes, published_at
            FROM skill_releases
            ORDER BY published_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()


@app.get("/v1/skills/latest", response_model=SkillLatestResponse)
def latest_skills(user: Annotated[sqlite3.Row, Depends(require_api_user)]):
    del user
    release = latest_skill_release()
    if release is None:
        return SkillLatestResponse(available=False)
    package_path = Path(release["file_path"])
    if not package_path.is_file():
        raise HTTPException(status_code=503, detail="最新版 Skills 文件暂不可用")
    return SkillLatestResponse(
        available=True,
        version=release["version"],
        file_name=release["file_name"],
        sha256=release["sha256"],
        file_size=package_path.stat().st_size,
        release_notes=release["release_notes"],
        published_at=release["published_at"],
        download_url="/v1/skills/latest/download",
    )


@app.get("/v1/skills/latest/download")
def download_latest_skills(user: Annotated[sqlite3.Row, Depends(require_api_user)]):
    del user
    release = latest_skill_release()
    if release is None:
        raise HTTPException(status_code=404, detail="尚未发布 Skills 版本")
    package_path = Path(release["file_path"])
    if not package_path.is_file():
        raise HTTPException(status_code=503, detail="最新版 Skills 文件暂不可用")
    return FileResponse(package_path, filename=release["file_name"], media_type="application/zip")


@knowledge_mcp.tool()
def knowledge_search(query: str, limit: int = 8) -> dict[str, object]:
    """检索团队知识库，返回命中文档编号、标题、摘要、资料类别和来源。"""
    return search_knowledge(query, limit)


@knowledge_mcp.tool()
def knowledge_document(document_id: int) -> dict[str, object]:
    """按检索结果中的文档编号读取完整正文和来源信息。"""
    return get_knowledge_document(document_id)


@knowledge_mcp.tool()
def knowledge_service_status() -> dict[str, object]:
    """查看知识库连接状态、文档总数与最近索引时间。"""
    return knowledge_index_stats()


app.mount("/mcp", MCPBearerMiddleware(knowledge_mcp.streamable_http_app()))
