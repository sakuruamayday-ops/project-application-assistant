"""Bounded, user-confirmed desktop diagnostics; never accepts raw logs."""
import re
import json
from typing import Literal
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator


# Exact client result codes; unknown codes remain ordinary issues requiring review.
_AUTOMATIC_OUTCOMES: dict[str, tuple[Literal['bug', 'other'], str, str]] = {
    'GC-AUTO-RECOVERED': ('other', '客户端过程问题已恢复', '任务已完成，过程问题已恢复；保留原异常记录供复盘。'),
    'GC-AUTO-PROTECTION': ('other', '客户端文件保护提示', '触发已有文件或删除保护；保留已有文件和诊断记录，不等同于运行故障。'),
    'GC-AUTO-CANCELLED-WITH-ISSUES': ('bug', '客户端任务已取消（含过程异常）', '用户已停止任务；停止前的过程异常仍需查看。'),
    'GC-AUTO-DELIVERED-WITH-ISSUES': ('bug', '客户端已有输出（含过程异常）', '任务已有输出；过程中仍有未确认恢复的异常，诊断记录保留。'),
    'GC-AUTO-INTERRUPTED': ('bug', '客户端任务中断（结果待确认）', '任务中断，未完成操作的结果待确认；保留异常记录。'),
}


def redact(value: str) -> str:
    value = re.sub(r"(?i)(authorization|api[_ -]?key|token|password|密码|密钥)\s*[:=：]\s*[^\n,，;；]+", "[已隐藏凭据]", value)
    value = re.sub(r"(?i)\b(?:bearer\s+\S+|(?:sk-|jtk_|gcd_)[A-Za-z0-9_\-]{8,}|eyJ[A-Za-z0-9_\-.]{20,})", "[已隐藏凭据]", value)
    value = re.sub(r"https?://[^\s<>]+", "[已隐藏网址]", value)
    value = re.sub(r"(?:[A-Za-z]:[\\/]|/|~/)[^\n,，;；<>]+", "[已隐藏路径]", value)
    return value


def feedback_category(diagnostic: dict) -> Literal["bug", "other"]:
    """Use exact current result codes; legacy upgrade stops still require current-turn event evidence."""
    outcome = _AUTOMATIC_OUTCOMES.get(diagnostic.get('code'))
    if outcome is not None:
        return outcome[0]
    if diagnostic.get("code") != "GC-AUTO-FAILURE":
        return "bug"
    context = json.loads(diagnostic.get("conversation_context") or "{}")
    if not isinstance(context, dict) or not isinstance(context.get("failed_turn"), int):
        return "bug"
    events = context.get("events")
    if not isinstance(events, list) or context.get("omitted_event_count", 0) != 0:
        return "bug"
    upgrade = False
    for event in events:
        if not isinstance(event, dict) or not isinstance(event.get("data"), dict):
            continue
        kind, data = event.get("type"), event["data"]
        message = data.get("message")
        tool_failed = (kind == "tool/ptc-dispatch" and data.get("isError") is True
                       or kind == "tool/result" and isinstance(message, dict) and message.get("isError") is True)
        source = data.get("source")
        delivery = source.get("delivery") if isinstance(source, dict) and source.get("kind") == "plugin:gongchuang-policy-gate" else None
        turn = delivery.get("turn") if kind == "user/message" and isinstance(delivery, dict) else data.get("turn")
        if turn != context["failed_turn"]:
            if turn is None and tool_failed:
                return "bug"
            continue
        if tool_failed or isinstance(delivery, dict) and delivery.get("phase") == "failed":
            return "bug"
        if kind == "turn/end":
            reason = data.get("reason")
            error = reason.get("error") if isinstance(reason, dict) else None
            if not (isinstance(reason, dict) and reason.get("kind") == "error"
                    and isinstance(error, dict) and error.get("code") == "GC-ACCOUNT-UPGRADE"):
                return "bug"
            upgrade = True
    return "other" if upgrade else "bug"


def feedback_subject(diagnostic: dict, category: Literal['bug', 'other']) -> str:
    """Choose a controlled title from saved metadata without loading conversation context."""
    outcome = _AUTOMATIC_OUTCOMES.get(diagnostic.get('code'))
    if outcome is not None:
        return outcome[1] + ' · ' + diagnostic['code']
    return '客户端升级拦截 · GC-ACCOUNT-UPGRADE' if category == 'other' else '客户端错误 · ' + diagnostic['code']


class ClientErrorReport(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    client_version: str = Field(min_length=1, max_length=64, pattern=r"^[0-9A-Za-z.+-]+$")
    skill_version: str = Field(max_length=64, pattern=r"^[0-9A-Za-z.+-]*$")
    platform: Literal["darwin-arm64", "darwin-x64", "win32-x64", "unknown"]
    occurred_at: datetime
    module: Literal["general", "workbench", "account", "model", "runtime", "conversation"]
    code: str = Field(min_length=1, max_length=64, pattern=r"^GC-[A-Z0-9-]+$")
    summary: str = Field(max_length=180)
    steps: str = Field(max_length=3000)
    conversation_context: str | None = Field(default=None, max_length=8_000_000)

    @field_validator('conversation_context')
    @classmethod
    def context_json(cls, value):
        if value is not None:
            json.loads(value)
        return value

    def diagnostic(self) -> dict:
        result = self.model_dump(mode="json")
        result["summary"] = {"conversation": "用户反馈的会话问题", "workbench": "申报与体检操作未完成", "account": "账号操作未完成", "model": "模型操作未完成", "runtime": "客户端运行异常", "general": "用户反馈的客户端问题"}[self.module]
        outcome = _AUTOMATIC_OUTCOMES.get(self.code)
        if outcome is not None:
            result['summary'] = outcome[2]
        result["steps"] = redact(self.steps)
        if self.conversation_context is not None:
            def clean(value, key=''):
                if re.search(r'(?:^|[_-])(?:authorization|api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret|cookie|headers|environment|env)$', key, re.I):
                    return '[已隐藏凭据]'
                if isinstance(value, dict):
                    return {k: clean(v, k) for k, v in value.items()}
                if isinstance(value, list):
                    return [clean(v) for v in value]
                if isinstance(value, str):
                    if re.match(r'^data:|^[A-Za-z0-9+/]{1000,}={0,2}$', value):
                        return '[已省略二进制内容]'
                    if key == 'type':
                        return value
                    value = re.sub(r"(?i)(authorization|api[_ -]?key|token|password|密码|密钥)\s*[\"']?\s*[:=：]\s*[\"']?[^\n,，;；]+", '[已隐藏凭据]', value)
                    value = re.sub(r"(?i)\b(?:bearer\s+\S+|(?:sk-|jtk_|gcd_)[A-Za-z0-9_\-]{8,}|eyJ[A-Za-z0-9_\-.]{20,})", '[已隐藏凭据]', value)
                    value = re.sub(r"https?://[^\s<>]+", '[已隐藏网址]', value)
                    return re.sub(r"(?:[A-Za-z]:[\\/]|/(?:Users|home|private|var|tmp|etc|opt)/|~/)[^\s\"'<>]+", '[已隐藏路径]', value)
                return value
            result['conversation_context'] = json.dumps(clean(json.loads(self.conversation_context)), ensure_ascii=False)
        else:
            result.pop('conversation_context', None)
        return result


class ErrorReportBodyLimit:
    """Bound diagnostic, final-report and original-attachment uploads before JSON parsing."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope["path"]
        if path in {"/v1/client-reports", "/v1/client-attachments"}:
            limit = 32_000
        elif re.fullmatch(r"/v1/client-(?:reports|attachments)/[^/]+/content", path):
            limit = 2_000_000
        elif path == "/v1/client-error-reports":
            limit = 48_000_000
        elif re.fullmatch(r"/v1/client-error-reports/\d+/files", path):
            limit = 2_000_000
        else:
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > limit:
                from starlette.responses import JSONResponse
                detail = ("原始附件过大" if path.startswith("/v1/client-attachments")
                          else "定稿报告过大" if path.startswith("/v1/client-reports") else "诊断报告过大")
                return await JSONResponse({"detail": detail}, status_code=413)(scope, receive, send)
            if not message.get("more_body", False):
                break
        delivered = False
        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()
        await self.app(scope, replay, send)
