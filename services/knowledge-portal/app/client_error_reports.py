"""Bounded, user-confirmed desktop diagnostics; never accepts raw logs."""
import re
import json
from typing import Literal
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator


def redact(value: str) -> str:
    value = re.sub(r"(?i)(authorization|api[_ -]?key|token|password|密码|密钥)\s*[:=：]\s*[^\n,，;；]+", "[已隐藏凭据]", value)
    value = re.sub(r"(?i)\b(?:bearer\s+\S+|(?:sk-|jtk_|gcd_)[A-Za-z0-9_\-]{8,}|eyJ[A-Za-z0-9_\-.]{20,})", "[已隐藏凭据]", value)
    value = re.sub(r"https?://[^\s<>]+", "[已隐藏网址]", value)
    value = re.sub(r"(?:[A-Za-z]:[\\/]|/|~/)[^\n,，;；<>]+", "[已隐藏路径]", value)
    return value


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
    """Reject oversized diagnostic uploads before authentication or JSON parsing."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] != "/v1/client-error-reports":
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > 48_000_000:
                from starlette.responses import JSONResponse
                return await JSONResponse({"detail": "诊断报告过大"}, status_code=413)(scope, receive, send)
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
