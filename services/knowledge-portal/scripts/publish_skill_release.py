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
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


TRUSTED_PUBLISHER_PUBLIC_KEY = (
    "ssh-ed25519 "
    "AAAAC3NzaC1lZDI1NTE5AAAAICcDJACg0boSFDFpF2Akq0srFwlQYU9XiIpm/ldEEFeU "
    "jiaotang-codex-skill-release"
)
TRUSTED_PUBLISHER_FINGERPRINT = (
    "SHA256:+BLR7x5xFci+u1Ue3KoFs9jFzzS+ebNk46JlfDUoEJI"
)
WORKBUDDY_SIGNATURE_NAMESPACE = "codex-workbuddy-plugin-manifest"
SSHSIG_MAGIC = b"SSHSIG"
SSH_ED25519 = b"ssh-ed25519"
MAX_EXPANDED_BYTES = 1024 * 1024 * 1024


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


ARTIFACT_TARGETS = ("generic", "workbuddy")


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
    if parsed["namespace"].decode("utf-8") != WORKBUDDY_SIGNATURE_NAMESPACE:
        raise ValueError("WorkBuddy 签名命名空间不匹配")
    if parsed["reserved"]:
        raise ValueError("OpenSSH SSHSIG reserved 字段必须为空")
    hash_name = parsed["hash_algorithm"].decode("ascii")
    if hash_name not in {"sha256", "sha512"}:
        raise ValueError(f"不支持的 OpenSSH SSHSIG 哈希算法：{hash_name}")
    payload_digest = hashlib.new(hash_name, payload).digest()
    signed_data = b"".join(
        (
            SSHSIG_MAGIC,
            _ssh_string(WORKBUDDY_SIGNATURE_NAMESPACE),
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


def _validate_workbuddy_integrity(
    archive: zipfile.ZipFile,
    names: list[str],
    suite: dict[str, object],
) -> dict[str, object]:
    file_names = {
        name for name in names if not archive.getinfo(name).is_dir()
    }
    manifests = [
        name
        for name in file_names
        if name.endswith("/plugin-release-manifest.json")
    ]
    if len(manifests) != 1:
        raise ValueError("WorkBuddy 包应且仅应包含一个插件签名清单")
    manifest_name = manifests[0]
    parts = PurePosixPath(manifest_name).parts
    if len(parts) != 4 or parts[1] != "plugins":
        raise ValueError("WorkBuddy 插件签名清单不在固定市场目录")
    archive_root, _, plugin_directory, _ = parts
    plugin_prefix = f"{archive_root}/plugins/{plugin_directory}/"
    signature_name = f"{manifest_name}.sig"
    metadata_name = (
        f"{plugin_prefix}plugin-release-signature.json"
    )
    public_key_name = f"{plugin_prefix}publisher-ed25519.pub"
    companions = {
        manifest_name,
        signature_name,
        metadata_name,
        public_key_name,
    }
    if not companions.issubset(file_names):
        raise ValueError("WorkBuddy 插件签名伴随物不完整")

    manifest_bytes = archive.read(manifest_name)
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    metadata = json.loads(archive.read(metadata_name).decode("utf-8"))
    expected_metadata = {
        "algorithm": "OpenSSH-Ed25519",
        "signature_namespace": WORKBUDDY_SIGNATURE_NAMESPACE,
        "signed_file": "plugin-release-manifest.json",
        "signature": "plugin-release-manifest.json.sig",
        "public_key": "publisher-ed25519.pub",
        "public_key_fingerprint": TRUSTED_PUBLISHER_FINGERPRINT,
    }
    if (
        not isinstance(metadata, dict)
        or any(metadata.get(key) != value for key, value in expected_metadata.items())
    ):
        raise ValueError("WorkBuddy 插件签名元数据不合规")
    _verify_manifest_signature(
        manifest_bytes,
        archive.read(signature_name),
        archive.read(public_key_name),
    )
    if (
        not isinstance(manifest, dict)
        or manifest.get("artifact_type") != "workbuddy-plugin"
        or manifest.get("plugin_name") != plugin_directory
        or manifest.get("release_tag") != suite.get("release", {}).get("tag")
        or manifest.get("skills") != suite.get("skills")
    ):
        raise ValueError("WorkBuddy 插件签名清单与套件清单不一致")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("WorkBuddy 插件签名清单缺少 files 哈希表")
    verified_files: set[str] = set()
    for relative, expected_hash in files.items():
        if (
            not isinstance(relative, str)
            or not isinstance(expected_hash, str)
            or not re.fullmatch(r"[0-9a-f]{64}", expected_hash)
        ):
            raise ValueError("WorkBuddy 插件签名清单包含非法文件或 SHA-256")
        relative_path = PurePosixPath(relative)
        if (
            relative_path.is_absolute()
            or ".." in relative_path.parts
            or "\\" in relative
            or ":" in relative
            or not relative_path.parts
        ):
            raise ValueError(f"WorkBuddy 签名清单包含不安全路径：{relative}")
        full_name = plugin_prefix + relative_path.as_posix()
        if full_name not in file_names:
            raise ValueError(f"WorkBuddy 签名文件缺失：{full_name}")
        actual_hash = hashlib.sha256(archive.read(full_name)).hexdigest()
        if actual_hash != expected_hash:
            raise ValueError(f"WorkBuddy 签名文件哈希不一致：{full_name}")
        verified_files.add(full_name)

    plugin_files = {
        name for name in file_names if name.startswith(plugin_prefix)
    }
    verified_allowlist = verified_files | companions
    unexpected_plugin_files = sorted(plugin_files - verified_allowlist)
    if unexpected_plugin_files:
        raise ValueError(
            "WorkBuddy 插件包含未签名文件："
            + "、".join(unexpected_plugin_files[:5])
        )
    outer_allowed = {
        f"{archive_root}/.codebuddy-plugin/marketplace.json",
        f"{archive_root}/INSTALL.md",
    }
    unexpected_outer = sorted(
        name
        for name in file_names
        if not name.startswith(plugin_prefix) and name not in outer_allowed
    )
    if unexpected_outer:
        raise ValueError(
            "WorkBuddy 包含未经允许的外层文件："
            + "、".join(unexpected_outer[:5])
        )
    if any(
        PurePosixPath(name).parent == PurePosixPath(archive_root)
        and PurePosixPath(name).suffix.lower() in {".command", ".cmd", ".ps1"}
        for name in file_names
    ):
        raise ValueError("WorkBuddy 包外层仍包含固定安装器")

    marketplace = json.loads(
        archive.read(
            f"{archive_root}/.codebuddy-plugin/marketplace.json"
        ).decode("utf-8")
    )
    plugin_json_name = f"{plugin_prefix}.codebuddy-plugin/plugin.json"
    if plugin_json_name not in verified_files:
        raise ValueError("WorkBuddy plugin.json 未被签名清单覆盖")
    plugin = json.loads(archive.read(plugin_json_name).decode("utf-8"))
    mcp_declaration = plugin.get("mcpServers")
    if isinstance(mcp_declaration, str):
        if mcp_declaration != "./.mcp.json":
            raise ValueError("WorkBuddy 外置 MCP 清单路径不合规")
        mcp_name = f"{plugin_prefix}.mcp.json"
        if mcp_name not in verified_files:
            raise ValueError("WorkBuddy 外置 .mcp.json 未被签名清单覆盖")
        mcp_payload = json.loads(archive.read(mcp_name).decode("utf-8"))
        mcp_servers = mcp_payload.get("mcpServers")
        mcp_configuration_mode = "signed_external_plugin_mcp_file"
    elif isinstance(mcp_declaration, dict):
        mcp_servers = mcp_declaration
        mcp_configuration_mode = "signed_inline_plugin_manifest"
    else:
        raise ValueError("WorkBuddy 插件缺少 MCP 声明")
    expected_server = {
        "command": "${CODEBUDDY_PLUGIN_ROOT}/bin/run-node",
        "args": [
            "${CODEBUDDY_PLUGIN_ROOT}/mcp/jiaotang-agent.mjs",
            "plugin-serve",
        ],
    }
    if (
        not isinstance(mcp_servers, dict)
        or mcp_servers != {"jiaotang-kb": expected_server}
    ):
        raise ValueError("WorkBuddy jiaotang-kb MCP 声明不合规")
    for required_runtime in (
        "bin/run-node",
        "bin/run-node.cmd",
        "mcp/jiaotang-agent.mjs",
    ):
        if plugin_prefix + required_runtime not in verified_files:
            raise ValueError(
                f"WorkBuddy MCP 运行文件未被签名清单覆盖：{required_runtime}"
            )
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
        raise ValueError("WorkBuddy marketplace.json 未固定指向已验签插件")
    return {
        "status": "verified",
        "publisher_fingerprint": TRUSTED_PUBLISHER_FINGERPRINT,
        "signature_namespace": WORKBUDDY_SIGNATURE_NAMESPACE,
        "verified_files": len(verified_files),
        "archive_entries": len(file_names),
        "outer_fixed_installers": False,
        "mcp_configuration_mode": mcp_configuration_mode,
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

            if target != "generic":
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
                str(staged["status"]) == "releasing"
                and str(staged["sha256"]) == expected_sha
                and staged_file.is_file()
                and sha256(staged_file) == expected_sha
            ):
                return {
                    **validation,
                    "status": "already-staged",
                    "release_state": "releasing",
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
                "releasing",
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
        "release_state": "releasing",
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
        if release is None or staged is None or str(staged["status"]) != "releasing":
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
            WHERE version=? AND target=? AND status='releasing'
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
) -> dict[str, object]:
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
                str(existing["status"]) == "releasing"
                and existing_hashes == expected_hashes
                and all(
                    Path(str(row["file_path"])).is_file()
                    and sha256(Path(str(row["file_path"])))
                    == str(row["sha256"])
                    for row in rows
                )
            ):
                return {
                    **validation,
                    "status": "already-staged",
                    "release_state": "releasing",
                    "github_url": str(existing["github_url"]),
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
                "releasing",
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
        "release_state": "releasing",
        "github_url": github_url.strip(),
        "staged_at": staged_at,
    }


def publish_selective(
    database_path: Path,
    release_directory: Path,
    packages: dict[str, Path],
    version: str,
    release_notes: str,
) -> dict[str, object]:
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
            target
            for target in ("generic", "workbuddy")
            if target in installed
        )
        primary = installed[primary_target]
        published_at = datetime.now(timezone.utc).isoformat()
        cursor = connection.execute(
            """
            INSERT INTO skill_releases(
                version,file_name,file_path,sha256,release_notes,published_at
            ) VALUES (?,?,?,?,?,?)
            """,
            (
                version,
                primary.name,
                str(primary),
                validation["artifacts"][primary_target]["sha256"],
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
    if staged is None or str(staged["status"]) != "releasing" or not rows:
        raise RuntimeError(f"版本 {version} 未处于可提升的正式发布中")
    if any(
        not Path(str(row["file_path"])).is_file()
        or sha256(Path(str(row["file_path"]))) != str(row["sha256"])
        for row in rows
    ):
        raise RuntimeError("正式发布中的候选包缺失或哈希发生变化")
    packages: dict[str, Path] = {}
    for row in rows:
        legacy_target = str(row["target"])
        target = (
            "workbuddy"
            if legacy_target in {"macos", "windows"}
            else legacy_target
        )
        path = Path(str(row["file_path"]))
        if target in packages and packages[target] != path:
            raise RuntimeError(
                "发布中记录仍包含两个系统专用 WorkBuddy 包，请撤销后按统一包重新暂存"
            )
        packages[target] = path
    result = publish_selective(
        database_path,
        release_directory,
        packages,
        version,
        str(staged["release_notes"]),
    )
    promoted_at = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            UPDATE skill_release_stages
            SET status='published',promoted_at=?
            WHERE version=? AND status='releasing'
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
                str(existing["status"]) == "releasing"
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
                    "release_state": "releasing",
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
                "releasing",
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
        "release_state": "releasing",
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
    if staged is None or str(staged["status"]) != "releasing":
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
            WHERE version=? AND status='releasing'
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
        ),
        required=True,
    )
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--generic-package", type=Path)
    parser.add_argument("--workbuddy-package", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--release-notes-file", type=Path)
    parser.add_argument("--git-commit", default="")
    parser.add_argument("--github-url", default="")
    parser.add_argument("--target", choices=ARTIFACT_TARGETS)
    arguments = parser.parse_args()
    if arguments.mode in {"stage", "stage-artifact"}:
        packages = {
            target: package
            for target, package in (
                ("generic", arguments.generic_package),
                ("workbuddy", arguments.workbuddy_package),
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
            )
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
        result = promote_selective(
            arguments.database,
            arguments.release_dir,
            arguments.version,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
