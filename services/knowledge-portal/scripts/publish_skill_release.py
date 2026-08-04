#!/usr/bin/env python3
"""Publish an already-signed generic + WorkBuddy release to the portal."""
from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import struct
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from release_transaction import (  # noqa: E402
    DEFAULT_LEASE_TTL_SECONDS,
    STATE_RANK,
    acquire_release_lease,
    monitor_release_transaction,
    supersede_failed_release_transaction,
    transition_release_transaction,
    verify_transaction_files,
)


TRUSTED_PUBLISHER_PUBLIC_KEY = (
    "ssh-ed25519 "
    "AAAAC3NzaC1lZDI1NTE5AAAAICcDJACg0boSFDFpF2Akq0srFwlQYU9XiIpm/ldEEFeU "
    "jiaotang-codex-skill-release"
)
TRUSTED_PUBLISHER_FINGERPRINT = (
    "SHA256:+BLR7x5xFci+u1Ue3KoFs9jFzzS+ebNk46JlfDUoEJI"
)
WORKBUDDY_SIGNATURE_NAMESPACE = "codex-workbuddy-plugin-manifest"
WORKBUDDY_MARKETPLACE_SIGNATURE_NAMESPACE = (
    "codex-workbuddy-marketplace-manifest"
)
GENERIC_SIGNATURE_NAMESPACE = "codex-skill-suite-manifest"
SSHSIG_MAGIC = b"SSHSIG"
SSH_ED25519 = b"ssh-ed25519"
MAX_EXPANDED_BYTES = 1024 * 1024 * 1024
STAGED_STATUS = "staged-awaiting-acceptance"
PENDING_STAGE_STATUSES = {STAGED_STATUS, "releasing"}


def _parse_lease_credential(payload: object) -> tuple[str, str]:
    if not isinstance(payload, dict):
        raise RuntimeError("发布租约凭证根节点必须是对象")
    owner = str(payload.get("holder_id") or "")
    token = str(payload.get("lease_token") or "")
    if not owner or not token:
        raise RuntimeError("发布租约凭证缺少holder_id或lease_token")
    return owner, token


def _load_lease_credential(arguments) -> tuple[str, str]:
    if arguments.lease_credential_stdin:
        return _parse_lease_credential(json.loads(sys.stdin.read()))
    if arguments.lease_credential_file is None:
        raise RuntimeError("发布写操作必须提供租约凭证")
    return _parse_lease_credential(
        json.loads(
            arguments.lease_credential_file.read_text(encoding="utf-8")
        )
    )


def _load_verified_transaction(arguments) -> tuple[dict[str, object], dict[str, object], str]:
    required = (
        arguments.transaction_manifest,
        arguments.transaction_signature,
        arguments.publisher_public_key,
    )
    if any(path is None for path in required):
        raise RuntimeError("发布写操作必须提供签名事务清单、签名和发布公钥")
    verification = verify_transaction_files(
        manifest_path=arguments.transaction_manifest,
        signature_path=arguments.transaction_signature,
        public_key_path=arguments.publisher_public_key,
        expected_fingerprint=TRUSTED_PUBLISHER_FINGERPRINT,
    )
    signature_payload = json.loads(
        arguments.transaction_signature.read_text(encoding="utf-8")
    )
    public_key_text = arguments.publisher_public_key.read_text(encoding="utf-8")
    manifest = verification["manifest"]
    if str(manifest.get("version") or "") != arguments.version:
        raise RuntimeError("发布事务版本与门户操作版本不一致")
    return verification, signature_payload, public_key_text


def _validate_transaction_artifacts(
    manifest: dict[str, object],
    artifacts: dict[str, object],
) -> None:
    participants = manifest.get("participants")
    if not isinstance(participants, dict):
        raise RuntimeError("发布事务清单缺少participants")
    portal = participants.get("portal")
    if not isinstance(portal, dict):
        raise RuntimeError("发布事务清单缺少portal参与方")
    expected = portal.get("package_sha256")
    if not isinstance(expected, dict):
        raise RuntimeError("发布事务清单缺少门户包哈希")
    actual = {
        target: str(data["sha256"])
        for target, data in artifacts.items()
        if isinstance(data, dict) and data.get("sha256")
    }
    if {str(key): str(value) for key, value in expected.items()} != actual:
        raise RuntimeError("门户候选包与签名发布事务清单不一致")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_members(archive: zipfile.ZipFile) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    expanded_bytes = 0
    for info in archive.infolist():
        name = info.filename.replace("\\", "/")
        path = PurePosixPath(name)
        mode = (info.external_attr >> 16) & 0o170000
        if (
            not name
            or path.is_absolute()
            or ".." in path.parts
            or "\\" in info.filename
            or "\x00" in name
            or ":" in name
            or re.match(r"^[A-Za-z]:", name)
            or mode == stat.S_IFLNK
        ):
            raise ValueError(f"ZIP 包含不安全路径：{name}")
        canonical = "/".join(part for part in path.parts if part not in {"", "."})
        if canonical in seen:
            raise ValueError(f"ZIP 包含重复路径：{name}")
        seen.add(canonical)
        expanded_bytes += int(info.file_size)
        if expanded_bytes > MAX_EXPANDED_BYTES:
            raise ValueError("ZIP 解压后超过 1 GiB 安全上限")
        names.append(name)
    return names


def _single_json(archive: zipfile.ZipFile, suffix: str) -> dict[str, object]:
    matches = [name for name in _safe_members(archive) if name.endswith(suffix)]
    if len(matches) != 1:
        raise ValueError(f"ZIP 中应且仅应包含一个 {suffix}，实际 {len(matches)} 个")
    value = json.loads(archive.read(matches[0]).decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{suffix} 必须是 JSON 对象")
    return value


def semantic_version(value: str) -> str:
    match = re.fullmatch(
        r"(\d+)\.(\d+)(?:\.(\d+))?(?:\.(\d+))?",
        value.strip(),
    )
    if not match:
        raise ValueError("版本必须形如 1.3、1.3.1 或 1.3.1.1")
    patch = match.group(3) or "0"
    hotfix = f".{match.group(4)}" if match.group(4) is not None else ""
    return f"{match.group(1)}.{match.group(2)}.{patch}{hotfix}"


ARTIFACT_TARGETS = ("generic", "workbuddy", "macos", "windows")


def require_complete_workbuddy_platform_set(
    packages: dict[str, Path],
    *,
    allow_platform_hotfix: bool = False,
) -> None:
    platform_targets = {
        target for target in packages if target in {"macos", "windows"}
    }
    if allow_platform_hotfix and platform_targets == {"windows"} and set(packages) == {"windows"}:
        return
    if platform_targets and platform_targets != {"macos", "windows"}:
        raise ValueError("macOS与Windows WorkBuddy包必须同一事务成对发布")
    if platform_targets and "workbuddy" in packages:
        raise ValueError("分平台WorkBuddy包不得与旧统一包混合发布")


def _ssh_string(value: bytes | str) -> bytes:
    payload = value.encode("utf-8") if isinstance(value, str) else value
    return struct.pack(">I", len(payload)) + payload


class _SshReader:
    def __init__(self, value: bytes, label: str) -> None:
        self.value = value
        self.label = label
        self.offset = 0

    def bytes(self, length: int) -> bytes:
        if length < 0 or self.offset + length > len(self.value):
            raise ValueError(f"{self.label} 数据截断或长度非法")
        result = self.value[self.offset : self.offset + length]
        self.offset += length
        return result

    def uint32(self) -> int:
        return struct.unpack(">I", self.bytes(4))[0]

    def string(self) -> bytes:
        return self.bytes(self.uint32())

    def finish(self) -> None:
        if self.offset != len(self.value):
            raise ValueError(f"{self.label} 含未解析的尾随数据")


def _strict_base64(value: str, label: str) -> bytes:
    if not value or not re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", value):
        raise ValueError(f"{label} 不是规范 Base64")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError(f"{label} 不是规范 Base64") from error
    canonical = base64.b64encode(decoded).decode("ascii").rstrip("=")
    if canonical != value.rstrip("="):
        raise ValueError(f"{label} 不是规范 Base64")
    return decoded


def _parse_public_key(value: bytes | str) -> dict[str, object]:
    text = value.decode("utf-8") if isinstance(value, bytes) else value
    lines = text.strip().splitlines()
    if len(lines) != 1 or "\x00" in text:
        raise ValueError("发布公钥必须且只能包含一把公钥")
    match = re.fullmatch(
        r"ssh-ed25519[ \t]+([A-Za-z0-9+/=]+)(?:[ \t]+.*)?",
        lines[0],
    )
    if not match:
        raise ValueError("发布公钥不是 OpenSSH Ed25519 公钥")
    blob = _strict_base64(match.group(1), "发布公钥主体")
    reader = _SshReader(blob, "发布公钥")
    algorithm = reader.string()
    raw_key = reader.string()
    reader.finish()
    canonical_blob = _ssh_string(SSH_ED25519) + _ssh_string(raw_key)
    if algorithm != SSH_ED25519 or len(raw_key) != 32 or blob != canonical_blob:
        raise ValueError("发布公钥不是规范 Ed25519 公钥")
    fingerprint = "SHA256:" + base64.b64encode(
        hashlib.sha256(blob).digest()
    ).decode("ascii").rstrip("=")
    return {
        "blob": blob,
        "raw_key": raw_key,
        "fingerprint": fingerprint,
    }


def _parse_sshsig(value: bytes) -> dict[str, bytes]:
    text = value.decode("utf-8")
    match = re.fullmatch(
        r"-----BEGIN SSH SIGNATURE-----\r?\n"
        r"([A-Za-z0-9+/=\r\n]+)\r?\n"
        r"-----END SSH SIGNATURE-----\s*",
        text,
    )
    if not match:
        raise ValueError("签名不是规范的 OpenSSH SSHSIG 文本")
    blob = _strict_base64(
        re.sub(r"\r?\n", "", match.group(1)),
        "OpenSSH SSHSIG",
    )
    reader = _SshReader(blob, "OpenSSH SSHSIG")
    if reader.bytes(len(SSHSIG_MAGIC)) != SSHSIG_MAGIC:
        raise ValueError("OpenSSH SSHSIG 魔数不正确")
    version = reader.uint32()
    public_key_blob = reader.string()
    namespace = reader.string()
    reserved = reader.string()
    hash_algorithm = reader.string()
    signature_blob = reader.string()
    reader.finish()
    if version != 1:
        raise ValueError(f"不支持的 OpenSSH SSHSIG 版本：{version}")
    signature_reader = _SshReader(signature_blob, "OpenSSH Ed25519 签名")
    signature_algorithm = signature_reader.string()
    signature = signature_reader.string()
    signature_reader.finish()
    if signature_algorithm != SSH_ED25519 or len(signature) != 64:
        raise ValueError("OpenSSH SSHSIG 不是有效 Ed25519 签名")
    return {
        "public_key_blob": public_key_blob,
        "namespace": namespace,
        "reserved": reserved,
        "hash_algorithm": hash_algorithm,
        "signature": signature,
    }


def _verify_manifest_signature(
    payload: bytes,
    signature: bytes,
    supplied_public_key: bytes,
    *,
    namespace: str = WORKBUDDY_SIGNATURE_NAMESPACE,
) -> None:
    pinned = _parse_public_key(TRUSTED_PUBLISHER_PUBLIC_KEY)
    supplied = _parse_public_key(supplied_public_key)
    if pinned["fingerprint"] != TRUSTED_PUBLISHER_FINGERPRINT:
        raise ValueError("内置发布公钥与固定指纹不一致")
    if supplied["blob"] != pinned["blob"]:
        raise ValueError("归档发布公钥与内置固定公钥不一致")
    parsed = _parse_sshsig(signature)
    if parsed["public_key_blob"] != pinned["blob"]:
        raise ValueError("签名内嵌公钥与固定公钥不一致")
    if parsed["namespace"].decode("utf-8") != namespace:
        raise ValueError("发布清单签名命名空间不匹配")
    if parsed["reserved"]:
        raise ValueError("OpenSSH SSHSIG reserved 字段必须为空")
    hash_name = parsed["hash_algorithm"].decode("ascii")
    if hash_name not in {"sha256", "sha512"}:
        raise ValueError(f"不支持的 OpenSSH SSHSIG 哈希算法：{hash_name}")
    payload_digest = hashlib.new(hash_name, payload).digest()
    signed_data = b"".join(
        (
            SSHSIG_MAGIC,
            _ssh_string(namespace),
            _ssh_string(b""),
            _ssh_string(hash_name),
            _ssh_string(payload_digest),
        )
    )
    try:
        Ed25519PublicKey.from_public_bytes(
            pinned["raw_key"]
        ).verify(parsed["signature"], signed_data)
    except InvalidSignature as error:
        raise ValueError("WorkBuddy Ed25519 签名验证失败") from error


def _validate_generic_integrity(
    archive: zipfile.ZipFile,
    names: list[str],
    suite: dict[str, object],
) -> dict[str, object]:
    file_names = {
        name for name in names if not archive.getinfo(name).is_dir()
    }
    suite_names = [
        name
        for name in file_names
        if name.endswith("/skills/suite-manifest.json")
    ]
    if len(suite_names) != 1:
        raise ValueError("通用包应且仅应包含一个套件清单")
    suite_name = suite_names[0]
    suite_parts = PurePosixPath(suite_name).parts
    if len(suite_parts) != 3 or suite_parts[1:] != (
        "skills",
        "suite-manifest.json",
    ):
        raise ValueError("通用包套件清单不在固定目录")
    bundle_root = suite_parts[0]
    prefix = f"{bundle_root}/"
    companions = {
        f"{prefix}suite-release-manifest.json",
        f"{prefix}suite-release-manifest.sig",
        f"{prefix}publisher-ed25519.pub",
        f"{prefix}publisher-key.json",
    }
    if not companions.issubset(file_names):
        raise ValueError("通用包签名伴随物不完整")
    unexpected_outer = sorted(
        name for name in file_names if not name.startswith(prefix)
    )
    if unexpected_outer:
        raise ValueError(
            "通用包包含固定根目录外文件："
            + "、".join(unexpected_outer[:5])
        )

    manifest_name = f"{prefix}suite-release-manifest.json"
    signature_name = f"{prefix}suite-release-manifest.sig"
    public_key_name = f"{prefix}publisher-ed25519.pub"
    metadata_name = f"{prefix}publisher-key.json"
    manifest_bytes = archive.read(manifest_name)
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    metadata = json.loads(archive.read(metadata_name).decode("utf-8"))
    if (
        not isinstance(metadata, dict)
        or metadata.get("algorithm") not in {"Ed25519", "OpenSSH-Ed25519"}
        or metadata.get("fingerprint_sha256")
        != TRUSTED_PUBLISHER_FINGERPRINT
    ):
        raise ValueError("通用包发布者元数据不合规")
    _verify_manifest_signature(
        manifest_bytes,
        archive.read(signature_name),
        archive.read(public_key_name),
        namespace=GENERIC_SIGNATURE_NAMESPACE,
    )
    release = suite.get("release")
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != 1
        or manifest.get("artifact_type") != "skill-suite"
        or manifest.get("release_tag")
        != (release.get("tag") if isinstance(release, dict) else None)
        or manifest.get("release_version")
        != (release.get("version") if isinstance(release, dict) else None)
        or manifest.get("skills") != suite.get("skills")
        or manifest.get("skill_count") != len(suite.get("skills") or [])
    ):
        raise ValueError("通用包签名清单与套件清单不一致")
    declared = manifest.get("files")
    if not isinstance(declared, dict) or not declared:
        raise ValueError("通用包签名清单缺少files哈希表")
    actual_files = {
        name[len(prefix) :]
        for name in file_names
        if name.startswith(prefix) and name not in companions
    }
    missing_skill_entries = [
        f"skills/{skill}/SKILL.md"
        for skill in suite.get("skills") or []
        if f"skills/{skill}/SKILL.md" not in actual_files
    ]
    if missing_skill_entries:
        raise ValueError(
            "通用包缺少声明技能入口："
            + "、".join(missing_skill_entries[:5])
        )
    if set(declared) != actual_files:
        missing = sorted(set(declared) - actual_files)
        unexpected = sorted(actual_files - set(declared))
        details = [
            *(f"缺少：{name}" for name in missing[:3]),
            *(f"未签名：{name}" for name in unexpected[:3]),
        ]
        raise ValueError("通用包文件集合与签名清单不一致：" + "；".join(details))
    for relative, expected_hash in declared.items():
        relative_path = PurePosixPath(str(relative))
        if (
            not isinstance(relative, str)
            or relative_path.is_absolute()
            or ".." in relative_path.parts
            or "\\" in relative
            or ":" in relative
            or not re.fullmatch(r"[0-9a-f]{64}", str(expected_hash))
        ):
            raise ValueError("通用包签名清单包含非法路径或SHA-256")
        actual_hash = hashlib.sha256(
            archive.read(prefix + relative)
        ).hexdigest()
        if actual_hash != expected_hash:
            raise ValueError(f"通用包签名文件哈希不一致：{relative}")
    return {
        "status": "verified",
        "publisher_fingerprint": TRUSTED_PUBLISHER_FINGERPRINT,
        "signature_namespace": GENERIC_SIGNATURE_NAMESPACE,
        "verified_files": len(declared),
        "archive_entries": len(file_names),
    }


def _validate_workbuddy_integrity(
    archive: zipfile.ZipFile,
    names: list[str],
    suite: dict[str, object],
    target: str,
) -> dict[str, object]:
    file_names = {
        name for name in names if not archive.getinfo(name).is_dir()
    }
    marketplace_names = [
        name
        for name in file_names
        if name.endswith("/.codebuddy-plugin/marketplace.json")
    ]
    plugin_names = [
        name
        for name in file_names
        if name.endswith("/.codebuddy-plugin/plugin.json")
    ]
    if len(marketplace_names) != 1 or len(plugin_names) != 1:
        raise ValueError("WorkBuddy 包应且仅应包含一个市场清单和一个插件清单")
    marketplace_name = marketplace_names[0]
    marketplace_parts = PurePosixPath(marketplace_name).parts
    plugin_json_name = plugin_names[0]
    plugin_parts = PurePosixPath(plugin_json_name).parts
    if (
        len(marketplace_parts) != 3
        or marketplace_parts[1] != ".codebuddy-plugin"
        or len(plugin_parts) != 5
        or plugin_parts[1] != "plugins"
        or plugin_parts[3] != ".codebuddy-plugin"
    ):
        raise ValueError("WorkBuddy 市场或插件清单不在固定目录")
    archive_root = marketplace_parts[0]
    plugin_directory = plugin_parts[2]
    if plugin_parts[0] != archive_root:
        raise ValueError("WorkBuddy 市场与插件根目录不一致")
    plugin_prefix = f"{archive_root}/plugins/{plugin_directory}/"
    outer_allowed = {
        marketplace_name,
        f"{archive_root}/INSTALL.md",
    }
    unexpected_outer = sorted(
        name
        for name in file_names
        if not name.startswith(plugin_prefix) and name not in outer_allowed
    )
    if unexpected_outer:
        raise ValueError(
            "WorkBuddy 包含简化安装不需要的外层文件："
            + "、".join(unexpected_outer[:5])
        )
    if any(
        PurePosixPath(name).parent == PurePosixPath(archive_root)
        and PurePosixPath(name).suffix.lower() in {".command", ".cmd", ".ps1"}
        for name in file_names
    ):
        raise ValueError("WorkBuddy 包外层仍包含固定安装器")

    forbidden_names = {
        ".mcp.json",
        "jiaotang-agent.mjs",
        "run-node",
        "run-node.cmd",
        "portable_skill_runtime.py",
        "workbuddy_preference_bridge.py",
        "plugin-release-manifest.json",
        "plugin-release-manifest.json.sig",
        "plugin-release-signature.json",
        "marketplace-release-manifest.json",
        "marketplace-release-manifest.json.sig",
        "marketplace-release-signature.json",
        "marketplace-publisher-ed25519.pub",
    }
    included_forbidden = sorted(
        name for name in file_names if PurePosixPath(name).name in forbidden_names
    )
    if included_forbidden:
        raise ValueError(
            "WorkBuddy 简化包仍包含旧机制："
            + "、".join(included_forbidden[:5])
        )
    marketplace = json.loads(archive.read(marketplace_name).decode("utf-8"))
    plugin = json.loads(archive.read(plugin_json_name).decode("utf-8"))
    if (
        not isinstance(plugin, dict)
        or plugin.get("hook_mode") != "behavior_only_fail_open"
        or plugin.get("mcp_configuration_mode")
        != "user_remote_streamable_http"
        or "mcpServers" in plugin
    ):
        raise ValueError("WorkBuddy 插件未声明简化远程 MCP 与最小行为 Hook")
    hook_name = f"{plugin_prefix}hooks/hooks.json"
    behavior_hook_name = (
        f"{plugin_prefix}scripts/workbuddy_behavior_hook_windows.exe"
        if target == "windows"
        else f"{plugin_prefix}scripts/workbuddy_behavior_hook.py"
    )
    if hook_name not in file_names or behavior_hook_name not in file_names:
        raise ValueError("WorkBuddy 简化包缺少最小行为 Hook")
    hooks = json.loads(archive.read(hook_name).decode("utf-8"))
    hook_events = hooks.get("hooks") if isinstance(hooks, dict) else None
    if not isinstance(hook_events, dict) or set(hook_events) != {
        "UserPromptSubmit",
        "Stop",
    }:
        raise ValueError("WorkBuddy 最小行为 Hook 事件范围不合规")
    hook_commands = json.dumps(hooks, ensure_ascii=False).casefold()
    windows_adapter = (
        f"{plugin_prefix}scripts/workbuddy_behavior_hook_windows.exe"
    )
    windows_legacy = {
        f"{plugin_prefix}scripts/workbuddy_hook_windows.cmd",
        f"{plugin_prefix}scripts/workbuddy_hook_windows.sh",
        f"{plugin_prefix}scripts/workbuddy_hook_windows.ps1",
    }
    macos_adapter = f"{plugin_prefix}scripts/workbuddy_hook_macos.sh"
    launcher = f"{plugin_prefix}scripts/workbuddy_hook_launcher.sh"
    if target == "windows":
        if plugin.get("platform") != "windows":
            raise ValueError("Windows包未声明Windows平台")
        if windows_adapter not in file_names:
            raise ValueError("Windows包缺少原生EXE行为Hook")
        if not archive.read(windows_adapter).startswith(b"MZ"):
            raise ValueError("Windows原生EXE不是有效PE文件")
        if (
            windows_legacy & file_names
            or macos_adapter in file_names
            or launcher in file_names
            or f"{plugin_prefix}scripts/workbuddy_behavior_hook.py" in file_names
        ):
            raise ValueError("Windows包混入旧桥接链或macOS Hook适配器")
        if any(
            marker in hook_commands
            for marker in (
                "cmd.exe",
                "/d /s /c",
                "if exist",
                "python3 -c",
                "workbuddy_hook_windows.sh",
                "workbuddy_hook_windows.cmd",
                "workbuddy_behavior_hook.py",
                "powershell",
                "executionpolicy",
                "bypass",
            )
        ):
            raise ValueError("Windows hooks.json仍使用旧桥接链或权限绕过")
        if (
            "workbuddy_behavior_hook_windows.exe" not in hook_commands
            or "workbuddy-windows-exe" not in hook_commands
        ):
            raise ValueError("Windows hooks.json未进入原生EXE行为Hook")
    elif target == "macos":
        if plugin.get("platform") != "macos":
            raise ValueError("macOS包未声明macOS平台")
        if macos_adapter not in file_names or launcher not in file_names:
            raise ValueError("macOS包缺少shell Hook适配器")
        if windows_adapter in file_names or windows_legacy & file_names:
            raise ValueError("macOS包混入Windows Hook适配器")
        if any(
            marker in hook_commands
            for marker in ("cmd.exe", ".cmd", "powershell.exe", ".ps1")
        ):
            raise ValueError("macOS hooks.json混入Windows入口")
    skills = suite.get("skills")
    expected_skills = [f"./skills/{name}" for name in skills]
    if plugin.get("skills") != expected_skills:
        raise ValueError("WorkBuddy plugin.json 技能清单与套件不一致")
    missing_skill_entries = [
        name
        for name in skills
        if f"{plugin_prefix}skills/{name}/SKILL.md" not in file_names
    ]
    if missing_skill_entries:
        raise ValueError(
            "WorkBuddy 技能入口缺失：" + "、".join(missing_skill_entries[:5])
        )
    frontmatter_names = []
    for skill in skills:
        entry = f"{plugin_prefix}skills/{skill}/SKILL.md"
        text = archive.read(entry).decode("utf-8")
        if not text.startswith("---\n"):
            raise ValueError(f"WorkBuddy 技能frontmatter不是首字节内容：{skill}")
        frontmatter = re.match(r"\A---\n(.*?)\n---(?:\n|\Z)", text, re.DOTALL)
        if not frontmatter:
            raise ValueError(f"WorkBuddy 技能frontmatter不完整：{skill}")
        declared_names = [
            line.split(":", 1)[1].strip().strip("'\"")
            for line in frontmatter.group(1).splitlines()
            if line.startswith("name:")
        ]
        if declared_names != [skill]:
            raise ValueError(f"WorkBuddy 技能名称与目录不一致：{skill}")
        hook_position = text.find("<!-- BEGIN WORKBUDDY BEHAVIOR HOOK -->")
        if hook_position < frontmatter.end():
            raise ValueError(f"WorkBuddy 行为Hook未位于frontmatter之后：{skill}")
        frontmatter_names.append(declared_names[0])
    if len(set(frontmatter_names)) != len(skills):
        raise ValueError("WorkBuddy 技能frontmatter名称存在重复")
    discovered_skills = {
        PurePosixPath(name.removeprefix(plugin_prefix)).parts[1]
        for name in file_names
        if name.startswith(f"{plugin_prefix}skills/")
        and name.endswith("/SKILL.md")
    }
    if discovered_skills != set(skills):
        raise ValueError("WorkBuddy 包含未声明技能或技能清单不完整")
    for name in file_names:
        info = archive.getinfo(name)
        if info.file_size > 4 * 1024 * 1024:
            continue
        content = archive.read(name)
        if re.search(rb"jtk_[A-Za-z0-9_-]{16,}", content):
            raise ValueError("WorkBuddy 公共包疑似包含个人 Token")
        if any(
            marker in content
            for marker in (
                b"jiaotang_kb_setup",
                b"bootstrap_url",
            )
        ):
            raise ValueError("WorkBuddy 简化包仍引用旧本地 MCP 或 bootstrap 协议")
    allowed_marketplace = {"name", "description", "owner", "plugins"}
    allowed_owner = {"name"}
    allowed_plugin = {"name", "description", "version", "source"}
    marketplace_plugins = marketplace.get("plugins")
    marketplace_plugin = (
        marketplace_plugins[0]
        if isinstance(marketplace_plugins, list)
        and len(marketplace_plugins) == 1
        and isinstance(marketplace_plugins[0], dict)
        else None
    )
    if (
        not isinstance(marketplace, dict)
        or set(marketplace) - allowed_marketplace
        or not isinstance(marketplace.get("owner"), dict)
        or set(marketplace["owner"]) - allowed_owner
        or marketplace_plugin is None
        or set(marketplace_plugin) - allowed_plugin
        or marketplace.get("name") != archive_root
        or marketplace_plugin.get("name") != plugin_directory
        or marketplace_plugin.get("name") != plugin.get("name")
        or marketplace_plugin.get("version") != plugin.get("version")
        or marketplace_plugin.get("source")
        != f"./plugins/{plugin_directory}"
    ):
        raise ValueError("WorkBuddy marketplace.json 未固定指向目标插件")
    return {
        "status": "verified",
        "verification_scope": "server_release_channel",
        "publisher_fingerprint": TRUSTED_PUBLISHER_FINGERPRINT,
        "verified_files": len(file_names),
        "archive_entries": len(file_names),
        "outer_fixed_installers": False,
        "hook_mode": "behavior_only_fail_open",
        "platform": target,
        "skill_entry_contract": "frontmatter-first-name-bound",
        "mcp_configuration_mode": "user_remote_streamable_http",
        "embedded_user_token": False,
    }


def validate_release_packages(
    packages: dict[str, Path],
    version: str,
) -> dict[str, object]:
    """Validate the generic Skills package and/or the cross-platform WorkBuddy package."""
    invalid = sorted(set(packages) - set(ARTIFACT_TARGETS))
    if invalid:
        raise ValueError("不支持的发布目标：" + "、".join(invalid))
    if not packages:
        raise ValueError("至少提供一个发布包")

    release_tag = f"V{version}"
    expected_version = semantic_version(version)
    canonical_skills: list[str] | None = None
    hashes: dict[str, str] = {}
    integrity: dict[str, dict[str, object]] = {}
    for target, package in packages.items():
        with zipfile.ZipFile(package) as archive:
            names = _safe_members(archive)
            suite = _single_json(archive, "/skills/suite-manifest.json")
            release = suite.get("release")
            if not isinstance(release, dict) or (
                release.get("tag") != release_tag
                or release.get("version") != expected_version
            ):
                raise ValueError(f"{target}包版本与发布版本不一致")
            skills = suite.get("skills")
            if (
                not isinstance(skills, list)
                or not skills
                or not all(
                    isinstance(name, str) and name.strip() for name in skills
                )
                or len(set(skills)) != len(skills)
            ):
                raise ValueError(f"{target}包技能清单不合规")
            if canonical_skills is None:
                canonical_skills = skills
            elif skills != canonical_skills:
                raise ValueError("各客户端包的技能清单不一致")

            if target == "generic":
                integrity[target] = _validate_generic_integrity(
                    archive,
                    names,
                    suite,
                )
            else:
                marketplace = _single_json(
                    archive, "/.codebuddy-plugin/marketplace.json"
                )
                plugin = _single_json(
                    archive, "/.codebuddy-plugin/plugin.json"
                )
                plugins = marketplace.get("plugins")
                marketplace_version = (
                    plugins[0].get("version")
                    if isinstance(plugins, list) and plugins
                    else None
                )
                if (
                    marketplace_version != expected_version
                    or plugin.get("version") != expected_version
                ):
                    raise ValueError(
                        f"{target}包的WorkBuddy插件版本不一致"
                    )
                if not any(
                    name.endswith("/.codebuddy-plugin/marketplace.json")
                    for name in names
                ):
                    raise ValueError(f"{target}包缺少WorkBuddy插件市场清单")
                integrity[target] = _validate_workbuddy_integrity(
                    archive,
                    names,
                    suite,
                    target,
                )
        hashes[target] = sha256(package)

    return {
        "version": version,
        "skill_count": len(canonical_skills or []),
        "targets": list(packages),
        "artifacts": {
            target: {
                "path": str(packages[target]),
                "sha256": hashes[target],
                "integrity": integrity.get(target),
            }
            for target in packages
        },
    }


def validate_packages(generic: Path, workbuddy: Path, version: str) -> dict[str, object]:
    validated = validate_release_packages(
        {"generic": generic, "workbuddy": workbuddy},
        version,
    )
    artifacts = validated["artifacts"]
    return {
        "version": version,
        "skill_count": validated["skill_count"],
        "generic_sha256": artifacts["generic"]["sha256"],
        "workbuddy_sha256": artifacts["workbuddy"]["sha256"],
    }


def _install_file(source: Path, target: Path) -> None:
    if target.exists():
        if sha256(target) == sha256(source):
            return
        raise RuntimeError(f"目标文件已存在且内容不同：{target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            quarantine = target.parent / ".quarantine"
            quarantine.mkdir(parents=True, exist_ok=True)
            failed_copy = quarantine / (
                f"{temporary.name}.failed-"
                f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
            )
            os.replace(temporary, failed_copy)


def _ensure_stage_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS skill_release_stages(
            version TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            generic_path TEXT NOT NULL,
            generic_sha256 TEXT NOT NULL,
            workbuddy_path TEXT NOT NULL,
            workbuddy_sha256 TEXT NOT NULL,
            release_notes TEXT NOT NULL,
            git_commit TEXT NOT NULL,
            github_url TEXT NOT NULL,
            staged_at TEXT NOT NULL,
            promoted_at TEXT
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS skill_release_stage_artifacts(
            version TEXT NOT NULL,
            target TEXT NOT NULL,
            file_path TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            PRIMARY KEY(version,target)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS skill_release_artifacts(
            release_id INTEGER NOT NULL,
            target TEXT NOT NULL,
            file_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            PRIMARY KEY(release_id,target)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS skill_release_artifact_stages(
            version TEXT NOT NULL,
            target TEXT NOT NULL,
            status TEXT NOT NULL,
            file_path TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            release_notes TEXT NOT NULL,
            git_commit TEXT NOT NULL,
            github_url TEXT NOT NULL,
            staged_at TEXT NOT NULL,
            promoted_at TEXT,
            PRIMARY KEY(version,target)
        )
        """
    )


def _artifact_name(version: str, target: str) -> str:
    suffix = {
        "generic": "",
        "workbuddy": "-WorkBuddy",
        "macos": "-macOS-WorkBuddy",
        "windows": "-Windows-WorkBuddy",
    }[target]
    return f"企业全生命周期助手-V{version}{suffix}.zip"


def stage_artifact_addition(
    database_path: Path,
    release_directory: Path,
    package: Path,
    target: str,
    version: str,
    release_notes: str,
    git_commit: str,
    github_url: str,
) -> dict[str, object]:
    """为已发布内容版本暂存一个尚不存在的客户端通道，不改旧资产。"""
    validation = validate_release_packages({target: package}, version)
    stage_directory = release_directory / ".staging" / f"V{version}"
    staged_path = stage_directory / _artifact_name(version, target)
    release_directory.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        _ensure_stage_table(connection)
        release = connection.execute(
            "SELECT id FROM skill_releases WHERE version=?",
            (version,),
        ).fetchone()
        if release is None:
            raise RuntimeError(
                f"版本 {version} 尚未正式发布，不能使用通道补发流程"
            )
        published = connection.execute(
            """
            SELECT file_path,sha256
            FROM skill_release_artifacts
            WHERE release_id=? AND target=?
            """,
            (int(release["id"]), target),
        ).fetchone()
        expected_sha = str(validation["artifacts"][target]["sha256"])
        if published is not None:
            published_path = Path(str(published["file_path"]))
            if (
                str(published["sha256"]) == expected_sha
                and published_path.is_file()
                and sha256(published_path) == expected_sha
            ):
                return {
                    **validation,
                    "status": "already-published",
                    "release_state": "published",
                }
            raise RuntimeError(
                f"版本 {version} 已存在不同内容的 {target} 通道"
            )
        staged = connection.execute(
            """
            SELECT * FROM skill_release_artifact_stages
            WHERE version=? AND target=?
            """,
            (version, target),
        ).fetchone()
        if staged is not None:
            staged_file = Path(str(staged["file_path"]))
            if (
                str(staged["status"]) in PENDING_STAGE_STATUSES
                and str(staged["sha256"]) == expected_sha
                and staged_file.is_file()
                and sha256(staged_file) == expected_sha
            ):
                return {
                    **validation,
                    "status": "already-staged",
                    "release_state": STAGED_STATUS,
                    "github_url": str(staged["github_url"]),
                }
            raise RuntimeError(
                f"版本 {version} 的 {target} 通道已有不同候选"
            )
        _install_file(package, staged_path)
        staged_at = datetime.now(timezone.utc).isoformat()
        connection.execute(
            """
            INSERT INTO skill_release_artifact_stages(
                version,target,status,file_path,sha256,release_notes,
                git_commit,github_url,staged_at,promoted_at
            ) VALUES (?,?,?,?,?,?,?,?,?,NULL)
            """,
            (
                version,
                target,
                STAGED_STATUS,
                str(staged_path),
                expected_sha,
                release_notes.strip(),
                git_commit.strip(),
                github_url.strip(),
                staged_at,
            ),
        )
        connection.commit()
    return {
        **validation,
        "status": "staged",
        "release_state": STAGED_STATUS,
        "github_url": github_url.strip(),
        "staged_at": staged_at,
    }


def promote_artifact_addition(
    database_path: Path,
    release_directory: Path,
    version: str,
    target: str,
) -> dict[str, object]:
    """原子提升已审查的通道候选，保留同版本已有资产。"""
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        _ensure_stage_table(connection)
        release = connection.execute(
            "SELECT id FROM skill_releases WHERE version=?",
            (version,),
        ).fetchone()
        staged = connection.execute(
            """
            SELECT * FROM skill_release_artifact_stages
            WHERE version=? AND target=?
            """,
            (version, target),
        ).fetchone()
        if (
            release is None
            or staged is None
            or str(staged["status"]) not in PENDING_STAGE_STATUSES
        ):
            raise RuntimeError(
                f"版本 {version} 的 {target} 通道未处于可提升状态"
            )
        staged_path = Path(str(staged["file_path"]))
        staged_sha = str(staged["sha256"])
        if not staged_path.is_file() or sha256(staged_path) != staged_sha:
            raise RuntimeError("通道候选缺失或哈希发生变化")
        validation = validate_release_packages({target: staged_path}, version)
        published = connection.execute(
            """
            SELECT file_path,sha256
            FROM skill_release_artifacts
            WHERE release_id=? AND target=?
            """,
            (int(release["id"]), target),
        ).fetchone()
        if published is not None:
            published_path = Path(str(published["file_path"]))
            if (
                str(published["sha256"]) == staged_sha
                and published_path.is_file()
                and sha256(published_path) == staged_sha
            ):
                return {
                    **validation,
                    "status": "already-published",
                    "release_state": "published",
                }
            raise RuntimeError(
                f"版本 {version} 已存在不同内容的 {target} 通道"
            )
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = database_path.with_name(
            f"{database_path.name}.before-v{version}-{target}-{timestamp}"
        )
        with sqlite3.connect(backup_path) as backup:
            connection.backup(backup)
        target_path = release_directory / _artifact_name(version, target)
        _install_file(staged_path, target_path)
        connection.execute(
            """
            INSERT INTO skill_release_artifacts(
                release_id,target,file_name,file_path,sha256
            ) VALUES (?,?,?,?,?)
            """,
            (
                int(release["id"]),
                target,
                target_path.name,
                str(target_path),
                staged_sha,
            ),
        )
        promoted_at = datetime.now(timezone.utc).isoformat()
        connection.execute(
            """
            UPDATE skill_release_artifact_stages
            SET status='published',promoted_at=?
            WHERE version=? AND target=?
              AND status IN ('releasing','staged-awaiting-acceptance')
            """,
            (promoted_at, version, target),
        )
        connection.commit()
    return {
        **validation,
        "status": "published",
        "release_state": "published",
        "database_backup": str(backup_path),
        "promoted_at": promoted_at,
    }


def stage_selective(
    database_path: Path,
    release_directory: Path,
    packages: dict[str, Path],
    version: str,
    release_notes: str,
    git_commit: str,
    github_url: str,
    *,
    allow_platform_hotfix: bool = False,
) -> dict[str, object]:
    require_complete_workbuddy_platform_set(
        packages,
        allow_platform_hotfix=allow_platform_hotfix,
    )
    validation = validate_release_packages(packages, version)
    stage_directory = release_directory / ".staging" / f"V{version}"
    release_directory.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        _ensure_stage_table(connection)
        if connection.execute(
            "SELECT 1 FROM skill_releases WHERE version=?", (version,)
        ).fetchone():
            raise RuntimeError(f"版本 {version} 已正式发布")
        existing = connection.execute(
            "SELECT * FROM skill_release_stages WHERE version=?", (version,)
        ).fetchone()
        if existing is not None:
            rows = connection.execute(
                """
                SELECT target,file_path,sha256
                FROM skill_release_stage_artifacts
                WHERE version=? ORDER BY target
                """,
                (version,),
            ).fetchall()
            existing_hashes = {
                str(row["target"]): str(row["sha256"]) for row in rows
            }
            expected_hashes = {
                target: str(data["sha256"])
                for target, data in validation["artifacts"].items()
            }
            if (
                str(existing["status"]) in PENDING_STAGE_STATUSES
                and existing_hashes == expected_hashes
                and all(
                    Path(str(row["file_path"])).is_file()
                    and sha256(Path(str(row["file_path"])))
                    == str(row["sha256"])
                    for row in rows
                )
            ):
                connection.execute(
                    """
                    UPDATE skill_release_stages
                    SET release_notes=?,git_commit=?,github_url=?
                    WHERE version=?
                      AND status IN ('releasing','staged-awaiting-acceptance')
                    """,
                    (
                        release_notes.strip(),
                        git_commit.strip(),
                        github_url.strip(),
                        version,
                    ),
                )
                connection.commit()
                return {
                    **validation,
                    "status": "already-staged",
                    "release_state": STAGED_STATUS,
                    "github_url": github_url.strip(),
                    "git_commit": git_commit.strip(),
                }
            raise RuntimeError(f"版本 {version} 已有不同内容的发布中记录")

        installed: dict[str, Path] = {}
        for target, source in packages.items():
            destination = stage_directory / _artifact_name(version, target)
            _install_file(source, destination)
            installed[target] = destination
        staged_at = datetime.now(timezone.utc).isoformat()
        connection.execute(
            """
            INSERT INTO skill_release_stages(
                version,status,generic_path,generic_sha256,
                workbuddy_path,workbuddy_sha256,release_notes,
                git_commit,github_url,staged_at,promoted_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,NULL)
            """,
            (
                version,
                STAGED_STATUS,
                str(installed.get("generic", "")),
                validation["artifacts"].get("generic", {}).get("sha256", ""),
                str(installed.get("workbuddy") or ""),
                validation["artifacts"].get("workbuddy", {}).get("sha256", ""),
                release_notes.strip(),
                git_commit.strip(),
                github_url.strip(),
                staged_at,
            ),
        )
        connection.executemany(
            """
            INSERT INTO skill_release_stage_artifacts(
                version,target,file_path,sha256
            ) VALUES (?,?,?,?)
            """,
            [
                (
                    version,
                    target,
                    str(installed[target]),
                    validation["artifacts"][target]["sha256"],
                )
                for target in packages
            ],
        )
        connection.commit()
    return {
        **validation,
        "status": "staged",
        "release_state": STAGED_STATUS,
        "github_url": github_url.strip(),
        "staged_at": staged_at,
    }


def publish_selective(
    database_path: Path,
    release_directory: Path,
    packages: dict[str, Path],
    version: str,
    release_notes: str,
    *,
    allow_platform_hotfix: bool = False,
) -> dict[str, object]:
    require_complete_workbuddy_platform_set(
        packages,
        allow_platform_hotfix=allow_platform_hotfix,
    )
    validation = validate_release_packages(packages, version)
    release_directory.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        _ensure_stage_table(connection)
        existing = connection.execute(
            "SELECT * FROM skill_releases WHERE version=?", (version,)
        ).fetchone()
        if existing is not None:
            rows = connection.execute(
                """
                SELECT target,file_path,sha256
                FROM skill_release_artifacts
                WHERE release_id=? ORDER BY target
                """,
                (int(existing["id"]),),
            ).fetchall()
            existing_hashes = {
                str(row["target"]): str(row["sha256"]) for row in rows
            }
            expected_hashes = {
                target: str(data["sha256"])
                for target, data in validation["artifacts"].items()
            }
            if existing_hashes == expected_hashes and all(
                Path(str(row["file_path"])).is_file()
                and sha256(Path(str(row["file_path"])))
                == str(row["sha256"])
                for row in rows
            ):
                return {
                    **validation,
                    "release_id": int(existing["id"]),
                    "status": "already-published",
                }
            raise RuntimeError(f"版本 {version} 已存在，但目标或哈希不一致")

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = database_path.with_name(
            f"{database_path.name}.before-v{version}-{timestamp}"
        )
        with sqlite3.connect(backup_path) as backup:
            connection.backup(backup)
        installed: dict[str, Path] = {}
        for target, source in packages.items():
            destination = release_directory / _artifact_name(version, target)
            _install_file(source, destination)
            installed[target] = destination
        primary_target = next(
            (
                target
                for target in ("generic", "workbuddy")
                if target in installed
            ),
            None,
        )
        primary = installed.get(primary_target) if primary_target else None
        published_at = datetime.now(timezone.utc).isoformat()
        cursor = connection.execute(
            """
            INSERT INTO skill_releases(
                version,file_name,file_path,sha256,release_notes,published_at
            ) VALUES (?,?,?,?,?,?)
            """,
            (
                version,
                primary.name if primary else "",
                str(primary) if primary else "",
                (
                    validation["artifacts"][primary_target]["sha256"]
                    if primary_target
                    else ""
                ),
                release_notes.strip(),
                published_at,
            ),
        )
        release_id = int(cursor.lastrowid)
        connection.executemany(
            """
            INSERT INTO skill_release_artifacts(
                release_id,target,file_name,file_path,sha256
            ) VALUES (?,?,?,?,?)
            """,
            [
                (
                    release_id,
                    target,
                    installed[target].name,
                    str(installed[target]),
                    validation["artifacts"][target]["sha256"],
                )
                for target in packages
            ],
        )
        connection.commit()
    return {
        **validation,
        "release_id": release_id,
        "status": "published",
        "database_backup": str(backup_path),
    }


def promote_selective(
    database_path: Path,
    release_directory: Path,
    version: str,
) -> dict[str, object]:
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        _ensure_stage_table(connection)
        staged = connection.execute(
            "SELECT * FROM skill_release_stages WHERE version=?", (version,)
        ).fetchone()
        rows = connection.execute(
            """
            SELECT target,file_path,sha256
            FROM skill_release_stage_artifacts
            WHERE version=? ORDER BY target
            """,
            (version,),
        ).fetchall()
    if (
        staged is None
        or str(staged["status"])
        not in {*PENDING_STAGE_STATUSES, "published"}
        or not rows
    ):
        raise RuntimeError(f"版本 {version} 未处于可提升的正式发布中")
    if any(
        not Path(str(row["file_path"])).is_file()
        or sha256(Path(str(row["file_path"]))) != str(row["sha256"])
        for row in rows
    ):
        raise RuntimeError("正式发布中的候选包缺失或哈希发生变化")
    packages: dict[str, Path] = {}
    for row in rows:
        target = str(row["target"])
        path = Path(str(row["file_path"]))
        packages[target] = path
    result = publish_selective(
        database_path,
        release_directory,
        packages,
        version,
        str(staged["release_notes"]),
        allow_platform_hotfix=set(packages) == {"windows"},
    )
    if str(staged["status"]) == "published":
        return {
            **result,
            "release_state": "published",
            "promoted_at": staged["promoted_at"],
        }
    promoted_at = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            UPDATE skill_release_stages
            SET status='published',promoted_at=?
            WHERE version=?
              AND status IN ('releasing','staged-awaiting-acceptance')
            """,
            (promoted_at, version),
        )
        connection.commit()
    return {
        **result,
        "release_state": "published",
        "promoted_at": promoted_at,
    }


def stage(
    database_path: Path,
    release_directory: Path,
    generic_package: Path,
    workbuddy_package: Path,
    version: str,
    release_notes: str,
    git_commit: str,
    github_url: str,
) -> dict[str, object]:
    validation = validate_packages(generic_package, workbuddy_package, version)
    stage_directory = release_directory / ".staging" / f"V{version}"
    generic_target = stage_directory / f"企业全生命周期助手-V{version}.zip"
    workbuddy_target = (
        stage_directory / f"企业全生命周期助手-V{version}-WorkBuddy.zip"
    )
    release_directory.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        _ensure_stage_table(connection)
        if connection.execute(
            "SELECT 1 FROM skill_releases WHERE version=?", (version,)
        ).fetchone():
            raise RuntimeError(f"版本 {version} 已正式发布，不能重新进入发布中")
        existing = connection.execute(
            "SELECT * FROM skill_release_stages WHERE version=?", (version,)
        ).fetchone()
        if existing is not None:
            if (
                str(existing["status"]) in PENDING_STAGE_STATUSES
                and str(existing["generic_sha256"]) == validation["generic_sha256"]
                and str(existing["workbuddy_sha256"])
                == validation["workbuddy_sha256"]
                and Path(str(existing["generic_path"])).is_file()
                and Path(str(existing["workbuddy_path"])).is_file()
                and sha256(Path(str(existing["generic_path"])))
                == str(existing["generic_sha256"])
                and sha256(Path(str(existing["workbuddy_path"])))
                == str(existing["workbuddy_sha256"])
            ):
                return {
                    **validation,
                    "status": "already-staged",
                    "release_state": STAGED_STATUS,
                    "github_url": str(existing["github_url"]),
                }
            raise RuntimeError(f"版本 {version} 已有不同内容的发布中记录")
        _install_file(generic_package, generic_target)
        _install_file(workbuddy_package, workbuddy_target)
        staged_at = datetime.now(timezone.utc).isoformat()
        connection.execute(
            """
            INSERT INTO skill_release_stages(
                version,status,generic_path,generic_sha256,
                workbuddy_path,workbuddy_sha256,release_notes,
                git_commit,github_url,staged_at,promoted_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,NULL)
            """,
            (
                version,
                STAGED_STATUS,
                str(generic_target),
                validation["generic_sha256"],
                str(workbuddy_target),
                validation["workbuddy_sha256"],
                release_notes.strip(),
                git_commit.strip(),
                github_url.strip(),
                staged_at,
            ),
        )
        connection.commit()
    return {
        **validation,
        "status": "staged",
        "release_state": STAGED_STATUS,
        "github_url": github_url.strip(),
        "staged_at": staged_at,
    }


def publish(
    database_path: Path,
    release_directory: Path,
    generic_package: Path,
    workbuddy_package: Path,
    version: str,
    release_notes: str,
) -> dict[str, object]:
    validation = validate_packages(generic_package, workbuddy_package, version)
    generic_target = release_directory / f"企业全生命周期助手-V{version}.zip"
    workbuddy_target = release_directory / f"企业全生命周期助手-V{version}-WorkBuddy.zip"
    release_directory.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        existing = connection.execute(
            "SELECT * FROM skill_releases WHERE version=?", (version,)
        ).fetchone()
        if existing is not None:
            if (
                str(existing["sha256"]) == validation["generic_sha256"]
                and Path(str(existing["file_path"])).is_file()
                and workbuddy_target.is_file()
                and sha256(workbuddy_target) == validation["workbuddy_sha256"]
            ):
                return {**validation, "release_id": int(existing["id"]), "status": "already-published"}
            raise RuntimeError(f"版本 {version} 已存在，但发布文件或哈希不一致")

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = database_path.with_name(f"{database_path.name}.before-v{version}-{timestamp}")
        with sqlite3.connect(backup_path) as backup:
            connection.backup(backup)

        _install_file(generic_package, generic_target)
        _install_file(workbuddy_package, workbuddy_target)
        published_at = datetime.now(timezone.utc).isoformat()
        cursor = connection.execute(
            """
            INSERT INTO skill_releases(
                version,file_name,file_path,sha256,release_notes,published_at
            ) VALUES (?,?,?,?,?,?)
            """,
            (
                version,
                generic_target.name,
                str(generic_target),
                validation["generic_sha256"],
                release_notes.strip(),
                published_at,
            ),
        )
        connection.commit()
    return {
        **validation,
        "release_id": int(cursor.lastrowid),
        "status": "published",
        "database_backup": str(backup_path),
        "generic_path": str(generic_target),
        "workbuddy_path": str(workbuddy_target),
    }


def promote(
    database_path: Path,
    release_directory: Path,
    version: str,
) -> dict[str, object]:
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        _ensure_stage_table(connection)
        staged = connection.execute(
            "SELECT * FROM skill_release_stages WHERE version=?", (version,)
        ).fetchone()
    if (
        staged is None
        or str(staged["status"]) not in PENDING_STAGE_STATUSES
    ):
        raise RuntimeError(f"版本 {version} 未处于正式发布中，禁止确认发布")
    generic_package = Path(str(staged["generic_path"]))
    workbuddy_package = Path(str(staged["workbuddy_path"]))
    if not generic_package.is_file() or not workbuddy_package.is_file():
        raise RuntimeError("正式发布中的候选包缺失")
    if (
        sha256(generic_package) != str(staged["generic_sha256"])
        or sha256(workbuddy_package) != str(staged["workbuddy_sha256"])
    ):
        raise RuntimeError("正式发布中的候选包哈希发生变化")
    result = publish(
        database_path,
        release_directory,
        generic_package,
        workbuddy_package,
        version,
        str(staged["release_notes"]),
    )
    promoted_at = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            UPDATE skill_release_stages
            SET status='published',promoted_at=?
            WHERE version=?
              AND status IN ('releasing','staged-awaiting-acceptance')
            """,
            (promoted_at, version),
        )
        connection.commit()
    return {
        **result,
        "release_state": "published",
        "promoted_at": promoted_at,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="两阶段发布已签名的通用与 WorkBuddy 技能包"
    )
    parser.add_argument(
        "--mode",
        choices=(
            "stage",
            "promote",
            "stage-artifact",
            "promote-artifact",
            "lease-acquire",
            "lease-monitor",
            "lease-supersede-failed",
            "lease-transition",
        ),
        required=True,
    )
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--generic-package", type=Path)
    parser.add_argument("--workbuddy-package", type=Path)
    parser.add_argument("--macos-package", type=Path)
    parser.add_argument("--windows-package", type=Path)
    parser.add_argument(
        "--platform-hotfix",
        choices=("windows",),
        help="允许单平台热修事务；仅可提供对应平台包，其他平台继续沿用上一正式版本",
    )
    parser.add_argument("--version", required=True)
    parser.add_argument("--release-notes-file", type=Path)
    parser.add_argument("--git-commit", default="")
    parser.add_argument("--github-url", default="")
    parser.add_argument("--target", choices=ARTIFACT_TARGETS)
    parser.add_argument("--transaction-manifest", type=Path)
    parser.add_argument("--transaction-signature", type=Path)
    parser.add_argument("--publisher-public-key", type=Path)
    parser.add_argument("--lease-credential-file", type=Path)
    parser.add_argument("--lease-credential-stdin", action="store_true")
    parser.add_argument("--transaction-sha256", default="")
    parser.add_argument("--superseded-transaction-sha256", default="")
    parser.add_argument("--transaction-state", default="")
    parser.add_argument("--transaction-evidence-file", type=Path)
    parser.add_argument(
        "--lease-ttl-seconds",
        type=int,
        default=DEFAULT_LEASE_TTL_SECONDS,
    )
    arguments = parser.parse_args()
    if (
        arguments.lease_credential_file is not None
        and arguments.lease_credential_stdin
    ):
        parser.error("租约凭证文件与标准输入不能同时提供")
    if arguments.mode in {"stage-artifact", "promote-artifact"}:
        raise RuntimeError(
            "全局发布事务已启用，禁止对同一版本绕过签名事务补发单个通道；"
            "请生成新的补丁版本并走完整stage/promote发布事务。"
        )
    if arguments.mode == "lease-monitor":
        with sqlite3.connect(arguments.database) as connection:
            connection.row_factory = sqlite3.Row
            result = monitor_release_transaction(
                connection,
                version=arguments.version,
            )
    elif arguments.mode == "lease-acquire":
        if (
            arguments.lease_credential_file is None
            and not arguments.lease_credential_stdin
        ):
            parser.error("lease-acquire必须提供租约凭证")
        verification, signature_payload, public_key_text = (
            _load_verified_transaction(arguments)
        )
        holder_id, lease_token = _load_lease_credential(arguments)
        with sqlite3.connect(arguments.database) as connection:
            connection.row_factory = sqlite3.Row
            result = acquire_release_lease(
                connection,
                verification=verification,
                signature_payload=signature_payload,
                public_key_text=public_key_text,
                holder_id=holder_id,
                lease_token=lease_token,
                ttl_seconds=arguments.lease_ttl_seconds,
            )
    elif arguments.mode == "lease-supersede-failed":
        if (
            (arguments.lease_credential_file is None and not arguments.lease_credential_stdin)
            or not arguments.superseded_transaction_sha256
            or arguments.transaction_evidence_file is None
        ):
            parser.error(
                "lease-supersede-failed必须提供原租约凭证、旧事务哈希和替换证据"
            )
        verification, signature_payload, public_key_text = (
            _load_verified_transaction(arguments)
        )
        holder_id, lease_token = _load_lease_credential(arguments)
        evidence = json.loads(
            arguments.transaction_evidence_file.read_text(encoding="utf-8")
        )
        if not isinstance(evidence, dict):
            raise RuntimeError("替换失败事务证据根节点必须是对象")
        with sqlite3.connect(arguments.database) as connection:
            connection.row_factory = sqlite3.Row
            result = supersede_failed_release_transaction(
                connection,
                verification=verification,
                signature_payload=signature_payload,
                public_key_text=public_key_text,
                previous_transaction_sha256=arguments.superseded_transaction_sha256,
                holder_id=holder_id,
                lease_token=lease_token,
                evidence=evidence,
                ttl_seconds=arguments.lease_ttl_seconds,
            )
    elif arguments.mode == "lease-transition":
        if (
            (
                arguments.lease_credential_file is None
                and not arguments.lease_credential_stdin
            )
            or not arguments.transaction_sha256
            or not arguments.transaction_state
        ):
            parser.error(
                "lease-transition必须提供租约凭证、事务哈希和目标状态"
            )
        holder_id, lease_token = _load_lease_credential(arguments)
        evidence = (
            json.loads(
                arguments.transaction_evidence_file.read_text(
                    encoding="utf-8"
                )
            )
            if arguments.transaction_evidence_file
            else {}
        )
        if not isinstance(evidence, dict):
            raise RuntimeError("发布事务证据根节点必须是对象")
        with sqlite3.connect(arguments.database) as connection:
            connection.row_factory = sqlite3.Row
            result = transition_release_transaction(
                connection,
                version=arguments.version,
                transaction_sha256=arguments.transaction_sha256,
                holder_id=holder_id,
                lease_token=lease_token,
                target_state=arguments.transaction_state,
                evidence=evidence,
                ttl_seconds=arguments.lease_ttl_seconds,
            )
    elif arguments.mode in {"stage", "stage-artifact"}:
        packages = {
            target: package
            for target, package in (
                ("generic", arguments.generic_package),
                ("workbuddy", arguments.workbuddy_package),
                ("macos", arguments.macos_package),
                ("windows", arguments.windows_package),
            )
            if package is not None
        }
        if (
            not packages
            or arguments.release_notes_file is None
            or not arguments.git_commit.strip()
            or not arguments.github_url.strip()
        ):
            parser.error(
                "stage模式必须至少提供一个客户端包，并提供发布说明、"
                "git提交和GitHub预发布地址"
            )
        if arguments.mode == "stage":
            if (
                arguments.lease_credential_file is None
                and not arguments.lease_credential_stdin
            ):
                parser.error("stage必须提供租约凭证")
            verification, signature_payload, public_key_text = (
                _load_verified_transaction(arguments)
            )
            holder_id, lease_token = _load_lease_credential(arguments)
            validation = validate_release_packages(
                packages,
                arguments.version,
            )
            _validate_transaction_artifacts(
                verification["manifest"],
                validation["artifacts"],
            )
            with sqlite3.connect(arguments.database) as connection:
                connection.row_factory = sqlite3.Row
                lease = acquire_release_lease(
                    connection,
                    verification=verification,
                    signature_payload=signature_payload,
                    public_key_text=public_key_text,
                    holder_id=holder_id,
                    lease_token=lease_token,
                    ttl_seconds=arguments.lease_ttl_seconds,
                )
            if lease.get("mode") != "writer":
                print(json.dumps(lease, ensure_ascii=False, indent=2))
                return
            if STATE_RANK.get(str(lease.get("state")), -1) < STATE_RANK[
                "github_staged"
            ]:
                raise RuntimeError(
                    "GitHub尚未在签名发布事务中完成预发布，禁止门户暂存"
                )
        if arguments.mode == "stage-artifact":
            if arguments.target is None or set(packages) != {arguments.target}:
                parser.error(
                    "stage-artifact 必须通过 --target 指定且只提供对应的一个包"
                )
            result = stage_artifact_addition(
                arguments.database,
                arguments.release_dir,
                packages[arguments.target],
                arguments.target,
                arguments.version,
                arguments.release_notes_file.read_text(encoding="utf-8"),
                arguments.git_commit,
                arguments.github_url,
            )
        else:
            result = stage_selective(
                arguments.database,
                arguments.release_dir,
                packages,
                arguments.version,
                arguments.release_notes_file.read_text(encoding="utf-8"),
                arguments.git_commit,
                arguments.github_url,
                allow_platform_hotfix=arguments.platform_hotfix == "windows",
            )
            with sqlite3.connect(arguments.database) as connection:
                connection.row_factory = sqlite3.Row
                transaction = transition_release_transaction(
                    connection,
                    version=arguments.version,
                    transaction_sha256=str(
                        verification["manifest_sha256"]
                    ),
                    holder_id=holder_id,
                    lease_token=lease_token,
                    target_state="portal_staged",
                    evidence={
                        "status": result.get("status"),
                        "artifacts": result.get("artifacts"),
                        "github_url": result.get("github_url"),
                    },
                    ttl_seconds=arguments.lease_ttl_seconds,
                )
            result["release_transaction"] = transaction
    elif arguments.mode == "promote-artifact":
        if arguments.target is None:
            parser.error("promote-artifact 必须提供 --target")
        result = promote_artifact_addition(
            arguments.database,
            arguments.release_dir,
            arguments.version,
            arguments.target,
        )
    else:
        if (
            arguments.lease_credential_file is None
            and not arguments.lease_credential_stdin
        ):
            parser.error("promote必须提供租约凭证")
        verification, signature_payload, public_key_text = (
            _load_verified_transaction(arguments)
        )
        holder_id, lease_token = _load_lease_credential(arguments)
        with sqlite3.connect(arguments.database) as connection:
            connection.row_factory = sqlite3.Row
            lease = acquire_release_lease(
                connection,
                verification=verification,
                signature_payload=signature_payload,
                public_key_text=public_key_text,
                holder_id=holder_id,
                lease_token=lease_token,
                ttl_seconds=arguments.lease_ttl_seconds,
            )
        if lease.get("mode") != "writer":
            print(json.dumps(lease, ensure_ascii=False, indent=2))
            return
        if STATE_RANK.get(str(lease.get("state")), -1) < STATE_RANK[
            "installed"
        ]:
            raise RuntimeError(
                "本机安装端尚未在签名发布事务中完成验签，禁止门户提升"
            )
        participants = verification["manifest"].get("participants")
        portal_contract = (
            participants.get("portal")
            if isinstance(participants, dict)
            else None
        )
        if not isinstance(portal_contract, dict):
            raise RuntimeError("发布事务清单缺少portal参与方")
        with sqlite3.connect(arguments.database) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT target,sha256 FROM skill_release_stage_artifacts
                WHERE version=? ORDER BY target
                """,
                (arguments.version,),
            ).fetchall()
        staged_artifacts = {
            str(row["target"]): {"sha256": str(row["sha256"])}
            for row in rows
        }
        _validate_transaction_artifacts(
            verification["manifest"],
            staged_artifacts,
        )
        result = promote_selective(
            arguments.database,
            arguments.release_dir,
            arguments.version,
        )
        with sqlite3.connect(arguments.database) as connection:
            connection.row_factory = sqlite3.Row
            transaction = transition_release_transaction(
                connection,
                version=arguments.version,
                transaction_sha256=str(
                    verification["manifest_sha256"]
                ),
                holder_id=holder_id,
                lease_token=lease_token,
                target_state="portal_published",
                evidence={
                    "release_id": result.get("release_id"),
                    "artifacts": result.get("artifacts"),
                    "promoted_at": result.get("promoted_at"),
                },
                ttl_seconds=arguments.lease_ttl_seconds,
            )
        result["release_transaction"] = transaction
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
