from __future__ import annotations

import json
import zipfile
from pathlib import Path

from scripts.build_standard_package import included
from scripts.public_namespace_gate import verify_public_namespace


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
    main = (PORTAL / "app" / "main.py").read_text()
    template = (PORTAL / "templates" / "portal.html").read_text()
    script = (PORTAL / "static" / "portal.js").read_text()

    assert "登录焦糖网站" not in assistant
    assert "登录共创研究院网站" in assistant
    assert "焦糖" not in main
    assert '@app.get("/install/jiaotang-agent.mjs")' not in main
    for storage_key in (
        "gongchuang-user-model-api",
        "gongchuang-page-direction",
        "gongchuang-kb-device-id",
        "gongchuang-cockpit-question",
    ):
        assert storage_key in script
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


def test_public_namespace_gate_covers_current_public_sources():
    report = verify_public_namespace(source_root=ROOT)
    assert report["status"] == "pass"
    assert report["finding_count"] == 0
    assert report["allowed_identifiers"] == ["jiaotang-kb", "zshjiaotang.cn"]
    assert report["allowed_compatibility_components"] == [
        "skills/_runtime/jiaotang-kb/jiaotang-agent.mjs",
        "_runtime/jiaotang-kb/jiaotang-agent.mjs",
    ]
    assert report["historical_release_policy"] == "preserve_immutable"


def test_public_namespace_gate_rejects_archive_content_and_paths(tmp_path):
    package = tmp_path / "gongchuang-release.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("skills/example/SKILL.md", "由焦糖生成")
        archive.writestr("mcp/jiaotang-agent.mjs", "export default true")
    report = verify_public_namespace(archives=[package])
    assert report["status"] == "fail"
    assert {item["kind"] for item in report["findings"]} == {
        "archive_content",
        "archive_path",
    }


def test_public_namespace_gate_allows_only_exact_mcp_and_domain_exceptions(tmp_path):
    package = tmp_path / "gongchuang-release.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(
            "skills/example/SKILL.md",
            "配置 mcpServers.jiaotang-kb 并连接 https://zshjiaotang.cn/mcp/",
        )
    report = verify_public_namespace(
        archives=[package],
        asset_names=["gongchuang-research-institute-skills-V1.6.3.zip"],
    )
    assert report["status"] == "pass"

    rejected = verify_public_namespace(
        asset_names=["jiaotang-research-institute-skills-V1.6.3.zip"],
    )
    assert rejected["status"] == "fail"
    assert rejected["findings"][0]["kind"] == "release_asset_name"

    extended_identifier = tmp_path / "extended-identifier.zip"
    with zipfile.ZipFile(extended_identifier, "w") as archive:
        archive.writestr("manifest.json", "jiaotang-kb-device-id")
    extended_report = verify_public_namespace(archives=[extended_identifier])
    assert extended_report["status"] == "fail"
    assert extended_report["findings"][0]["kind"] == "archive_content"


def test_public_namespace_gate_allows_only_exact_generic_runtime_component(tmp_path):
    package = tmp_path / "gongchuang-release.zip"
    component = "skills/_runtime/jiaotang-kb/jiaotang-agent.mjs"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(
            "gongchuang-research-institute-skills/" + component,
            'const protocol = "JIAOTANG-SIGNATURE-V1";',
        )
        archive.writestr(
            "gongchuang-research-institute-skills/suite-release-manifest.json",
            json.dumps({component: "0" * 64}),
        )
    report = verify_public_namespace(archives=[package])
    assert report["status"] == "pass"

    desktop_index = tmp_path / "desktop-index.zip"
    with zipfile.ZipFile(desktop_index, "w") as archive:
        archive.writestr(
            "skill-bundle-index.json",
            json.dumps({"files": {"_runtime/jiaotang-kb/jiaotang-agent.mjs": "0" * 64}}),
        )
    desktop_report = verify_public_namespace(archives=[desktop_index])
    assert desktop_report["status"] == "pass"

    rejected = tmp_path / "wrong-runtime-location.zip"
    with zipfile.ZipFile(rejected, "w") as archive:
        archive.writestr(
            "mcp/jiaotang-agent.mjs",
            'const protocol = "JIAOTANG-SIGNATURE-V1";',
        )
    rejected_report = verify_public_namespace(archives=[rejected])
    assert rejected_report["status"] == "fail"


def test_standard_package_excludes_legacy_local_mcp_runtime():
    assert not included(Path("skills/_runtime/jiaotang-kb/jiaotang-agent.mjs"))
    source = (ROOT / "scripts/build_standard_package.py").read_text(encoding="utf-8")
    assert 'f"gongchuang-research-institute-skills-{release[\'tag\']}.zip"' in source
    assert '"name": "共创研究院企业全生命周期助手"' in source
