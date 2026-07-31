#!/usr/bin/env python3
"""Build, verify and install a hash-locked offline Python wheelhouse.

The build command is the only command allowed to contact a package index. The
verify and install commands are deliberately offline and fail closed when the
lock, manifest, runtime ABI or wheel bytes do not match.
"""

from __future__ import annotations

import argparse
from email.parser import Parser
import hashlib
import json
import os
import platform
import re
import stat
import subprocess
import sys
import sysconfig
from zipfile import BadZipFile, ZipFile
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1
MANIFEST_NAME = "wheelhouse-manifest.json"
DIGEST_NAME = "wheelhouse-manifest.sha256"
INSTALL_LOCK_NAME = "wheelhouse-install.lock"
LOCK_METADATA_NAME = "requirements-lock-metadata.json"
LOCK_GENERATOR_NAME = "uv"
LOCK_GENERATOR_VERSION = "0.11.28"
LOCK_TARGET_PYTHON = "3.12"
WHEEL_NAME_RE = re.compile(r"^[A-Za-z0-9_.+-]+\.whl$")
PINNED_REQUIREMENT_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*"
    r"(?:\[[A-Za-z0-9_,.-]+\])?"
    r"==[^;\s]+(?:\s*;\s*.+?)?"
    r"(?:\s+--hash=sha256:[0-9a-f]{64})+$"
)
FORBIDDEN_LOCK_DIRECTIVES = (
    "-r ",
    "--requirement ",
    "-c ",
    "--constraint ",
    "--index-url ",
    "--extra-index-url ",
    "--find-links ",
    "--trusted-host ",
    "-e ",
    "--editable ",
)


class SupplyChainError(RuntimeError):
    """Raised when a supply-chain invariant is not satisfied."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SupplyChainError(f"JSON 包含重复字段：{key}")
        result[key] = value
    return result


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SupplyChainError(f"无法读取 JSON：{path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SupplyChainError(f"JSON 顶层必须是对象：{path}")
    return value


def _logical_lock_lines(text: str) -> list[str]:
    logical: list[str] = []
    pending = ""
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        continued = stripped.endswith("\\")
        fragment = stripped[:-1].strip() if continued else stripped
        pending = f"{pending} {fragment}".strip()
        if not continued:
            logical.append(pending)
            pending = ""
    if pending:
        raise SupplyChainError("依赖锁最后一行存在未闭合的续行符")
    return logical


def validate_hash_lock(lock_path: Path) -> list[str]:
    if not lock_path.is_file() or lock_path.is_symlink():
        raise SupplyChainError(f"依赖锁必须是普通文件：{lock_path}")
    try:
        text = lock_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SupplyChainError(f"无法读取依赖锁：{lock_path}: {exc}") from exc
    lines = _logical_lock_lines(text)
    if not lines:
        raise SupplyChainError(f"依赖锁为空：{lock_path}")
    for line in lines:
        lowered = line.lower()
        if lowered.startswith(FORBIDDEN_LOCK_DIRECTIVES):
            raise SupplyChainError(f"依赖锁包含禁止的外部来源指令：{line}")
        normalized = re.sub(r"\s+", " ", line)
        if not PINNED_REQUIREMENT_RE.fullmatch(normalized):
            raise SupplyChainError(
                "依赖必须使用精确 == 版本并至少绑定一个 SHA-256："
                f"{line}"
            )
    return lines


def runtime_identity() -> dict[str, str]:
    implementation = platform.python_implementation()
    return {
        "implementation": implementation,
        "python_version": platform.python_version(),
        "python_major_minor": f"{sys.version_info.major}.{sys.version_info.minor}",
        "python_abi": str(sysconfig.get_config_var("SOABI") or ""),
        "system": platform.system().lower(),
        "machine": platform.machine().lower(),
    }


def _regular_wheel_files(wheelhouse: Path) -> list[Path]:
    if not wheelhouse.is_dir() or wheelhouse.is_symlink():
        raise SupplyChainError(f"wheelhouse 必须是普通目录：{wheelhouse}")
    wheels: list[Path] = []
    seen_casefold: set[str] = set()
    for path in sorted(wheelhouse.iterdir(), key=lambda item: item.name):
        if path.name in {MANIFEST_NAME, DIGEST_NAME, INSTALL_LOCK_NAME}:
            continue
        mode = path.lstat().st_mode
        if not stat.S_ISREG(mode) or path.is_symlink():
            raise SupplyChainError(f"wheelhouse 含非普通文件：{path.name}")
        if not WHEEL_NAME_RE.fullmatch(path.name):
            raise SupplyChainError(f"wheelhouse 含非 wheel 制品：{path.name}")
        folded = path.name.casefold()
        if folded in seen_casefold:
            raise SupplyChainError(f"wheelhouse 存在大小写冲突：{path.name}")
        seen_casefold.add(folded)
        wheels.append(path)
    if not wheels:
        raise SupplyChainError("wheelhouse 中没有 wheel 制品")
    return wheels


def _wheel_records(wheels: Iterable[Path]) -> list[dict[str, object]]:
    return [
        {
            "filename": path.name,
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in wheels
    ]


def _content_identity(
    lock_sha256: str,
    build_lock_sha256: str,
    install_lock_sha256: str,
    runtime: dict[str, str],
    files: list[dict[str, object]],
) -> str:
    payload = {
        "lock_sha256": lock_sha256,
        "build_lock_sha256": build_lock_sha256,
        "install_lock_sha256": install_lock_sha256,
        "runtime": runtime,
        "files": files,
    }
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def expected_install_lock(wheelhouse: Path) -> str:
    records: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for wheel in _regular_wheel_files(wheelhouse):
        try:
            with ZipFile(wheel) as archive:
                metadata_names = [
                    name
                    for name in archive.namelist()
                    if name.endswith(".dist-info/METADATA")
                ]
                if len(metadata_names) != 1:
                    raise SupplyChainError(
                        f"wheel 元数据数量异常：{wheel.name}"
                    )
                metadata_text = archive.read(metadata_names[0]).decode(
                    "utf-8"
                )
        except (BadZipFile, KeyError, UnicodeDecodeError) as exc:
            raise SupplyChainError(
                f"无法读取 wheel 元数据：{wheel.name}: {exc}"
            ) from exc
        metadata = Parser().parsestr(metadata_text)
        raw_name = str(metadata.get("Name") or "").strip()
        version = str(metadata.get("Version") or "").strip()
        canonical_name = re.sub(r"[-_.]+", "-", raw_name).lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", canonical_name):
            raise SupplyChainError(f"wheel 包名非法：{wheel.name}")
        if not version or re.search(r"[\s;]", version):
            raise SupplyChainError(f"wheel 版本非法：{wheel.name}")
        if canonical_name in seen:
            raise SupplyChainError(f"wheel 包名重复：{canonical_name}")
        seen.add(canonical_name)
        records.append((canonical_name, version, sha256_file(wheel)))
    return "".join(
        f"{name}=={version} --hash=sha256:{digest}\n"
        for name, version, digest in sorted(records)
    )


def write_install_lock(wheelhouse: Path) -> Path:
    install_lock = wheelhouse / INSTALL_LOCK_NAME
    install_lock.write_text(
        expected_install_lock(wheelhouse),
        encoding="utf-8",
    )
    validate_hash_lock(install_lock)
    return install_lock


def _lock_record(lock_path: Path) -> dict[str, object]:
    requirements = validate_hash_lock(lock_path)
    return {
        "filename": lock_path.name,
        "sha256": sha256_file(lock_path),
        "size": lock_path.stat().st_size,
        "requirement_count": len(requirements),
    }


def build_manifest(
    lock_path: Path,
    build_lock_path: Path,
    wheelhouse: Path,
) -> dict[str, object]:
    requirements = validate_hash_lock(lock_path)
    validate_hash_lock(build_lock_path)
    wheels = _regular_wheel_files(wheelhouse)
    files = _wheel_records(wheels)
    lock_sha256 = sha256_file(lock_path)
    build_lock_sha256 = sha256_file(build_lock_path)
    install_lock_path = wheelhouse / INSTALL_LOCK_NAME
    if not install_lock_path.is_file() or install_lock_path.is_symlink():
        raise SupplyChainError("wheelhouse 缺少最终 wheel 安装锁")
    if install_lock_path.read_text(encoding="utf-8") != expected_install_lock(
        wheelhouse
    ):
        raise SupplyChainError("最终 wheel 安装锁与 wheel 集合不一致")
    install_lock_sha256 = sha256_file(install_lock_path)
    runtime = runtime_identity()
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "jiaotang-python-wheelhouse",
        "lock": _lock_record(lock_path),
        "build_lock": _lock_record(build_lock_path),
        "install_lock": _lock_record(install_lock_path),
        "runtime": runtime,
        "policy": {
            "hash_algorithm": "sha256",
            "only_binary": True,
            "source_distributions_built_before_publish": True,
            "builder_from_hash_lock": True,
            "install_lock_from_final_wheels": True,
            "native_source_builds": False,
            "offline_install": True,
            "require_hashes": True,
            "dependency_resolution_during_install": False,
        },
        "files": files,
        "content_identity_sha256": _content_identity(
            lock_sha256,
            build_lock_sha256,
            install_lock_sha256,
            runtime,
            files,
        ),
    }


def write_manifest(
    manifest: dict[str, object],
    manifest_path: Path,
    digest_path: Path,
) -> str:
    manifest_path.write_bytes(canonical_json_bytes(manifest))
    manifest_sha256 = sha256_file(manifest_path)
    digest_path.write_text(
        f"{manifest_sha256}  {manifest_path.name}\n",
        encoding="ascii",
    )
    return manifest_sha256


def _expected_sidecar_digest(digest_path: Path, manifest_path: Path) -> str:
    try:
        line = digest_path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError) as exc:
        raise SupplyChainError(f"无法读取 manifest 摘要：{digest_path}: {exc}") from exc
    match = re.fullmatch(
        rf"([0-9a-f]{{64}})  {re.escape(manifest_path.name)}",
        line,
    )
    if not match:
        raise SupplyChainError(f"manifest 摘要格式非法：{digest_path}")
    return match.group(1)


def verify_manifest(
    lock_path: Path,
    build_lock_path: Path,
    wheelhouse: Path,
    *,
    expected_manifest_sha256: str | None = None,
    enforce_runtime: bool = True,
) -> dict[str, object]:
    requirements = validate_hash_lock(lock_path)
    validate_hash_lock(build_lock_path)
    manifest_path = wheelhouse / MANIFEST_NAME
    digest_path = wheelhouse / DIGEST_NAME
    for path in (manifest_path, digest_path):
        if not path.is_file() or path.is_symlink():
            raise SupplyChainError(f"wheelhouse 元数据必须是普通文件：{path}")
    manifest = load_json(manifest_path)
    sidecar_digest = _expected_sidecar_digest(digest_path, manifest_path)
    actual_manifest_digest = sha256_file(manifest_path)
    if sidecar_digest != actual_manifest_digest:
        raise SupplyChainError("wheelhouse manifest 与摘要旁车不一致")
    if expected_manifest_sha256 is not None:
        expected = expected_manifest_sha256.strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise SupplyChainError("期望 manifest SHA-256 格式非法")
        if expected != actual_manifest_digest:
            raise SupplyChainError("wheelhouse manifest 与受控发布期望摘要不一致")

    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise SupplyChainError("wheelhouse manifest schema 不受支持")
    if manifest.get("artifact_type") != "jiaotang-python-wheelhouse":
        raise SupplyChainError("wheelhouse manifest artifact_type 不匹配")
    lock_record = manifest.get("lock")
    if not isinstance(lock_record, dict):
        raise SupplyChainError("wheelhouse manifest 缺少 lock 对象")
    expected_lock = _lock_record(lock_path)
    if lock_record != expected_lock:
        raise SupplyChainError("wheelhouse manifest 绑定的依赖锁不匹配")
    build_lock_record = manifest.get("build_lock")
    if not isinstance(build_lock_record, dict):
        raise SupplyChainError("wheelhouse manifest 缺少 build_lock 对象")
    expected_build_lock = _lock_record(build_lock_path)
    if build_lock_record != expected_build_lock:
        raise SupplyChainError("wheelhouse manifest 绑定的构建工具锁不匹配")
    install_lock_path = wheelhouse / INSTALL_LOCK_NAME
    if not install_lock_path.is_file() or install_lock_path.is_symlink():
        raise SupplyChainError("wheelhouse 缺少普通文件形式的最终安装锁")
    expected_install_lock_text = expected_install_lock(wheelhouse)
    try:
        actual_install_lock_text = install_lock_path.read_text(
            encoding="utf-8"
        )
    except (OSError, UnicodeDecodeError) as exc:
        raise SupplyChainError(f"无法读取最终安装锁：{exc}") from exc
    if actual_install_lock_text != expected_install_lock_text:
        raise SupplyChainError("最终安装锁与 wheel 集合不一致")
    validate_hash_lock(install_lock_path)
    install_lock_record = manifest.get("install_lock")
    expected_install_lock_record = _lock_record(install_lock_path)
    if install_lock_record != expected_install_lock_record:
        raise SupplyChainError("wheelhouse manifest 绑定的最终安装锁不匹配")

    runtime_record = manifest.get("runtime")
    if not isinstance(runtime_record, dict):
        raise SupplyChainError("wheelhouse manifest 缺少 runtime 对象")
    if enforce_runtime:
        current = runtime_identity()
        for key in (
            "implementation",
            "python_major_minor",
            "python_abi",
            "system",
            "machine",
        ):
            if runtime_record.get(key) != current[key]:
                raise SupplyChainError(
                    f"wheelhouse 运行时不兼容：{key}="
                    f"{runtime_record.get(key)!r}，当前={current[key]!r}"
                )

    policy = manifest.get("policy")
    required_policy = {
        "hash_algorithm": "sha256",
        "only_binary": True,
        "source_distributions_built_before_publish": True,
        "builder_from_hash_lock": True,
        "install_lock_from_final_wheels": True,
        "native_source_builds": False,
        "offline_install": True,
        "require_hashes": True,
        "dependency_resolution_during_install": False,
    }
    if policy != required_policy:
        raise SupplyChainError("wheelhouse manifest 安装策略不满足离线门禁")

    actual_files = _wheel_records(_regular_wheel_files(wheelhouse))
    if manifest.get("files") != actual_files:
        raise SupplyChainError("wheelhouse 文件集合、大小或 SHA-256 不匹配")
    expected_content_identity = _content_identity(
        expected_lock["sha256"],
        expected_build_lock["sha256"],
        expected_install_lock_record["sha256"],
        runtime_record,
        actual_files,
    )
    if manifest.get("content_identity_sha256") != expected_content_identity:
        raise SupplyChainError("wheelhouse 内容身份摘要不匹配")
    return manifest


def dependency_identity(
    lock_path: Path,
    build_lock_path: Path,
    manifest: dict[str, object],
    manifest_sha256: str,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "jiaotang-python-dependency-identity",
        "dependency_lock_sha256": sha256_file(lock_path),
        "dependency_build_lock_sha256": sha256_file(build_lock_path),
        "wheelhouse_install_lock_sha256": manifest["install_lock"]["sha256"],
        "wheelhouse_manifest_sha256": manifest_sha256,
        "wheelhouse_content_identity_sha256": manifest[
            "content_identity_sha256"
        ],
        "runtime": manifest["runtime"],
    }
    payload["dependency_identity_sha256"] = hashlib.sha256(
        canonical_json_bytes(payload)
    ).hexdigest()
    return payload


def _file_record(path: Path) -> dict[str, object]:
    return {
        "filename": path.name,
        "sha256": sha256_file(path),
        "size": path.stat().st_size,
    }


def expected_lock_metadata(portal_dir: Path) -> dict[str, object]:
    requirements_in = portal_dir / "requirements.in"
    requirements_test_in = portal_dir / "requirements-test.in"
    requirements_build_in = portal_dir / "requirements-build.in"
    production_lock = portal_dir / "requirements.lock"
    test_lock = portal_dir / "requirements-test.lock"
    build_lock = portal_dir / "requirements-build.lock"
    for path in (
        requirements_in,
        requirements_test_in,
        requirements_build_in,
        production_lock,
        test_lock,
        build_lock,
    ):
        if not path.is_file() or path.is_symlink():
            raise SupplyChainError(f"依赖锁元数据源必须是普通文件：{path}")
    validate_hash_lock(production_lock)
    validate_hash_lock(test_lock)
    validate_hash_lock(build_lock)
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "jiaotang-python-lock-metadata",
        "generator": {
            "name": LOCK_GENERATOR_NAME,
            "version": LOCK_GENERATOR_VERSION,
            "target_python": LOCK_TARGET_PYTHON,
            "universal": True,
            "generate_hashes": True,
        },
        "targets": {
            "build": {
                "inputs": [_file_record(requirements_build_in)],
                "lock": _file_record(build_lock),
            },
            "production": {
                "inputs": [_file_record(requirements_in)],
                "lock": _file_record(production_lock),
            },
            "test": {
                "inputs": [
                    _file_record(requirements_in),
                    _file_record(requirements_test_in),
                ],
                "lock": _file_record(test_lock),
            },
        },
    }


def write_lock_metadata(portal_dir: Path) -> Path:
    metadata_path = portal_dir / LOCK_METADATA_NAME
    metadata_path.write_bytes(
        canonical_json_bytes(expected_lock_metadata(portal_dir))
    )
    return metadata_path


def verify_lock_metadata(portal_dir: Path) -> dict[str, object]:
    metadata_path = portal_dir / LOCK_METADATA_NAME
    actual = load_json(metadata_path)
    expected = expected_lock_metadata(portal_dir)
    if actual != expected:
        raise SupplyChainError(
            "依赖输入、锁文件或生成器身份已变化；必须重新生成并评审依赖锁"
        )
    return actual


def _ensure_new_wheelhouse(path: Path) -> None:
    if path.exists():
        if path.is_symlink() or not path.is_dir():
            raise SupplyChainError(f"wheelhouse 输出路径不是普通目录：{path}")
        if any(path.iterdir()):
            raise SupplyChainError(
                "wheelhouse 输出目录必须不存在或为空；保留现有内容并换用新目录"
            )
    else:
        path.mkdir(parents=True)


def _run_or_fail(
    command: list[str],
    *,
    message: str,
    env: dict[str, str] | None = None,
) -> None:
    completed = subprocess.run(command, check=False, env=env)
    if completed.returncode != 0:
        raise SupplyChainError(message)


def _builder_python(builder_dir: Path) -> Path:
    if os.name == "nt":
        return builder_dir / "Scripts" / "python.exe"
    return builder_dir / "bin" / "python"


def _require_supported_build_runtime() -> None:
    current = runtime_identity()
    if (
        current["implementation"] != "CPython"
        or current["python_major_minor"] != LOCK_TARGET_PYTHON
    ):
        raise SupplyChainError(
            "wheelhouse 只能使用 "
            f"CPython {LOCK_TARGET_PYTHON} 构建；"
            f"当前为 {current['implementation']} "
            f"{current['python_major_minor']}"
        )


def _enforce_pure_sdist_build_outputs(
    sourcehouse: Path,
    wheelhouse: Path,
) -> None:
    downloaded_wheels = {
        path.name
        for path in sourcehouse.iterdir()
        if path.is_file()
        and not path.is_symlink()
        and WHEEL_NAME_RE.fullmatch(path.name)
    }
    for wheel in _regular_wheel_files(wheelhouse):
        if (
            wheel.name not in downloaded_wheels
            and not wheel.name.endswith("-none-any.whl")
        ):
            raise SupplyChainError(
                "源码包构建出了平台相关 wheel，禁止发布："
                f"{wheel.name}"
            )


def build_wheelhouse(
    lock_path: Path,
    build_lock_path: Path,
    wheelhouse: Path,
) -> dict[str, object]:
    _require_supported_build_runtime()
    validate_hash_lock(lock_path)
    validate_hash_lock(build_lock_path)
    _ensure_new_wheelhouse(wheelhouse)
    staging_root = wheelhouse.parent / f"{wheelhouse.name}.build-inputs"
    _ensure_new_wheelhouse(staging_root)
    sourcehouse = staging_root / "sourcehouse"
    sourcehouse.mkdir()
    builder_dir = staging_root / "builder"

    for current_lock in (build_lock_path, lock_path):
        command = [
            sys.executable,
            "-m",
            "pip",
            "download",
            "--disable-pip-version-check",
            "--no-cache-dir",
            "--require-hashes",
            "--no-deps",
            "--dest",
            str(sourcehouse),
            "-r",
            str(current_lock),
        ]
        if current_lock == build_lock_path:
            command.insert(-4, "--only-binary=:all:")
        else:
            command.insert(-4, "--no-build-isolation")
        _run_or_fail(
            command,
            message=(
                "hash-locked 构建输入下载失败；为便于审计，"
                "已保留未完成目录"
            ),
        )

    _run_or_fail(
        [
            sys.executable,
            "-m",
            "venv",
            "--without-pip",
            str(builder_dir),
        ],
        message="无法创建隔离 wheel 构建环境",
    )
    builder_python = _builder_python(builder_dir)
    _run_or_fail(
        [
            sys.executable,
            "-m",
            "pip",
            "--python",
            str(builder_python),
            "install",
            "--disable-pip-version-check",
            "--no-index",
            "--require-hashes",
            "--only-binary=:all:",
            "--no-deps",
            "--find-links",
            str(sourcehouse),
            "-r",
            str(build_lock_path),
        ],
        message="无法从 hash-locked 构建工具锁创建隔离 builder",
    )
    build_env = dict(os.environ)
    build_env.update(
        {
            "CC": "false",
            "CXX": "false",
            "LC_ALL": "C",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_FIND_LINKS": str(sourcehouse),
            "PIP_NO_INDEX": "1",
            "PYTHONHASHSEED": "0",
            "SOURCE_DATE_EPOCH": "0",
            "TZ": "UTC",
        }
    )
    command = [
        str(builder_python),
        "-m",
        "pip",
        "wheel",
        "--disable-pip-version-check",
        "--no-cache-dir",
        "--no-index",
        "--require-hashes",
        "--no-build-isolation",
        "--no-deps",
        "--find-links",
        str(sourcehouse),
        "--wheel-dir",
        str(wheelhouse),
        "-r",
        str(lock_path),
    ]
    _run_or_fail(
        command,
        message=(
            "离线 wheel 构建失败；为便于审计，已保留 sourcehouse、"
            "builder 与未完成 wheelhouse"
        ),
        env=build_env,
    )
    _enforce_pure_sdist_build_outputs(sourcehouse, wheelhouse)
    write_install_lock(wheelhouse)
    manifest = build_manifest(lock_path, build_lock_path, wheelhouse)
    write_manifest(
        manifest,
        wheelhouse / MANIFEST_NAME,
        wheelhouse / DIGEST_NAME,
    )
    return manifest


def install_wheelhouse(
    lock_path: Path,
    build_lock_path: Path,
    wheelhouse: Path,
    *,
    expected_manifest_sha256: str,
) -> None:
    verify_manifest(
        lock_path,
        build_lock_path,
        wheelhouse,
        expected_manifest_sha256=expected_manifest_sha256,
        enforce_runtime=True,
    )
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-index",
        "--require-hashes",
        "--only-binary=:all:",
        "--no-deps",
        "--find-links",
        str(wheelhouse),
        "-r",
        str(wheelhouse / INSTALL_LOCK_NAME),
    ]
    _run_or_fail(
        command,
        message="离线 wheelhouse 安装失败",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("build", "verify", "install"):
        command = subparsers.add_parser(name)
        command.add_argument("--lock", type=Path, required=True)
        command.add_argument("--build-lock", type=Path, required=True)
        command.add_argument("--wheelhouse", type=Path, required=True)
    verify = subparsers.choices["verify"]
    verify.add_argument("--expected-manifest-sha256")
    verify.add_argument("--identity-output", type=Path)
    verify.add_argument(
        "--allow-foreign-runtime",
        action="store_true",
        help="仅供制品审计；生产安装不得使用",
    )
    install = subparsers.choices["install"]
    install.add_argument("--expected-manifest-sha256", required=True)
    for name in ("lock-metadata-write", "lock-metadata-verify"):
        command = subparsers.add_parser(name)
        command.add_argument("--portal-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command in {"lock-metadata-write", "lock-metadata-verify"}:
            portal_dir = args.portal_dir.resolve(strict=True)
            if args.command == "lock-metadata-write":
                metadata = load_json(write_lock_metadata(portal_dir))
            else:
                metadata = verify_lock_metadata(portal_dir)
            print(json.dumps(metadata, ensure_ascii=False, sort_keys=True))
            return 0
        lock_path = args.lock.absolute()
        build_lock_path = args.build_lock.absolute()
        wheelhouse = args.wheelhouse.absolute()
        if args.command == "build":
            manifest = build_wheelhouse(
                lock_path,
                build_lock_path,
                wheelhouse,
            )
            manifest_sha256 = sha256_file(wheelhouse / MANIFEST_NAME)
            print(
                json.dumps(
                    dependency_identity(
                        lock_path,
                        build_lock_path,
                        manifest,
                        manifest_sha256,
                    ),
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        elif args.command == "verify":
            manifest = verify_manifest(
                lock_path,
                build_lock_path,
                wheelhouse,
                expected_manifest_sha256=args.expected_manifest_sha256,
                enforce_runtime=not args.allow_foreign_runtime,
            )
            manifest_sha256 = sha256_file(wheelhouse / MANIFEST_NAME)
            identity = dependency_identity(
                lock_path,
                build_lock_path,
                manifest,
                manifest_sha256,
            )
            if args.identity_output:
                args.identity_output.write_bytes(canonical_json_bytes(identity))
            print(json.dumps(identity, ensure_ascii=False, sort_keys=True))
        else:
            install_wheelhouse(
                lock_path,
                build_lock_path,
                wheelhouse,
                expected_manifest_sha256=args.expected_manifest_sha256,
            )
            print("离线 wheelhouse 验证并安装成功")
    except (OSError, SupplyChainError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
