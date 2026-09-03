"""Publish the desktop client's independent skill-bundle update feed."""

from __future__ import annotations

import base64
import binascii
import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import zipfile
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


PRODUCT_ID = "cn.gongchuang.enterprise-assistant"
VERSION_PATTERN = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)")
CLIENT_SKILL_UPDATE_PUBLIC_KEY_SHA256 = (
    "1fd8ab82ab5d6cd413f611cf7923df79e6e4eaaaab016d5c9df88927f75fddd2"
)
MAX_EXPANDED_BYTES = 1024 * 1024 * 1024


@dataclass(frozen=True)
class SkillUpdateFeedReceipt:
    """Paths written for one current skill-bundle release."""

    archive_path: Path
    manifest_path: Path
    version: str


def _version_tuple(value: str) -> tuple[int, int, int]:
    if VERSION_PATTERN.fullmatch(value) is None:
        raise ValueError("技能包更新版本必须使用三段语义化版本")
    return tuple(int(part) for part in value.split("."))  # type: ignore[return-value]


def _archive_files(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    files: dict[str, zipfile.ZipInfo] = {}
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
            or mode == stat.S_IFLNK
        ):
            raise ValueError(f"客户端技能更新 ZIP 包含不安全路径：{name}")
        canonical = "/".join(part for part in path.parts if part not in {"", "."})
        if info.is_dir():
            continue
        if canonical in files:
            raise ValueError(f"客户端技能更新 ZIP 包含重复路径：{name}")
        expanded_bytes += int(info.file_size)
        if expanded_bytes > MAX_EXPANDED_BYTES:
            raise ValueError("客户端技能更新 ZIP 解压后超过 1 GiB 安全上限")
        files[canonical] = info
    return files


def _read_json_entry(
    archive: zipfile.ZipFile,
    files: dict[str, zipfile.ZipInfo],
    name: str,
) -> dict[str, object]:
    if name not in files:
        raise ValueError(f"客户端技能更新 ZIP 缺少 {name}")
    payload = json.loads(archive.read(files[name]).decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"客户端技能更新 ZIP 的 {name} 必须是 JSON 对象")
    return payload


def validate_skill_update_archive(archive_path: Path, version: str) -> dict[str, object]:
    """Verify the exact archive format and signature consumed by desktop clients."""

    normalized_version = version.strip().removeprefix("V").removeprefix("v")
    _version_tuple(normalized_version)
    if not archive_path.is_file() or archive_path.is_symlink():
        raise ValueError("技能包更新源必须是普通 ZIP 文件")
    if archive_path.suffix.casefold() != ".zip":
        raise ValueError("技能包更新源必须是 ZIP 文件")

    with zipfile.ZipFile(archive_path) as archive:
        files = _archive_files(archive)
        if "skill-bundle-index.json" not in files:
            raise ValueError("客户端技能更新 ZIP 缺少 skill-bundle-index.json")
        index_bytes = archive.read(files["skill-bundle-index.json"])
        index = _read_json_entry(archive, files, "skill-bundle-index.json")
        receipt = _read_json_entry(archive, files, "staging-receipt.json")
        try:
            signature_text = archive.read(
                files["skill-bundle-index.sig"]
            ).decode("ascii").strip()
            signature = base64.b64decode(signature_text, validate=True)
            public_pem = archive.read(files["skill-bundle-index.pub.pem"])
        except (KeyError, UnicodeDecodeError, ValueError, binascii.Error) as error:
            raise ValueError("客户端技能更新签名伴随物缺失或格式错误") from error

        public_key_sha256 = hashlib.sha256(public_pem).hexdigest()
        if public_key_sha256 != CLIENT_SKILL_UPDATE_PUBLIC_KEY_SHA256:
            raise ValueError("客户端技能更新公钥与正式客户端固定公钥不一致")
        try:
            public_key = serialization.load_pem_public_key(public_pem)
        except ValueError as error:
            raise ValueError("客户端技能更新公钥不是有效 PEM") from error
        if not isinstance(public_key, Ed25519PublicKey):
            raise ValueError("客户端技能更新公钥不是 Ed25519 公钥")
        try:
            public_key.verify(signature, index_bytes)
        except InvalidSignature as error:
            raise ValueError("客户端技能更新索引签名验证失败") from error

        skills = index.get("skills")
        declared_files = index.get("files")
        if (
            index.get("schemaVersion") != 1
            or index.get("productId") != PRODUCT_ID
            or index.get("skillBundleVersion") != normalized_version
            or index.get("sourceReleaseTag") != f"V{normalized_version}"
            or index.get("signingTier") != "formal"
            or not isinstance(skills, list)
            or not skills
            or not all(
                isinstance(skill, str)
                and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", skill)
                for skill in skills
            )
            or len(set(skills)) != len(skills)
            or not isinstance(declared_files, dict)
            or not declared_files
        ):
            raise ValueError("客户端技能更新索引身份、版本或技能清单不合规")
        if any(
            not isinstance(path, str)
            or not isinstance(digest, str)
            or not path
            or path.startswith("/")
            or "\\" in path
            or ":" in path
            or ".." in PurePosixPath(path).parts
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            for path, digest in declared_files.items()
        ):
            raise ValueError("客户端技能更新索引文件表不合规")

        companions = {
            "skill-bundle-index.json",
            "skill-bundle-index.sig",
            "skill-bundle-index.pub.pem",
            "staging-receipt.json",
        }
        expected_archive_files = companions | {
            f"skills/{path}" for path in declared_files
        }
        if set(files) != expected_archive_files:
            raise ValueError("客户端技能更新 ZIP 与签名索引文件集合不一致")
        for path, digest in declared_files.items():
            actual = hashlib.sha256(archive.read(files[f"skills/{path}"])).hexdigest()
            if actual != digest:
                raise ValueError(f"客户端技能更新文件哈希不一致：{path}")
        if any(f"skills/{skill}/SKILL.md" not in files for skill in skills):
            raise ValueError("客户端技能更新缺少已声明技能入口")

        suite = _read_json_entry(archive, files, "skills/suite-manifest.json")
        release = suite.get("release")
        if (
            not isinstance(release, dict)
            or release.get("version") != normalized_version
            or release.get("tag") != f"V{normalized_version}"
            or suite.get("skills") != skills
        ):
            raise ValueError("客户端技能更新套件清单与签名索引不一致")
        if (
            receipt.get("schemaVersion") != 1
            or receipt.get("skillBundleVersion") != normalized_version
            or receipt.get("projectionPurpose") != "independent-update"
            or receipt.get("signingTier") != "formal"
            or receipt.get("indexSha256")
            != hashlib.sha256(index_bytes).hexdigest()
            or receipt.get("publicKeySha256") != public_key_sha256
            or receipt.get("fileCount") != len(declared_files)
            or receipt.get("skillCount") != len(skills)
        ):
            raise ValueError("客户端技能更新构建回执与签名内容不一致")

    return {
        "status": "verified",
        "version": normalized_version,
        "skill_count": len(skills),
        "file_count": len(declared_files),
        "archive_sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
        "public_key_sha256": public_key_sha256,
    }


def _quarantine_incomplete(temporary: Path, destination: Path) -> None:
    if not temporary.exists():
        return
    quarantine = destination.parent / ".quarantine"
    quarantine.mkdir(parents=True, exist_ok=True)
    failed = quarantine / (
        f"{temporary.name}.failed-"
        f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    )
    os.replace(temporary, failed)


def _same_file_bytes(first: Path, second: Path) -> bool:
    if first.stat().st_size != second.stat().st_size:
        return False
    with first.open("rb") as left, second.open("rb") as right:
        while True:
            left_chunk = left.read(1024 * 1024)
            right_chunk = right.read(1024 * 1024)
            if left_chunk != right_chunk:
                return False
            if not left_chunk:
                return True


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.name}.{secrets.token_hex(8)}.tmp"
    )
    try:
        with source.open("rb") as input_stream, temporary.open("xb") as output_stream:
            shutil.copyfileobj(input_stream, output_stream, 1024 * 1024)
            output_stream.flush()
            os.fsync(output_stream.fileno())
        os.replace(temporary, destination)
    finally:
        _quarantine_incomplete(temporary, destination)


def _atomic_json(payload: dict[str, object], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.name}.{secrets.token_hex(8)}.tmp"
    )
    try:
        with temporary.open("x", encoding="utf-8") as output:
            json.dump(payload, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
    finally:
        _quarantine_incomplete(temporary, destination)


def publish_skill_update_feed(
    *,
    release_directory: Path,
    archive: Path,
    version: str,
    release_notes: str,
) -> SkillUpdateFeedReceipt:
    """Atomically expose a validated desktop projection through the public v1 feed.

    The archive must use the desktop updater's root-level signed-index layout;
    the independently downloadable generic suite is a different artifact and
    must never be placed behind this feed. The caller validates the projection
    before invoking this function.
    A versioned archive is immutable: publishing different bytes under an
    existing version is rejected and requires a new release version.
    """

    normalized_version = version.strip().removeprefix("V").removeprefix("v")
    incoming_version = _version_tuple(normalized_version)
    validate_skill_update_archive(archive, normalized_version)

    release_directory.mkdir(parents=True, exist_ok=True)
    # 各版本租约不能保护共享 latest。比较、不可变归档和清单替换必须
    # 持有同一个跨进程锁；锁文件保留，避免删除后产生两个不同的锁 inode。
    with (release_directory / ".publish.lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        manifest_path = release_directory / "latest.json"
        if manifest_path.exists():
            if manifest_path.is_symlink() or not manifest_path.is_file():
                raise ValueError("技能包更新清单被非普通文件占用")
            current = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(current, dict) or not isinstance(
                current.get("skillBundleVersion"), str
            ):
                raise ValueError("现有技能包更新清单格式错误")
            current_version = _version_tuple(str(current["skillBundleVersion"]))
            if incoming_version < current_version:
                raise ValueError("禁止把客户端技能更新源降级到旧版本")

        archive_name = f"Gongchuang-Enterprise-Assistant-Skills-V{normalized_version}.zip"
        destination = release_directory / archive_name
        if destination.exists():
            if destination.is_symlink() or not destination.is_file():
                raise ValueError("技能包更新目标被非普通文件占用")
            if not _same_file_bytes(destination, archive):
                raise ValueError("同一技能包版本已存在不同内容")
        else:
            _atomic_copy(archive, destination)

        _atomic_json(
            {
                "schemaVersion": 1,
                "productId": PRODUCT_ID,
                "skillBundleVersion": normalized_version,
                "sourceReleaseTag": f"V{normalized_version}",
                "archiveUrl": f"./{archive_name}",
                "releaseNotes": release_notes.strip(),
            },
            manifest_path,
        )
    return SkillUpdateFeedReceipt(
        archive_path=destination,
        manifest_path=manifest_path,
        version=normalized_version,
    )
