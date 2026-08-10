from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
PORTAL = ROOT / "services" / "knowledge-portal"
ALLOWED = ("jiaotang-kb", "zshjiaotang.cn")


def remove_allowed_identifiers(blob: bytes) -> bytes:
    cleaned = blob
    for value in ALLOWED:
        for encoding in ("ascii", "utf-16le", "utf-16be"):
            cleaned = cleaned.replace(value.encode(encoding), b"")
    return cleaned


def has_legacy_brand(blob: bytes) -> bool:
    patterns = (
        b"jiaotang",
        b"JIAOTANG",
        "jiaotang".encode("utf-16le"),
        "JIAOTANG".encode("utf-16le"),
        "jiaotang".encode("utf-16be"),
        "JIAOTANG".encode("utf-16be"),
        "焦糖".encode("utf-8"),
        "焦糖".encode("utf-16le"),
        "焦糖".encode("utf-16be"),
    )
    return any(pattern in blob for pattern in patterns)


def test_public_skill_sources_only_retain_mcp_and_endpoint_compatibility():
    suite = json.loads((SKILLS / "suite-manifest.json").read_text())
    findings: list[str] = []
    for skill_name in suite["skills"]:
        skill_root = SKILLS / skill_name
        for path in sorted(skill_root.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            relative = path.relative_to(SKILLS).as_posix()
            public_name = relative.lower()
            for allowed in ALLOWED:
                public_name = public_name.replace(allowed, "")
            if "jiaotang" in public_name or "焦糖" in relative:
                findings.append(f"path:{relative}")
            if has_legacy_brand(remove_allowed_identifiers(path.read_bytes())):
                findings.append(f"content:{relative}")
    assert findings == []


def test_portal_visible_configuration_uses_public_namespace():
    assistant = (PORTAL / "app" / "assistant_runtime.py").read_text()
    template = (PORTAL / "templates" / "portal.html").read_text()
    script = (PORTAL / "static" / "portal.js").read_text()

    assert "登录焦糖网站" not in assistant
    assert "登录共创研究院网站" in assistant
    for legacy_name in (
        "JIAOTANG_KB_BASE_URL=",
        "JIAOTANG_KB_API_BASE_URL=",
        "JIAOTANG_KB_ENDPOINT=",
        "JIAOTANG_KB_MCP_URL=",
        "JIAOTANG_KB_DEVICE_ID=",
        "JIAOTANG_KB_DEVICE_NAME=",
        "JIAOTANG_KB_TOKEN=",
    ):
        assert legacy_name not in template
        assert legacy_name not in script
    for public_name in (
        "GONGCHUANG_KB_BASE_URL=",
        "GONGCHUANG_KB_API_BASE_URL=",
        "GONGCHUANG_KB_ENDPOINT=",
        "GONGCHUANG_KB_MCP_URL=",
        "GONGCHUANG_KB_DEVICE_ID=",
        "GONGCHUANG_KB_TOKEN=",
    ):
        assert public_name in template
        assert public_name in script
