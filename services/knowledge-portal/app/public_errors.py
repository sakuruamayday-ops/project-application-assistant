from __future__ import annotations

import re
from dataclasses import dataclass


_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(?:api[-_ ]?key|authorization|password|secret|token)\b\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"\b(?:sk|jtk)_[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
)
_PATH_PATTERNS = (
    re.compile(r"(?:/Users|/home|/private|/opt|/srv|/var|/etc|/tmp)/[^\s\"']+"),
    re.compile(r"\b[A-Za-z]:\\[^\r\n\"']+"),
)
_INTERNAL_PATTERNS = (
    re.compile(r"(?i)\btraceback\b|\bstack trace\b"),
    re.compile(r"(?i)\b(?:FileNotFoundError|PermissionError|ConnectionError|TimeoutError|OSError)\b"),
    re.compile(r"\b[A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception)\b"),
    re.compile(r"(?i)\b(?:urllib3?|httpx|requests|sqlite3|pydantic)\."),
    re.compile(r"(?i)<!doctype\s+html|<html\b|<body\b"),
    re.compile(r"(?i)\b(?:upstream|connection refused|name or service not known)\b"),
)


@dataclass(frozen=True)
class PublicError:
    detail: str
    diagnostic_code: str
    redacted: bool


def diagnostic_code(status_code: int, *, unexpected: bool = False) -> str:
    if unexpected:
        return "GC-SVC-UNEXPECTED"
    family = "REQ" if 400 <= status_code < 500 else "SVC"
    return f"GC-{family}-{status_code}"


def redacted_log_detail(value: object) -> str:
    """Return a bounded diagnostic string that contains no secret or local path."""

    text = re.sub(r"[\x00-\x1f\x7f]+", " ", str(value or "")).strip()
    for pattern in (*_SECRET_PATTERNS, *_PATH_PATTERNS):
        text = pattern.sub("[已脱敏]", text)
    text = re.sub(r"\s+", " ", text)
    return text[:500]


def needs_public_redaction(value: object) -> bool:
    text = str(value or "")
    if any(pattern.search(text) for pattern in _SECRET_PATTERNS):
        return True
    if any(pattern.search(text) for pattern in _PATH_PATTERNS):
        return True
    return any(pattern.search(text) for pattern in _INTERNAL_PATTERNS)


def default_public_detail(status_code: int) -> str:
    if status_code == 400:
        return "请求内容未通过校验，请检查后重试。"
    if status_code == 401:
        return "登录状态无效，请重新登录。"
    if status_code == 403:
        return "当前账号无权执行此操作。"
    if status_code == 404:
        return "请求的资源不存在。"
    if status_code == 409:
        return "当前状态已发生变化，请刷新后重试。"
    if status_code == 422:
        return "请求参数不完整或格式不正确。"
    if status_code == 429:
        return "请求过于频繁，请稍后重试。"
    return "服务暂时不可用，请稍后重试。"


def public_error(
    status_code: int,
    detail: object,
    *,
    unexpected: bool = False,
) -> PublicError:
    normalized = re.sub(r"[\x00-\x1f\x7f]+", " ", str(detail or "")).strip()
    redacted = unexpected or not normalized or needs_public_redaction(normalized)
    return PublicError(
        detail=default_public_detail(status_code) if redacted else normalized[:500],
        diagnostic_code=diagnostic_code(status_code, unexpected=unexpected),
        redacted=redacted,
    )


def public_error_payload(
    status_code: int,
    detail: object,
    *,
    unexpected: bool = False,
) -> dict[str, str]:
    error = public_error(status_code, detail, unexpected=unexpected)
    return {
        "detail": error.detail,
        "diagnostic_code": error.diagnostic_code,
    }


def public_error_text(
    status_code: int,
    detail: object,
    *,
    unexpected: bool = False,
) -> str:
    """Format a controlled error for HTML views without exposing raw details."""

    error = public_error(status_code, detail, unexpected=unexpected)
    return f"{error.detail}（诊断码：{error.diagnostic_code}）"
