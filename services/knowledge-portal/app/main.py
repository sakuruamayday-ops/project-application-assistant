from __future__ import annotations

import hashlib
import hmac
import html
import ipaddress
import csv
import io
import json
import math
import os
import queue
import re
import secrets
import shutil
import sqlite3
import threading
import time
import urllib.error
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from base64 import urlsafe_b64encode
from contextlib import closing
from contextlib import asynccontextmanager
from collections import Counter
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Callable, Iterator
from zoneinfo import ZoneInfo
from urllib.parse import quote, urlparse

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Cookie, Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from markupsafe import Markup
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse
from starlette.middleware.gzip import GZipMiddleware

from app.assistant_runtime import (
    assistant_tool_schemas,
    quick_guide_answer,
    route_assistant_skills,
    skill_context,
    skill_guidance,
)


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
FIRST_PUBLIC_SKILL_VERSION = os.environ.get("JIAOTANG_FIRST_PUBLIC_SKILL_VERSION", "1.0").strip()
TOKEN_DERIVATION_SECRET = os.environ.get(
    "JIAOTANG_TOKEN_DERIVATION_SECRET", "development-only-token-secret"
).encode("utf-8")
INDEX_SNAPSHOT_DIR = Path(os.environ.get("JIAOTANG_INDEX_SNAPSHOT_DIR", DATA_DIR / "index-snapshots"))
MEMBER_COMPANY = os.environ.get("JIAOTANG_MEMBER_COMPANY", "共创集团").strip()
SESSION_COOKIE = "jiaotang_session"
SESSION_HOURS = int(os.environ.get("JIAOTANG_SESSION_HOURS", "12"))
REMEMBER_SESSION_DAYS = 7
SECURE_COOKIES = os.environ.get("JIAOTANG_SECURE_COOKIES", "true").lower() == "true"
HEALTH_STATUS_PATH = DATA_DIR / "health-status.json"
BACKUP_STATUS_PATH = DATA_DIR / "backup-status.json"
OSS_SYNC_STATUS_PATH = DATA_DIR / "oss-sync-status.json"
OSS_INDEX_CACHE_STATUS_PATH = DATA_DIR / "oss-index-cache-status.json"
OSS_SYNC_REQUEST_PATH = DATA_DIR / "oss-sync-request.json"
SNAPSHOT_RETENTION_STATUS_PATH = DATA_DIR / "snapshot-retention-status.json"
DEPLOYED_USER_GUIDE_PATH = BASE_DIR / "docs" / "user-guide" / "企业全生命周期助手用户使用手册.md"
SOURCE_USER_GUIDE_PATH = BASE_DIR.parents[1] / "docs" / "user-guide" / "企业全生命周期助手用户使用手册.md"
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
WEB_SEARCH_RSS_URL = os.environ.get(
    "JIAOTANG_WEB_SEARCH_RSS_URL",
    "https://www.bing.com/search?format=rss&q={query}",
).strip()
ASSISTANT_DAILY_LIMIT = int(os.environ.get("JIAOTANG_ASSISTANT_DAILY_LIMIT", "5"))
ASSISTANT_TIMEZONE = ZoneInfo("Asia/Shanghai")
DEPLOYED_SKILL_SOURCE_DIR = BASE_DIR / "skills"
SOURCE_SKILL_SOURCE_DIR = BASE_DIR.parents[1] / "skills"
SKILL_SOURCE_DIR = Path(
    os.environ.get(
        "JIAOTANG_SKILL_SOURCE_DIR",
        DEPLOYED_SKILL_SOURCE_DIR if DEPLOYED_SKILL_SOURCE_DIR.is_dir() else SOURCE_SKILL_SOURCE_DIR,
    )
)
DEPLOYED_PROJECT_INDEX_PATH = (
    DEPLOYED_SKILL_SOURCE_DIR / "project-matching" / "references" / "canonical-project-index.jsonl"
)
SOURCE_PROJECT_INDEX_PATH = (
    SOURCE_SKILL_SOURCE_DIR / "project-matching" / "references" / "canonical-project-index.jsonl"
)
PROJECT_INDEX_PATH = Path(
    os.environ.get(
        "JIAOTANG_PROJECT_INDEX_PATH",
        DEPLOYED_PROJECT_INDEX_PATH
        if DEPLOYED_PROJECT_INDEX_PATH.is_file()
        else SOURCE_PROJECT_INDEX_PATH,
    )
)
PROJECT_QUERY_ALIASES_PATH = PROJECT_INDEX_PATH.parent / "query-aliases.json"
PROJECT_RETRIEVAL_RULES_PATH = PROJECT_INDEX_PATH.parent / "high-frequency-project-retrieval-rules.json"

POLICY_INTENT_TERMS = (
    "条件",
    "要求",
    "标准",
    "门槛",
    "办法",
    "政策",
    "申报",
    "认定",
    "复核",
    "通知",
    "公示",
    "名单",
    "截止",
    "材料",
    "流程",
)


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
IDENTITY_CODE_PATTERN = re.compile(r"^\d{4}$")
MOBILE_PHONE_PATTERN = re.compile(r"^1\d{10}$")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
public_host = os.environ.get("JIAOTANG_PUBLIC_HOST", "localhost").strip()
knowledge_mcp = FastMCP(
    "企业全生命周期助手知识库",
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


app = FastAPI(title="企业全生命周期助手知识库", docs_url=None, redoc_url=None, lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=500, compresslevel=6)
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
    validity_status: str
    updated_at: str


class SearchResponse(BaseModel):
    query: str
    clarification: str | None = None
    results: list[SearchResult]


class PublicListSearchRequest(BaseModel):
    enterprise_name: str = Field(default="", max_length=200)
    project_name: str = Field(default="", max_length=200)
    year: int | None = Field(default=None, ge=2000, le=2100)
    batch: str = Field(default="", max_length=50)
    region: str = Field(default="", max_length=100)
    limit: int = Field(default=20, ge=1, le=50)


class PolicySearchRequest(BaseModel):
    query: str = Field(default="", max_length=500)
    project_name: str = Field(default="", max_length=200)
    region: str = Field(default="", max_length=100)
    document_stage: str = Field(default="", max_length=100)
    validity_status: str = Field(default="", max_length=50)
    year: int | None = Field(default=None, ge=2000, le=2100)
    limit: int = Field(default=8, ge=1, le=20)


class ProjectCatalogMatchRequest(BaseModel):
    regions: list[str] = Field(default_factory=list, max_length=20)
    keywords: list[str] = Field(default_factory=list, max_length=30)
    limit: int = Field(default=20, ge=1, le=50)


class ProjectAliasCorrectionRequest(BaseModel):
    raw_project_name: str = Field(min_length=2, max_length=200)
    canonical_project_name: str = Field(min_length=2, max_length=200)
    region: str = Field(default="", max_length=100)
    start_year: int | None = Field(default=None, ge=2000, le=2100)
    end_year: int | None = Field(default=None, ge=2000, le=2100)
    note: str = Field(default="", max_length=1000)


class PolicyVerificationReviewRequest(BaseModel):
    queue_id: int = Field(ge=1)
    status: str = Field(pattern="^(verified|rejected)$")
    official_source_url: str = Field(default="", max_length=1000)
    official_document_title: str = Field(default="", max_length=500)
    official_published_at: str | None = Field(default=None, max_length=50)
    verification_note: str = Field(default="", max_length=2000)
    validity_status: str | None = Field(
        default=None,
        pattern="^(active_candidate|revised|trial|draft|invalid|superseded|historical_reference)$",
    )
    propagate_cluster: bool = True


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
    activity_type: str = "rest_api"
    activity_name: str = ""
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


def format_chinese_datetime(value: str | None) -> str:
    if not value:
        return "—"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(ASSISTANT_TIMEZONE).strftime("%Y年%m月%d日 %H:%M:%S")
    except ValueError:
        return str(value)


templates.env.filters["cn_datetime"] = format_chinese_datetime


def format_row_datetimes(
    rows: list[sqlite3.Row], *field_names: str
) -> list[dict[str, object]]:
    formatted_rows: list[dict[str, object]] = []
    for row in rows:
        item = dict(row)
        for field_name in field_names:
            if field_name in item and item[field_name]:
                item[field_name] = format_chinese_datetime(str(item[field_name]))
        formatted_rows.append(item)
    return formatted_rows


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def user_access_token(user_id: int, token_seed: str) -> str:
    digest = hmac.new(
        TOKEN_DERIVATION_SECRET,
        f"jiaotang-user-token:{user_id}:{token_seed}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return "jtk_" + urlsafe_b64encode(digest).decode("ascii").rstrip("=")


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


def normalize_identity_code(value: str) -> str:
    normalized = re.sub(r"[\s\-()（）]", "", value.strip())
    if normalized.startswith("+86"):
        normalized = normalized[3:]
    elif normalized.startswith("86") and len(normalized) == 13:
        normalized = normalized[2:]
    if IDENTITY_CODE_PATTERN.fullmatch(normalized):
        return normalized
    if MOBILE_PHONE_PATTERN.fullmatch(normalized):
        return normalized[-4:]
    raise ValueError("请填写企业微信绑定的完整11位手机号或手机号后四位。")


def registration_invite_token(authorization: sqlite3.Row | dict[str, object]) -> str:
    authorization_id = int(authorization["id"])
    message = (
        f"registration-invite:{authorization_id}:{authorization['real_name']}:"
        f"{authorization['identity_code']}:{authorization['created_at']}"
    ).encode("utf-8")
    signature = urlsafe_b64encode(
        hmac.new(TOKEN_DERIVATION_SECRET, message, hashlib.sha256).digest()
    ).decode("ascii").rstrip("=")
    return f"{authorization_id}.{signature}"


def registration_authorization_from_invite(invite_token: str) -> sqlite3.Row | None:
    try:
        authorization_id_text, provided_signature = invite_token.strip().split(".", 1)
        authorization_id = int(authorization_id_text)
    except (TypeError, ValueError):
        return None
    with closing(database()) as connection:
        authorization = connection.execute(
            "SELECT * FROM registration_authorizations WHERE id=? AND deleted_at IS NULL",
            (authorization_id,),
        ).fetchone()
    if authorization is None:
        return None
    expected_signature = registration_invite_token(authorization).split(".", 1)[1]
    if not secrets.compare_digest(provided_signature, expected_signature):
        return None
    return authorization


def read_status_file(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def request_oss_sync(reason: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temporary = OSS_SYNC_REQUEST_PATH.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {
                "requested_at": isoformat(utc_now()),
                "reason": reason[:200],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    os.chmod(temporary, 0o640)
    os.replace(temporary, OSS_SYNC_REQUEST_PATH)


def format_storage_size(size: int) -> str:
    value = float(max(0, size))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} TB"


def directory_storage_size(path: Path) -> int:
    try:
        if not path.exists():
            return 0
        if path.is_file():
            return path.stat().st_size
    except OSError:
        return 0
    total = 0
    for root, _, files in os.walk(path):
        for file_name in files:
            try:
                total += (Path(root) / file_name).stat().st_size
            except OSError:
                continue
    return total


def production_disk_breakdown() -> dict[str, object]:
    usage = shutil.disk_usage(DATA_DIR)
    components = [
        ("云端知识库原始资料", KNOWLEDGE_FILES_DIR),
        ("全文与结构化索引", INDEX_DIR),
        ("索引快照与回滚", INDEX_SNAPSHOT_DIR),
        ("Skills 发布包", SKILL_RELEASE_DIR),
        ("门户数据库与任务", DATA_DIR),
        ("系统备份", Path(os.environ.get("JIAOTANG_BACKUP_DIR", "/var/backups/jiaotang-kb"))),
        ("网站应用", BASE_DIR),
    ]
    rows = []
    for label, path in components:
        size = directory_storage_size(path)
        rows.append(
            {
                "label": label,
                "path": str(path),
                "bytes": size,
                "size": format_storage_size(size),
                "percent": round(size / usage.total * 100, 1) if usage.total else 0,
            }
        )
    rows.sort(key=lambda item: int(item["bytes"]), reverse=True)
    return {
        "total": format_storage_size(usage.total),
        "used": format_storage_size(usage.used),
        "free": format_storage_size(usage.free),
        "percent": round(usage.used / usage.total * 100, 1) if usage.total else 0,
        "components": rows,
    }


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


def fts_expression_variants(queries: list[str]) -> str:
    expressions = [fts_expression(query) for query in queries if query.strip()]
    if len(expressions) == 1:
        return expressions[0]
    return " OR ".join(f"({expression})" for expression in expressions)


def query_terms(query: str) -> list[str]:
    return [term for term in re.split(r"\s+", query.strip()) if term]


def project_result_priority(row: sqlite3.Row, retrieval_queries: list[str]) -> int:
    title = re.sub(r"\s+", "", str(row["title"] or ""))
    source = re.sub(r"\s+", "", str(row["source"] or ""))
    phrases = [re.sub(r"\s+", "", query) for query in retrieval_queries if query.strip()]
    collision_suffixes = {
        "高新技术企业": ("研究开发中心", "研究院", "产业园", "产品"),
    }
    for phrase in phrases:
        if not phrase or phrase not in title:
            continue
        suffix = title.split(phrase, 1)[1]
        if any(suffix.startswith(term) for term in collision_suffixes.get(phrase, ())):
            continue
        return 0
    for phrase in phrases:
        if not phrase or phrase not in source:
            continue
        suffix = source.rsplit(phrase, 1)[1]
        if any(suffix.startswith(term) for term in collision_suffixes.get(phrase, ())):
            continue
        return 1
    return 2


def filter_project_results(
    question: str,
    rows: list[sqlite3.Row] | list[dict[str, object]],
) -> list[sqlite3.Row] | list[dict[str, object]]:
    if not rows or not project_query_is_resolved(question):
        return rows
    retrieval_queries = project_query_variants(question)
    retrieval_rule = matched_project_retrieval_rule(question)
    if retrieval_rule:
        allowed_terms = [str(term) for term in retrieval_rule.get("allowed_title_terms", [])]
        excluded_terms = [str(term) for term in retrieval_rule.get("excluded_title_terms", [])]
        allowed_rows = [
            row
            for row in rows
            if any(
                term in f"{str(row['title'] or '')} {str(row['source'] or '')}"
                for term in allowed_terms
            )
        ]
        if allowed_rows:
            rows = allowed_rows
        rows = [
            row
            for row in rows
            if not any(term in str(row["title"] or "") for term in excluded_terms)
        ]
    strict_rows = [row for row in rows if project_result_priority(row, retrieval_queries) < 2]
    selected = strict_rows or rows
    if any(term in question for term in ("条件", "要求", "标准", "门槛", "办法", "申报")) and not any(
        term in question for term in ("公示", "名单", "补助", "奖励")
    ):
        rule_rows = [
            row
            for row in selected
            if not any(
                term in str(row["title"] or "")
                for term in ("公示", "名单", "拟兑现", "补助资金", "奖励资金")
            )
        ]
        if rule_rows:
            selected = rule_rows
        if not re.search(r"(?<!\d)20\d{2}(?:年|年度)?", question):
            recent_floor = datetime.now(ASSISTANT_TIMEZONE).year - 1
            current_rows = []
            for row in selected:
                title = str(row["title"] or "")
                title_years = [int(year) for year in re.findall(r"(?<!\d)(20\d{2})(?:年|年度)?", title)]
                if not title_years or max(title_years) >= recent_floor or any(
                    term in title for term in ("管理办法", "认定办法", "实施办法", "条例", "规定", "标准")
                ):
                    current_rows.append(row)
            if current_rows:
                selected = current_rows
    return selected


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


@lru_cache(maxsize=1)
def metadata_project_catalog() -> tuple[dict[str, object], ...]:
    from scripts.build_knowledge_content_index import load_project_catalog

    return tuple(load_project_catalog(PROJECT_INDEX_PATH))


def derive_document_metadata(
    title: str,
    source: str,
    content: str,
    document_role: str,
) -> dict[str, object]:
    from scripts.build_knowledge_content_index import infer_document_metadata

    corrections: list[dict[str, object]] = []
    try:
        with closing(content_database()) as connection:
            corrections = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM project_alias_corrections WHERE status='confirmed'"
                ).fetchall()
            ]
    except (sqlite3.Error, HTTPException):
        corrections = []
    return infer_document_metadata(
        title,
        source,
        content,
        document_role,
        list(metadata_project_catalog()),
        corrections,
    )


def insert_entity_indexes(
    connection: sqlite3.Connection,
    document_id: int,
    content: str,
    document_role: str,
    metadata: dict[str, object],
) -> None:
    from scripts.build_knowledge_content_index import (
        enterprise_mentions,
        insert_metadata_audit_records,
    )

    connection.execute(
        """
        DELETE FROM metadata_match_evidence
        WHERE document_id=?
          AND match_method NOT IN ('official_manual_review','official_cluster_propagation')
        """,
        (document_id,),
    )
    connection.execute(
        "DELETE FROM policy_verification_queue WHERE document_id=? AND status='pending'",
        (document_id,),
    )

    for enterprise_name, sequence_no, context in enterprise_mentions(content):
        connection.execute(
            "INSERT OR IGNORE INTO enterprise_mentions(document_id,enterprise_name,sequence_no,context) VALUES (?,?,?,?)",
            (document_id, enterprise_name, sequence_no, context),
        )
        if document_role != "50_名单与对标":
            continue
        confidence = (
            "high"
            if metadata["canonical_project_name"] and metadata["document_stage"] != "其他"
            else "medium"
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO public_list_entities(
                document_id,enterprise_name,sequence_no,canonical_project_name,
                policy_year,batch,region,list_status,context,confidence
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                document_id,
                enterprise_name,
                sequence_no,
                metadata["canonical_project_name"],
                metadata["policy_year"],
                metadata["batch"],
                metadata["region"],
                metadata["document_stage"],
                context,
                confidence,
            ),
        )
    insert_metadata_audit_records(
        connection, document_id, document_role, metadata
    )


def add_document_to_index(
    path: Path,
    digest: str,
    original_name: str,
    text: str,
    document_role: str,
    job_id: int,
) -> tuple[int, Path]:
    from scripts.build_knowledge_content_index import iter_chunks, rebuild_policy_document_clusters

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
            metadata = derive_document_metadata(
                original_name, source, text, document_role
            )
            cursor = connection.execute(
                """
                INSERT INTO documents(
                    source_key,title,content,source,cloud_path,document_role,
                    sensitivity,sha256,updated_at,canonical_project_name,region,
                    document_stage,validity_status,policy_year,batch,replacement_title,
                    replacement_basis,replacement_url
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                    metadata["canonical_project_name"],
                    metadata["region"],
                    metadata["document_stage"],
                    metadata["validity_status"],
                    metadata["policy_year"],
                    metadata["batch"],
                    metadata["replacement_title"],
                    metadata["replacement_basis"],
                    metadata["replacement_url"],
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
            insert_entity_indexes(
                connection, document_id, text, document_role, metadata
            )
            rebuild_policy_document_clusters(connection)
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


def requires_current_policy_sources(query: str) -> bool:
    project_terms = (
        "专精特新",
        "小巨人",
        "梯度培育",
        "研发中心",
        "企业研究院",
        "高新技术企业",
        "高企",
        "高新",
    )
    return any(term in query for term in project_terms) and any(
        term in query for term in POLICY_INTENT_TERMS
    )


def requires_current_sme_policy_sources(query: str) -> bool:
    project_terms = (
        "优质中小企业梯度培育",
        "专精特新",
        "重点专精特新",
        "小巨人",
        "重点小巨人",
    )
    return requires_current_policy_sources(query) and any(term in query for term in project_terms)


def base_knowledge_search_query(query: str) -> str:
    normalized = query.replace("高企", "高新技术企业")
    if "高新技术企业" not in normalized and "高新" in normalized:
        normalized = normalized.replace("高新", "高新技术企业")
    if "公司法" in normalized:
        legal_terms = [
            term
            for term in ("公司法", "注册资本", "股东出资", "股权转让", "董事", "清算", "注销")
            if term in normalized
        ]
        return " ".join(legal_terms[:3]) or "公司法"
    if not requires_current_policy_sources(normalized):
        return normalized
    terms: list[str] = []
    for term in (
        "优质中小企业梯度培育",
        "重点专精特新",
        "重点小巨人",
        "专精特新",
        "小巨人",
        "杭州市",
        "宁波市",
        "金华市",
        "绍兴市",
        "浙江省",
        "研发中心",
        "企业研究院",
        "高新技术企业",
        "高新技术企业",
    ):
        if term in normalized and term not in terms:
            terms.append(term)
    return " ".join(terms) or normalized


@lru_cache(maxsize=1)
def load_project_query_aliases() -> dict[str, tuple[str, ...]]:
    if not PROJECT_QUERY_ALIASES_PATH.is_file():
        return {}
    try:
        payload = json.loads(PROJECT_QUERY_ALIASES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    aliases: dict[str, tuple[str, ...]] = {}
    for raw_alias, raw_targets in payload.items():
        alias = str(raw_alias).strip()
        targets = tuple(
            dict.fromkeys(
                str(target).strip()
                for target in (raw_targets if isinstance(raw_targets, list) else [raw_targets])
                if str(target).strip()
            )
        )
        if alias and targets:
            aliases[alias] = targets
    return aliases


@lru_cache(maxsize=1)
def load_project_retrieval_rules() -> list[dict[str, object]]:
    if not PROJECT_RETRIEVAL_RULES_PATH.is_file():
        return []
    try:
        payload = json.loads(PROJECT_RETRIEVAL_RULES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rules = payload.get("rules", []) if isinstance(payload, dict) else []
    return [rule for rule in rules if isinstance(rule, dict)]


def matched_project_retrieval_rule(query: str) -> dict[str, object] | None:
    matches: list[tuple[int, dict[str, object]]] = []
    for rule in load_project_retrieval_rules():
        for alias in rule.get("aliases", []):
            normalized_alias = str(alias).strip()
            if normalized_alias and normalized_alias in query:
                matches.append((len(normalized_alias), rule))
    return max(matches, key=lambda item: item[0])[1] if matches else None


def matched_project_alias(query: str, rule: dict[str, object]) -> str:
    aliases = [str(alias).strip() for alias in rule.get("aliases", []) if str(alias).strip()]
    matches = [alias for alias in aliases if alias in query]
    return max(matches, key=len) if matches else ""


def selected_project_targets(query: str, rule: dict[str, object]) -> list[str]:
    targets = [str(target).strip() for target in rule.get("targets", []) if str(target).strip()]
    selectors = rule.get("selectors", {})
    if isinstance(selectors, dict):
        for selector, target in sorted(selectors.items(), key=lambda item: len(str(item[0])), reverse=True):
            if str(selector) in query and str(target) in targets:
                return [str(target)]
    rule_id = str(rule.get("id") or "")
    if rule_id == "green-factory":
        if "国家" in query:
            return ["国家绿色工厂"]
        if "浙江省" in query or "省级" in query:
            return ["浙江省绿色低碳工厂"]
        if re.search(r"[\u4e00-\u9fff]{2,8}(?:区|县)", query) or "区级" in query:
            return ["区级绿色工厂"]
        if re.search(r"[\u4e00-\u9fff]{2,8}市", query) or "市级" in query:
            return ["市级绿色工厂"]
    return targets


def explicit_project_regions(query: str) -> list[str]:
    return list(
        dict.fromkeys(
            region
            for region in re.findall(r"[\u4e00-\u9fff]{2,8}(?:省|自治区|市|区|县)", query)
            if not region.startswith(("重点", "省级", "市级", "区级", "国家"))
        )
    )


def project_region_prompt(query: str, rule: dict[str, object], targets: list[str]) -> str | None:
    regions = explicit_project_regions(query)
    required_level = str(rule.get("required_region_level") or "")
    if required_level == "city" and not any(region.endswith("市") for region in regions):
        return str(rule.get("region_prompt") or "请先说明企业所在城市。")
    if required_level == "district" and not any(region.endswith(("区", "县")) for region in regions):
        return str(rule.get("region_prompt") or "请先说明企业所在区县。")
    region_required_targets = {
        str(target) for target in rule.get("region_required_targets", []) if str(target).strip()
    }
    if region_required_targets.intersection(targets):
        needs_district = any(target.startswith("区级") for target in targets)
        suffixes = ("区", "县") if needs_district else ("市",)
        if not any(region.endswith(suffixes) for region in regions):
            return str(rule.get("region_prompt") or "请先说明企业所在地区。")
    return None


def project_selection_prompt(query: str) -> str | None:
    rule = matched_project_retrieval_rule(query)
    if not rule:
        return None
    selected_targets = selected_project_targets(query, rule)
    region_prompt = project_region_prompt(query, rule, selected_targets)
    if region_prompt:
        return region_prompt
    if not bool(rule.get("selection_required")):
        return None
    targets = [str(target) for target in rule.get("targets", [])]
    if len(selected_targets) == 1:
        return None
    return str(rule.get("selection_prompt") or f"请选择具体项目：{'、'.join(targets)}。")


def project_query_variants(query: str) -> list[str]:
    normalized = query.strip().replace("高企", "高新技术企业")
    if "高新技术企业" not in normalized and "高新" in normalized:
        normalized = normalized.replace("高新", "高新技术企业")
    region_terms = explicit_project_regions(normalized)

    def with_regions(project_name: str) -> str:
        prefixes = [region for region in region_terms if region not in project_name]
        return " ".join((*prefixes, project_name))

    retrieval_rule = matched_project_retrieval_rule(query)
    if retrieval_rule:
        targets = selected_project_targets(query, retrieval_rule)
        if targets:
            return list(dict.fromkeys(with_regions(name) for name in targets))

    records = load_project_index_records()
    formal_matches: list[str] = []
    indexed_alias_matches: list[str] = []
    for record in records:
        canonical_name = str(record.get("canonical_project_name") or "").strip()
        if canonical_name and canonical_name in normalized:
            formal_matches.append(canonical_name)
            continue
        for alias in record.get("aliases", []):
            normalized_alias = str(alias).strip()
            if normalized_alias and normalized_alias in normalized:
                indexed_alias_matches.append(canonical_name)
                break
    if formal_matches:
        return list(dict.fromkeys(with_regions(name) for name in formal_matches))
    if indexed_alias_matches:
        return list(dict.fromkeys(with_regions(name) for name in indexed_alias_matches))

    configured_aliases = load_project_query_aliases()
    matched_aliases = [alias for alias in configured_aliases if alias in normalized]
    if matched_aliases:
        longest = max(len(alias) for alias in matched_aliases)
        variants: list[str] = []
        for alias in matched_aliases:
            if len(alias) != longest:
                continue
            variants.extend(configured_aliases[alias])
        return list(dict.fromkeys(with_regions(name) for name in variants))

    base_query = base_knowledge_search_query(normalized)
    if base_query != normalized:
        return [base_query]
    reduced = normalized
    for term in sorted(POLICY_INTENT_TERMS, key=len, reverse=True):
        reduced = reduced.replace(term, " ")
    reduced = re.sub(r"(?:帮我|请问|查询|检索|一下|有哪些|是什么|怎么报|如何报|怎么申请|如何申请)", " ", reduced)
    reduced = re.sub(r"[的，。！？、：:；;（）()]+", " ", reduced)
    reduced = re.sub(r"\s+", " ", reduced).strip()
    return [reduced or normalized]


def project_query_is_resolved(query: str) -> bool:
    normalized = query.strip().replace("高企", "高新技术企业")
    if "高新技术企业" not in normalized and "高新" in normalized:
        normalized = normalized.replace("高新", "高新技术企业")
    if "高新技术企业" in normalized and not any(
        term in normalized for term in ("研究开发中心", "研究院", "产业园", "产品")
    ):
        return True
    for record in load_project_index_records():
        canonical_name = str(record.get("canonical_project_name") or "").strip()
        if canonical_name and canonical_name in normalized:
            return True
        if any(str(alias).strip() and str(alias).strip() in normalized for alias in record.get("aliases", [])):
            return True
    return any(alias in normalized for alias in load_project_query_aliases())


def knowledge_search_query(query: str) -> str:
    return project_query_variants(query)[0]


def policy_source_layer(query: str) -> str:
    dynamic_terms = ("最新", "当前", "通知", "公示", "名单", "截止", "开放", "批次")
    rule_terms = ("条件", "门槛", "标准", "评分", "管理办法", "办法", "材料", "模板", "要求", "维护")
    has_dynamic = any(term in query for term in dynamic_terms) or bool(re.search(r"20\d{2}", query))
    has_rule = any(term in query for term in rule_terms)
    if has_dynamic and not has_rule:
        return "dynamic"
    if has_rule and not has_dynamic:
        return "curated"
    return "mixed"


def policy_source_order(query: str) -> str:
    dynamic_source = "documents.source LIKE '%/政策数据库/企策顾问/%'"
    layer = policy_source_layer(query)
    if layer == "dynamic":
        return f"CASE WHEN {dynamic_source} THEN 0 ELSE 1 END,"
    if layer == "curated":
        return f"CASE WHEN {dynamic_source} THEN 1 ELSE 0 END,"
    return ""


def knowledge_source_metadata(row: sqlite3.Row) -> dict[str, object]:
    source = str(row["source"] or "")
    source_layer = "动态层" if "/政策数据库/企策顾问/" in source else "规则层"
    official_source_detected = bool(row["official_source_detected"])
    validity_status = str(row["validity_status"] or "active_candidate")
    labels = [source_layer]
    if official_source_detected:
        labels.append("官方原文")
    if validity_status in {"historical_reference", "superseded", "invalid"}:
        verification_status = "已识别历史或替代状态"
    elif official_source_detected:
        verification_status = "已识别官方来源链接"
    elif source_layer == "动态层":
        verification_status = "待官方原文核验"
    else:
        verification_status = "待时效复核"
    return {
        "source_layer": source_layer,
        "source_labels": labels,
        "verification_status": verification_status,
        "validity_status": validity_status,
    }


def search_knowledge(query: str, limit: int = 8) -> dict[str, object]:
    normalized_query = query.strip()
    if not normalized_query:
        raise HTTPException(status_code=422, detail="检索词不能为空")
    bounded_limit = max(1, min(int(limit), 20))
    clarification = project_selection_prompt(normalized_query)
    if clarification:
        return {
            "query": normalized_query,
            "retrieval_queries": [],
            "clarification": clarification,
            "results": [],
        }
    retrieval_queries = project_query_variants(normalized_query)
    project_query_resolved = project_query_is_resolved(normalized_query)
    current_policy_only = requires_current_policy_sources(normalized_query) or (
        project_query_resolved and any(term in normalized_query for term in POLICY_INTENT_TERMS)
    )
    current_sme_policy_only = requires_current_sme_policy_sources(normalized_query)
    year_match = re.search(r"(?<!\d)(20\d{2})(?:年|年度)?", normalized_query)
    requested_year = int(year_match.group(1)) if year_match else None
    retrieval_query = retrieval_queries[0]
    candidate_limit = min(max(bounded_limit * 8, 40), 160)
    source_order = policy_source_order(normalized_query)
    validity_clause = (
        "AND COALESCE(documents.validity_status, 'active_candidate') "
        "NOT IN ('historical_reference','superseded','invalid')"
        if current_policy_only
        else ""
    )
    if current_sme_policy_only:
        validity_clause += " AND COALESCE(documents.policy_year, 0) >= 2026"
    if requested_year is not None:
        validity_clause += f" AND COALESCE(documents.policy_year, 0) = {requested_year}"
    with closing(content_database()) as connection:
        rows = []
        try:
            rows = connection.execute(
                """
                SELECT documents.id, documents.title,
                       snippet(documents_fts_trigram, 1, '<mark>', '</mark>', '…', 36) AS excerpt,
                       documents.source, documents.document_role, documents.updated_at,
                       documents.validity_status,
                       CASE WHEN lower(COALESCE(documents.replacement_url, '') || ' ' ||
                                                COALESCE(documents.content, '')) LIKE '%gov.cn%'
                            THEN 1 ELSE 0 END AS official_source_detected
                FROM documents_fts_trigram
                JOIN documents ON documents.id = documents_fts_trigram.rowid
                WHERE documents_fts_trigram MATCH ?
                {validity_clause}
                ORDER BY {source_order}
                         CASE documents.document_stage
                             WHEN '申报通知' THEN 0
                             WHEN '管理办法' THEN 1
                             WHEN '实施办法' THEN 1
                             WHEN '认定办法' THEN 1
                             WHEN '通知' THEN 2
                             WHEN '公示名单' THEN 3
                             WHEN '认定名单' THEN 3
                             ELSE 4 END,
                         CASE documents.validity_status
                             WHEN 'active_candidate' THEN 0
                             WHEN 'revised' THEN 1
                             WHEN 'trial' THEN 2
                             WHEN 'draft' THEN 3
                             ELSE 4 END,
                         COALESCE(documents.policy_year, 0) DESC,
                         bm25(documents_fts_trigram)
                LIMIT ?
                """.format(validity_clause=validity_clause, source_order=source_order),
                (fts_expression_variants(retrieval_queries), candidate_limit),
            ).fetchall()
        except sqlite3.OperationalError:
            pass
        if not rows:
            conditions = []
            parameters: list[object] = []
            variant_conditions: list[str] = []
            for variant in retrieval_queries:
                term_conditions: list[str] = []
                for term in query_terms(variant):
                    escaped = term.replace("%", "\\%").replace("_", "\\_")
                    value = f"%{escaped}%"
                    term_conditions.append(
                        "(title LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\' OR source LIKE ? ESCAPE '\\')"
                    )
                    parameters.extend((value, value, value))
                if term_conditions:
                    variant_conditions.append(f"({' AND '.join(term_conditions)})")
            if variant_conditions:
                conditions.append(f"({' OR '.join(variant_conditions)})")
            if current_policy_only:
                conditions.append(
                    "COALESCE(validity_status, 'active_candidate') "
                    "NOT IN ('historical_reference','superseded','invalid')"
                )
            if current_sme_policy_only:
                conditions.append("COALESCE(policy_year, 0) >= 2026")
            if requested_year is not None:
                conditions.append("COALESCE(policy_year, 0) = ?")
                parameters.append(requested_year)
            parameters.append(candidate_limit)
            rows = connection.execute(
                f"""
                SELECT id, title, substr(content, 1, 600) AS excerpt, source,
                       document_role, updated_at, validity_status,
                       CASE WHEN lower(COALESCE(replacement_url, '') || ' ' || COALESCE(content, ''))
                                      LIKE '%gov.cn%'
                            THEN 1 ELSE 0 END AS official_source_detected
                FROM documents
                WHERE {' AND '.join(conditions)}
                ORDER BY {source_order}
                         CASE document_stage
                             WHEN '申报通知' THEN 0
                             WHEN '管理办法' THEN 1
                             WHEN '实施办法' THEN 1
                             WHEN '认定办法' THEN 1
                             WHEN '通知' THEN 2
                             WHEN '公示名单' THEN 3
                             WHEN '认定名单' THEN 3
                             ELSE 4 END,
                         CASE validity_status
                             WHEN 'active_candidate' THEN 0
                             WHEN 'revised' THEN 1
                             WHEN 'trial' THEN 2
                             WHEN 'draft' THEN 3
                             ELSE 4 END,
                         COALESCE(policy_year, 0) DESC,
                         updated_at DESC
                LIMIT ?
                """.format(source_order=source_order.replace("documents.", "")),
                parameters,
            ).fetchall()
    rows = sorted(rows, key=lambda row: project_result_priority(row, retrieval_queries))
    rows = filter_project_results(normalized_query, rows)[:bounded_limit]
    return {
        "query": normalized_query,
        "retrieval_queries": retrieval_queries,
        "results": [
            {
                "document_id": int(row["id"]),
                "title": row["title"],
                "excerpt": row["excerpt"],
                "source": row["source"],
                "document_role": row["document_role"],
                "index_layer": "content",
                **knowledge_source_metadata(row),
                "updated_at": row["updated_at"],
            }
            for row in rows
        ],
    }


def public_search_knowledge(query: str, limit: int = 8) -> dict[str, object]:
    result = search_knowledge(query, limit)
    hidden_fields = {"source_layer", "source_labels", "verification_status"}
    return {
        "query": result["query"],
        "clarification": result.get("clarification"),
        "results": [
            {key: value for key, value in item.items() if key not in hidden_fields}
            for item in result["results"]
        ],
    }


def _like_filter(column: str, value: str, conditions: list[str], parameters: list[object]) -> None:
    normalized = value.strip()
    if not normalized:
        return
    escaped = normalized.replace("%", "\\%").replace("_", "\\_")
    conditions.append(f"{column} LIKE ? ESCAPE '\\'")
    parameters.append(f"%{escaped}%")


def search_public_list_entities(
    enterprise_name: str = "",
    project_name: str = "",
    year: int | None = None,
    batch: str = "",
    region: str = "",
    limit: int = 20,
) -> dict[str, object]:
    if not any((enterprise_name.strip(), project_name.strip(), year, batch.strip(), region.strip())):
        raise HTTPException(status_code=422, detail="名单查询至少需要一个筛选条件")
    conditions = ["1 = 1"]
    parameters: list[object] = []
    _like_filter("e.enterprise_name", enterprise_name, conditions, parameters)
    _like_filter("e.canonical_project_name", project_name, conditions, parameters)
    _like_filter("e.batch", batch, conditions, parameters)
    _like_filter("e.region", region, conditions, parameters)
    if year is not None:
        conditions.append("e.policy_year = ?")
        parameters.append(int(year))
    bounded_limit = max(1, min(int(limit), 50))
    with closing(content_database()) as connection:
        try:
            rows = connection.execute(
                f"""
                SELECT e.enterprise_name,e.sequence_no,e.canonical_project_name,
                       e.policy_year,e.batch,e.region,e.list_status,e.context,e.confidence,
                       d.id AS document_id,d.title,d.source,d.updated_at
                FROM public_list_entities e
                JOIN documents d ON d.id = e.document_id
                WHERE {' AND '.join(conditions)}
                ORDER BY COALESCE(e.policy_year, 0) DESC,
                         CASE e.confidence WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                         e.enterprise_name
                LIMIT ?
                """,
                [*parameters, bounded_limit],
            ).fetchall()
        except sqlite3.OperationalError as error:
            raise HTTPException(status_code=503, detail="名单实体索引尚未重建") from error
    return {
        "filters": {
            "enterprise_name": enterprise_name.strip(),
            "project_name": project_name.strip(),
            "year": year,
            "batch": batch.strip(),
            "region": region.strip(),
        },
        "results": [dict(row) for row in rows],
    }


def search_policy_documents(
    query: str = "",
    project_name: str = "",
    region: str = "",
    document_stage: str = "",
    validity_status: str = "",
    year: int | None = None,
    limit: int = 8,
) -> dict[str, object]:
    if not any(
        (
            query.strip(),
            project_name.strip(),
            region.strip(),
            document_stage.strip(),
            validity_status.strip(),
            year,
        )
    ):
        raise HTTPException(status_code=422, detail="政策查询至少需要一个筛选条件")
    conditions = [
        "document_role IN ('10_政策与通知','10_政策与目录','20_项目规则与指南','20_申报指南与规则')"
    ]
    parameters: list[object] = []
    current_policy_context = " ".join(
        value.strip() for value in (query, project_name) if value.strip()
    )
    current_policy_only = requires_current_policy_sources(current_policy_context)
    current_sme_policy_only = requires_current_sme_policy_sources(current_policy_context)
    if current_policy_only and not validity_status.strip():
        conditions.append(
            "COALESCE(validity_status, 'active_candidate') "
            "NOT IN ('historical_reference','superseded','invalid')"
        )
    if current_sme_policy_only and year is None:
        conditions.append("COALESCE(policy_year, 0) >= 2026")
    _like_filter("canonical_project_name", project_name, conditions, parameters)
    _like_filter("region", region, conditions, parameters)
    _like_filter("document_stage", document_stage, conditions, parameters)
    _like_filter("validity_status", validity_status, conditions, parameters)
    if query.strip():
        escaped = query.strip().replace("%", "\\%").replace("_", "\\_")
        value = f"%{escaped}%"
        conditions.append(
            "(title LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\' OR source LIKE ? ESCAPE '\\')"
        )
        parameters.extend((value, value, value))
    if year is not None:
        conditions.append("policy_year = ?")
        parameters.append(int(year))
    bounded_limit = max(1, min(int(limit), 20))
    with closing(content_database()) as connection:
        try:
            rows = connection.execute(
                f"""
                SELECT id AS document_id,title,substr(content,1,800) AS excerpt,source,
                       document_role,canonical_project_name,region,document_stage,
                       validity_status,policy_year,batch,replacement_title,
                       replacement_basis,replacement_url,updated_at
                FROM documents
                WHERE {' AND '.join(conditions)}
                ORDER BY CASE validity_status
                             WHEN 'active_candidate' THEN 0
                             WHEN 'revised' THEN 1
                             WHEN 'trial' THEN 2
                             WHEN 'draft' THEN 3
                             WHEN 'historical_reference' THEN 4
                             WHEN 'superseded' THEN 5
                             WHEN 'invalid' THEN 6
                             ELSE 7 END,
                         COALESCE(policy_year, 0) DESC, updated_at DESC
                LIMIT ?
                """,
                [*parameters, bounded_limit],
            ).fetchall()
        except sqlite3.OperationalError as error:
            raise HTTPException(status_code=503, detail="政策元数据索引尚未重建") from error
    return {
        "filters": {
            "query": query.strip(),
            "project_name": project_name.strip(),
            "region": region.strip(),
            "document_stage": document_stage.strip(),
            "validity_status": validity_status.strip(),
            "year": year,
        },
        "results": [dict(row) for row in rows],
    }


@lru_cache(maxsize=1)
def load_project_index_records() -> tuple[dict[str, object], ...]:
    if not PROJECT_INDEX_PATH.is_file():
        return ()
    records: list[dict[str, object]] = []
    for line in PROJECT_INDEX_PATH.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("canonical_project_name"):
            records.append(record)
    return tuple(records)


def match_project_catalog(
    regions: list[str] | None = None,
    keywords: list[str] | None = None,
    limit: int = 20,
) -> dict[str, object]:
    from scripts.project_catalog_matching import match_project_records

    try:
        return match_project_records(regions, keywords, limit, PROJECT_INDEX_PATH)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def _mutate_content_index(label: str, callback: Callable[[sqlite3.Connection], object]) -> object:
    snapshot_content_database(label)
    temporary = CONTENT_DATABASE_PATH.with_name(
        f"{CONTENT_DATABASE_PATH.stem}.{label}-{secrets.token_hex(4)}.tmp.sqlite3"
    )
    shutil.copy2(CONTENT_DATABASE_PATH, temporary)
    try:
        with closing(sqlite3.connect(temporary)) as connection:
            connection.row_factory = sqlite3.Row
            result = callback(connection)
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            if integrity != "ok":
                raise RuntimeError(f"结构化索引完整性检查失败：{integrity}")
            connection.commit()
        os.replace(temporary, CONTENT_DATABASE_PATH)
        return result
    finally:
        if temporary.exists():
            failed_directory = INDEX_SNAPSHOT_DIR / "failed-builds"
            failed_directory.mkdir(parents=True, exist_ok=True)
            temporary.replace(failed_directory / temporary.name)


def create_project_alias_correction(
    payload: ProjectAliasCorrectionRequest,
    confirmed_by: str,
) -> dict[str, object]:
    if payload.start_year and payload.end_year and payload.start_year > payload.end_year:
        raise HTTPException(status_code=422, detail="起始年度不能晚于结束年度")

    def apply(connection: sqlite3.Connection) -> dict[str, object]:
        from scripts.build_knowledge_content_index import (
            infer_document_metadata,
            insert_metadata_audit_records,
            load_project_catalog,
            normalize_match_text,
            rebuild_policy_document_clusters,
        )

        now = isoformat(utc_now())
        connection.execute(
            """
            INSERT INTO project_alias_corrections(
                raw_project_name,canonical_project_name,region,start_year,end_year,
                status,confirmed_by,confirmed_at,note,created_at,updated_at
            ) VALUES (?,?,?,?,?,'confirmed',?,?,?,?,?)
            ON CONFLICT DO UPDATE SET status='confirmed',confirmed_by=excluded.confirmed_by,
                          confirmed_at=excluded.confirmed_at,note=excluded.note,
                          updated_at=excluded.updated_at
            """,
            (
                payload.raw_project_name.strip(), payload.canonical_project_name.strip(),
                payload.region.strip(), payload.start_year, payload.end_year,
                confirmed_by, now, payload.note.strip(), now, now,
            ),
        )
        correction = connection.execute(
            """
            SELECT * FROM project_alias_corrections
            WHERE raw_project_name=? AND canonical_project_name=? AND region=?
              AND start_year IS ? AND end_year IS ?
            """,
            (
                payload.raw_project_name.strip(), payload.canonical_project_name.strip(),
                payload.region.strip(), payload.start_year, payload.end_year,
            ),
        ).fetchone()
        corrections = [
            dict(row) for row in connection.execute(
                "SELECT * FROM project_alias_corrections WHERE status='confirmed'"
            ).fetchall()
        ]
        catalog = load_project_catalog(PROJECT_INDEX_PATH)
        target = normalize_match_text(payload.raw_project_name)
        matched_documents = 0
        for document in connection.execute(
            "SELECT id,title,source,content,document_role FROM documents"
        ).fetchall():
            haystack = normalize_match_text(
                f"{document['title']} {Path(str(document['source'])).name}"
            )
            if target not in haystack:
                continue
            metadata = infer_document_metadata(
                str(document["title"]), str(document["source"]),
                str(document["content"]), str(document["document_role"]),
                catalog, corrections,
            )
            if metadata["canonical_project_name"] != payload.canonical_project_name.strip():
                continue
            connection.execute(
                """
                UPDATE documents SET canonical_project_name=?,region=?,document_stage=?,
                    validity_status=?,policy_year=?,batch=?,replacement_title=?,
                    replacement_basis=?,replacement_url=? WHERE id=?
                """,
                (
                    metadata["canonical_project_name"], metadata["region"],
                    metadata["document_stage"], metadata["validity_status"],
                    metadata["policy_year"], metadata["batch"],
                    metadata["replacement_title"], metadata["replacement_basis"],
                    metadata["replacement_url"], int(document["id"]),
                ),
            )
            connection.execute(
                """
                UPDATE public_list_entities SET canonical_project_name=?,policy_year=?,
                    batch=?,region=?,list_status=? WHERE document_id=?
                """,
                (
                    metadata["canonical_project_name"], metadata["policy_year"],
                    metadata["batch"], metadata["region"], metadata["document_stage"],
                    int(document["id"]),
                ),
            )
            connection.execute(
                """
                DELETE FROM metadata_match_evidence
                WHERE document_id=?
                  AND match_method NOT IN ('official_manual_review','official_cluster_propagation')
                """,
                (int(document["id"]),),
            )
            connection.execute(
                "DELETE FROM policy_verification_queue WHERE document_id=? AND status='pending'",
                (int(document["id"]),),
            )
            insert_metadata_audit_records(
                connection, int(document["id"]), str(document["document_role"]), metadata
            )
            matched_documents += 1
        rebuild_policy_document_clusters(connection)
        return {"correction": dict(correction), "matched_documents": matched_documents, "snapshot_created": True}

    return dict(_mutate_content_index("alias-correction", apply))


def preview_project_alias_correction(payload: ProjectAliasCorrectionRequest) -> dict[str, object]:
    if payload.start_year and payload.end_year and payload.start_year > payload.end_year:
        raise HTTPException(status_code=422, detail="起始年度不能晚于结束年度")
    from scripts.build_knowledge_content_index import (
        infer_document_metadata,
        load_project_catalog,
        normalize_match_text,
    )

    catalog = load_project_catalog(PROJECT_INDEX_PATH)
    target = normalize_match_text(payload.raw_project_name)
    with closing(content_database()) as connection:
        corrections = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM project_alias_corrections WHERE status='confirmed'"
            ).fetchall()
        ]
        corrections.append(
            {
                **payload.model_dump(),
                "status": "confirmed",
            }
        )
        affected: list[dict[str, object]] = []
        for document in connection.execute(
            "SELECT id,title,source,content,document_role,canonical_project_name,region,policy_year "
            "FROM documents ORDER BY id"
        ).fetchall():
            haystack = normalize_match_text(
                f"{document['title']} {Path(str(document['source'])).name}"
            )
            if target not in haystack:
                continue
            metadata = infer_document_metadata(
                str(document["title"]), str(document["source"]),
                str(document["content"]), str(document["document_role"]),
                catalog, corrections,
            )
            if metadata["canonical_project_name"] != payload.canonical_project_name.strip():
                continue
            affected.append(
                {
                    "document_id": int(document["id"]),
                    "title": str(document["title"]),
                    "source": str(document["source"]),
                    "before": str(document["canonical_project_name"] or "未映射"),
                    "after": str(metadata["canonical_project_name"]),
                    "detail": f"地区：{document['region'] or '未识别'} → {metadata['region'] or '未识别'}；"
                    f"年度：{document['policy_year'] or '未识别'} → {metadata['policy_year'] or '未识别'}",
                }
            )
    return {"total": len(affected), "results": affected[:200]}


def preview_policy_verification(payload: PolicyVerificationReviewRequest) -> dict[str, object]:
    if payload.status == "verified" and not payload.official_source_url.strip():
        raise HTTPException(status_code=422, detail="确认政策时必须填写官方网站来源")
    if payload.status == "rejected" and payload.validity_status:
        raise HTTPException(status_code=422, detail="驳回核验时不能同时写入政策有效性")
    with closing(content_database()) as connection:
        queue_row = connection.execute(
            "SELECT q.*,d.title FROM policy_verification_queue q "
            "JOIN documents d ON d.id=q.document_id WHERE q.id=?",
            (payload.queue_id,),
        ).fetchone()
        if queue_row is None:
            raise HTTPException(status_code=404, detail="政策核验任务不存在")
        membership = connection.execute(
            "SELECT cluster_id FROM policy_document_cluster_members WHERE document_id=?",
            (int(queue_row["document_id"]),),
        ).fetchone()
        document_ids = (
            _policy_cluster_document_ids(connection, int(membership["cluster_id"]))
            if membership and payload.propagate_cluster
            else [int(queue_row["document_id"])]
        )
        placeholders = ",".join("?" for _ in document_ids)
        rows = connection.execute(
            f"SELECT id,title,source,validity_status FROM documents WHERE id IN ({placeholders}) ORDER BY id",
            document_ids,
        ).fetchall()
    target_status = payload.validity_status or "保持原值"
    return {
        "total": len(rows),
        "cluster_id": int(membership["cluster_id"]) if membership else None,
        "results": [
            {
                "document_id": int(row["id"]),
                "title": str(row["title"]),
                "source": str(row["source"]),
                "before": str(row["validity_status"] or "未识别"),
                "after": target_status,
                "detail": f"核验结论：{payload.status}；官方标题：{payload.official_document_title or '未填写'}",
            }
            for row in rows
        ],
    }


def review_policy_verification(
    payload: PolicyVerificationReviewRequest,
    verified_by: str,
) -> dict[str, object]:
    if payload.status == "verified" and not payload.official_source_url.strip():
        raise HTTPException(status_code=422, detail="确认政策时必须填写官方网站来源")
    if payload.status == "rejected" and payload.validity_status:
        raise HTTPException(status_code=422, detail="驳回核验时不能同时写入政策有效性")

    def apply(connection: sqlite3.Connection) -> dict[str, object]:
        from scripts.build_knowledge_content_index import (
            POLICY_CLUSTER_RULE_VERSION,
            ensure_policy_cluster_schema,
            rebuild_policy_document_clusters,
        )

        ensure_policy_cluster_schema(connection)
        rebuild_policy_document_clusters(connection)
        queue_row = connection.execute(
            "SELECT * FROM policy_verification_queue WHERE id=?", (payload.queue_id,)
        ).fetchone()
        if queue_row is None:
            raise HTTPException(status_code=404, detail="核验任务不存在")
        membership = connection.execute(
            """
            SELECT m.cluster_id,c.cluster_key,c.document_number,c.match_method,c.confidence
            FROM policy_document_cluster_members m
            JOIN policy_document_clusters c ON c.id=m.cluster_id
            WHERE m.document_id=?
            """,
            (int(queue_row["document_id"]),),
        ).fetchone()
        cluster_id = int(membership["cluster_id"]) if membership else 0
        if payload.propagate_cluster and membership:
            target_document_ids = [
                int(row[0])
                for row in connection.execute(
                    "SELECT document_id FROM policy_document_cluster_members WHERE cluster_id=? ORDER BY document_id",
                    (cluster_id,),
                ).fetchall()
            ]
        else:
            target_document_ids = [int(queue_row["document_id"])]
        now = isoformat(utc_now())
        placeholders = ",".join("?" for _ in target_document_ids)
        connection.execute(
            f"""
            UPDATE policy_verification_queue
            SET status=?,official_source_url=?,official_document_title=?,
                official_published_at=?,verification_note=?,verified_by=?,
                verified_at=?,updated_at=?
            WHERE reason=? AND document_id IN ({placeholders})
              AND (status='pending' OR id=?)
            """,
            (
                payload.status, payload.official_source_url.strip(),
                payload.official_document_title.strip(), payload.official_published_at,
                payload.verification_note.strip(), verified_by, now, now,
                str(queue_row["reason"]), *target_document_ids, payload.queue_id,
            ),
        )
        if payload.validity_status and payload.status == "verified":
            connection.execute(
                f"UPDATE documents SET validity_status=? WHERE id IN ({placeholders})",
                (payload.validity_status, *target_document_ids),
            )
            for target_document_id in target_document_ids:
                is_source = target_document_id == int(queue_row["document_id"])
                method = "official_manual_review" if is_source else "official_cluster_propagation"
                excerpt = payload.official_source_url.strip()
                if not is_source:
                    excerpt = (
                        f"从文档#{int(queue_row['document_id'])}的官方核验传播；"
                        f"同源簇#{cluster_id}；{payload.official_source_url.strip()}"
                    )
                evidence_update = connection.execute(
                    """
                    UPDATE metadata_match_evidence
                    SET inferred_value=?,matched_term=?,match_method=?,
                        source_scope='official_source',source_excerpt=?,confidence='high',
                        review_status='confirmed',rule_version=?,created_at=?
                    WHERE document_id=? AND field_name='validity_status'
                      AND match_method IN ('official_manual_review','official_cluster_propagation')
                    """,
                    (
                        payload.validity_status, payload.official_document_title.strip(),
                        method, excerpt[:800], POLICY_CLUSTER_RULE_VERSION, now,
                        target_document_id,
                    ),
                )
                if evidence_update.rowcount == 0:
                    connection.execute(
                        """
                        INSERT INTO metadata_match_evidence(
                            document_id,field_name,inferred_value,matched_term,match_method,
                            source_scope,source_excerpt,rule_version,confidence,review_status,
                            correction_id,created_at
                        ) VALUES (?,'validity_status',?,?,?,'official_source',?,?,'high',
                                  'confirmed',NULL,?)
                        """,
                        (
                            target_document_id, payload.validity_status,
                            payload.official_document_title.strip(), method, excerpt[:800],
                            POLICY_CLUSTER_RULE_VERSION, now,
                        ),
                    )
                if not is_source and cluster_id:
                    connection.execute(
                        """
                        INSERT INTO policy_verification_propagations(
                            source_queue_id,cluster_id,source_document_id,target_document_id,
                            field_name,propagated_value,official_source_url,evidence_excerpt,
                            rule_version,propagated_by,propagated_at
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(source_queue_id,target_document_id,field_name) DO UPDATE SET
                            propagated_value=excluded.propagated_value,
                            official_source_url=excluded.official_source_url,
                            evidence_excerpt=excluded.evidence_excerpt,
                            rule_version=excluded.rule_version,
                            propagated_by=excluded.propagated_by,
                            propagated_at=excluded.propagated_at
                        """,
                        (
                            payload.queue_id, cluster_id, int(queue_row["document_id"]),
                            target_document_id, "validity_status", payload.validity_status,
                            payload.official_source_url.strip(), excerpt[:800],
                            POLICY_CLUSTER_RULE_VERSION, verified_by, now,
                        ),
                    )
        elif cluster_id:
            for target_document_id in target_document_ids:
                if target_document_id == int(queue_row["document_id"]):
                    continue
                excerpt = (
                    f"从文档#{int(queue_row['document_id'])}的核验结论传播；"
                    f"同源簇#{cluster_id}；{payload.verification_note.strip()}"
                )
                connection.execute(
                    """
                    INSERT INTO policy_verification_propagations(
                        source_queue_id,cluster_id,source_document_id,target_document_id,
                        field_name,propagated_value,official_source_url,evidence_excerpt,
                        rule_version,propagated_by,propagated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(source_queue_id,target_document_id,field_name) DO UPDATE SET
                        propagated_value=excluded.propagated_value,
                        official_source_url=excluded.official_source_url,
                        evidence_excerpt=excluded.evidence_excerpt,
                        rule_version=excluded.rule_version,
                        propagated_by=excluded.propagated_by,
                        propagated_at=excluded.propagated_at
                    """,
                    (
                        payload.queue_id, cluster_id, int(queue_row["document_id"]),
                        target_document_id, "verification_status", payload.status,
                        payload.official_source_url.strip(), excerpt[:800],
                        POLICY_CLUSTER_RULE_VERSION, verified_by, now,
                    ),
                )
        reviewed = connection.execute(
            """
            SELECT q.*,d.title,d.canonical_project_name,d.region,d.document_stage,d.validity_status
            FROM policy_verification_queue q JOIN documents d ON d.id=q.document_id
            WHERE q.id=?
            """,
            (payload.queue_id,),
        ).fetchone()
        reviewed_tasks = int(
            connection.execute(
                f"SELECT COUNT(*) FROM policy_verification_queue WHERE reason=? AND document_id IN ({placeholders}) AND status=?",
                (str(queue_row["reason"]), *target_document_ids, payload.status),
            ).fetchone()[0]
        )
        return {
            "review": dict(reviewed),
            "cluster": dict(membership) if membership else None,
            "cluster_documents": len(target_document_ids),
            "propagated_documents": max(0, len(target_document_ids) - 1),
            "reviewed_tasks": reviewed_tasks,
            "snapshot_created": True,
        }

    return dict(_mutate_content_index("policy-verification", apply))


def _policy_cluster_document_ids(connection: sqlite3.Connection, cluster_id: int) -> list[int]:
    return [
        int(row[0])
        for row in connection.execute(
            "SELECT document_id FROM policy_document_cluster_members WHERE cluster_id=? ORDER BY document_id",
            (cluster_id,),
        ).fetchall()
    ]


def _policy_manual_assignment_snapshot(
    connection: sqlite3.Connection, document_ids: list[int]
) -> dict[str, dict[str, object] | None]:
    placeholders = ",".join("?" for _ in document_ids)
    rows = connection.execute(
        f"SELECT * FROM policy_cluster_manual_assignments WHERE document_id IN ({placeholders})",
        document_ids,
    ).fetchall()
    existing = {str(row["document_id"]): dict(row) for row in rows}
    return {str(document_id): existing.get(str(document_id)) for document_id in document_ids}


def split_policy_document_cluster(
    cluster_id: int,
    document_ids: list[int],
    note: str,
    operated_by: str,
) -> dict[str, object]:
    selected_ids = sorted({int(document_id) for document_id in document_ids})
    if not selected_ids:
        raise HTTPException(status_code=422, detail="请至少选择一份需要拆出的文档")

    def apply(connection: sqlite3.Connection) -> dict[str, object]:
        from scripts.build_knowledge_content_index import (
            ensure_policy_cluster_schema,
            rebuild_policy_document_clusters,
        )

        ensure_policy_cluster_schema(connection)
        rebuild_policy_document_clusters(connection)
        cluster_document_ids = _policy_cluster_document_ids(connection, cluster_id)
        if not cluster_document_ids:
            raise HTTPException(status_code=404, detail="政策簇不存在或已发生变化")
        if not set(selected_ids).issubset(cluster_document_ids):
            raise HTTPException(status_code=422, detail="所选文档不属于当前政策簇")
        if len(selected_ids) >= len(cluster_document_ids):
            raise HTTPException(status_code=422, detail="不能拆出政策簇中的全部文档")
        now = isoformat(utc_now())
        manual_key = f"manual:split:{secrets.token_hex(12)}"
        previous_assignments = _policy_manual_assignment_snapshot(connection, selected_ids)
        connection.executemany(
            """
            INSERT INTO policy_cluster_manual_assignments(
                document_id,manual_cluster_key,operation_type,note,updated_by,updated_at
            ) VALUES (?,?,'split',?,?,?)
            ON CONFLICT(document_id) DO UPDATE SET
                manual_cluster_key=excluded.manual_cluster_key,
                operation_type=excluded.operation_type,note=excluded.note,
                updated_by=excluded.updated_by,updated_at=excluded.updated_at
            """,
            ((document_id, manual_key, note.strip(), operated_by, now) for document_id in selected_ids),
        )
        connection.execute(
            """
            INSERT INTO policy_cluster_manual_operations(
                operation_type,source_cluster_ids,document_ids,target_manual_cluster_key,
                note,operated_by,operated_at,previous_assignments
            ) VALUES ('split',?,?,?,?,?,?,?)
            """,
            (
                json.dumps([cluster_id]), json.dumps(selected_ids), manual_key,
                note.strip(), operated_by, now,
                json.dumps(previous_assignments, ensure_ascii=False),
            ),
        )
        rebuild_policy_document_clusters(connection)
        new_cluster = connection.execute(
            "SELECT id FROM policy_document_clusters WHERE cluster_key=?", (manual_key,)
        ).fetchone()
        return {
            "operation": "split",
            "source_cluster_id": cluster_id,
            "target_cluster_id": int(new_cluster[0]),
            "moved_documents": len(selected_ids),
        }

    return dict(_mutate_content_index("policy-cluster-split", apply))


def merge_policy_document_clusters(
    source_cluster_id: int,
    target_cluster_id: int,
    note: str,
    operated_by: str,
) -> dict[str, object]:
    if source_cluster_id == target_cluster_id:
        raise HTTPException(status_code=422, detail="不能将政策簇合并到自身")

    def apply(connection: sqlite3.Connection) -> dict[str, object]:
        from scripts.build_knowledge_content_index import (
            ensure_policy_cluster_schema,
            rebuild_policy_document_clusters,
        )

        ensure_policy_cluster_schema(connection)
        rebuild_policy_document_clusters(connection)
        source_ids = _policy_cluster_document_ids(connection, source_cluster_id)
        target_ids = _policy_cluster_document_ids(connection, target_cluster_id)
        if not source_ids or not target_ids:
            raise HTTPException(status_code=404, detail="源政策簇或目标政策簇不存在")
        merged_ids = sorted(set(source_ids + target_ids))
        now = isoformat(utc_now())
        manual_key = f"manual:merge:{secrets.token_hex(12)}"
        previous_assignments = _policy_manual_assignment_snapshot(connection, merged_ids)
        connection.executemany(
            """
            INSERT INTO policy_cluster_manual_assignments(
                document_id,manual_cluster_key,operation_type,note,updated_by,updated_at
            ) VALUES (?,?,'merge',?,?,?)
            ON CONFLICT(document_id) DO UPDATE SET
                manual_cluster_key=excluded.manual_cluster_key,
                operation_type=excluded.operation_type,note=excluded.note,
                updated_by=excluded.updated_by,updated_at=excluded.updated_at
            """,
            ((document_id, manual_key, note.strip(), operated_by, now) for document_id in merged_ids),
        )
        connection.execute(
            """
            INSERT INTO policy_cluster_manual_operations(
                operation_type,source_cluster_ids,document_ids,target_manual_cluster_key,
                note,operated_by,operated_at,previous_assignments
            ) VALUES ('merge',?,?,?,?,?,?,?)
            """,
            (
                json.dumps([source_cluster_id, target_cluster_id]),
                json.dumps(merged_ids), manual_key, note.strip(), operated_by, now,
                json.dumps(previous_assignments, ensure_ascii=False),
            ),
        )
        rebuild_policy_document_clusters(connection)
        merged_cluster = connection.execute(
            "SELECT id FROM policy_document_clusters WHERE cluster_key=?", (manual_key,)
        ).fetchone()
        return {
            "operation": "merge",
            "source_cluster_ids": [source_cluster_id, target_cluster_id],
            "target_cluster_id": int(merged_cluster[0]),
            "merged_documents": len(merged_ids),
        }

    return dict(_mutate_content_index("policy-cluster-merge", apply))


def undo_policy_cluster_operation(operation_id: int, undone_by: str) -> dict[str, object]:
    def apply(connection: sqlite3.Connection) -> dict[str, object]:
        from scripts.build_knowledge_content_index import (
            ensure_policy_cluster_schema,
            rebuild_policy_document_clusters,
        )

        ensure_policy_cluster_schema(connection)
        operation = connection.execute(
            "SELECT * FROM policy_cluster_manual_operations WHERE id=?", (operation_id,)
        ).fetchone()
        if operation is None:
            raise HTTPException(status_code=404, detail="人工政策簇操作不存在")
        if operation["undone_at"]:
            raise HTTPException(status_code=409, detail="该操作已经撤销")
        document_ids = {int(value) for value in json.loads(str(operation["document_ids"]))}
        later_rows = connection.execute(
            """
            SELECT id,document_ids FROM policy_cluster_manual_operations
            WHERE id>? AND undone_at IS NULL ORDER BY id
            """,
            (operation_id,),
        ).fetchall()
        conflicting = [
            int(row["id"])
            for row in later_rows
            if document_ids.intersection(int(value) for value in json.loads(str(row["document_ids"])))
        ]
        if conflicting:
            raise HTTPException(
                status_code=409,
                detail=f"相关文档存在更晚操作#{conflicting[0]}，请先撤销后续操作",
            )
        previous = json.loads(str(operation["previous_assignments"] or "{}"))
        for document_id in sorted(document_ids):
            assignment = previous.get(str(document_id))
            if assignment is None:
                connection.execute(
                    "DELETE FROM policy_cluster_manual_assignments WHERE document_id=?",
                    (document_id,),
                )
                continue
            connection.execute(
                """
                INSERT INTO policy_cluster_manual_assignments(
                    document_id,manual_cluster_key,operation_type,note,updated_by,updated_at
                ) VALUES (?,?,?,?,?,?)
                ON CONFLICT(document_id) DO UPDATE SET
                    manual_cluster_key=excluded.manual_cluster_key,
                    operation_type=excluded.operation_type,note=excluded.note,
                    updated_by=excluded.updated_by,updated_at=excluded.updated_at
                """,
                (
                    document_id, assignment["manual_cluster_key"], assignment["operation_type"],
                    assignment.get("note", ""), assignment["updated_by"], assignment["updated_at"],
                ),
            )
        now = isoformat(utc_now())
        connection.execute(
            "UPDATE policy_cluster_manual_operations SET undone_by=?,undone_at=? WHERE id=?",
            (undone_by, now, operation_id),
        )
        rebuild_policy_document_clusters(connection)
        return {"operation_id": operation_id, "restored_documents": len(document_ids)}

    return dict(_mutate_content_index("policy-cluster-undo", apply))


def list_policy_cluster_manual_operations(limit: int = 30) -> dict[str, object]:
    with closing(content_database()) as connection:
        schema_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='policy_cluster_manual_operations'"
        ).fetchone()
        if not schema_exists:
            return {"results": [], "total": 0}
        total = int(connection.execute("SELECT COUNT(*) FROM policy_cluster_manual_operations").fetchone()[0])
        rows = connection.execute(
            "SELECT * FROM policy_cluster_manual_operations ORDER BY operated_at DESC,id DESC LIMIT ?",
            (max(1, min(limit, 200)),),
        ).fetchall()
    results = []
    for row in rows:
        item = dict(row)
        item["source_cluster_ids"] = json.loads(str(item["source_cluster_ids"]))
        item["document_ids"] = json.loads(str(item["document_ids"]))
        results.append(item)
    return {"results": results, "total": total}


POLICY_CLAUSE_KEYWORDS = (
    "申报条件", "申报要求", "申报对象", "应当", "不得", "截止", "期限", "有效期",
    "补助", "资助", "奖励", "比例", "评分", "废止", "替代", "实施", "知识产权",
    "研发", "营业收入", "销售收入", "认定条件", "评价指标",
)


def extract_policy_key_clauses(content: str, limit: int = 24) -> list[str]:
    lines = [
        re.sub(r"\s+", " ", item).strip(" -—·\t")
        for item in re.split(r"[\r\n]+|(?<=[。；])", content)
    ]
    lines = [item for item in lines if 10 <= len(item) <= 500]
    selected = [item for item in lines if any(keyword in item for keyword in POLICY_CLAUSE_KEYWORDS)]
    return (selected or lines)[:limit]


def highlight_policy_clause_diff(baseline: str, candidate: str) -> Markup:
    fragments: list[str] = []
    for operation, start_a, end_a, start_b, end_b in SequenceMatcher(
        None, baseline, candidate, autojunk=False
    ).get_opcodes():
        old_text = html.escape(baseline[start_a:end_a])
        new_text = html.escape(candidate[start_b:end_b])
        if operation == "equal":
            fragments.append(new_text)
        elif operation == "insert":
            fragments.append(f'<mark class="diff-add">{new_text}</mark>')
        elif operation == "delete":
            fragments.append(f'<del class="diff-remove">{old_text}</del>')
        else:
            fragments.append(f'<del class="diff-remove">{old_text}</del>')
            fragments.append(f'<mark class="diff-add">{new_text}</mark>')
    return Markup("".join(fragments))


def compare_policy_cluster(cluster_id: int) -> dict[str, object]:
    with closing(content_database()) as connection:
        cluster = connection.execute(
            "SELECT * FROM policy_document_clusters WHERE id=?", (cluster_id,)
        ).fetchone()
        if cluster is None:
            raise HTTPException(status_code=404, detail="政策簇不存在")
        rows = connection.execute(
            """
            SELECT d.id,d.title,d.source,d.content,d.document_number,d.policy_year,
                   d.validity_status,d.document_stage
            FROM policy_document_cluster_members m
            JOIN documents d ON d.id=m.document_id
            WHERE m.cluster_id=? ORDER BY d.id
            """,
            (cluster_id,),
        ).fetchall()
    documents = [dict(row) for row in rows]
    if not documents:
        raise HTTPException(status_code=404, detail="政策簇中没有文档")
    baseline_clauses = extract_policy_key_clauses(str(documents[0]["content"] or ""))
    baseline_text = "\n".join(baseline_clauses)
    comparisons = []
    for document in documents[1:]:
        clauses = extract_policy_key_clauses(str(document["content"] or ""))
        comparisons.append(
            {
                **document,
                "clause_count": len(clauses),
                "diff_html": highlight_policy_clause_diff(baseline_text, "\n".join(clauses)),
            }
        )
    return {
        "cluster": dict(cluster),
        "baseline": {**documents[0], "clauses": baseline_clauses},
        "comparisons": comparisons,
        "document_count": len(documents),
    }


def list_project_alias_corrections(status_filter: str = "", limit: int = 100) -> dict[str, object]:
    conditions, parameters = ["1=1"], []
    if status_filter.strip():
        conditions.append("status=?")
        parameters.append(status_filter.strip())
    with closing(content_database()) as connection:
        rows = connection.execute(
            f"SELECT * FROM project_alias_corrections WHERE {' AND '.join(conditions)} ORDER BY updated_at DESC LIMIT ?",
            [*parameters, max(1, min(limit, 500))],
        ).fetchall()
    return {"results": [dict(row) for row in rows]}


def list_metadata_evidence(review_status: str = "needs_review", confidence: str = "", limit: int = 100) -> dict[str, object]:
    conditions, parameters = ["1=1"], []
    if review_status.strip():
        conditions.append("e.review_status=?")
        parameters.append(review_status.strip())
    if confidence.strip():
        conditions.append("e.confidence=?")
        parameters.append(confidence.strip())
    with closing(content_database()) as connection:
        rows = connection.execute(
            f"""
            SELECT e.*,d.title,d.source,d.document_role
            FROM metadata_match_evidence e JOIN documents d ON d.id=e.document_id
            WHERE {' AND '.join(conditions)}
            ORDER BY CASE e.confidence WHEN 'low' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                     e.document_id,e.field_name LIMIT ?
            """,
            [*parameters, max(1, min(limit, 500))],
        ).fetchall()
    return {"results": [dict(row) for row in rows]}


def _active_learning_project_phrase(title: str) -> str:
    """Extract a reviewable project phrase without treating it as confirmed metadata."""
    phrase = Path(title).stem
    phrase = re.sub(r"^(?:附件|[附件一二三四五六七八九十\d]+)[：:]\s*", "", phrase)
    phrase = re.sub(r"(?:19|20)\d{2}\s*年度?", "", phrase)
    phrase = re.sub(r"^[\s\d._-]+", "", phrase)
    phrase = re.sub(r"第[一-龥\d]+批(?:次)?", "", phrase)
    phrase = re.sub(
        r"^.*?关于(?:组织)?(?:开展|做好|申报|推荐|征集|遘选)",
        "",
        phrase,
    )
    phrase = re.sub(
        r"^(?:关于)?(?:组织)?(?:开展|申报|推荐|评选|认定|征集|遘选)+",
        "",
        phrase,
    )
    phrase = re.sub(
        r"(?:申报通知|工作通知|认定通知|公示名单|认定名单|结果公示|申报指南|实施细则|管理办法|评价标准|征求意见稿|通知|公示|名单)$",
        "",
        phrase,
    )
    phrase = re.sub(r"(?:工作的?|工作)$", "", phrase)
    phrase = re.sub(r"[《》【】（）()]", "", phrase)
    phrase = re.sub(r"[\s_—–-]+", "", phrase).strip()
    return phrase or Path(title).stem.strip()


def _normalized_learning_text(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value.lower())


def _suggest_project_alias(project_phrase: str) -> tuple[str, float]:
    target = _normalized_learning_text(project_phrase)
    if not target:
        return "", 0.0
    best_name, best_score = "", 0.0
    for record in load_project_index_records():
        canonical = str(record.get("canonical_project_name") or "").strip()
        terms = [canonical, *[str(item) for item in record.get("aliases", [])]]
        for term in terms:
            normalized = _normalized_learning_text(term)
            if not normalized:
                continue
            if target in normalized or normalized in target:
                score = min(len(target), len(normalized)) / max(len(target), len(normalized))
                score = max(score, 0.74)
            else:
                score = SequenceMatcher(None, target, normalized).ratio()
            if score > best_score:
                best_name, best_score = canonical, score
    return (best_name, round(best_score, 3)) if best_score >= 0.42 else ("", round(best_score, 3))


def list_active_learning_alias_candidates(limit: int = 100) -> dict[str, object]:
    """Rank unconfirmed project aliases by downstream impact and application risk."""
    with closing(content_database()) as connection:
        rows = connection.execute(
            """
            SELECT d.id,d.title,d.source,d.document_role,d.document_stage,d.region,
                   d.policy_year,d.updated_at,COUNT(e.id) AS list_entities
            FROM documents d
            LEFT JOIN public_list_entities e ON e.document_id=d.id
            WHERE trim(d.canonical_project_name)=''
              AND (d.document_role LIKE '10_%' OR d.document_role LIKE '20_%'
                   OR d.document_role LIKE '50_%')
            GROUP BY d.id
            ORDER BY d.id
            """
        ).fetchall()
        confirmed_aliases = {
            _normalized_learning_text(str(row["raw_project_name"]))
            for row in connection.execute(
                "SELECT raw_project_name FROM project_alias_corrections WHERE status='confirmed'"
            ).fetchall()
        }
    groups: dict[str, dict[str, object]] = {}
    current_year = utc_now().astimezone(ASSISTANT_TIMEZONE).year
    high_risk_stages = {"申报通知", "管理办法", "实施细则", "申报指南", "评价标准"}
    for row in rows:
        phrase = _active_learning_project_phrase(str(row["title"]))
        key = _normalized_learning_text(phrase)
        generic_phrases = {
            "目录", "附件", "通知", "公示", "名单", "申报办法", "人员网上申报办法",
            "申报材料", "申报指南", "申报要求", "管理办法", "实施细则",
        }
        if len(key) < 4 or key in generic_phrases or key in confirmed_aliases:
            continue
        group = groups.setdefault(
            key,
            {
                "raw_project_name": phrase,
                "impacted_documents": 0,
                "impacted_list_entities": 0,
                "high_risk_documents": 0,
                "recent_documents": 0,
                "regions": set(),
                "sample_titles": [],
                "sample_documents": [],
            },
        )
        group["impacted_documents"] = int(group["impacted_documents"]) + 1
        group["impacted_list_entities"] = int(group["impacted_list_entities"]) + int(row["list_entities"] or 0)
        stage = str(row["document_stage"] or "")
        role = str(row["document_role"] or "")
        if role.startswith(("10_", "20_")) or stage in high_risk_stages:
            group["high_risk_documents"] = int(group["high_risk_documents"]) + 1
        if int(row["policy_year"] or 0) >= current_year - 1:
            group["recent_documents"] = int(group["recent_documents"]) + 1
        if row["region"]:
            group["regions"].add(str(row["region"]))
        if len(group["sample_titles"]) < 3:
            group["sample_titles"].append(str(row["title"]))
            group["sample_documents"].append(
                {"document_id": int(row["id"]), "title": str(row["title"])}
            )

    ranked: list[dict[str, object]] = []
    for group in groups.values():
        documents = int(group["impacted_documents"])
        entities = int(group["impacted_list_entities"])
        risky = int(group["high_risk_documents"])
        recent = int(group["recent_documents"])
        impact_points = min(35.0, documents * 7.0)
        entity_points = min(20.0, math.log10(entities + 1) * 8.0)
        risk_points = min(30.0, risky * 12.0)
        recency_points = min(15.0, recent * 5.0)
        reasons = [f"影响 {documents} 份文档"]
        if entities:
            reasons.append(f"关联 {entities} 条名单实体")
        if risky:
            reasons.append(f"{risky} 份高风险政策文档")
        if recent:
            reasons.append(f"{recent} 份近两年资料")
        ranked.append(
            {
                **group,
                "regions": sorted(group["regions"]),
                "learning_score": round(impact_points + entity_points + risk_points + recency_points, 1),
                "score_breakdown": {
                    "document_impact": round(impact_points, 1),
                    "list_impact": round(entity_points, 1),
                    "application_risk": round(risk_points, 1),
                    "recency": round(recency_points, 1),
                },
                "learning_reasons": reasons,
            }
        )
    ranked.sort(
        key=lambda item: (
            -float(item["learning_score"]),
            -int(item["impacted_documents"]),
            str(item["raw_project_name"]),
        )
    )
    limited = ranked[: max(1, min(limit, 500))]
    for item in limited:
        suggestion, similarity = _suggest_project_alias(str(item["raw_project_name"]))
        item["suggested_canonical_project_name"] = suggestion
        item["suggestion_similarity"] = similarity
    return {"results": limited, "total": len(ranked)}


def list_policy_verification_queue(status_filter: str = "pending", priority: str = "", limit: int = 100) -> dict[str, object]:
    conditions, parameters = ["1=1"], []
    if status_filter.strip():
        conditions.append("q.status=?")
        parameters.append(status_filter.strip())
    if priority.strip():
        conditions.append("q.priority=?")
        parameters.append(priority.strip())
    with closing(content_database()) as connection:
        cluster_schema = bool(
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='policy_document_cluster_members'"
            ).fetchone()
        )
        cluster_fields = (
            "m.cluster_id,c.cluster_key,c.document_number,c.match_method AS cluster_match_method,"
            "c.confidence AS cluster_confidence,"
            "(SELECT COUNT(*) FROM policy_document_cluster_members cm WHERE cm.cluster_id=m.cluster_id) AS cluster_document_count"
            if cluster_schema
            else "NULL AS cluster_id,'' AS cluster_key,'' AS document_number,'' AS cluster_match_method,'' AS cluster_confidence,1 AS cluster_document_count"
        )
        cluster_joins = (
            "LEFT JOIN policy_document_cluster_members m ON m.document_id=d.id "
            "LEFT JOIN policy_document_clusters c ON c.id=m.cluster_id"
            if cluster_schema
            else ""
        )
        rows = connection.execute(
            f"""
            SELECT q.*,d.title,d.source,d.canonical_project_name,d.region,
                   d.document_stage,d.validity_status,d.policy_year,{cluster_fields}
            FROM policy_verification_queue q JOIN documents d ON d.id=q.document_id
            {cluster_joins}
            WHERE {' AND '.join(conditions)}
            ORDER BY q.id
            """,
            parameters,
        ).fetchall()
        document_impact = {
            str(row["canonical_project_name"]): int(row["count"])
            for row in connection.execute(
                "SELECT canonical_project_name,COUNT(*) AS count FROM documents WHERE trim(canonical_project_name)<>'' GROUP BY canonical_project_name"
            ).fetchall()
        }
        entity_impact = {
            str(row["canonical_project_name"]): int(row["count"])
            for row in connection.execute(
                "SELECT canonical_project_name,COUNT(*) AS count FROM public_list_entities WHERE trim(canonical_project_name)<>'' GROUP BY canonical_project_name"
            ).fetchall()
        }
        member_map: dict[int, list[dict[str, object]]] = {}
        cluster_ids = sorted({int(row["cluster_id"]) for row in rows if row["cluster_id"]})
        if cluster_ids:
            placeholders = ",".join("?" for _ in cluster_ids)
            for member in connection.execute(
                f"""
                SELECT m.cluster_id,d.id AS document_id,d.title,d.source,d.document_role
                FROM policy_document_cluster_members m
                JOIN documents d ON d.id=m.document_id
                WHERE m.cluster_id IN ({placeholders})
                ORDER BY m.cluster_id,d.id
                """,
                cluster_ids,
            ).fetchall():
                member_map.setdefault(int(member["cluster_id"]), []).append(dict(member))
    grouped_rows: dict[tuple[object, str], dict[str, object]] = {}
    priority_rank = {"high": 0, "medium": 1, "low": 2}
    for row in rows:
        item = dict(row)
        group_key = (
            int(item["cluster_id"]) if item.get("cluster_id") else f"document:{item['document_id']}",
            str(item["reason"]),
        )
        existing = grouped_rows.get(group_key)
        if existing is None or priority_rank.get(str(item["priority"]), 3) < priority_rank.get(str(existing["priority"]), 3):
            item["cluster_pending_tasks"] = int(existing["cluster_pending_tasks"]) + 1 if existing else 1
            grouped_rows[group_key] = item
        else:
            existing["cluster_pending_tasks"] = int(existing["cluster_pending_tasks"]) + 1
    current_year = utc_now().astimezone(ASSISTANT_TIMEZONE).year
    stage_weight = {"申报通知": 25, "管理办法": 22, "实施细则": 18, "申报指南": 16, "评价标准": 16}
    validity_weight = {"active_candidate": 18, "trial": 12, "revised": 12, "draft": 8}
    ranked: list[dict[str, object]] = []
    for item in grouped_rows.values():
        canonical = str(item.get("canonical_project_name") or "")
        related_documents = document_impact.get(canonical, 1) if canonical else 1
        related_entities = entity_impact.get(canonical, 0) if canonical else 0
        priority_points = {"high": 45, "medium": 25, "low": 10}.get(str(item.get("priority")), 10)
        stage_points = stage_weight.get(str(item.get("document_stage")), 6)
        validity_points = validity_weight.get(str(item.get("validity_status")), 3)
        missing_project_points = 18 if not canonical else 0
        year = int(item.get("policy_year") or 0)
        recency_points = 15 if year >= current_year else (8 if year == current_year - 1 else 0)
        cluster_documents = int(item.get("cluster_document_count") or 1)
        cluster_points = min(12.0, max(0, cluster_documents - 1) * 4.0)
        impact_points = min(
            20.0,
            related_documents * 2.0
            + math.log10(related_entities + 1) * 4.0
            + cluster_points,
        )
        score = priority_points + stage_points + validity_points + missing_project_points + recency_points + impact_points
        reasons = [f"{item.get('priority', 'low')} 优先级待核验", f"{item.get('document_stage') or '其他'}阶段"]
        if not canonical:
            reasons.append("未映射标准项目")
        if related_documents > 1:
            reasons.append(f"影响同项目 {related_documents} 份文档")
        if related_entities:
            reasons.append(f"关联 {related_entities} 条名单实体")
        if cluster_documents > 1:
            reasons.append(f"同源文档簇共 {cluster_documents} 份")
        if recency_points:
            reasons.append("近期申报年度")
        item.update(
            {
                "related_documents": related_documents,
                "related_list_entities": related_entities,
                "cluster_members": member_map.get(int(item["cluster_id"]), []) if item.get("cluster_id") else [],
                "learning_score": round(score, 1),
                "score_breakdown": {
                    "queue_priority": priority_points,
                    "application_stage": stage_points,
                    "validity_risk": validity_points,
                    "missing_project": missing_project_points,
                    "recency": recency_points,
                    "downstream_impact": round(impact_points, 1),
                    "duplicate_cluster": round(cluster_points, 1),
                },
                "learning_reasons": reasons,
            }
        )
        ranked.append(item)
    ranked.sort(key=lambda item: (-float(item["learning_score"]), int(item["id"])))
    limited = ranked[: max(1, min(limit, 500))]
    return {
        "results": limited,
        "total": len(ranked),
        "high_priority_total": sum(1 for item in ranked if item.get("priority") == "high"),
    }


def list_policy_verification_propagations(limit: int = 100) -> dict[str, object]:
    with closing(content_database()) as connection:
        if not connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='policy_verification_propagations'"
        ).fetchone():
            return {"results": [], "total": 0}
        total = int(
            connection.execute("SELECT COUNT(*) FROM policy_verification_propagations").fetchone()[0]
        )
        rows = connection.execute(
            """
            SELECT p.*,c.document_number,c.match_method AS cluster_match_method,
                   source.title AS source_title,target.title AS target_title,
                   target.source AS target_source
            FROM policy_verification_propagations p
            JOIN policy_document_clusters c ON c.id=p.cluster_id
            JOIN documents source ON source.id=p.source_document_id
            JOIN documents target ON target.id=p.target_document_id
            ORDER BY p.id DESC LIMIT ?
            """,
            (max(1, min(limit, 500)),),
        ).fetchall()
    return {"results": [dict(row) for row in rows], "total": total}


def assistant_chat_url(api_base: str | None = None) -> str:
    base = (api_base or AI_API_BASE).rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def request_assistant_model(
    messages: list[dict[str, object]],
    model_config: dict[str, str] | None = None,
) -> dict[str, object]:
    config = model_config or {"api_base": AI_API_BASE, "api_key": AI_API_KEY, "model": AI_MODEL}
    payload = {
        "model": config["model"],
        "temperature": 0.2,
        "messages": messages,
        "tools": assistant_tool_schemas(),
        "tool_choice": "auto",
    }
    request = urllib.request.Request(
        assistant_chat_url(config["api_base"]),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {config['api_key']}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=AI_TIMEOUT_SECONDS) as response:
        body = json.loads(response.read().decode("utf-8"))
    return body["choices"][0]["message"]


def execute_assistant_tool(name: str, arguments: dict[str, object]) -> tuple[dict[str, object], list[dict[str, object]]]:
    if name == "knowledge_search":
        query = str(arguments.get("query") or "").strip()[:500]
        if not query:
            raise ValueError("检索词不能为空")
        limit = max(1, min(int(arguments.get("limit") or 5), 8))
        result = search_knowledge(query, limit)
        return result, list(result["results"])
    if name == "knowledge_document":
        document_id = int(arguments.get("document_id") or 0)
        if document_id < 1:
            raise ValueError("文档编号无效")
        document = get_knowledge_document(document_id)
        tool_document = dict(document)
        tool_document["content"] = str(tool_document["content"])[:12000]
        return tool_document, [document]
    if name == "public_list_search":
        result = search_public_list_entities(
            enterprise_name=str(arguments.get("enterprise_name") or "")[:200],
            project_name=str(arguments.get("project_name") or "")[:200],
            year=int(arguments["year"]) if arguments.get("year") is not None else None,
            batch=str(arguments.get("batch") or "")[:50],
            region=str(arguments.get("region") or "")[:100],
            limit=max(1, min(int(arguments.get("limit") or 20), 50)),
        )
        sources = [dict(item) for item in result["results"]]
        return result, sources
    if name == "policy_search":
        result = search_policy_documents(
            query=str(arguments.get("query") or "")[:500],
            project_name=str(arguments.get("project_name") or "")[:200],
            region=str(arguments.get("region") or "")[:100],
            document_stage=str(arguments.get("document_stage") or "")[:100],
            validity_status=str(arguments.get("validity_status") or "")[:50],
            year=int(arguments["year"]) if arguments.get("year") is not None else None,
            limit=max(1, min(int(arguments.get("limit") or 8), 20)),
        )
        sources = [dict(item) for item in result["results"]]
        return result, sources
    if name == "project_catalog_match":
        regions = arguments.get("regions") or []
        keywords = arguments.get("keywords") or []
        if not isinstance(regions, list) or not isinstance(keywords, list):
            raise ValueError("地区和关键词必须使用数组")
        return (
            match_project_catalog(
                regions=[str(region)[:100] for region in regions[:20]],
                keywords=[str(keyword)[:100] for keyword in keywords[:30]],
                limit=max(1, min(int(arguments.get("limit") or 20), 50)),
            ),
            [],
        )
    if name == "skill_guidance":
        skill_name = str(arguments.get("skill_name") or "")
        return {"skill_name": skill_name, "guidance": skill_guidance(skill_name, SKILL_SOURCE_DIR)}, []
    raise ValueError("不允许调用未登记工具")


def merge_assistant_sources(*groups: list[dict[str, object]]) -> list[dict[str, object]]:
    merged: list[dict[str, object]] = []
    seen: set[int] = set()
    for group in groups:
        for item in group:
            document_id = int(item["document_id"])
            if document_id in seen:
                continue
            seen.add(document_id)
            merged.append(
                {
                    "document_id": document_id,
                    "title": str(item["title"]),
                    "source": str(item.get("source") or ""),
                }
            )
    return merged


def merge_assistant_sources_for_question(
    question: str,
    *groups: list[dict[str, object]],
) -> list[dict[str, object]]:
    return list(filter_project_results(question, merge_assistant_sources(*groups)))


def assistant_model_error_reason(error: Exception) -> tuple[str, str]:
    if isinstance(error, urllib.error.HTTPError):
        return f"model_http_{error.code}", f"上游模型接口返回HTTP {error.code}"
    if isinstance(error, (urllib.error.URLError, TimeoutError)):
        return "model_network_or_timeout", "模型网络连接或响应超时"
    if isinstance(error, RuntimeError):
        return "tool_round_limit", "模型连续工具调用达到安全轮次上限"
    if isinstance(error, (KeyError, IndexError, json.JSONDecodeError)):
        return "model_response_invalid", "模型返回格式不完整"
    return type(error).__name__, "模型请求未正常完成"


def current_policy_guardrail(question: str) -> str:
    notices: list[str] = []
    if any(term in question for term in ("专精特新", "小巨人", "梯度培育")):
        notices.append(
            "专精特新现行门禁：新申请使用工信部企业〔2026〕2号。工信部企业〔2022〕63号已被替代，"
            "不得用于新申请；仅当期通知明确规定的复核过渡情形可按旧标准。回答必须先说明版本，再列条件。"
        )
    if "杭州市" in question and "研发中心" in question:
        notices.append(
            "杭州研发机构门禁：正式项目名称为杭州市企业高新技术研究开发中心。杭科高〔2022〕39号"
            "在2025年杭州市科技局清理结果中继续有效；旧培训简称和旧讲义只能作历史参考。"
        )
    if any(term in question for term in ("浙江省研发中心", "省级研发中心", "省高企研发中心")):
        notices.append(
            "浙江省研发机构门禁：原省高新技术企业研究开发中心已纳入省企业研究院序列，不再重复申报认定。"
            "新申报优先匹配浙江省企业研究院，更高层级匹配浙江省重点企业研究院，按浙经信高新〔2025〕169号及当期通知。"
        )
    if any(
        term in question
        for term in ("省研究院", "省企业研究院", "省重点研究院", "浙江省企业研究院", "浙江省重点企业研究院")
    ):
        notices.append(
            "浙江省企业研究院门禁：普通层级匹配浙江省企业研究院，更高层级匹配浙江省重点企业研究院。"
            "条件执行浙经信高新〔2025〕169号，并叠加2026年度申报通知；旧科技部门办法、培训解读和历史材料不得替代现行口径。"
        )
    return "\n".join(notices)


def current_policy_fallback(question: str) -> str:
    sections: list[str] = []
    priority_support_program = any(term in question for term in ("重点专精特新", "重点小巨人"))
    if any(term in question for term in ("专精特新", "小巨人", "梯度培育")):
        sections.append(
            "现行版本：新申请统一执行《优质中小企业梯度培育管理办法》工信部企业〔2026〕2号；"
            "工信部企业〔2022〕63号及其旧评分表、培训材料不得用于新申请判断。"
            "2026年度小巨人复核仅在当期通知明确的过渡范围内继续使用旧标准。"
        )
    if priority_support_program:
        sections.append(
            "“重点专精特新”或“重点小巨人”属于支持项目口径，不是新的企业资质层级。"
            "申报对象、支持领域、绩效目标、资金使用和材料要求必须以当年度财政部、工信部及属地主管部门通知为准，"
            "不得直接套用专精特新中小企业或小巨人认定条件替代当期项目条件。"
        )
    elif "小巨人" in question:
        sections.append(
            "专精特新小巨人新申请核心条件：已获专精特新中小企业称号并深耕细分市场满3年；"
            "上年度营业收入不低于5000万元，主营业务收入占比不低于90%，近两年营收复合增长率不低于5%，"
            "资产负债率不超过75%；近两年研发费用合计不低于1200万元且每年研发强度不低于3%；"
            "至少4项与主导产品相关、实际应用并产生经济效益的I类知识产权；"
            "主导产品细分市场占有率达到10%以上或国内前三；位于重点产业链关键环节；"
            "当年度专精特新发展质量评价得分达到60分以上。"
        )
    elif "专精特新" in question or "梯度培育" in question:
        sections.append(
            "专精特新中小企业新申请核心条件：已获科技和创新型中小企业称号并深耕细分市场满3年；"
            "上年度营业收入不低于1500万元，或近两年合格机构投资者实缴股权投资合计不低于2000万元；"
            "主营业务收入占比不低于80%，资产负债率不超过80%；近两年研发费用每年不低于100万元且研发强度不低于3%；"
            "至少1项与主导产品相关、实际应用并产生经济效益的I类知识产权；当年度质量评价得分达到50分以上。"
        )
    if "杭州市" in question and "研发中心" in question:
        sections.append(
            "杭州市现行项目名称为“杭州市企业高新技术研究开发中心”。杭科高〔2022〕39号仍继续有效，"
            "旧培训简称和旧材料清单仅作历史参考。"
        )
    if any(term in question for term in ("浙江省研发中心", "省级研发中心", "省高企研发中心")):
        sections.append(
            "浙江省原“省高新技术企业研究开发中心”已纳入企业研究院序列；新申报匹配“浙江省企业研究院”，"
            "更高层级匹配“浙江省重点企业研究院”，执行浙经信高新〔2025〕169号及当期通知。"
        )
    if any(
        term in question
        for term in ("省研究院", "省企业研究院", "省重点研究院", "浙江省企业研究院", "浙江省重点企业研究院")
    ):
        sections.append(
            "“省研究院”需区分浙江省企业研究院和浙江省重点企业研究院。现行判断执行浙经信高新〔2025〕169号，"
            "并叠加2026年度申报通知；旧科技部门办法、培训解读和历史材料只作历史参考。"
        )
    return "\n\n".join(sections)


def answer_with_knowledge(
    question: str,
    results: list[dict[str, object]],
    progress: Callable[[str, str, dict[str, object]], None] | None = None,
    model_config: dict[str, str] | None = None,
) -> tuple[str, str, list[dict[str, object]], list[str]]:
    def emit(stage: str, message: str, details: dict[str, object] | None = None) -> None:
        if progress:
            progress(stage, message, details or {})

    clean_results = []
    for result in results:
        clean_results.append(
            {
                "title": str(result["title"]),
                "excerpt": re.sub(r"<[^>]+>", "", str(result["excerpt"])),
                "source": str(result.get("source") or ""),
            }
        )
    routed_skills = route_assistant_skills(question)
    emit("skills", f"已加载{len(routed_skills)}项专业Skill", {"skills": routed_skills})
    active_model_config = model_config or {
        "api_base": AI_API_BASE,
        "api_key": AI_API_KEY,
        "model": AI_MODEL,
    }
    if not all(active_model_config.values()):
        emit("fallback", "大模型未配置，使用知识库检索模式整理答案", {})
        policy_fallback = current_policy_fallback(question)
        if policy_fallback:
            emit("compose", "已按现行政策硬门禁生成答复", {"sources": len(results)})
            return policy_fallback, "policy-guardrail", merge_assistant_sources_for_question(question, results), routed_skills
        if not clean_results:
            return (
                "当前团队知识库未命中相关资料。请补充企业、地区、项目名称或年份后再试。",
                "knowledge-search",
                [],
                routed_skills,
            )
        lines = ["当前以免费知识库检索模式返回最相关资料："]
        for index, result in enumerate(clean_results[:4], start=1):
            excerpt = result["excerpt"].strip().replace("\n", " ")
            lines.append(f"{index}. {result['title']}：{excerpt[:220]}")
        lines.append("需要形成正式结论时，请在 Agent 中调用企业全生命周期助手，并核验原文件与当期官方通知。")
        emit("compose", "已按命中资料生成可追溯答复", {"sources": len(results)})
        return "\n".join(lines), "knowledge-search", merge_assistant_sources_for_question(question, results), routed_skills

    context = "\n\n".join(
        f"资料{index}｜{result['title']}\n{result['excerpt']}\n来源：{result['source']}"
        for index, result in enumerate(clean_results[:5], start=1)
    )
    policy_guardrail = current_policy_guardrail(question)
    messages: list[dict[str, object]] = [
            {
                "role": "system",
                "content": (
                    "你是企业全生命周期助手网站答疑员。只能使用本轮加载的专业Skill规则、团队知识片段和只读工具结果。"
                    "先给结论，再给依据和资料缺口；精确政策、企业、专利和财务事实必须可追溯。"
                    "资料不足时明确说明，不承诺企业一定符合或项目一定获批。禁止调用写入、上传、删除、提交或外部联络能力。"
                    f"\n\n现行政策硬门禁：{policy_guardrail or '按知识库政策版本字段和当期官方通知核验。'}"
                    f"\n\n本轮已加载Skills：{', '.join(routed_skills)}\n\n{skill_context(routed_skills, SKILL_SOURCE_DIR)}"
                ),
            },
            {"role": "user", "content": f"问题：{question}\n\n团队知识片段：\n{context or '当前未命中资料'}"},
        ]
    collected_sources: list[list[dict[str, object]]] = [results]
    try:
        for round_number in range(1, 7):
            emit("model", f"模型正在进行第{round_number}轮证据判断", {"round": round_number})
            message = request_assistant_model(messages, active_model_config)
            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                answer = str(message.get("content") or "").strip()
                if not answer:
                    raise KeyError("模型未返回答案")
                emit(
                    "compose",
                    "证据整理完成，正在形成最终结论",
                    {"sources": len(merge_assistant_sources_for_question(question, *collected_sources))},
                )
                return (
                    answer,
                    "language-model",
                    merge_assistant_sources_for_question(question, *collected_sources),
                    routed_skills,
                )
            messages.append(message)
            for tool_call in tool_calls:
                function = tool_call.get("function") or {}
                name = str(function.get("name") or "")
                try:
                    arguments = json.loads(str(function.get("arguments") or "{}"))
                    visible_arguments = {
                        key: value
                        for key, value in arguments.items()
                        if key
                        in {
                            "query",
                            "limit",
                            "document_id",
                            "skill_name",
                            "enterprise_name",
                            "project_name",
                            "year",
                            "batch",
                            "region",
                            "regions",
                            "keywords",
                            "document_stage",
                            "validity_status",
                        }
                    }
                    emit("tool", f"调用只读工具：{name}", {"tool": name, **visible_arguments})
                    tool_result, sources = execute_assistant_tool(name, arguments)
                    collected_sources.append(sources)
                    content = json.dumps(tool_result, ensure_ascii=False)
                    emit(
                        "evidence",
                        f"工具{name}返回完成",
                        {"new_sources": len(sources)},
                    )
                except (ValueError, TypeError, json.JSONDecodeError, HTTPException) as tool_error:
                    content = json.dumps({"error": str(tool_error)}, ensure_ascii=False)
                    emit("tool-error", f"工具{name}未成功返回，继续使用现有证据", {})
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": str(tool_call.get("id") or ""),
                        "content": content,
                    }
                )
        raise RuntimeError("模型工具调用轮次超过限制")
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        KeyError,
        IndexError,
        json.JSONDecodeError,
        RuntimeError,
    ) as error:
        fallback_results: list[dict[str, str]] = []
        seen_fallback_documents: set[int] = set()
        for source_group in collected_sources:
            for source_item in source_group:
                document_id = int(source_item["document_id"])
                if document_id in seen_fallback_documents:
                    continue
                seen_fallback_documents.add(document_id)
                excerpt = str(source_item.get("excerpt") or source_item.get("content") or "").strip()
                if excerpt:
                    fallback_results.append(
                        {
                            "title": str(source_item["title"]),
                            "excerpt": excerpt,
                            "source": str(source_item.get("source") or ""),
                        }
                    )
        fallback_code, fallback_message = assistant_model_error_reason(error)
        policy_fallback = current_policy_fallback(question)
        if policy_fallback:
            emit(
                "fallback",
                "模型工具轮次已停止，改用现行政策硬门禁直接回答",
                {"reason": fallback_code},
            )
            return (
                policy_fallback,
                "policy-guardrail",
                merge_assistant_sources_for_question(question, *collected_sources),
                routed_skills,
            )
        if fallback_results:
            emit(
                "fallback",
                f"{fallback_message}，切换为知识库检索答案",
                {"reason": fallback_code},
            )
            fallback, _ = answer_with_knowledge_without_model(fallback_results)
            return (
                f"本次模型请求未正常完成，原因：{fallback_message}。已切换知识库检索模式。\n\n{fallback}",
                "knowledge-search",
                merge_assistant_sources_for_question(question, *collected_sources),
                routed_skills,
            )
        raise HTTPException(status_code=502, detail=f"智能答疑服务暂不可用：{type(error).__name__}") from error


def answer_with_knowledge_without_model(results: list[dict[str, str]]) -> tuple[str, str]:
    lines = ["当前以免费知识库检索模式返回最相关资料："]
    for index, result in enumerate(results[:4], start=1):
        excerpt = result["excerpt"].strip().replace("\n", " ")
        lines.append(f"{index}. {result['title']}：{excerpt[:220]}")
    return "\n".join(lines), "knowledge-search"


def search_public_web(query: str, limit: int = 5) -> list[dict[str, str]]:
    normalized_query = query.strip()[:500]
    if not normalized_query or not WEB_SEARCH_RSS_URL:
        return []
    url = WEB_SEARCH_RSS_URL.format(query=quote(normalized_query))
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "JiaotangKnowledgePortal/1.0"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        payload = response.read(2 * 1024 * 1024)
    root = ET.fromstring(payload)
    results: list[dict[str, str]] = []
    for item in root.findall("./channel/item"):
        title = str(item.findtext("title") or "").strip()
        source_url = str(item.findtext("link") or "").strip()
        description = re.sub(r"<[^>]+>", "", str(item.findtext("description") or ""))
        parsed = urlparse(source_url)
        if not title or parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        results.append(
            {
                "title": title[:300],
                "excerpt": html.unescape(description).strip()[:800],
                "source": source_url,
                "url": source_url,
            }
        )
        if len(results) >= max(1, min(limit, 8)):
            break
    return results


def answer_with_knowledge_then_web(
    question: str,
    knowledge_results: list[dict[str, object]],
    progress: Callable[[str, str, dict[str, object]], None] | None = None,
    model_config: dict[str, str] | None = None,
) -> tuple[str, str, list[dict[str, object]], list[str]]:
    clarification = project_selection_prompt(question)
    if clarification:
        if progress:
            progress("clarification", "需要先确认具体项目层级", {})
        return clarification, "clarification", [], route_assistant_skills(question)
    if knowledge_results:
        return answer_with_knowledge(
            question,
            knowledge_results,
            progress=progress,
            model_config=model_config,
        )
    structured_results: list[dict[str, object]] = []
    seen_structured_documents: set[int] = set()
    structured_variants = project_query_variants(question) if project_query_is_resolved(question) else []
    for variant in structured_variants:
        canonical_name = variant.split()[-1]
        try:
            policy_results = search_policy_documents(
                project_name=canonical_name,
                limit=5,
            )["results"]
        except HTTPException:
            policy_results = []
        for item in policy_results:
            document_id = int(item["document_id"])
            if document_id in seen_structured_documents:
                continue
            seen_structured_documents.add(document_id)
            structured_results.append(item)
    if structured_results:
        if progress:
            progress(
                "structured-search",
                f"全文未命中，政策结构化索引补充命中{len(structured_results)}份资料",
                {"sources": len(structured_results)},
            )
        return answer_with_knowledge(
            question,
            structured_results[:8],
            progress=progress,
            model_config=model_config,
        )
    active_model_config = model_config or {
        "api_base": AI_API_BASE,
        "api_key": AI_API_KEY,
        "model": AI_MODEL,
    }
    if all(active_model_config.values()):
        if progress:
            progress(
                "project-tools",
                "全文与政策索引未命中，继续调用项目地图和只读检索工具",
                {},
            )
        return answer_with_knowledge(
            question,
            [],
            progress=progress,
            model_config=active_model_config,
        )
    routed_skills = route_assistant_skills(question)
    if progress:
        progress("web-search", "团队知识库未命中，正在联网检索公开信息", {"query": question})
    try:
        web_results = search_public_web(question, 5)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ET.ParseError):
        web_results = []
    if not web_results:
        return answer_with_knowledge(
            question,
            [],
            progress=progress,
            model_config=model_config,
        )
    lines = ["团队知识库未命中相关资料，已按知识优先规则联网检索："]
    for index, result in enumerate(web_results, start=1):
        lines.append(
            f"{index}. {result['title']}\n{result['excerpt'][:220]}\n来源：{result['source']}"
        )
    lines.append("联网结果仅作为补充线索；涉及政策、企业、专利和财务结论时仍需打开原文核验。")
    if progress:
        progress("web-result", f"联网检索命中{len(web_results)}条公开结果", {"sources": len(web_results)})
    return "\n\n".join(lines), "web-search", list(web_results), routed_skills


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
            connection.execute("DELETE FROM public_list_entities WHERE document_id = ?", (document_id,))
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
    from scripts.build_knowledge_content_index import iter_chunks

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
            metadata = derive_document_metadata(
                str(payload["title"]),
                str(payload["source"]),
                str(payload["content"]),
                str(payload["document_role"]),
            )
            columns = (
                "id", "source_key", "title", "content", "source", "cloud_path",
                "document_role", "sensitivity", "sha256", "updated_at",
                "canonical_project_name", "region", "document_stage",
                "validity_status", "policy_year", "batch", "replacement_title",
                "replacement_basis", "replacement_url",
            )
            values = {
                **payload,
                **metadata,
            }
            connection.execute(
                f"INSERT INTO documents({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                tuple(values[column] for column in columns),
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
            insert_entity_indexes(
                connection,
                document_id,
                str(payload["content"]),
                str(payload["document_role"]),
                metadata,
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
    from scripts.build_knowledge_content_index import iter_chunks

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
            metadata = derive_document_metadata(title, source, content, document_role)
            for table in ("documents_fts", "documents_fts_trigram"):
                connection.execute(
                    f"INSERT INTO {table}({table},rowid,title,content,source,document_role) VALUES ('delete',?,?,?,?,?)",
                    (document_id, old["title"], old["content"], old["source"], old["document_role"]),
                )
            connection.execute(
                """
                UPDATE documents
                SET title = ?, content = ?, source = ?, document_role = ?, updated_at = ?,
                    canonical_project_name = ?, region = ?, document_stage = ?,
                    validity_status = ?, policy_year = ?, batch = ?, replacement_title = ?,
                    replacement_basis = ?, replacement_url = ?
                WHERE id = ?
                """,
                (
                    title,
                    content,
                    source,
                    document_role,
                    isoformat(utc_now()),
                    metadata["canonical_project_name"],
                    metadata["region"],
                    metadata["document_stage"],
                    metadata["validity_status"],
                    metadata["policy_year"],
                    metadata["batch"],
                    metadata["replacement_title"],
                    metadata["replacement_basis"],
                    metadata["replacement_url"],
                    document_id,
                ),
            )
            for table in ("documents_fts", "documents_fts_trigram"):
                connection.execute(
                    f"INSERT INTO {table}(rowid,title,content,source,document_role) VALUES (?,?,?,?,?)",
                    (document_id, title, content, source, document_role),
                )
            connection.execute("DELETE FROM document_chunks_fts WHERE document_id = ?", (document_id,))
            connection.execute("DELETE FROM document_chunks WHERE document_id = ?", (document_id,))
            connection.execute("DELETE FROM public_list_entities WHERE document_id = ?", (document_id,))
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
            insert_entity_indexes(
                connection, document_id, content, document_role, metadata
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
                real_name TEXT,
                password_hash TEXT NOT NULL,
                company_name TEXT NOT NULL DEFAULT '共创集团',
                is_admin INTEGER NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                deleted_at TEXT
            );

            CREATE TABLE IF NOT EXISTS registration_authorizations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                real_name TEXT NOT NULL,
                identity_code TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                user_id INTEGER REFERENCES users(id),
                created_by INTEGER REFERENCES users(id),
                created_at TEXT NOT NULL,
                registered_at TEXT,
                revoked_at TEXT,
                deleted_at TEXT,
                UNIQUE(real_name, identity_code)
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                csrf_token TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS password_reset_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                client_ip TEXT NOT NULL,
                succeeded INTEGER NOT NULL DEFAULT 0,
                attempted_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS password_reset_attempts_lookup_idx
            ON password_reset_attempts(client_ip, username, attempted_at DESC);

            CREATE TABLE IF NOT EXISTS device_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                label TEXT NOT NULL,
                token_prefix TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                token_seed TEXT NOT NULL DEFAULT '',
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
                activity_type TEXT NOT NULL DEFAULT 'rest_api',
                activity_name TEXT NOT NULL DEFAULT '',
                counts_toward_usage INTEGER NOT NULL DEFAULT 1,
                called_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS api_usage_user_time_idx
            ON api_usage(user_id, called_at DESC);

            CREATE TABLE IF NOT EXISTS assistant_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                question TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                answer_mode TEXT,
                routed_skills TEXT NOT NULL DEFAULT '[]',
                tool_calls TEXT NOT NULL DEFAULT '[]',
                source_count INTEGER NOT NULL DEFAULT 0,
                duration_ms INTEGER,
                fallback_reason TEXT,
                error_type TEXT,
                error_message TEXT,
                quota_counted INTEGER NOT NULL DEFAULT 1,
                provider_mode TEXT NOT NULL DEFAULT 'platform'
            );

            CREATE INDEX IF NOT EXISTS assistant_usage_user_time_idx
            ON assistant_usage(user_id, started_at DESC);

            CREATE TABLE IF NOT EXISTS feedback_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                category TEXT NOT NULL,
                subject TEXT NOT NULL,
                content TEXT NOT NULL,
                page_url TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                admin_note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                resolved_at TEXT
            );

            CREATE INDEX IF NOT EXISTS feedback_messages_user_time_idx
            ON feedback_messages(user_id, created_at DESC);

            CREATE INDEX IF NOT EXISTS feedback_messages_status_time_idx
            ON feedback_messages(status, created_at DESC);

            CREATE TABLE IF NOT EXISTS skill_releases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version TEXT NOT NULL UNIQUE,
                file_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                release_notes TEXT NOT NULL,
                published_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS release_announcements (
                release_id INTEGER PRIMARY KEY REFERENCES skill_releases(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                quick_phrases TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'draft',
                updated_at TEXT NOT NULL,
                published_at TEXT
            );

            CREATE TABLE IF NOT EXISTS user_release_acknowledgements (
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                release_id INTEGER NOT NULL REFERENCES skill_releases(id) ON DELETE CASCADE,
                acknowledged_at TEXT NOT NULL,
                PRIMARY KEY(user_id,release_id)
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
        if "assistant_daily_limit" not in user_columns:
            connection.execute("ALTER TABLE users ADD COLUMN assistant_daily_limit INTEGER")
        if "real_name" not in user_columns:
            connection.execute("ALTER TABLE users ADD COLUMN real_name TEXT")
        if "deleted_at" not in user_columns:
            connection.execute("ALTER TABLE users ADD COLUMN deleted_at TEXT")
        authorization_columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(registration_authorizations)"
            ).fetchall()
        }
        if "identity_code" not in authorization_columns:
            connection.execute(
                "ALTER TABLE registration_authorizations "
                "RENAME TO registration_authorizations_legacy_20260719"
            )
            connection.executescript(
                """
                CREATE TABLE registration_authorizations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    real_name TEXT NOT NULL,
                    identity_code TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    user_id INTEGER REFERENCES users(id),
                    created_by INTEGER REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    registered_at TEXT,
                    revoked_at TEXT,
                    deleted_at TEXT,
                    UNIQUE(real_name, identity_code)
                );
                INSERT INTO registration_authorizations(
                    id,real_name,identity_code,status,user_id,created_by,
                    created_at,registered_at,revoked_at,deleted_at
                )
                SELECT legacy.id,legacy.real_name,
                       COALESCE(users.username,'legacy-' || legacy.id),
                       legacy.status,legacy.user_id,legacy.created_by,
                       legacy.created_at,legacy.registered_at,legacy.revoked_at,NULL
                FROM registration_authorizations_legacy_20260719 AS legacy
                LEFT JOIN users ON users.id=legacy.user_id;
                """
            )
        authorization_columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(registration_authorizations)"
            ).fetchall()
        }
        if "deleted_at" not in authorization_columns:
            connection.execute(
                "ALTER TABLE registration_authorizations ADD COLUMN deleted_at TEXT"
            )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS registration_authorizations_status_idx "
            "ON registration_authorizations(status, created_at DESC)"
        )
        duplicate_authorizations = connection.execute(
            """
            SELECT user_id FROM registration_authorizations
            WHERE user_id IS NOT NULL
            GROUP BY user_id HAVING COUNT(*) > 1
            """
        ).fetchall()
        for duplicate in duplicate_authorizations:
            rows = connection.execute(
                """
                SELECT id FROM registration_authorizations
                WHERE user_id=?
                ORDER BY CASE WHEN deleted_at IS NULL THEN 0 ELSE 1 END,
                         CASE WHEN status='registered' THEN 0 ELSE 1 END,
                         id
                """,
                (duplicate["user_id"],),
            ).fetchall()
            connection.executemany(
                "UPDATE registration_authorizations SET user_id=NULL WHERE id=?",
                ((row["id"],) for row in rows[1:]),
            )
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS registration_authorizations_one_user_idx "
            "ON registration_authorizations(user_id) WHERE user_id IS NOT NULL"
        )
        connection.execute(
            """
            UPDATE users
            SET real_name=(
                SELECT label FROM device_tokens
                WHERE device_tokens.user_id=users.id
                ORDER BY CASE WHEN revoked_at IS NULL THEN 0 ELSE 1 END,id DESC
                LIMIT 1
            )
            WHERE COALESCE(real_name,'')=''
              AND EXISTS(SELECT 1 FROM device_tokens WHERE device_tokens.user_id=users.id)
            """
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO registration_authorizations(
                real_name,identity_code,status,user_id,created_at,registered_at
            )
            SELECT real_name,username,'registered',id,created_at,created_at
            FROM users
            WHERE COALESCE(real_name,'')<>''
              AND NOT EXISTS(
                  SELECT 1 FROM registration_authorizations authorization
                  WHERE authorization.user_id=users.id
              )
            """
        )
        token_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(device_tokens)").fetchall()
        }
        if "token_seed" not in token_columns:
            connection.execute(
                "ALTER TABLE device_tokens ADD COLUMN token_seed TEXT NOT NULL DEFAULT ''"
            )
        now = isoformat(utc_now())
        for token_user in connection.execute("SELECT id FROM users ORDER BY id").fetchall():
            active_rows = connection.execute(
                "SELECT id,token_seed FROM device_tokens "
                "WHERE user_id=? AND revoked_at IS NULL ORDER BY id DESC",
                (int(token_user["id"]),),
            ).fetchall()
            if not active_rows:
                continue
            keeper = active_rows[0]
            seed = str(keeper["token_seed"] or secrets.token_urlsafe(24))
            raw_token = user_access_token(int(token_user["id"]), seed)
            connection.execute(
                "UPDATE device_tokens SET token_seed=?,token_prefix=?,token_hash=? WHERE id=?",
                (seed, raw_token[:12], token_hash(raw_token), int(keeper["id"])),
            )
            if len(active_rows) > 1:
                connection.executemany(
                    "UPDATE device_tokens SET revoked_at=? WHERE id=?",
                    ((now, int(row["id"])) for row in active_rows[1:]),
                )
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS device_tokens_one_active_per_user "
            "ON device_tokens(user_id) WHERE revoked_at IS NULL"
        )
        api_usage_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(api_usage)").fetchall()
        }
        api_usage_migrations = {
            "activity_type": "TEXT NOT NULL DEFAULT 'rest_api'",
            "activity_name": "TEXT NOT NULL DEFAULT ''",
            "counts_toward_usage": "INTEGER NOT NULL DEFAULT 1",
        }
        for column_name, declaration in api_usage_migrations.items():
            if column_name not in api_usage_columns:
                connection.execute(
                    f"ALTER TABLE api_usage ADD COLUMN {column_name} {declaration}"
                )
        connection.execute(
            """
            UPDATE api_usage
            SET activity_type='mcp_legacy', activity_name='历史MCP未分类', counts_toward_usage=0
            WHERE endpoint='/mcp' AND activity_type='rest_api' AND activity_name=''
            """
        )
        connection.execute(
            """
            UPDATE api_usage
            SET activity_type='mcp_connection', activity_name='MCP连接检测', counts_toward_usage=0
            WHERE endpoint='/mcp' AND method IN ('GET','HEAD')
            """
        )
        connection.execute(
            "UPDATE api_usage SET counts_toward_usage=0 WHERE activity_type IN ('mcp_connection','mcp_tools_list')"
        )
        assistant_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(assistant_usage)").fetchall()
        }
        assistant_migrations = {
            "answer_mode": "TEXT",
            "routed_skills": "TEXT NOT NULL DEFAULT '[]'",
            "tool_calls": "TEXT NOT NULL DEFAULT '[]'",
            "source_count": "INTEGER NOT NULL DEFAULT 0",
            "duration_ms": "INTEGER",
            "fallback_reason": "TEXT",
            "error_type": "TEXT",
            "error_message": "TEXT",
            "quota_counted": "INTEGER NOT NULL DEFAULT 1",
            "provider_mode": "TEXT NOT NULL DEFAULT 'platform'",
        }
        for column_name, declaration in assistant_migrations.items():
            if column_name not in assistant_columns:
                connection.execute(
                    f"ALTER TABLE assistant_usage ADD COLUMN {column_name} {declaration}"
                )
        connection.execute(
            "UPDATE assistant_usage SET status = 'failed', completed_at = ? WHERE status = 'running'",
            (isoformat(utc_now()),),
        )
        connection.commit()


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=604800, immutable"
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
              AND (
                  users.is_admin = 1 OR EXISTS(
                      SELECT 1 FROM registration_authorizations authorization
                      WHERE authorization.user_id=users.id
                        AND authorization.status='registered'
                        AND authorization.deleted_at IS NULL
                  )
              )
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


def authenticate_api_token(
    authorization: str | None,
    endpoint: str,
    method: str,
    *,
    record_usage: bool = True,
    activity_type: str = "rest_api",
    activity_name: str = "",
    counts_toward_usage: bool = True,
) -> sqlite3.Row:
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
              AND (
                  users.is_admin = 1 OR EXISTS(
                      SELECT 1 FROM registration_authorizations authorization
                      WHERE authorization.user_id=users.id
                        AND authorization.status='registered'
                        AND authorization.deleted_at IS NULL
                  )
              )
            """,
            (token_hash(raw_token),),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=401, detail="用户访问凭据无效或已吊销")
        connection.execute(
            "UPDATE device_tokens SET last_used_at = ? WHERE id = ?",
            (isoformat(utc_now()), row["device_token_id"]),
        )
        if record_usage:
            connection.execute(
                """
                INSERT INTO api_usage(
                    user_id, device_token_id, endpoint, method,
                    activity_type, activity_name, counts_toward_usage, called_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    row["device_token_id"],
                    endpoint,
                    method,
                    activity_type,
                    activity_name,
                    int(counts_toward_usage),
                    isoformat(utc_now()),
                ),
            )
        connection.commit()
        return row


def record_api_usage(
    user: sqlite3.Row,
    endpoint: str,
    method: str,
    activity_type: str,
    activity_name: str,
    counts_toward_usage: bool,
) -> None:
    with closing(database()) as connection:
        connection.execute(
            """
            INSERT INTO api_usage(
                user_id, device_token_id, endpoint, method,
                activity_type, activity_name, counts_toward_usage, called_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user["id"],
                user["device_token_id"],
                endpoint,
                method,
                activity_type,
                activity_name,
                int(counts_toward_usage),
                isoformat(utc_now()),
            ),
        )
        connection.commit()


MCP_SEARCH_TOOLS = {
    "knowledge_search",
    "policy_search",
    "public_list_search",
    "project_catalog_match",
}


def classify_mcp_request(body: bytes, http_method: str = "POST") -> tuple[str, str, bool]:
    if http_method.upper() in {"GET", "HEAD", "OPTIONS"}:
        return "mcp_connection", "MCP连接检测", False
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "mcp_other", "未识别MCP请求", True
    if isinstance(payload, list):
        messages = [item for item in payload if isinstance(item, dict)]
    elif isinstance(payload, dict):
        messages = [payload]
    else:
        messages = []
    classifications: list[tuple[str, str, bool]] = []
    for message in messages:
        rpc_method = str(message.get("method") or "")
        if rpc_method in {"ping", "initialize", "notifications/initialized"}:
            classifications.append(("mcp_connection", "MCP连接检测", False))
            continue
        if rpc_method == "tools/list":
            classifications.append(("mcp_tools_list", "工具列表", False))
            continue
        if rpc_method == "tools/call":
            params = message.get("params")
            tool_name = str(params.get("name") or "") if isinstance(params, dict) else ""
            if tool_name == "knowledge_document":
                classifications.append(("mcp_document", "文档读取", True))
            elif tool_name in MCP_SEARCH_TOOLS:
                classifications.append(("mcp_search", "实际检索", True))
            elif tool_name == "knowledge_service_status":
                classifications.append(("mcp_connection", "MCP连接检测", False))
            else:
                classifications.append(("mcp_tool", tool_name or "MCP工具调用", True))
            continue
        classifications.append(("mcp_other", rpc_method or "MCP请求", True))
    if not classifications:
        return "mcp_other", "未识别MCP请求", True
    priority = {
        "mcp_document": 5,
        "mcp_search": 4,
        "mcp_tool": 3,
        "mcp_tools_list": 2,
        "mcp_other": 1,
        "mcp_connection": 0,
    }
    return max(classifications, key=lambda item: priority[item[0]])


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
            user = authenticate_api_token(
                headers.get("authorization"),
                "/mcp",
                scope.get("method", "POST"),
                record_usage=False,
            )
        except HTTPException as error:
            response = JSONResponse({"detail": error.detail}, status_code=error.status_code)
            await response(scope, receive, send)
            return
        body_parts: list[bytes] = []

        async def capture_receive():
            message = await receive()
            if message.get("type") == "http.request" and message.get("body"):
                body_parts.append(message["body"])
            return message

        try:
            await self.application(scope, capture_receive, send)
        finally:
            activity_type, activity_name, counts_toward_usage = classify_mcp_request(
                b"".join(body_parts), scope.get("method", "POST")
            )
            record_api_usage(
                user,
                "/mcp",
                scope.get("method", "POST"),
                activity_type,
                activity_name,
                counts_toward_usage,
            )


def validate_csrf(user: sqlite3.Row, supplied: str) -> None:
    if not secrets.compare_digest(user["csrf_token"], supplied):
        raise HTTPException(status_code=403, detail="请求校验失败")


def validate_user_model_config(
    api_base: str | None,
    api_key: str | None,
    model: str | None,
) -> dict[str, str] | None:
    values = [str(value or "").strip() for value in (api_base, api_key, model)]
    if not any(values):
        return None
    if not all(values):
        raise HTTPException(status_code=422, detail="自带API需要同时填写接口地址、API Key和模型名称。")
    parsed = urlparse(values[0])
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(status_code=422, detail="自带API地址必须是公开HTTPS地址。")
    hostname = parsed.hostname.lower()
    if hostname == "localhost" or hostname.endswith(".local"):
        raise HTTPException(status_code=422, detail="自带API地址不能指向本机或内网。")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise HTTPException(status_code=422, detail="自带API地址不能指向本机或内网。")
    if not re.fullmatch(r"[A-Za-z0-9._:/-]{1,200}", values[2]):
        raise HTTPException(status_code=422, detail="模型名称格式不正确。")
    if len(values[1]) > 500:
        raise HTTPException(status_code=422, detail="API Key长度超过限制。")
    return {"api_base": values[0], "api_key": values[1], "model": values[2]}


def require_admin(user: sqlite3.Row) -> None:
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="仅管理员可执行此操作")


def assistant_day_bounds() -> tuple[str, str]:
    local_now = utc_now().astimezone(ASSISTANT_TIMEZONE)
    local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    local_end = local_start + timedelta(days=1)
    return isoformat(local_start.astimezone(timezone.utc)), isoformat(local_end.astimezone(timezone.utc))


def assistant_limit_for_user(user_id: int, connection: sqlite3.Connection | None = None) -> int:
    if connection is not None:
        row = connection.execute(
            "SELECT assistant_daily_limit FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    else:
        with closing(database()) as owned_connection:
            row = owned_connection.execute(
                "SELECT assistant_daily_limit FROM users WHERE id = ?", (user_id,)
            ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return int(row["assistant_daily_limit"] or ASSISTANT_DAILY_LIMIT)


def assistant_usage_today(user_id: int) -> int:
    day_start, day_end = assistant_day_bounds()
    with closing(database()) as connection:
        return int(
            connection.execute(
                "SELECT COUNT(*) FROM assistant_usage WHERE user_id = ? AND started_at >= ? AND started_at < ? AND status IN ('running', 'completed') AND quota_counted = 1",
                (user_id, day_start, day_end),
            ).fetchone()[0]
        )


def reserve_assistant_usage(user_id: int, question: str) -> tuple[int, int, int]:
    day_start, day_end = assistant_day_bounds()
    with closing(database()) as connection:
        connection.execute("BEGIN IMMEDIATE")
        daily_limit = assistant_limit_for_user(user_id, connection)
        used = int(
            connection.execute(
                "SELECT COUNT(*) FROM assistant_usage WHERE user_id = ? AND started_at >= ? AND started_at < ? AND status IN ('running', 'completed') AND quota_counted = 1",
                (user_id, day_start, day_end),
            ).fetchone()[0]
        )
        if used >= daily_limit:
            connection.rollback()
            raise HTTPException(
                status_code=429,
                detail=f"今日知识库答疑次数已用完，当前账号每天最多{daily_limit}次，请明日再试。",
            )
        cursor = connection.execute(
            "INSERT INTO assistant_usage(user_id, question, status, started_at) VALUES (?, ?, 'running', ?)",
            (user_id, question, isoformat(utc_now())),
        )
        connection.commit()
        return int(cursor.lastrowid), daily_limit - used - 1, daily_limit


def create_unmetered_assistant_usage(
    user_id: int,
    question: str,
    provider_mode: str = "user-api",
) -> int:
    with closing(database()) as connection:
        cursor = connection.execute(
            """
            INSERT INTO assistant_usage(
                user_id,question,status,started_at,quota_counted,provider_mode
            ) VALUES (?,?,'running',?,0,?)
            """,
            (user_id, question, isoformat(utc_now()), provider_mode),
        )
        connection.commit()
        return int(cursor.lastrowid)


def assistant_quota_payload(
    remaining: int | None,
    daily_limit: int | None,
    counted: bool,
    unlimited: bool = False,
) -> dict[str, object]:
    return {
        "remaining": remaining,
        "limit": daily_limit,
        "counted": counted,
        "unlimited": unlimited,
    }


class AllPortalSections(str):
    visible_sections = {
        "overview",
        "cockpit",
        "health",
        "access",
        "skills",
        "knowledge-admin",
        "skill-admin",
        "members",
        "feedback",
    }

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str) and other in self.visible_sections:
            return True
        return super().__eq__(other)

    __hash__ = str.__hash__


def complete_assistant_usage(
    usage_id: int,
    status_value: str,
    *,
    answer_mode: str | None = None,
    routed_skills: list[str] | None = None,
    tool_calls: list[str] | None = None,
    source_count: int = 0,
    duration_ms: int | None = None,
    fallback_reason: str | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
) -> None:
    with closing(database()) as connection:
        connection.execute(
            """
            UPDATE assistant_usage
            SET status = ?, completed_at = ?, answer_mode = ?, routed_skills = ?,
                tool_calls = ?, source_count = ?, duration_ms = ?, fallback_reason = ?,
                error_type = ?, error_message = ?
            WHERE id = ?
            """,
            (
                status_value,
                isoformat(utc_now()),
                answer_mode,
                json.dumps(routed_skills or [], ensure_ascii=False),
                json.dumps(tool_calls or [], ensure_ascii=False),
                source_count,
                duration_ms,
                fallback_reason,
                error_type,
                (error_message or "")[:500] or None,
                usage_id,
            ),
        )
        connection.commit()


def portal_payload(
    request: Request,
    user: sqlite3.Row,
    new_token: str | None = None,
    message: str | None = None,
    error: str | None = None,
    active_page: str = "overview",
) -> dict[str, object]:
    with closing(database()) as connection:
        device_tokens = connection.execute(
            """
            SELECT device_tokens.id, device_tokens.label, device_tokens.token_prefix,
                   device_tokens.token_seed,
                   device_tokens.created_at, device_tokens.last_used_at,
                   device_tokens.revoked_at,
                   COUNT(CASE WHEN api_usage.counts_toward_usage = 1 THEN 1 END) AS call_count
            FROM device_tokens
            LEFT JOIN api_usage ON api_usage.device_token_id = device_tokens.id
            WHERE device_tokens.user_id = ? AND device_tokens.revoked_at IS NULL
            GROUP BY device_tokens.id
            ORDER BY device_tokens.id DESC
            """,
            (user["id"],),
        ).fetchall()
        active_device_token = next(
            (row for row in device_tokens if not row["revoked_at"]), None
        )
        reusable_token = (
            user_access_token(int(user["id"]), str(active_device_token["token_seed"]))
            if active_device_token and active_device_token["token_seed"]
            else None
        )
        recent_calls = format_row_datetimes(connection.execute(
            """
            SELECT api_usage.endpoint, api_usage.method, api_usage.called_at,
                   api_usage.activity_type, api_usage.activity_name,
                   COALESCE(NULLIF(api_usage.activity_name,''), api_usage.endpoint) AS activity_display,
                   device_tokens.label
            FROM api_usage
            JOIN device_tokens ON device_tokens.id = api_usage.device_token_id
            WHERE api_usage.user_id = ?
            ORDER BY api_usage.id DESC
            LIMIT 12
            """,
            (user["id"],),
        ).fetchall(), "called_at")
        usage_total = int(
            connection.execute(
                "SELECT COUNT(*) FROM api_usage WHERE user_id = ? AND counts_toward_usage = 1",
                (user["id"],)
            ).fetchone()[0]
        )
        assistant_used_today = int(
            connection.execute(
                "SELECT COUNT(*) FROM assistant_usage WHERE user_id = ? AND started_at >= ? AND started_at < ? AND status IN ('running', 'completed') AND quota_counted = 1",
                (user["id"], *assistant_day_bounds()),
            ).fetchone()[0]
        )
        assistant_daily_limit = (
            None if user["is_admin"] else assistant_limit_for_user(int(user["id"]), connection)
        )
        users = []
        registration_authorizations = []
        feedback_messages = []
        update_jobs = []
        releases = []
        admin_health: dict[str, object] = {}
        if user["is_admin"]:
            users = format_row_datetimes(connection.execute(
                "SELECT id, username, real_name, company_name, is_admin, active, created_at FROM users WHERE deleted_at IS NULL ORDER BY id"
            ).fetchall(), "created_at")
            registration_authorization_rows = connection.execute(
                """
                SELECT registration_authorizations.*,users.username
                FROM registration_authorizations
                LEFT JOIN users ON users.id=registration_authorizations.user_id
                WHERE registration_authorizations.deleted_at IS NULL
                ORDER BY registration_authorizations.id DESC
                """
            ).fetchall()
            public_endpoint = str(request.base_url).rstrip("/")
            registration_authorizations = [
                {
                    **dict(authorization),
                    "invitation_url": (
                        f"{public_endpoint}/register?invite="
                        f"{quote(registration_invite_token(authorization))}"
                        if authorization["status"] == "pending"
                        else None
                    ),
                    "created_at_display": format_chinese_datetime(authorization["created_at"]),
                    "registered_at_display": format_chinese_datetime(
                        authorization["registered_at"]
                    ),
                }
                for authorization in registration_authorization_rows
            ]
        feedback_query = """
            SELECT feedback_messages.*,users.username,users.real_name
            FROM feedback_messages
            JOIN users ON users.id=feedback_messages.user_id
        """
        feedback_parameters: tuple[object, ...] = ()
        if not user["is_admin"]:
            feedback_query += " WHERE feedback_messages.user_id=?"
            feedback_parameters = (int(user["id"]),)
        feedback_query += " ORDER BY feedback_messages.id DESC LIMIT 100"
        feedback_messages = format_row_datetimes(
            connection.execute(feedback_query, feedback_parameters).fetchall(),
            "created_at",
            "updated_at",
            "resolved_at",
        )
        if user["is_admin"]:
            update_jobs = format_row_datetimes(connection.execute(
                """
                SELECT id, original_name, status, extraction_status, text_characters,
                       document_id, error_message, created_at, completed_at,
                       rolled_back_at, snapshot_path
                FROM knowledge_update_jobs
                ORDER BY id DESC
                LIMIT 20
                """
            ).fetchall(), "created_at", "completed_at", "rolled_back_at")
        if user["is_admin"]:
            release_rows = connection.execute(
                """
                SELECT id, version, file_name, sha256, release_notes, published_at
                FROM skill_releases
                WHERE version = ?
                ORDER BY published_at DESC, id DESC
                LIMIT 20
                """,
                (FIRST_PUBLIC_SKILL_VERSION,),
            ).fetchall()
            releases = [
                {
                    **dict(row),
                    "published_at_display": format_chinese_datetime(row["published_at"]),
                    "release_notes_html": render_guide_markdown(str(row["release_notes"])),
                }
                for row in release_rows
            ]
        if user["is_admin"]:
            since_24_hours = isoformat(utc_now() - timedelta(hours=24))
            since_7_days = isoformat(utc_now() - timedelta(days=7))
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
                        "SELECT COUNT(*) FROM api_usage WHERE called_at >= ? AND counts_toward_usage = 1",
                        (since_24_hours,)
                    ).fetchone()[0]
                ),
                "failed_updates": int(
                    connection.execute(
                        "SELECT COUNT(*) FROM knowledge_update_jobs WHERE status = 'failed'"
                    ).fetchone()[0]
                ),
                "assistant_7d": int(
                    connection.execute(
                        "SELECT COUNT(*) FROM assistant_usage WHERE started_at >= ?",
                        (since_7_days,),
                    ).fetchone()[0]
                ),
                "assistant_anomalies": int(
                    connection.execute(
                        """
                        SELECT COUNT(*) FROM assistant_usage
                        WHERE started_at >= ?
                          AND (status = 'failed' OR fallback_reason IS NOT NULL OR COALESCE(duration_ms, 0) >= 30000)
                        """,
                        (since_7_days,),
                    ).fetchone()[0]
                ),
                "pending_feedback": int(
                    connection.execute(
                        "SELECT COUNT(*) FROM feedback_messages WHERE status IN ('pending','reviewing')"
                    ).fetchone()[0]
                ),
                "runtime": read_status_file(HEALTH_STATUS_PATH),
                "backup": read_status_file(BACKUP_STATUS_PATH),
                "oss_sync": read_status_file(OSS_SYNC_STATUS_PATH),
                "oss_cache": read_status_file(OSS_INDEX_CACHE_STATUS_PATH),
                "snapshot_retention": read_status_file(SNAPSHOT_RETENTION_STATUS_PATH),
            }
        latest_release = connection.execute(
            """
            SELECT id, version, file_name, sha256, release_notes, published_at
            FROM skill_releases
            ORDER BY published_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
        latest_release_payload = (
            {
                **dict(latest_release),
                "published_at_display": format_chinese_datetime(latest_release["published_at"]),
                "release_notes_html": render_guide_markdown(str(latest_release["release_notes"])),
            }
            if latest_release
            else None
        )
        release_announcement = None
        if latest_release:
            release_announcement = connection.execute(
                """
                SELECT a.*,r.version
                FROM release_announcements a
                JOIN skill_releases r ON r.id=a.release_id
                LEFT JOIN user_release_acknowledgements u
                  ON u.release_id=a.release_id AND u.user_id=?
                WHERE a.release_id=? AND a.status='published' AND u.user_id IS NULL
                """,
                (user["id"], latest_release["id"]),
            ).fetchone()
        announcement_payload = None
        if release_announcement:
            announcement_payload = {
                **dict(release_announcement),
                "body_html": render_guide_markdown(str(release_announcement["body"])),
                "quick_phrases": json.loads(str(release_announcement["quick_phrases"])),
            }
    return {
        "request": request,
        "user": user,
        "device_tokens": device_tokens,
        "active_device_token": active_device_token,
        "reusable_token": reusable_token,
        "recent_calls": recent_calls,
        "usage_total": usage_total,
        "assistant_daily_limit": assistant_daily_limit,
        "assistant_used_today": assistant_used_today,
        "assistant_remaining_today": (
            None
            if assistant_daily_limit is None
            else max(0, assistant_daily_limit - assistant_used_today)
        ),
        "users": users,
        "registration_authorizations": registration_authorizations,
        "feedback_messages": feedback_messages,
        "update_jobs": update_jobs,
        "releases": releases,
        "latest_release": latest_release_payload,
        "first_public_skill_version": FIRST_PUBLIC_SKILL_VERSION,
        "release_announcement": announcement_payload,
        "knowledge_stats": knowledge_index_stats(),
        "new_token": new_token,
        "message": message,
        "error": error,
        "admin_health": admin_health,
        "assistant_mode": "大模型增强" if AI_API_BASE and AI_API_KEY and AI_MODEL else "免费知识检索",
        "public_endpoint": str(request.base_url).rstrip("/"),
        "active_page": AllPortalSections(active_page),
        "single_page": True,
        "greeting": (
            "晚上好"
            if datetime.now(ASSISTANT_TIMEZONE).hour >= 18
            else ("上午好" if datetime.now(ASSISTANT_TIMEZONE).hour < 12 else "下午好")
        ),
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
def login_page(
    request: Request,
    initialized: int = 0,
    registered: int = 0,
    password_reset: int = 0,
):
    if user_count() == 0:
        return RedirectResponse("/setup", status_code=303)
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "error": None,
            "initialized": initialized == 1,
            "registered": registered == 1,
            "password_reset": password_reset == 1,
        },
    )


@app.get("/password/reset", response_class=HTMLResponse)
def password_reset_page(request: Request):
    if user_count() == 0:
        return RedirectResponse("/setup", status_code=303)
    return templates.TemplateResponse(request, "password_reset.html", {"error": None})


@app.post("/password/reset", response_class=HTMLResponse)
def password_reset_submit(
    request: Request,
    username: Annotated[str, Form(min_length=3, max_length=64)],
    real_name: Annotated[str, Form(min_length=2, max_length=20)],
    company_name: Annotated[str, Form(min_length=2, max_length=100)],
    password: Annotated[str, Form(min_length=MIN_PASSWORD_LENGTH, max_length=256)],
    confirm_password: Annotated[str, Form(min_length=MIN_PASSWORD_LENGTH, max_length=256)],
):
    try:
        normalized_username = normalize_account_name(username)
        normalized_real_name = normalize_real_name(real_name)
    except ValueError:
        normalized_username = ""
        normalized_real_name = ""
    if password != confirm_password:
        return templates.TemplateResponse(
            request,
            "password_reset.html",
            {"error": "两次输入的新密码不一致。"},
            status_code=400,
        )
    client_ip = (request.headers.get("x-forwarded-for") or "").split(",", 1)[0].strip()
    if not client_ip and request.client:
        client_ip = request.client.host
    client_ip = client_ip or "unknown"
    reset_window_start = isoformat(utc_now() - timedelta(minutes=30))
    with closing(database()) as connection:
        connection.execute(
            "DELETE FROM password_reset_attempts WHERE attempted_at < ?",
            (isoformat(utc_now() - timedelta(days=1)),),
        )
        recent_failures = connection.execute(
            """
            SELECT COUNT(*) FROM password_reset_attempts
            WHERE succeeded=0 AND attempted_at>=?
              AND (client_ip=? OR username=?)
            """,
            (reset_window_start, client_ip, normalized_username),
        ).fetchone()[0]
        if int(recent_failures) >= 5:
            connection.commit()
            return templates.TemplateResponse(
                request,
                "password_reset.html",
                {"error": "密码找回尝试次数过多，请30分钟后重试。"},
                status_code=429,
            )
        user = connection.execute(
            """
            SELECT * FROM users
            WHERE username=? AND real_name=? AND company_name=?
              AND active=1 AND deleted_at IS NULL
              AND (
                  is_admin=1 OR EXISTS(
                      SELECT 1 FROM registration_authorizations authorization
                      WHERE authorization.user_id=users.id
                        AND authorization.status='registered'
                        AND authorization.deleted_at IS NULL
                  )
              )
            """,
            (normalized_username, normalized_real_name, company_name.strip()),
        ).fetchone()
        if user is None:
            connection.execute(
                """
                INSERT INTO password_reset_attempts(username,client_ip,succeeded,attempted_at)
                VALUES (?,?,0,?)
                """,
                (normalized_username, client_ip, isoformat(utc_now())),
            )
            connection.commit()
            return templates.TemplateResponse(
                request,
                "password_reset.html",
                {"error": "身份验证未通过，请核对登录账号、真实姓名和所属公司全称。"},
                status_code=403,
            )
        connection.execute(
            "UPDATE users SET password_hash=? WHERE id=?",
            (password_hasher.hash(password), int(user["id"])),
        )
        connection.execute("DELETE FROM sessions WHERE user_id=?", (int(user["id"]),))
        connection.execute(
            "DELETE FROM password_reset_attempts WHERE client_ip=? OR username=?",
            (client_ip, normalized_username),
        )
        connection.commit()
    return RedirectResponse("/login?password_reset=1", status_code=303)


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request, invite: str = ""):
    if user_count() == 0:
        return RedirectResponse("/setup", status_code=303)
    authorization = registration_authorization_from_invite(invite) if invite else None
    error = None
    if invite and (authorization is None or authorization["status"] != "pending"):
        error = "注册邀请链接无效、已使用或已撤销，请联系管理员重新发送。"
        authorization = None
    return templates.TemplateResponse(
        request,
        "register.html",
        {
            "error": error,
            "invite_token": invite if authorization else "",
            "invited_member": dict(authorization) if authorization else None,
        },
        status_code=400 if error else 200,
    )


@app.post("/register", response_class=HTMLResponse)
def register_submit(
    request: Request,
    username: Annotated[str, Form(min_length=3, max_length=64)],
    real_name: Annotated[str, Form(min_length=2, max_length=20)],
    identity_code: Annotated[str, Form(min_length=4, max_length=24)],
    company_name: Annotated[str, Form(min_length=2, max_length=100)],
    password: Annotated[str, Form(min_length=MIN_PASSWORD_LENGTH, max_length=256)],
    confirm_password: Annotated[str, Form(min_length=MIN_PASSWORD_LENGTH, max_length=256)],
    invite_token: Annotated[str, Form()] = "",
):
    invited_authorization = (
        registration_authorization_from_invite(invite_token) if invite_token else None
    )
    template_context = {
        "invite_token": invite_token if invited_authorization else "",
        "invited_member": dict(invited_authorization) if invited_authorization else None,
    }
    if invite_token and (
        invited_authorization is None or invited_authorization["status"] != "pending"
    ):
        return templates.TemplateResponse(
            request,
            "register.html",
            {
                "error": "注册邀请链接无效、已使用或已撤销，请联系管理员重新发送。",
                "invite_token": "",
                "invited_member": None,
            },
            status_code=403,
        )
    try:
        normalized_username = normalize_account_name(username)
        if invited_authorization:
            normalized_real_name = str(invited_authorization["real_name"])
            normalized_identity_code = str(invited_authorization["identity_code"])
        else:
            normalized_real_name = normalize_real_name(real_name)
            normalized_identity_code = normalize_identity_code(identity_code)
    except ValueError as exc:
        return templates.TemplateResponse(
            request,
            "register.html",
            {"error": str(exc), **template_context},
            status_code=400,
        )
    if not company_verified(company_name):
        return templates.TemplateResponse(
            request,
            "register.html",
            {"error": "公司名称验证未通过，请填写完整公司名称。", **template_context},
            status_code=403,
        )
    if password != confirm_password:
        return templates.TemplateResponse(
            request,
            "register.html",
            {"error": "两次输入的密码不一致。", **template_context},
            status_code=400,
        )
    try:
        with closing(database()) as connection:
            if invited_authorization:
                authorization = connection.execute(
                    "SELECT * FROM registration_authorizations WHERE id=? AND deleted_at IS NULL",
                    (invited_authorization["id"],),
                ).fetchone()
            else:
                authorization = connection.execute(
                    "SELECT * FROM registration_authorizations WHERE real_name=? AND identity_code=? AND deleted_at IS NULL",
                    (normalized_real_name, normalized_identity_code),
                ).fetchone()
            if authorization is None or authorization["status"] == "revoked":
                return templates.TemplateResponse(
                    request,
                    "register.html",
                    {
                        "error": "姓名或企微手机号后四位未获得注册权限，请联系管理员添加或核对。",
                        **template_context,
                    },
                    status_code=403,
                )
            if authorization["status"] == "registered" or authorization["user_id"]:
                return templates.TemplateResponse(
                    request,
                    "register.html",
                    {"error": "该邀请已完成注册，如需处理请联系管理员。", **template_context},
                    status_code=409,
                )
            connection.execute(
                """
                INSERT INTO users(username, real_name, password_hash, company_name, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    normalized_username,
                    normalized_real_name,
                    password_hasher.hash(password),
                    MEMBER_COMPANY,
                    isoformat(utc_now()),
                ),
            )
            new_user_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
            connection.execute(
                """
                UPDATE registration_authorizations
                SET status='registered',user_id=?,registered_at=?,revoked_at=NULL
                WHERE id=? AND status='pending'
                """,
                (new_user_id, isoformat(utc_now()), authorization["id"]),
            )
            connection.commit()
    except sqlite3.IntegrityError:
        return templates.TemplateResponse(
            request,
            "register.html",
            {"error": "该用户名称已经注册。", **template_context},
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
            """
            SELECT * FROM users
            WHERE username = ? AND active = 1
              AND (
                  is_admin = 1 OR EXISTS(
                      SELECT 1 FROM registration_authorizations authorization
                      WHERE authorization.user_id=users.id
                        AND authorization.status='registered'
                        AND authorization.deleted_at IS NULL
                  )
              )
            """,
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
    return templates.TemplateResponse(
        request, "portal.html", portal_payload(request, user, active_page="overview")
    )


def portal_page_response(request: Request, user: sqlite3.Row, active_page: str) -> HTMLResponse:
    admin_pages = {"health", "knowledge-admin", "skill-admin", "members"}
    if active_page in admin_pages:
        require_admin(user)
    return templates.TemplateResponse(
        request, "portal.html", portal_payload(request, user, active_page=active_page)
    )


@app.get("/feedback", response_class=HTMLResponse)
def feedback_page(
    request: Request,
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
    submitted: int = 0,
    updated: int = 0,
):
    message = "留言已提交，管理员将在网站内处理。" if submitted else None
    if updated and user["is_admin"]:
        message = "留言处理状态已更新。"
    return templates.TemplateResponse(
        request,
        "portal.html",
        portal_payload(request, user, message=message, active_page="feedback"),
    )


@app.post("/feedback")
def feedback_submit(
    category: Annotated[str, Form()],
    subject: Annotated[str, Form(min_length=2, max_length=100)],
    content: Annotated[str, Form(min_length=5, max_length=3000)],
    page_url: Annotated[str, Form(max_length=500)],
    csrf_token: Annotated[str, Form()],
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
):
    validate_csrf(user, csrf_token)
    normalized_category = category.strip().lower()
    if normalized_category not in {"bug", "suggestion", "content", "other"}:
        raise HTTPException(status_code=422, detail="留言类型无效")
    now = isoformat(utc_now())
    with closing(database()) as connection:
        connection.execute(
            """
            INSERT INTO feedback_messages(
                user_id,category,subject,content,page_url,status,created_at,updated_at
            ) VALUES (?,?,?,?,?,'pending',?,?)
            """,
            (
                int(user["id"]),
                normalized_category,
                subject.strip(),
                content.strip(),
                page_url.strip(),
                now,
                now,
            ),
        )
        connection.commit()
    return RedirectResponse("/feedback?submitted=1#feedback", status_code=303)


@app.post("/admin/feedback/{feedback_id}")
def admin_feedback_update(
    feedback_id: int,
    feedback_status: Annotated[str, Form()],
    admin_note: Annotated[str, Form(max_length=2000)],
    csrf_token: Annotated[str, Form()],
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
):
    require_admin(user)
    validate_csrf(user, csrf_token)
    normalized_status = feedback_status.strip().lower()
    if normalized_status not in {"pending", "reviewing", "resolved", "closed"}:
        raise HTTPException(status_code=422, detail="留言状态无效")
    now = isoformat(utc_now())
    resolved_at = now if normalized_status in {"resolved", "closed"} else None
    with closing(database()) as connection:
        cursor = connection.execute(
            """
            UPDATE feedback_messages
            SET status=?,admin_note=?,updated_at=?,resolved_at=?
            WHERE id=?
            """,
            (normalized_status, admin_note.strip(), now, resolved_at, feedback_id),
        )
        if cursor.rowcount != 1:
            raise HTTPException(status_code=404, detail="留言不存在")
        connection.commit()
    return RedirectResponse("/feedback?updated=1#feedback", status_code=303)


@app.get("/cockpit", response_class=HTMLResponse)
def cockpit_page(request: Request, user: Annotated[sqlite3.Row, Depends(require_web_user)]):
    return portal_page_response(request, user, "cockpit")


@app.get("/access", response_class=HTMLResponse)
def access_page(request: Request, user: Annotated[sqlite3.Row, Depends(require_web_user)]):
    return portal_page_response(request, user, "access")


@app.get("/skills", response_class=HTMLResponse)
def skills_page(request: Request, user: Annotated[sqlite3.Row, Depends(require_web_user)]):
    return portal_page_response(request, user, "skills")


@app.get("/admin/operations", response_class=HTMLResponse)
def operations_page(request: Request, user: Annotated[sqlite3.Row, Depends(require_web_user)]):
    return portal_page_response(request, user, "health")


@app.get("/admin/knowledge-update", response_class=HTMLResponse)
def knowledge_update_page(
    request: Request, user: Annotated[sqlite3.Row, Depends(require_web_user)]
):
    return portal_page_response(request, user, "knowledge-admin")


@app.get("/admin/releases", response_class=HTMLResponse)
def releases_page(request: Request, user: Annotated[sqlite3.Row, Depends(require_web_user)]):
    return portal_page_response(request, user, "skill-admin")


@app.get("/admin/members", response_class=HTMLResponse)
def members_page(request: Request, user: Annotated[sqlite3.Row, Depends(require_web_user)]):
    return portal_page_response(request, user, "members")


@app.post("/admin/registration-authorizations")
def create_registration_authorization(
    real_name: Annotated[str, Form(min_length=2, max_length=20)],
    identity_code: Annotated[str, Form(min_length=4, max_length=24)],
    csrf_token: Annotated[str, Form()],
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
):
    validate_csrf(user, csrf_token)
    require_admin(user)
    try:
        normalized_real_name = normalize_real_name(real_name)
        normalized_identity_code = normalize_identity_code(identity_code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    now = isoformat(utc_now())
    with closing(database()) as connection:
        existing = connection.execute(
            "SELECT * FROM registration_authorizations WHERE real_name=? AND identity_code=?",
            (normalized_real_name, normalized_identity_code),
        ).fetchone()
        if existing:
            authorization_id = int(existing["id"])
            if existing["user_id"]:
                linked_user = connection.execute(
                    "SELECT * FROM users WHERE id=?", (existing["user_id"],)
                ).fetchone()
                if linked_user and linked_user["active"] and not linked_user["deleted_at"] and not existing["deleted_at"]:
                    raise HTTPException(status_code=409, detail="该成员已经完成注册")
                connection.execute(
                    "UPDATE users SET active=1,deleted_at=NULL WHERE id=?",
                    (existing["user_id"],),
                )
                connection.execute(
                    """
                    UPDATE registration_authorizations
                    SET status='registered',created_by=?,created_at=?,revoked_at=NULL,deleted_at=NULL
                    WHERE id=?
                    """,
                    (user["id"], now, existing["id"]),
                )
            else:
                connection.execute(
                    """
                    UPDATE registration_authorizations
                    SET status='pending',created_by=?,created_at=?,
                        registered_at=NULL,revoked_at=NULL,deleted_at=NULL
                    WHERE id=?
                    """,
                    (user["id"], now, existing["id"]),
                )
        else:
            cursor = connection.execute(
                """
                INSERT INTO registration_authorizations(
                    real_name,identity_code,status,created_by,created_at
                )
                VALUES (?,?,'pending',?,?)
                """,
                (normalized_real_name, normalized_identity_code, user["id"], now),
            )
            authorization_id = int(cursor.lastrowid)
        connection.commit()
    return RedirectResponse(f"/admin/members#invite-{authorization_id}", status_code=303)


def registration_import_rows(upload_name: str, payload: bytes) -> list[tuple[str, str]]:
    suffix = Path(upload_name).suffix.lower()
    if suffix == ".csv":
        text = payload.decode("utf-8-sig")
        rows = list(csv.reader(io.StringIO(text)))
    elif suffix == ".xlsx":
        from openpyxl import load_workbook

        workbook = load_workbook(io.BytesIO(payload), read_only=True, data_only=True)
        worksheet = workbook.active
        rows = [list(row) for row in worksheet.iter_rows(values_only=True)]
        workbook.close()
    else:
        raise ValueError("仅支持 CSV 或 XLSX 名单。")
    if not rows:
        raise ValueError("名单文件为空。")
    headers = [str(value or "").strip() for value in rows[0]]
    name_aliases = {"中文真实姓名", "真实姓名", "姓名", "real_name"}
    code_aliases = {
        "企业微信绑定手机号后四位",
        "企业微信绑定手机号或后四位",
        "企业微信绑定手机号",
        "企微手机号",
        "手机号",
        "mobile",
        "phone",
        "企微手机号后四位",
        "手机号后四位",
        "成员识别码",
        "identity_code",
    }
    try:
        name_index = next(index for index, value in enumerate(headers) if value in name_aliases)
        code_index = next(index for index, value in enumerate(headers) if value in code_aliases)
    except StopIteration as exc:
        raise ValueError(
            "名单必须包含“中文真实姓名”和“企业微信绑定手机号或后四位”两列。"
        ) from exc
    parsed: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row_number, row in enumerate(rows[1:], start=2):
        real_name = str(row[name_index] or "").strip() if name_index < len(row) else ""
        identity_code = str(row[code_index] or "").strip() if code_index < len(row) else ""
        if not real_name and not identity_code:
            continue
        try:
            item = (normalize_real_name(real_name), normalize_identity_code(identity_code))
        except ValueError as exc:
            raise ValueError(f"第{row_number}行：{exc}") from exc
        if item not in seen:
            parsed.append(item)
            seen.add(item)
    if not parsed:
        raise ValueError("名单中没有可导入的成员。")
    return parsed


@app.get("/admin/registration-authorizations/template.csv")
def download_registration_import_template(
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
):
    require_admin(user)
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["中文真实姓名", "企业微信绑定手机号或后四位"])
    writer.writerow(["王小明", "13800000826"])
    payload = "\ufeff" + output.getvalue()
    return Response(
        payload.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''registration-members-template.csv"
        },
    )


@app.post("/admin/registration-authorizations/import", response_class=HTMLResponse)
async def import_registration_authorizations(
    request: Request,
    member_file: Annotated[UploadFile, File()],
    csrf_token: Annotated[str, Form()],
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
):
    validate_csrf(user, csrf_token)
    require_admin(user)
    payload = await member_file.read()
    if len(payload) > 2 * 1024 * 1024:
        return templates.TemplateResponse(
            request,
            "portal.html",
            portal_payload(request, user, error="成员名单不得超过2MB。", active_page="members"),
            status_code=413,
        )
    try:
        rows = registration_import_rows(member_file.filename or "", payload)
    except (UnicodeDecodeError, ValueError) as exc:
        return templates.TemplateResponse(
            request,
            "portal.html",
            portal_payload(request, user, error=str(exc), active_page="members"),
            status_code=400,
        )
    inserted = 0
    restored = 0
    overwritten = 0
    now = isoformat(utc_now())
    with closing(database()) as connection:
        for real_name, identity_code in rows:
            existing = connection.execute(
                "SELECT * FROM registration_authorizations WHERE real_name=? AND identity_code=?",
                (real_name, identity_code),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO registration_authorizations(
                        real_name,identity_code,status,created_by,created_at
                    ) VALUES (?,?,'pending',?,?)
                    """,
                    (real_name, identity_code, user["id"], now),
                )
                inserted += 1
            else:
                was_inactive = bool(existing["deleted_at"] or existing["status"] == "revoked")
                if existing["user_id"]:
                    connection.execute(
                        "UPDATE users SET active=1,deleted_at=NULL WHERE id=?",
                        (existing["user_id"],),
                    )
                    connection.execute(
                        """
                        UPDATE registration_authorizations
                        SET status='registered',created_by=?,created_at=?,revoked_at=NULL,deleted_at=NULL
                        WHERE id=?
                        """,
                        (user["id"], now, existing["id"]),
                    )
                else:
                    connection.execute(
                        """
                        UPDATE registration_authorizations
                        SET status='pending',created_by=?,created_at=?,
                            registered_at=NULL,revoked_at=NULL,deleted_at=NULL
                        WHERE id=?
                        """,
                        (user["id"], now, existing["id"]),
                    )
                restored += int(was_inactive)
                overwritten += int(not was_inactive)
        connection.commit()
    return templates.TemplateResponse(
        request,
        "portal.html",
        portal_payload(
            request,
            user,
            message=f"名单导入完成：新增{inserted}人，恢复{restored}人，覆盖重复{overwritten}人。",
            active_page="members",
        ),
    )


@app.post("/admin/registration-authorizations/{authorization_id}/revoke")
def revoke_registration_authorization(
    authorization_id: int,
    csrf_token: Annotated[str, Form()],
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
):
    validate_csrf(user, csrf_token)
    require_admin(user)
    with closing(database()) as connection:
        authorization = connection.execute(
            "SELECT * FROM registration_authorizations WHERE id=? AND deleted_at IS NULL",
            (authorization_id,),
        ).fetchone()
        if authorization is None:
            raise HTTPException(status_code=404, detail="注册授权不存在")
        if authorization["status"] == "registered":
            raise HTTPException(status_code=409, detail="已注册成员请在账号列表中停用")
        connection.execute(
            "UPDATE registration_authorizations SET status='revoked',revoked_at=? WHERE id=?",
            (isoformat(utc_now()), authorization_id),
        )
        connection.commit()
    return RedirectResponse("/admin/members", status_code=303)


@app.get("/admin/registration-authorizations/{authorization_id}", response_class=HTMLResponse)
def registration_authorization_detail(
    request: Request,
    authorization_id: int,
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
):
    require_admin(user)
    with closing(database()) as connection:
        authorization = connection.execute(
            """
            SELECT registration_authorizations.*, users.username
            FROM registration_authorizations
            LEFT JOIN users ON users.id=registration_authorizations.user_id
            WHERE registration_authorizations.id=?
            """,
            (authorization_id,),
        ).fetchone()
    if authorization is None:
        raise HTTPException(status_code=404, detail="注册邀请不存在")
    invitation_url = None
    if authorization["status"] == "pending" and not authorization["deleted_at"]:
        invitation_url = (
            f"{str(request.base_url).rstrip('/')}/register?invite="
            f"{quote(registration_invite_token(authorization))}"
        )
    return templates.TemplateResponse(
        request,
        "admin_registration_detail.html",
        {
            "user": user,
            "authorization": {
                **dict(authorization),
                "invitation_url": invitation_url,
                "created_at_display": format_chinese_datetime(authorization["created_at"]),
                "registered_at_display": format_chinese_datetime(authorization["registered_at"]),
                "revoked_at_display": format_chinese_datetime(authorization["revoked_at"]),
                "deleted_at_display": format_chinese_datetime(authorization["deleted_at"]),
            },
        },
    )


@app.post("/admin/registration-authorizations/{authorization_id}/trash")
def trash_registration_authorization(
    authorization_id: int,
    csrf_token: Annotated[str, Form()],
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
):
    validate_csrf(user, csrf_token)
    require_admin(user)
    now = isoformat(utc_now())
    with closing(database()) as connection:
        authorization = connection.execute(
            "SELECT * FROM registration_authorizations WHERE id=? AND deleted_at IS NULL",
            (authorization_id,),
        ).fetchone()
        if authorization is None:
            raise HTTPException(status_code=404, detail="注册邀请不存在")
        connection.execute(
            """
            UPDATE registration_authorizations
            SET deleted_at=?, status='revoked', revoked_at=COALESCE(revoked_at, ?)
            WHERE id=?
            """,
            (now, now, authorization_id),
        )
        if authorization["user_id"]:
            connection.execute(
                "UPDATE users SET active=0 WHERE id=?", (authorization["user_id"],)
            )
            connection.execute(
                "DELETE FROM sessions WHERE user_id=?", (authorization["user_id"],)
            )
        connection.commit()
    return RedirectResponse("/admin/members", status_code=303)


@app.post("/admin/registration-authorizations/{authorization_id}/restore")
def restore_registration_authorization(
    authorization_id: int,
    csrf_token: Annotated[str, Form()],
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
):
    validate_csrf(user, csrf_token)
    require_admin(user)
    with closing(database()) as connection:
        authorization = connection.execute(
            "SELECT * FROM registration_authorizations WHERE id=? AND deleted_at IS NOT NULL",
            (authorization_id,),
        ).fetchone()
        if authorization is None:
            raise HTTPException(status_code=404, detail="回收记录不存在")
        status_value = "registered" if authorization["user_id"] else "pending"
        connection.execute(
            """
            UPDATE registration_authorizations
            SET deleted_at=NULL, status=?, revoked_at=NULL
            WHERE id=?
            """,
            (status_value, authorization_id),
        )
        if authorization["user_id"]:
            connection.execute(
                "UPDATE users SET active=1,deleted_at=NULL WHERE id=?",
                (authorization["user_id"],),
            )
        connection.commit()
    return RedirectResponse(
        f"/admin/registration-authorizations/{authorization_id}", status_code=303
    )


@app.get("/admin/users/{member_id}", response_class=HTMLResponse)
def admin_user_detail(
    request: Request,
    member_id: int,
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
):
    require_admin(user)
    with closing(database()) as connection:
        member = connection.execute(
            """
            SELECT users.*,
                   COUNT(DISTINCT CASE WHEN device_tokens.revoked_at IS NULL THEN device_tokens.id END) AS active_tokens,
                   COUNT(DISTINCT CASE WHEN api_usage.counts_toward_usage = 1 THEN api_usage.id END) AS call_count,
                   MAX(api_usage.called_at) AS last_called_at
            FROM users
            LEFT JOIN device_tokens ON device_tokens.user_id=users.id
            LEFT JOIN api_usage ON api_usage.user_id=users.id
            WHERE users.id=?
            GROUP BY users.id
            """,
            (member_id,),
        ).fetchone()
    if member is None:
        raise HTTPException(status_code=404, detail="成员不存在")
    return templates.TemplateResponse(
        request,
        "admin_user_detail.html",
        {
            "user": user,
            "member": {
                **dict(member),
                "created_at_display": format_chinese_datetime(member["created_at"]),
                "last_called_at_display": format_chinese_datetime(member["last_called_at"]),
                "deleted_at_display": format_chinese_datetime(member["deleted_at"]),
            },
        },
    )


@app.post("/admin/users/{member_id}/trash")
def trash_user(
    member_id: int,
    csrf_token: Annotated[str, Form()],
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
):
    validate_csrf(user, csrf_token)
    require_admin(user)
    if member_id == user["id"]:
        raise HTTPException(status_code=400, detail="不能删除当前管理员账号")
    with closing(database()) as connection:
        member = connection.execute(
            "SELECT id FROM users WHERE id=? AND deleted_at IS NULL", (member_id,)
        ).fetchone()
        if member is None:
            raise HTTPException(status_code=404, detail="成员不存在")
        connection.execute(
            "UPDATE users SET active=0,deleted_at=? WHERE id=?",
            (isoformat(utc_now()), member_id),
        )
        connection.execute("DELETE FROM sessions WHERE user_id=?", (member_id,))
        connection.commit()
    return RedirectResponse("/admin/members", status_code=303)


@app.post("/admin/users/{member_id}/restore")
def restore_user(
    member_id: int,
    csrf_token: Annotated[str, Form()],
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
):
    validate_csrf(user, csrf_token)
    require_admin(user)
    with closing(database()) as connection:
        member = connection.execute(
            "SELECT id FROM users WHERE id=? AND deleted_at IS NOT NULL", (member_id,)
        ).fetchone()
        if member is None:
            raise HTTPException(status_code=404, detail="回收记录不存在")
        connection.execute(
            "UPDATE users SET active=1,deleted_at=NULL WHERE id=?", (member_id,)
        )
        connection.commit()
    return RedirectResponse(f"/admin/users/{member_id}", status_code=303)


@app.get("/admin/members/trash", response_class=HTMLResponse)
def member_trash_page(
    request: Request, user: Annotated[sqlite3.Row, Depends(require_web_user)]
):
    require_admin(user)
    with closing(database()) as connection:
        deleted_users = format_row_datetimes(
            connection.execute(
                "SELECT * FROM users WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC"
            ).fetchall(),
            "created_at",
            "deleted_at",
        )
        deleted_authorizations = format_row_datetimes(
            connection.execute(
                "SELECT * FROM registration_authorizations WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC"
            ).fetchall(),
            "created_at",
            "registered_at",
            "revoked_at",
            "deleted_at",
        )
    return templates.TemplateResponse(
        request,
        "admin_member_trash.html",
        {
            "user": user,
            "deleted_users": deleted_users,
            "deleted_authorizations": deleted_authorizations,
        },
    )


def assistant_sse_event(event_name: str, payload: dict[str, object]) -> str:
    return f"event: {event_name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def assistant_guide_stream(
    answer: str,
    skill_name: str,
    remaining: int | None,
    daily_limit: int | None,
    unlimited: bool = False,
) -> Iterator[str]:
    yield assistant_sse_event(
        "progress",
        {"stage": "guide", "message": "正在加载平台使用指南", "details": {"skill": skill_name}},
    )
    yield assistant_sse_event(
        "result",
        {
            "answer": answer,
            "mode": "usage-guide",
            "sources": [],
            "skills": [skill_name],
            "quota": assistant_quota_payload(
                remaining, daily_limit, False, unlimited=unlimited
            ),
        },
    )


def record_assistant_trace(
    trace: dict[str, object],
    stage: str,
    details: dict[str, object],
) -> None:
    if stage == "skills":
        trace["skills"] = list(details.get("skills") or [])
    elif stage == "tool" and details.get("tool"):
        tools = trace.setdefault("tools", [])
        if isinstance(tools, list):
            tools.append(str(details["tool"]))
    elif stage == "fallback":
        trace["fallback_reason"] = str(details.get("reason") or "model_unconfigured")


def assistant_answer_stream(
    question: str,
    usage_id: int,
    remaining: int | None,
    daily_limit: int | None,
    model_config: dict[str, str] | None = None,
    quota_counted: bool = True,
    unlimited: bool = False,
) -> Iterator[str]:
    events: queue.Queue[tuple[str, dict[str, object]]] = queue.Queue()
    trace: dict[str, object] = {"skills": [], "tools": [], "fallback_reason": None}
    started = time.perf_counter()

    def publish(stage: str, message: str, details: dict[str, object]) -> None:
        record_assistant_trace(trace, stage, details)
        events.put(("progress", {"stage": stage, "message": message, "details": details}))

    def worker() -> None:
        try:
            publish("search", "正在检索团队知识库", {"query": question})
            search_result = search_knowledge(question, 5)
            clarification = str(search_result.get("clarification") or "")
            if clarification:
                complete_assistant_usage(
                    usage_id,
                    "completed",
                    answer_mode="clarification",
                    routed_skills=["project-matching"],
                    tool_calls=[],
                    source_count=0,
                    duration_ms=round((time.perf_counter() - started) * 1000),
                )
                events.put(
                    (
                        "result",
                        {
                            "answer": clarification,
                            "mode": "clarification",
                            "sources": [],
                            "skills": ["project-matching"],
                            "quota": assistant_quota_payload(
                                remaining, daily_limit, quota_counted, unlimited=unlimited
                            ),
                        },
                    )
                )
                return
            publish(
                "search-result",
                f"知识库初步命中{len(search_result['results'])}份资料",
                {"sources": len(search_result["results"])},
            )
            answer, mode, sources, skills = answer_with_knowledge_then_web(
                question,
                search_result["results"],
                progress=publish,
                model_config=model_config,
            )
            complete_assistant_usage(
                usage_id,
                "completed",
                answer_mode=mode,
                routed_skills=list(trace["skills"]),
                tool_calls=list(trace["tools"]),
                source_count=len(sources),
                duration_ms=round((time.perf_counter() - started) * 1000),
                fallback_reason=str(trace["fallback_reason"] or "") or None,
            )
            events.put(
                (
                    "result",
                    {
                        "answer": answer,
                        "mode": mode,
                        "sources": sources,
                        "skills": skills,
                        "quota": assistant_quota_payload(
                            remaining, daily_limit, quota_counted, unlimited=unlimited
                        ),
                    },
                )
            )
        except Exception as error:
            complete_assistant_usage(
                usage_id,
                "failed",
                routed_skills=list(trace["skills"]),
                tool_calls=list(trace["tools"]),
                duration_ms=round((time.perf_counter() - started) * 1000),
                fallback_reason=str(trace["fallback_reason"] or "") or None,
                error_type=type(error).__name__,
                error_message=str(error),
            )
            detail = error.detail if isinstance(error, HTTPException) else "知识库答疑暂时不可用，请稍后重试。"
            events.put(("error", {"detail": str(detail)}))

    threading.Thread(target=worker, daemon=True, name=f"assistant-{usage_id}").start()
    while True:
        event_name, payload = events.get()
        yield assistant_sse_event(event_name, payload)
        if event_name in {"result", "error"}:
            break


@app.post("/assistant/answer")
def assistant_answer(
    request: Request,
    question: Annotated[str, Form(min_length=2, max_length=500)],
    csrf_token: Annotated[str, Form()],
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
    stream: Annotated[str | None, Form()] = None,
    user_api_base: Annotated[str | None, Form(max_length=500)] = None,
    user_api_key: Annotated[str | None, Form(max_length=500)] = None,
    user_api_model: Annotated[str | None, Form(max_length=200)] = None,
):
    validate_csrf(user, csrf_token)
    admin_unlimited = bool(user["is_admin"])
    guide = quick_guide_answer(question, str(request.base_url))
    if guide:
        answer, skill_name = guide
        daily_limit = None if admin_unlimited else assistant_limit_for_user(int(user["id"]))
        remaining = (
            None
            if admin_unlimited
            else max(0, int(daily_limit) - assistant_usage_today(int(user["id"])))
        )
        if stream == "true":
            return StreamingResponse(
                assistant_guide_stream(
                    answer, skill_name, remaining, daily_limit, unlimited=admin_unlimited
                ),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        return JSONResponse(
            {
                "answer": answer,
                "mode": "usage-guide",
                "sources": [],
                "skills": [skill_name],
                "quota": assistant_quota_payload(
                    remaining, daily_limit, False, unlimited=admin_unlimited
                ),
            }
        )
    model_config = validate_user_model_config(user_api_base, user_api_key, user_api_model)
    if model_config or admin_unlimited:
        usage_id = create_unmetered_assistant_usage(
            int(user["id"]),
            question,
            provider_mode="user-api" if model_config else "admin-unlimited",
        )
        daily_limit = None if admin_unlimited else assistant_limit_for_user(int(user["id"]))
        remaining = (
            None
            if admin_unlimited
            else max(0, int(daily_limit) - assistant_usage_today(int(user["id"])))
        )
    else:
        usage_id, remaining, daily_limit = reserve_assistant_usage(int(user["id"]), question)
    if stream == "true":
        return StreamingResponse(
            assistant_answer_stream(
                question,
                usage_id,
                remaining,
                daily_limit,
                model_config=model_config,
                quota_counted=not bool(model_config) and not admin_unlimited,
                unlimited=admin_unlimited,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    started = time.perf_counter()
    trace: dict[str, object] = {"skills": [], "tools": [], "fallback_reason": None}

    def capture_progress(stage: str, message: str, details: dict[str, object]) -> None:
        del message
        record_assistant_trace(trace, stage, details)

    try:
        search_result = search_knowledge(question, 5)
        clarification = str(search_result.get("clarification") or "")
        if clarification:
            complete_assistant_usage(
                usage_id,
                "completed",
                answer_mode="clarification",
                routed_skills=["project-matching"],
                tool_calls=[],
                source_count=0,
                duration_ms=round((time.perf_counter() - started) * 1000),
            )
            return JSONResponse(
                {
                    "answer": clarification,
                    "mode": "clarification",
                    "sources": [],
                    "skills": ["project-matching"],
                    "quota": assistant_quota_payload(
                        remaining,
                        daily_limit,
                        not bool(model_config) and not admin_unlimited,
                        unlimited=admin_unlimited,
                    ),
                }
            )
        answer, mode, sources, skills = answer_with_knowledge_then_web(
            question,
            search_result["results"],
            progress=capture_progress,
            model_config=model_config,
        )
        complete_assistant_usage(
            usage_id,
            "completed",
            answer_mode=mode,
            routed_skills=skills,
            tool_calls=list(trace["tools"]),
            source_count=len(sources),
            duration_ms=round((time.perf_counter() - started) * 1000),
            fallback_reason=str(trace["fallback_reason"] or "") or None,
        )
        return JSONResponse(
            {
                "answer": answer,
                "mode": mode,
                "sources": sources,
                "skills": skills,
                "quota": assistant_quota_payload(
                    remaining,
                    daily_limit,
                    not bool(model_config) and not admin_unlimited,
                    unlimited=admin_unlimited,
                ),
            }
        )
    except Exception as error:
        complete_assistant_usage(
            usage_id,
            "failed",
            routed_skills=list(trace["skills"]),
            tool_calls=list(trace["tools"]),
            duration_ms=round((time.perf_counter() - started) * 1000),
            fallback_reason=str(trace["fallback_reason"] or "") or None,
            error_type=type(error).__name__,
            error_message=str(error),
        )
        raise


@app.get("/admin/health/{section}", response_class=HTMLResponse)
def admin_health_detail(
    request: Request,
    section: str,
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
):
    require_admin(user)
    runtime = read_status_file(HEALTH_STATUS_PATH)
    backup = read_status_file(BACKUP_STATUS_PATH)
    oss_sync = read_status_file(OSS_SYNC_STATUS_PATH)
    oss_cache = read_status_file(OSS_INDEX_CACHE_STATUS_PATH)
    snapshot_retention = read_status_file(SNAPSHOT_RETENTION_STATUS_PATH)
    index = knowledge_index_stats()
    requested_activity = request.query_params.get("activity", "").strip()
    activity_filters = {
        "business": ("业务调用", "api_usage.counts_toward_usage = 1"),
        "mcp_connection": ("MCP连接检测", "api_usage.activity_type = 'mcp_connection'"),
        "mcp_tools_list": ("工具列表", "api_usage.activity_type = 'mcp_tools_list'"),
        "mcp_search": ("实际检索", "api_usage.activity_type = 'mcp_search'"),
        "mcp_document": ("文档读取", "api_usage.activity_type = 'mcp_document'"),
    }
    selected_activity = requested_activity if requested_activity in activity_filters else ""
    activity_filter_label = activity_filters.get(selected_activity, ("全部调用", ""))[0]
    activity_descriptions = {
        "business": "计入用户累计调用的REST请求和实际MCP工具调用。连接检测与工具发现不计入。",
        "mcp_connection": "扣子或其他客户端用于初始化、状态确认和保持连接，不读取知识库正文。",
        "mcp_tools_list": (
            "客户端读取当前MCP提供的工具清单，包括知识检索、文档读取、公示名单查询、"
            "政策检索、项目目录匹配和服务状态检查；不读取具体知识内容。"
        ),
        "mcp_search": "客户端已经执行知识库、公示名单、政策或项目目录检索。",
        "mcp_document": "客户端根据检索结果中的文档编号读取完整正文和来源信息。",
    }
    activity_description = activity_descriptions.get(selected_activity, "显示最近的REST与MCP调用记录。")
    with closing(database()) as connection:
        active_users = int(connection.execute("SELECT COUNT(*) FROM users WHERE active = 1").fetchone()[0])
        active_tokens = int(
            connection.execute("SELECT COUNT(*) FROM device_tokens WHERE revoked_at IS NULL").fetchone()[0]
        )
        calls_since_24_hours = isoformat(utc_now() - timedelta(hours=24))
        recent_calls_query = """
            SELECT api_usage.endpoint, api_usage.method, api_usage.called_at,
                   api_usage.activity_type, api_usage.activity_name,
                   COALESCE(NULLIF(api_usage.activity_name,''), api_usage.endpoint) AS activity_display,
                   users.username, device_tokens.label
            FROM api_usage
            JOIN users ON users.id = api_usage.user_id
            JOIN device_tokens ON device_tokens.id = api_usage.device_token_id
        """
        recent_calls_parameters: tuple[object, ...] = ()
        if selected_activity:
            recent_calls_query += (
                f" WHERE api_usage.called_at >= ? AND {activity_filters[selected_activity][1]}"
            )
            recent_calls_parameters = (calls_since_24_hours,)
        recent_calls_query += " ORDER BY api_usage.id DESC LIMIT ?"
        recent_calls_parameters += (100 if selected_activity else 30,)
        recent_calls = format_row_datetimes(
            connection.execute(recent_calls_query, recent_calls_parameters).fetchall(),
            "called_at",
        )
        business_calls_24h = int(
            connection.execute(
                "SELECT COUNT(*) FROM api_usage WHERE called_at >= ? AND counts_toward_usage = 1",
                (calls_since_24_hours,),
            ).fetchone()[0]
        )
        mcp_activity_counts = {
            str(row["activity_type"]): int(row["calls"])
            for row in connection.execute(
                """
                SELECT activity_type, COUNT(*) AS calls
                FROM api_usage
                WHERE called_at >= ? AND activity_type LIKE 'mcp_%'
                GROUP BY activity_type
                """,
                (calls_since_24_hours,),
            ).fetchall()
        }
        failed_updates = format_row_datetimes(connection.execute(
            """
            SELECT id, original_name, status, error_message, created_at, completed_at
            FROM knowledge_update_jobs WHERE status = 'failed'
            ORDER BY id DESC LIMIT 30
            """
        ).fetchall(), "created_at", "completed_at")
        access_users = format_row_datetimes(connection.execute(
            """
            SELECT users.id, users.username, users.company_name, users.is_admin, users.active,
                   users.created_at,
                   COUNT(DISTINCT device_tokens.id) AS token_count,
                   COUNT(DISTINCT CASE WHEN device_tokens.revoked_at IS NULL THEN device_tokens.id END) AS active_token_count,
                   COUNT(DISTINCT CASE WHEN device_tokens.revoked_at IS NOT NULL THEN device_tokens.id END) AS revoked_token_count,
                   COUNT(CASE WHEN api_usage.counts_toward_usage = 1 THEN 1 END) AS call_count,
                   MAX(device_tokens.last_used_at) AS last_used_at
            FROM users
            LEFT JOIN device_tokens ON device_tokens.user_id = users.id
            LEFT JOIN api_usage ON api_usage.device_token_id = device_tokens.id
            GROUP BY users.id
            ORDER BY users.active DESC, users.is_admin DESC, users.id
            """
        ).fetchall(), "created_at", "last_used_at")
        access_tokens = format_row_datetimes(connection.execute(
            """
            SELECT device_tokens.id, users.username, device_tokens.label,
                   device_tokens.token_prefix, device_tokens.created_at,
                   device_tokens.last_used_at, device_tokens.revoked_at,
                   COUNT(CASE WHEN api_usage.counts_toward_usage = 1 THEN 1 END) AS call_count
            FROM device_tokens
            JOIN users ON users.id = device_tokens.user_id
            LEFT JOIN api_usage ON api_usage.device_token_id = device_tokens.id
            GROUP BY device_tokens.id
            ORDER BY device_tokens.id DESC
            LIMIT 100
            """
        ).fetchall(), "created_at", "last_used_at", "revoked_at")
        assistant_since_7_days = isoformat(utc_now() - timedelta(days=7))
        assistant_day_start, assistant_day_end = assistant_day_bounds()
        assistant_summary = connection.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed,
                   SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed,
                   SUM(CASE WHEN fallback_reason IS NOT NULL THEN 1 ELSE 0 END) AS fallbacks,
                   ROUND(AVG(CASE WHEN duration_ms IS NOT NULL THEN duration_ms END)) AS avg_duration_ms,
                   MAX(duration_ms) AS max_duration_ms
            FROM assistant_usage
            WHERE started_at >= ?
            """,
            (assistant_since_7_days,),
        ).fetchone()
        assistant_user_rows = connection.execute(
            """
            SELECT users.id, users.username, users.active, users.assistant_daily_limit,
                   COUNT(assistant_usage.id) AS calls_7d,
                   SUM(CASE WHEN assistant_usage.status = 'failed' THEN 1 ELSE 0 END) AS failed_7d,
                   SUM(CASE WHEN assistant_usage.fallback_reason IS NOT NULL THEN 1 ELSE 0 END) AS fallback_7d,
                   ROUND(AVG(assistant_usage.duration_ms)) AS avg_duration_ms,
                   SUM(CASE WHEN assistant_usage.started_at >= ? AND assistant_usage.started_at < ?
                                 AND assistant_usage.status IN ('running','completed')
                                 AND assistant_usage.quota_counted = 1 THEN 1 ELSE 0 END) AS used_today,
                   SUM(CASE WHEN assistant_usage.provider_mode = 'user-api' THEN 1 ELSE 0 END) AS user_api_7d
            FROM users
            LEFT JOIN assistant_usage
              ON assistant_usage.user_id = users.id AND assistant_usage.started_at >= ?
            GROUP BY users.id
            ORDER BY calls_7d DESC, users.id
            """,
            (assistant_day_start, assistant_day_end, assistant_since_7_days),
        ).fetchall()
        assistant_recent_rows = connection.execute(
            """
            SELECT assistant_usage.id, users.username, assistant_usage.question,
                   assistant_usage.status, assistant_usage.answer_mode,
                   assistant_usage.routed_skills, assistant_usage.tool_calls,
                   assistant_usage.source_count, assistant_usage.duration_ms,
                   assistant_usage.fallback_reason, assistant_usage.error_type,
                   assistant_usage.error_message, assistant_usage.started_at,
                   assistant_usage.provider_mode, assistant_usage.quota_counted
            FROM assistant_usage
            JOIN users ON users.id = assistant_usage.user_id
            WHERE assistant_usage.started_at >= ?
            ORDER BY assistant_usage.id DESC
            LIMIT 100
            """,
            (assistant_since_7_days,),
        ).fetchall()
        assistant_anomaly_rows = connection.execute(
            """
            SELECT assistant_usage.id, users.username, assistant_usage.question,
                   assistant_usage.status, assistant_usage.answer_mode,
                   assistant_usage.source_count, assistant_usage.duration_ms,
                   assistant_usage.fallback_reason, assistant_usage.error_type,
                   assistant_usage.error_message, assistant_usage.started_at
            FROM assistant_usage
            JOIN users ON users.id = assistant_usage.user_id
            WHERE assistant_usage.started_at >= ?
              AND (assistant_usage.status = 'failed'
                   OR assistant_usage.fallback_reason IS NOT NULL
                   OR COALESCE(assistant_usage.duration_ms, 0) >= 30000)
            ORDER BY assistant_usage.id DESC
            LIMIT 50
            """,
            (assistant_since_7_days,),
        ).fetchall()
        assistant_problem_question_rows = connection.execute(
            """
            SELECT question,
                   COUNT(*) AS calls_7d,
                   SUM(CASE WHEN status = 'failed' OR fallback_reason IS NOT NULL THEN 1 ELSE 0 END) AS abnormal_7d,
                   ROUND(AVG(duration_ms)) AS avg_duration_ms,
                   ROUND(AVG(source_count), 1) AS avg_source_count,
                   MAX(started_at) AS last_called_at
            FROM assistant_usage
            WHERE started_at >= ?
            GROUP BY question
            HAVING COUNT(*) >= 3
               AND 1.0 * SUM(CASE WHEN status = 'failed' OR fallback_reason IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*) >= 0.4
            ORDER BY 1.0 * abnormal_7d / calls_7d DESC, calls_7d DESC, last_called_at DESC
            LIMIT 30
            """,
            (assistant_since_7_days,),
        ).fetchall()
    skill_counts: Counter[str] = Counter()
    tool_counts: Counter[str] = Counter()
    skill_metrics: dict[str, dict[str, int]] = {}
    project_metrics: dict[str, dict[str, object]] = {}
    assistant_recent: list[dict[str, object]] = []
    for row in assistant_recent_rows:
        item = dict(row)
        try:
            skills = json.loads(str(item.get("routed_skills") or "[]"))
        except json.JSONDecodeError:
            skills = []
        try:
            tools = json.loads(str(item.get("tool_calls") or "[]"))
        except json.JSONDecodeError:
            tools = []
        skill_counts.update(str(skill) for skill in skills)
        tool_counts.update(str(tool) for tool in tools)
        item["skills_display"] = "、".join(str(skill) for skill in skills) or "未记录"
        item["tools_display"] = "、".join(str(tool) for tool in tools) or "未调用"
        item["started_at"] = format_chinese_datetime(str(item.get("started_at") or ""))
        assistant_recent.append(item)
        retrieval_rule = matched_project_retrieval_rule(str(item.get("question") or ""))
        if retrieval_rule:
            rule_id = str(retrieval_rule.get("id") or "未命名项目")
            project = project_metrics.setdefault(
                rule_id,
                {
                    "rule_id": rule_id,
                    "aliases": set(),
                    "total": 0,
                    "clarifications": 0,
                    "zero_sources": 0,
                    "abnormal": 0,
                    "duration": 0,
                },
            )
            alias = matched_project_alias(str(item.get("question") or ""), retrieval_rule)
            if alias:
                project["aliases"].add(alias)
            project["total"] += 1
            project["clarifications"] += int(item.get("answer_mode") == "clarification")
            project["zero_sources"] += int(int(item.get("source_count") or 0) == 0)
            project["abnormal"] += int(bool(item.get("status") == "failed" or item.get("fallback_reason")))
            project["duration"] += int(item.get("duration_ms") or 0)
        for skill in skills:
            metrics = skill_metrics.setdefault(
                str(skill), {"total": 0, "abnormal": 0, "sources": 0, "duration": 0}
            )
            metrics["total"] += 1
            metrics["sources"] += int(item.get("source_count") or 0)
            metrics["duration"] += int(item.get("duration_ms") or 0)
            if item.get("status") == "failed" or item.get("fallback_reason"):
                metrics["abnormal"] += 1
    assistant_anomalies = format_row_datetimes(assistant_anomaly_rows, "started_at")
    assistant_problem_questions = format_row_datetimes(
        assistant_problem_question_rows, "last_called_at"
    )
    assistant_alerts: list[dict[str, str]] = []
    total_calls = int(assistant_summary["total"] or 0)
    abnormal_calls = int(assistant_summary["failed"] or 0) + int(assistant_summary["fallbacks"] or 0)
    if total_calls >= 3 and abnormal_calls / total_calls >= 0.2:
        assistant_alerts.append(
            {"level": "high", "title": "整体问答异常率偏高", "detail": f"近7日{abnormal_calls}/{total_calls}次失败或降级，请检查模型和检索链路。"}
        )
    assistant_users: list[dict[str, object]] = []
    for row in assistant_user_rows:
        item = dict(row)
        calls = int(item.get("calls_7d") or 0)
        abnormal = int(item.get("failed_7d") or 0) + int(item.get("fallback_7d") or 0)
        if calls >= 3 and abnormal / calls >= 0.4:
            item["risk_label"] = "高异常率"
            assistant_alerts.append(
                {"level": "high", "title": f"用户 {item['username']} 异常率偏高", "detail": f"近7日{abnormal}/{calls}次失败或降级。"}
            )
        elif calls >= 30:
            item["risk_label"] = "高频调用"
            assistant_alerts.append(
                {"level": "medium", "title": f"用户 {item['username']} 调用频繁", "detail": f"近7日共{calls}次问答，请确认是否为正常批量使用。"}
            )
        else:
            item["risk_label"] = "正常"
        assistant_users.append(item)
    slow_calls = sum(1 for item in assistant_anomalies if int(item.get("duration_ms") or 0) >= 30000)
    if slow_calls >= 3:
        assistant_alerts.append(
            {"level": "medium", "title": "慢问答连续出现", "detail": f"近7日有{slow_calls}次问答超过30秒。"}
        )
    for item in assistant_problem_questions[:5]:
        calls = int(item.get("calls_7d") or 0)
        abnormal = int(item.get("abnormal_7d") or 0)
        assistant_alerts.append(
            {
                "level": "high",
                "title": "高失败率问题已自动标记",
                "detail": f"“{item['question']}”近7日{abnormal}/{calls}次失败或降级。",
            }
        )
    routing_recommendations: list[str] = []
    for skill, metrics in sorted(skill_metrics.items(), key=lambda item: (-item[1]["total"], item[0])):
        if metrics["total"] < 3:
            continue
        abnormal_rate = metrics["abnormal"] / metrics["total"]
        average_sources = metrics["sources"] / metrics["total"]
        average_duration = metrics["duration"] / metrics["total"]
        if abnormal_rate >= 0.25:
            routing_recommendations.append(f"{skill}：异常率{abnormal_rate:.0%}，优先收紧触发词并检查模型降级原因。")
        elif average_sources < 2:
            routing_recommendations.append(f"{skill}：平均来源{average_sources:.1f}份，补充检索同义词和现行政策过滤。")
        elif average_duration >= 20000:
            routing_recommendations.append(f"{skill}：平均耗时{average_duration / 1000:.1f}秒，减少重复工具轮次。")
    if not routing_recommendations:
        routing_recommendations.append("样本尚不足或当前路由稳定；累计一周真实问答后自动生成针对性建议。")
    assistant_project_metrics = []
    for project in sorted(project_metrics.values(), key=lambda item: (-int(item["total"]), str(item["rule_id"]))):
        total = max(1, int(project["total"]))
        assistant_project_metrics.append(
            {
                **project,
                "aliases_display": "、".join(sorted(project["aliases"])) or "正式项目名",
                "clarification_rate": int(project["clarifications"]) / total,
                "abnormal_rate": int(project["abnormal"]) / total,
                "avg_duration_ms": int(project["duration"]) / total,
            }
        )
    sections = {
        "runtime": ("应用服务", [("状态", runtime.get("status", "待采集")), ("检查时间", runtime.get("checked_at", "待采集")), ("公开地址", os.environ.get("JIAOTANG_PUBLIC_HOST", "未配置"))]),
        "index": ("全文索引", [("连接状态", "已连接" if index["connected"] else "未连接"), ("全文资料", index["documents"]), ("文本字符", index["characters"]), ("索引更新时间", index["updated_at"] or "待采集")]),
        "backup": ("最近备份", [("状态", backup.get("status", "待采集")), ("完成时间", backup.get("completed_at", "待采集")), ("备份位置", backup.get("backup_path", "由服务器备份任务管理"))]),
        "oss": (
            "OSS 权威知识源",
            [
                ("本地缓存状态", oss_cache.get("status", "待首次校验")),
                ("缓存模式", oss_cache.get("mode", "OSS 权威源 + 服务器查询缓存")),
                ("缓存校验时间", oss_cache.get("checked_at", "待采集")),
                ("缓存更新时间", oss_cache.get("cache_updated_at", "尚未更新")),
                ("OSS 同步状态", oss_sync.get("status", "待首次同步")),
                ("OSS 同步完成时间", oss_sync.get("completed_at", "待采集")),
                ("目标 Bucket", oss_sync.get("bucket", "未配置")),
                ("本次上传文件", oss_sync.get("uploaded_files", 0)),
                ("跳过未变化文件", oss_sync.get("skipped_files", 0)),
                ("索引快照", oss_sync.get("index_snapshot", "本次未生成")),
            ],
        ),
        "snapshot": (
            "服务器快照保留",
            [
                ("状态", snapshot_retention.get("status", "待首次整理")),
                ("完成时间", snapshot_retention.get("completed_at", "待采集")),
                ("热回滚快照", snapshot_retention.get("hot_snapshots", 0)),
                ("本次归档快照", snapshot_retention.get("archived_snapshots", 0)),
                ("保留规则", snapshot_retention.get("policy", "最近12份热快照，其余按年月归档")),
            ],
        ),
        "certificate": ("HTTPS 证书", [("证书状态", runtime.get("certificate_status", "待采集")), ("到期时间", runtime.get("certificate_expires", "待采集")), ("域名", os.environ.get("JIAOTANG_PUBLIC_HOST", "未配置"))]),
        "disk": ("磁盘使用", [("使用率", runtime.get("disk_percent", "待采集")), ("检查时间", runtime.get("checked_at", "待采集")), ("数据目录", str(DATA_DIR))]),
        "access": ("用户与凭据", [("有效用户", active_users), ("有效 API 访问凭据", active_tokens), ("权限模式", "统一知识权限")]),
        "calls": (
            "调用记录",
            [
                ("24小时业务调用", business_calls_24h, "/admin/health/calls?activity=business"),
                ("MCP连接检测", mcp_activity_counts.get("mcp_connection", 0), "/admin/health/calls?activity=mcp_connection"),
                ("工具列表", mcp_activity_counts.get("mcp_tools_list", 0), "/admin/health/calls?activity=mcp_tools_list"),
                ("实际检索", mcp_activity_counts.get("mcp_search", 0), "/admin/health/calls?activity=mcp_search"),
                ("文档读取", mcp_activity_counts.get("mcp_document", 0), "/admin/health/calls?activity=mcp_document"),
            ],
        ),
        "updates": ("失败更新", [("待处理失败", len(failed_updates)), ("回滚机制", "成功更新均保留快照")]),
        "assistant": (
            "问答分析",
            [
                ("近7日问答", int(assistant_summary["total"] or 0)),
                ("完成/失败", f"{int(assistant_summary['completed'] or 0)} / {int(assistant_summary['failed'] or 0)}"),
                ("降级回答", int(assistant_summary["fallbacks"] or 0)),
                ("平均耗时", f"{int(assistant_summary['avg_duration_ms'] or 0) / 1000:.1f} 秒"),
                ("最长耗时", f"{int(assistant_summary['max_duration_ms'] or 0) / 1000:.1f} 秒"),
                ("统计窗口", "最近7天"),
            ],
        ),
    }
    if section not in sections:
        raise HTTPException(status_code=404, detail="健康详情不存在")
    title, details = sections[section]
    disk_breakdown = production_disk_breakdown() if section == "disk" else None
    return templates.TemplateResponse(
        request,
        "admin_health_detail.html",
        {
            "user": user,
            "section": section,
            "title": title,
            "details": details,
            "recent_calls": recent_calls if section == "calls" else [],
            "activity_filter_label": activity_filter_label,
            "activity_description": activity_description,
            "selected_activity": selected_activity,
            "failed_updates": failed_updates if section == "updates" else [],
            "access_users": access_users if section == "access" else [],
            "access_tokens": access_tokens if section == "access" else [],
            "assistant_users": assistant_users if section == "assistant" else [],
            "assistant_recent": assistant_recent if section == "assistant" else [],
            "assistant_anomalies": assistant_anomalies if section == "assistant" else [],
            "assistant_skill_counts": skill_counts.most_common() if section == "assistant" else [],
            "assistant_tool_counts": tool_counts.most_common() if section == "assistant" else [],
            "assistant_alerts": assistant_alerts if section == "assistant" else [],
            "assistant_problem_questions": assistant_problem_questions if section == "assistant" else [],
            "assistant_project_metrics": assistant_project_metrics if section == "assistant" else [],
            "routing_recommendations": routing_recommendations if section == "assistant" else [],
            "assistant_default_limit": ASSISTANT_DAILY_LIMIT,
            "disk_breakdown": disk_breakdown,
        },
    )


@app.post("/admin/users/{target_user_id}/assistant-limit")
def update_user_assistant_limit(
    target_user_id: int,
    daily_limit: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()],
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
):
    require_admin(user)
    validate_csrf(user, csrf_token)
    normalized = daily_limit.strip()
    override: int | None = None
    if normalized:
        try:
            override = int(normalized)
        except ValueError as error:
            raise HTTPException(status_code=422, detail="每日额度必须为整数") from error
        if not 1 <= override <= 100:
            raise HTTPException(status_code=422, detail="每日额度须为1至100次，留空恢复默认值")
    with closing(database()) as connection:
        cursor = connection.execute(
            "UPDATE users SET assistant_daily_limit = ? WHERE id = ?",
            (override, target_user_id),
        )
        if cursor.rowcount != 1:
            raise HTTPException(status_code=404, detail="用户不存在")
        connection.commit()
    return RedirectResponse("/admin/health/assistant", status_code=303)


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


@app.get("/admin/metadata-review", response_class=HTMLResponse)
def admin_metadata_review(
    request: Request,
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
    view: str = "aliases",
    saved: str = "",
):
    require_admin(user)
    selected_view = view if view in {"aliases", "policies"} else "aliases"
    alias_candidates = list_active_learning_alias_candidates(50)
    policy_queue = list_policy_verification_queue("pending", "", 50)
    policy_propagations = list_policy_verification_propagations(30)
    cluster_operations = list_policy_cluster_manual_operations(30)
    alias_history = list_project_alias_corrections("confirmed", 30)["results"]
    project_options = sorted(
        {
            str(record.get("canonical_project_name") or "").strip()
            for record in load_project_index_records()
            if record.get("canonical_project_name")
        }
    )
    high_priority = int(policy_queue.get("high_priority_total") or 0)
    return templates.TemplateResponse(
        request,
        "admin_metadata_review.html",
        {
            "user": user,
            "selected_view": selected_view,
            "alias_candidates": alias_candidates["results"],
            "alias_candidate_total": alias_candidates["total"],
            "alias_history": alias_history,
            "policy_queue": policy_queue["results"],
            "policy_queue_total": policy_queue["total"],
            "policy_propagations": policy_propagations["results"],
            "policy_propagation_total": policy_propagations["total"],
            "cluster_operations": cluster_operations["results"],
            "cluster_operation_total": cluster_operations["total"],
            "high_priority_total": high_priority,
            "project_options": project_options,
            "saved": saved,
        },
    )


@app.post("/admin/metadata-review/aliases")
def admin_confirm_project_alias(
    raw_project_name: Annotated[str, Form()],
    canonical_project_name: Annotated[str, Form()],
    region: Annotated[str, Form()],
    start_year: Annotated[str, Form()],
    end_year: Annotated[str, Form()],
    note: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()],
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
):
    require_admin(user)
    validate_csrf(user, csrf_token)
    try:
        payload = ProjectAliasCorrectionRequest(
            raw_project_name=raw_project_name.strip(),
            canonical_project_name=canonical_project_name.strip(),
            region=region.strip(),
            start_year=int(start_year) if start_year.strip() else None,
            end_year=int(end_year) if end_year.strip() else None,
            note=note.strip(),
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail="适用年度必须为四位数字") from error
    result = create_project_alias_correction(payload, str(user["username"]))
    affected = int(result.get("matched_documents") or 0)
    return RedirectResponse(
        f"/admin/metadata-review?view=aliases&saved={quote(f'别名已确认，重新映射 {affected} 份文档')}",
        status_code=303,
    )


@app.post("/admin/metadata-review/aliases/preview", response_class=HTMLResponse)
def admin_preview_project_alias(
    request: Request,
    raw_project_name: Annotated[str, Form()],
    canonical_project_name: Annotated[str, Form()],
    region: Annotated[str, Form()],
    start_year: Annotated[str, Form()],
    end_year: Annotated[str, Form()],
    note: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()],
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
):
    require_admin(user)
    validate_csrf(user, csrf_token)
    try:
        payload = ProjectAliasCorrectionRequest(
            raw_project_name=raw_project_name.strip(),
            canonical_project_name=canonical_project_name.strip(),
            region=region.strip(),
            start_year=int(start_year) if start_year.strip() else None,
            end_year=int(end_year) if end_year.strip() else None,
            note=note.strip(),
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail="适用年度必须为四位数字") from error
    preview = preview_project_alias_correction(payload)
    return templates.TemplateResponse(
        request,
        "admin_metadata_preview.html",
        {
            "user": user,
            "preview_kind": "alias",
            "title": "别名确认预览",
            "summary": f"将“{payload.raw_project_name}”映射为“{payload.canonical_project_name}”",
            "action": "/admin/metadata-review/aliases",
            "payload": payload.model_dump(),
            "preview": preview,
        },
    )


@app.post("/admin/metadata-review/policies")
def admin_review_policy(
    queue_id: Annotated[int, Form()],
    review_status: Annotated[str, Form()],
    official_source_url: Annotated[str, Form()],
    official_document_title: Annotated[str, Form()],
    official_published_at: Annotated[str, Form()],
    validity_status: Annotated[str, Form()],
    verification_note: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()],
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
):
    require_admin(user)
    validate_csrf(user, csrf_token)
    payload = PolicyVerificationReviewRequest(
        queue_id=queue_id,
        status=review_status,
        official_source_url=official_source_url.strip(),
        official_document_title=official_document_title.strip(),
        official_published_at=official_published_at.strip() or None,
        validity_status=validity_status.strip() or None,
        verification_note=verification_note.strip(),
    )
    result = review_policy_verification(payload, str(user["username"]))
    propagated = int(result.get("propagated_documents") or 0)
    message = "政策核验结果已写入证据链"
    if propagated:
        message += f"，并传播至 {propagated} 份同源文档"
    return RedirectResponse(
        f"/admin/metadata-review?view=policies&saved={quote(message)}",
        status_code=303,
    )


@app.post("/admin/metadata-review/policies/preview", response_class=HTMLResponse)
def admin_preview_policy(
    request: Request,
    queue_id: Annotated[int, Form()],
    review_status: Annotated[str, Form()],
    official_source_url: Annotated[str, Form()],
    official_document_title: Annotated[str, Form()],
    official_published_at: Annotated[str, Form()],
    validity_status: Annotated[str, Form()],
    verification_note: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()],
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
):
    require_admin(user)
    validate_csrf(user, csrf_token)
    payload = PolicyVerificationReviewRequest(
        queue_id=queue_id,
        status=review_status,
        official_source_url=official_source_url.strip(),
        official_document_title=official_document_title.strip(),
        official_published_at=official_published_at.strip() or None,
        validity_status=validity_status.strip() or None,
        verification_note=verification_note.strip(),
    )
    preview = preview_policy_verification(payload)
    return templates.TemplateResponse(
        request,
        "admin_metadata_preview.html",
        {
            "user": user,
            "preview_kind": "policy",
            "title": "政策核验预览",
            "summary": f"核验任务 #{payload.queue_id}，预计影响 {preview['total']} 份同源文档",
            "action": "/admin/metadata-review/policies",
            "payload": payload.model_dump(),
            "preview": preview,
        },
    )


@app.post("/admin/metadata-review/policy-clusters/split")
def admin_split_policy_cluster(
    cluster_id: Annotated[int, Form()],
    document_ids: Annotated[list[int], Form()],
    note: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()],
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
):
    require_admin(user)
    validate_csrf(user, csrf_token)
    result = split_policy_document_cluster(cluster_id, document_ids, note, str(user["username"]))
    message = f"已从政策簇#{cluster_id}拆出 {result['moved_documents']} 份文档"
    return RedirectResponse(
        f"/admin/metadata-review?view=policies&saved={quote(message)}",
        status_code=303,
    )


@app.post("/admin/metadata-review/policy-clusters/{operation_id}/undo")
def admin_undo_policy_cluster_operation(
    operation_id: int,
    csrf_token: Annotated[str, Form()],
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
):
    require_admin(user)
    validate_csrf(user, csrf_token)
    result = undo_policy_cluster_operation(operation_id, str(user["username"]))
    message = f"人工政策簇操作#{operation_id}已撤销，恢复 {result['restored_documents']} 份文档"
    return RedirectResponse(
        f"/admin/metadata-review?view=policies&saved={quote(message)}",
        status_code=303,
    )


@app.get("/admin/metadata-review/policy-clusters/{cluster_id}/compare", response_class=HTMLResponse)
def admin_compare_policy_cluster(
    request: Request,
    cluster_id: int,
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
):
    require_admin(user)
    comparison = compare_policy_cluster(cluster_id)
    return templates.TemplateResponse(
        request,
        "admin_policy_cluster_compare.html",
        {"user": user, **comparison},
    )


@app.post("/admin/metadata-review/policy-clusters/merge")
def admin_merge_policy_clusters(
    source_cluster_id: Annotated[int, Form()],
    target_cluster_id: Annotated[int, Form()],
    note: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()],
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
):
    require_admin(user)
    validate_csrf(user, csrf_token)
    result = merge_policy_document_clusters(
        source_cluster_id, target_cluster_id, note, str(user["username"])
    )
    message = (
        f"政策簇#{source_cluster_id}与#{target_cluster_id}已合并，"
        f"共 {result['merged_documents']} 份文档"
    )
    return RedirectResponse(
        f"/admin/metadata-review?view=policies&saved={quote(message)}",
        status_code=303,
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
    request_oss_sync(f"knowledge-trash:{trash_id}")
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
    request_oss_sync(f"knowledge-trash-restore:{trash_id}")
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
    request_oss_sync(f"knowledge-revision:{revision_id}")
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
    request_oss_sync(f"knowledge-revision-rollback:{revision_id}")
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
            portal_payload(request, user, error=str(exc), active_page="access"),
            status_code=400,
        )
    if not company_verified(company_name):
        return templates.TemplateResponse(
            request,
            "portal.html",
            portal_payload(
                request,
                user,
                error="公司名称验证未通过，未生成用户凭据。",
                active_page="access",
            ),
            status_code=403,
        )
    with closing(database()) as connection:
        active_token = connection.execute(
            "SELECT id,token_seed FROM device_tokens "
            "WHERE user_id=? AND revoked_at IS NULL ORDER BY id DESC LIMIT 1",
            (user["id"],),
        ).fetchone()
        if active_token:
            seed = str(active_token["token_seed"] or secrets.token_urlsafe(24))
            raw_token = user_access_token(int(user["id"]), seed)
            connection.execute(
                "UPDATE device_tokens SET label=?,token_seed=?,token_prefix=?,token_hash=? WHERE id=?",
                (
                    normalized_real_name, seed, raw_token[:12], token_hash(raw_token),
                    int(active_token["id"]),
                ),
            )
        else:
            seed = secrets.token_urlsafe(24)
            raw_token = user_access_token(int(user["id"]), seed)
            connection.execute(
                """
                INSERT INTO device_tokens(
                    user_id,label,token_prefix,token_hash,token_seed,created_at
                ) VALUES (?,?,?,?,?,?)
                """,
                (
                    user["id"], normalized_real_name, raw_token[:12], token_hash(raw_token),
                    seed, isoformat(utc_now()),
                ),
            )
        connection.execute(
            "UPDATE users SET real_name=? WHERE id=?",
            (normalized_real_name, user["id"]),
        )
        connection.commit()
        updated_user = connection.execute(
            "SELECT * FROM users WHERE id=?", (user["id"],)
        ).fetchone()
    return templates.TemplateResponse(
        request,
        "portal.html",
        portal_payload(request, updated_user, message="唯一用户 Token 已启用，可随时查看和复制。", active_page="access"),
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
    return RedirectResponse("/access", status_code=303)


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
            portal_payload(
                request,
                user,
                error=f"暂不支持 {extension or '无扩展名'} 文件。",
                active_page="knowledge-admin",
            ),
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
                request_oss_sync(f"knowledge-upload-duplicate:{job_id}")
                return RedirectResponse("/admin/knowledge-update", status_code=303)
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
                request_oss_sync(f"knowledge-upload-waiting:{job_id}")
                return RedirectResponse("/admin/knowledge-update", status_code=303)
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
            request_oss_sync(f"knowledge-upload-indexed:{job_id}")
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
    return RedirectResponse("/admin/knowledge-update", status_code=303)


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
    request_oss_sync(f"knowledge-upload-rollback:{job_id}")
    return RedirectResponse("/admin/knowledge-update", status_code=303)


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
    if not re.fullmatch(r"\d+\.\d+(?:\.\d+)?(?:[-+][0-9A-Za-z.-]+)?", normalized_version):
        return templates.TemplateResponse(
            request,
            "portal.html",
            portal_payload(
                request,
                user,
                error="版本号必须使用 1.0 或 1.2.3 格式。",
                active_page="skill-admin",
            ),
            status_code=400,
        )
    with closing(database()) as connection:
        if connection.execute(
            "SELECT 1 FROM skill_releases WHERE version = ?", (normalized_version,)
        ).fetchone():
            return templates.TemplateResponse(
                request,
                "portal.html",
                portal_payload(
                    request,
                    user,
                    error="该 Skills 版本已经存在。",
                    active_page="skill-admin",
                ),
                status_code=409,
            )
    if Path(skill_package.filename or "").suffix.lower() != ".zip":
        return templates.TemplateResponse(
            request,
            "portal.html",
            portal_payload(
                request,
                user,
                error="Skills 发布包必须是 ZIP 文件。",
                active_page="skill-admin",
            ),
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
            portal_payload(
                request,
                user,
                error=f"Skills 发布包校验失败：{error}",
                active_page="skill-admin",
            ),
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
    return RedirectResponse("/admin/releases", status_code=303)


@app.post("/releases/{release_id}/acknowledge")
def acknowledge_release_announcement(
    release_id: int,
    csrf_token: Annotated[str, Form()],
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
):
    validate_csrf(user, csrf_token)
    with closing(database()) as connection:
        announcement = connection.execute(
            "SELECT 1 FROM release_announcements WHERE release_id=? AND status='published'",
            (release_id,),
        ).fetchone()
        if announcement is None:
            raise HTTPException(status_code=404, detail="版本公告不存在或尚未发布")
        connection.execute(
            """
            INSERT INTO user_release_acknowledgements(user_id,release_id,acknowledged_at)
            VALUES (?,?,?) ON CONFLICT(user_id,release_id) DO NOTHING
            """,
            (user["id"], release_id, isoformat(utc_now())),
        )
        connection.commit()
    return RedirectResponse("/portal", status_code=303)


@app.get("/admin/releases/{release_id}/announcement-preview", response_class=HTMLResponse)
def preview_release_announcement(
    request: Request,
    release_id: int,
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
):
    require_admin(user)
    with closing(database()) as connection:
        row = connection.execute(
            """
            SELECT a.*,r.version,r.release_notes
            FROM release_announcements a JOIN skill_releases r ON r.id=a.release_id
            WHERE a.release_id=?
            """,
            (release_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="版本公告草稿不存在")
    announcement = {
        **dict(row),
        "body_html": render_guide_markdown(str(row["body"])),
        "quick_phrases": json.loads(str(row["quick_phrases"])),
    }
    return templates.TemplateResponse(
        request,
        "release_announcement_preview.html",
        {"user": user, "announcement": announcement},
    )


@app.post("/admin/releases/{release_id}/announcement/publish")
def publish_release_announcement(
    release_id: int,
    csrf_token: Annotated[str, Form()],
    user: Annotated[sqlite3.Row, Depends(require_web_user)],
):
    require_admin(user)
    validate_csrf(user, csrf_token)
    with closing(database()) as connection:
        announcement = connection.execute(
            "SELECT 1 FROM release_announcements WHERE release_id=?", (release_id,)
        ).fetchone()
        if announcement is None:
            raise HTTPException(status_code=404, detail="版本公告草稿不存在")
        now = isoformat(utc_now())
        connection.execute(
            "UPDATE release_announcements SET status='published',published_at=?,updated_at=? "
            "WHERE release_id=?",
            (now, now, release_id),
        )
        connection.execute(
            "DELETE FROM user_release_acknowledgements WHERE release_id=?", (release_id,)
        )
        connection.commit()
    return RedirectResponse(f"/admin/releases/{release_id}/announcement-preview", status_code=303)


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
    return SearchResponse.model_validate(public_search_knowledge(payload.query, payload.limit))


@app.post("/v1/lists/search")
def list_search_api(
    payload: PublicListSearchRequest,
    user: Annotated[sqlite3.Row, Depends(require_api_user)],
):
    del user
    return search_public_list_entities(**payload.model_dump())


@app.post("/v1/policies/search")
def policy_search_api(
    payload: PolicySearchRequest,
    user: Annotated[sqlite3.Row, Depends(require_api_user)],
):
    del user
    return search_policy_documents(**payload.model_dump())


@app.post("/v1/projects/match")
def project_match_api(
    payload: ProjectCatalogMatchRequest,
    user: Annotated[sqlite3.Row, Depends(require_api_user)],
):
    del user
    return match_project_catalog(**payload.model_dump())


@app.get("/v1/admin/project-aliases")
def project_aliases_api(
    user: Annotated[sqlite3.Row, Depends(require_api_user)],
    status_filter: str = "",
    limit: int = 100,
):
    require_admin(user)
    return list_project_alias_corrections(status_filter, limit)


@app.get("/v1/admin/project-alias-candidates")
def project_alias_candidates_api(
    user: Annotated[sqlite3.Row, Depends(require_api_user)],
    limit: int = 100,
):
    require_admin(user)
    return list_active_learning_alias_candidates(limit)


@app.post("/v1/admin/project-aliases")
def create_project_alias_api(
    payload: ProjectAliasCorrectionRequest,
    user: Annotated[sqlite3.Row, Depends(require_api_user)],
):
    require_admin(user)
    return create_project_alias_correction(payload, str(user["username"]))


@app.get("/v1/admin/metadata-evidence")
def metadata_evidence_api(
    user: Annotated[sqlite3.Row, Depends(require_api_user)],
    review_status: str = "needs_review",
    confidence: str = "",
    limit: int = 100,
):
    require_admin(user)
    return list_metadata_evidence(review_status, confidence, limit)


@app.get("/v1/admin/policy-verification")
def policy_verification_queue_api(
    user: Annotated[sqlite3.Row, Depends(require_api_user)],
    status_filter: str = "pending",
    priority: str = "",
    limit: int = 100,
):
    require_admin(user)
    return list_policy_verification_queue(status_filter, priority, limit)


@app.get("/v1/admin/policy-propagations")
def policy_verification_propagations_api(
    user: Annotated[sqlite3.Row, Depends(require_api_user)],
    limit: int = 100,
):
    require_admin(user)
    return list_policy_verification_propagations(limit)


@app.post("/v1/admin/policy-verification")
def review_policy_verification_api(
    payload: PolicyVerificationReviewRequest,
    user: Annotated[sqlite3.Row, Depends(require_api_user)],
):
    require_admin(user)
    return review_policy_verification(payload, str(user["username"]))


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
                "SELECT COUNT(*) FROM api_usage WHERE user_id = ? AND counts_toward_usage = 1",
                (user["id"],),
            ).fetchone()[0]
        )
        calls_last_30_days = int(
            connection.execute(
                "SELECT COUNT(*) FROM api_usage WHERE user_id = ? AND called_at >= ? AND counts_toward_usage = 1",
                (user["id"], thirty_days_ago),
            ).fetchone()[0]
        )
        endpoint_rows = connection.execute(
            """
            SELECT endpoint, COUNT(*) AS calls
            FROM api_usage
            WHERE user_id = ? AND counts_toward_usage = 1
            GROUP BY endpoint
            ORDER BY calls DESC, endpoint
            """,
            (user["id"],),
        ).fetchall()
        recent_rows = connection.execute(
            """
            SELECT endpoint, method, activity_type, activity_name, called_at
            FROM api_usage
            WHERE user_id = ? AND counts_toward_usage = 1
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
            UsageCall(
                endpoint=row["endpoint"],
                method=row["method"],
                activity_type=row["activity_type"],
                activity_name=row["activity_name"],
                called_at=row["called_at"],
            )
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
    return public_search_knowledge(query, limit)


@knowledge_mcp.tool()
def knowledge_document(document_id: int) -> dict[str, object]:
    """按检索结果中的文档编号读取完整正文和来源信息。"""
    return get_knowledge_document(document_id)


@knowledge_mcp.tool()
def public_list_search(
    enterprise_name: str = "",
    project_name: str = "",
    year: int | None = None,
    batch: str = "",
    region: str = "",
    limit: int = 20,
) -> dict[str, object]:
    """按企业、项目、年度、批次或地区查询政府公示与认定名单实体。"""
    return search_public_list_entities(
        enterprise_name, project_name, year, batch, region, limit
    )


@knowledge_mcp.tool()
def policy_search(
    query: str = "",
    project_name: str = "",
    region: str = "",
    document_stage: str = "",
    validity_status: str = "",
    year: int | None = None,
    limit: int = 8,
) -> dict[str, object]:
    """按标准项目、地区、文件阶段、有效性和年度查询政策文档。"""
    return search_policy_documents(
        query, project_name, region, document_stage, validity_status, year, limit
    )


@knowledge_mcp.tool()
def project_catalog_match(
    regions: list[str] | None = None,
    keywords: list[str] | None = None,
    limit: int = 20,
) -> dict[str, object]:
    """按地区和企业关键词匹配理论候选项目，不替代当期政策核验。"""
    return match_project_catalog(regions, keywords, limit)


@knowledge_mcp.tool()
def knowledge_service_status() -> dict[str, object]:
    """查看知识库连接状态、文档总数与最近索引时间。"""
    return knowledge_index_stats()


app.mount("/mcp", MCPBearerMiddleware(knowledge_mcp.streamable_http_app()))
