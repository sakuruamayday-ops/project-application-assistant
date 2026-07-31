from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "python_supply_chain.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("python_supply_chain", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_lock(path: Path, *, package: str = "demo", digest: str | None = None):
    wheel_digest = digest or ("a" * 64)
    path.write_text(
        f"{package}==1.0.0 \\\n"
        f"    --hash=sha256:{wheel_digest}\n",
        encoding="utf-8",
    )


def write_fake_wheel(path: Path, *, name: str = "demo", version: str = "1.0.0"):
    dist_info = f"{name.replace('-', '_')}-{version}.dist-info"
    with ZipFile(path, "w") as archive:
        archive.writestr(
            f"{dist_info}/METADATA",
            "Metadata-Version: 2.1\n"
            f"Name: {name}\n"
            f"Version: {version}\n",
        )


def write_complete_wheelhouse(module, tmp_path: Path):
    lock = tmp_path / "requirements.lock"
    build_lock = tmp_path / "requirements-build.lock"
    write_lock(lock)
    write_lock(build_lock, package="wheel")
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    wheel = wheelhouse / "demo-1.0.0-py3-none-any.whl"
    write_fake_wheel(wheel)
    module.write_install_lock(wheelhouse)
    manifest = module.build_manifest(lock, build_lock, wheelhouse)
    manifest_digest = module.write_manifest(
        manifest,
        wheelhouse / module.MANIFEST_NAME,
        wheelhouse / module.DIGEST_NAME,
    )
    return lock, build_lock, wheelhouse, wheel, manifest_digest


def test_hash_lock_requires_exact_versions_and_hashes(tmp_path: Path):
    module = load_module()
    lock = tmp_path / "requirements.lock"
    write_lock(lock)
    assert module.validate_hash_lock(lock) == [
        f"demo==1.0.0 --hash=sha256:{'a' * 64}"
    ]

    for invalid in (
        "demo>=1.0\n",
        "demo==1.0\n",
        "-r other.txt\n",
        "--index-url https://example.invalid/simple\n",
        "demo @ https://example.invalid/demo.whl\n",
    ):
        lock.write_text(invalid, encoding="utf-8")
        with pytest.raises(module.SupplyChainError):
            module.validate_hash_lock(lock)


def test_manifest_binds_lock_runtime_and_exact_wheel_bytes(tmp_path: Path):
    module = load_module()
    lock, build_lock, wheelhouse, wheel, manifest_digest = write_complete_wheelhouse(
        module,
        tmp_path,
    )
    verified = module.verify_manifest(
        lock,
        build_lock,
        wheelhouse,
        expected_manifest_sha256=manifest_digest,
    )
    assert verified["policy"]["offline_install"] is True
    assert verified["policy"]["dependency_resolution_during_install"] is False
    assert verified["lock"]["sha256"] == module.sha256_file(lock)

    wheel.write_bytes(b"tampered")
    with pytest.raises(module.SupplyChainError):
        module.verify_manifest(
            lock,
            build_lock,
            wheelhouse,
            expected_manifest_sha256=manifest_digest,
        )


def test_manifest_rejects_extra_file_and_duplicate_json_keys(tmp_path: Path):
    module = load_module()
    extra_root = tmp_path / "extra"
    extra_root.mkdir()
    lock, build_lock, wheelhouse, _wheel, manifest_digest = write_complete_wheelhouse(
        module,
        extra_root,
    )
    (wheelhouse / "unexpected.txt").write_text("x", encoding="utf-8")
    with pytest.raises(module.SupplyChainError, match="非 wheel"):
        module.verify_manifest(
            lock,
            build_lock,
            wheelhouse,
            expected_manifest_sha256=manifest_digest,
        )

    duplicate_root = tmp_path / "duplicate"
    duplicate_root.mkdir()
    lock, build_lock, wheelhouse, _wheel, _digest = write_complete_wheelhouse(
        module,
        duplicate_root,
    )
    manifest_path = wheelhouse / module.MANIFEST_NAME
    manifest_path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
    new_digest = module.sha256_file(manifest_path)
    (wheelhouse / module.DIGEST_NAME).write_text(
        f"{new_digest}  {module.MANIFEST_NAME}\n",
        encoding="ascii",
    )
    with pytest.raises(module.SupplyChainError, match="重复字段"):
        module.verify_manifest(
            lock,
            build_lock,
            wheelhouse,
            expected_manifest_sha256=new_digest,
        )


def test_manifest_rejects_runtime_mismatch(tmp_path: Path):
    module = load_module()
    lock, build_lock, wheelhouse, _wheel, _digest = write_complete_wheelhouse(
        module,
        tmp_path,
    )
    manifest_path = wheelhouse / module.MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["runtime"]["python_major_minor"] = "0.0"
    manifest["content_identity_sha256"] = module._content_identity(
        manifest["lock"]["sha256"],
        manifest["build_lock"]["sha256"],
        manifest["install_lock"]["sha256"],
        manifest["runtime"],
        manifest["files"],
    )
    digest = module.write_manifest(
        manifest,
        manifest_path,
        wheelhouse / module.DIGEST_NAME,
    )
    with pytest.raises(module.SupplyChainError, match="运行时不兼容"):
        module.verify_manifest(
            lock,
            build_lock,
            wheelhouse,
            expected_manifest_sha256=digest,
        )
    module.verify_manifest(
        lock,
        build_lock,
        wheelhouse,
        expected_manifest_sha256=digest,
        enforce_runtime=False,
    )


def test_build_uses_pinned_offline_builder_and_preserves_partial_output(
    tmp_path: Path,
    monkeypatch,
):
    module = load_module()
    supported_runtime = module.runtime_identity()
    supported_runtime["implementation"] = "CPython"
    supported_runtime["python_major_minor"] = module.LOCK_TARGET_PYTHON
    monkeypatch.setattr(
        module,
        "runtime_identity",
        lambda: supported_runtime,
    )
    lock = tmp_path / "requirements.lock"
    build_lock = tmp_path / "requirements-build.lock"
    write_lock(lock)
    write_lock(build_lock, package="wheel")
    wheelhouse = tmp_path / "wheelhouse"
    calls = []

    def fake_run(command, check, **_kwargs):
        calls.append(command)
        write_fake_wheel(
            wheelhouse / "demo-1.0.0-py3-none-any.whl"
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    module.build_wheelhouse(lock, build_lock, wheelhouse)
    for command in calls[:2]:
        assert "download" in command
        assert "--require-hashes" in command
        assert "--no-deps" in command
        assert "--dest" in command
    builder_install = calls[3]
    assert "install" in builder_install
    assert "--no-index" in builder_install
    assert "--require-hashes" in builder_install
    assert "--only-binary=:all:" in builder_install
    wheel_build = calls[4]
    assert "wheel" in wheel_build
    assert "--no-index" in wheel_build
    assert "--require-hashes" in wheel_build
    assert "--no-build-isolation" in wheel_build

    with pytest.raises(module.SupplyChainError, match="不存在或为空"):
        module.build_wheelhouse(lock, build_lock, wheelhouse)


def test_build_rejects_wrong_python_and_native_sdist_wheel(
    tmp_path: Path,
    monkeypatch,
):
    module = load_module()
    unsupported_runtime = module.runtime_identity()
    unsupported_runtime["python_major_minor"] = "0.0"
    monkeypatch.setattr(
        module,
        "runtime_identity",
        lambda: unsupported_runtime,
    )
    with pytest.raises(module.SupplyChainError, match="CPython 3.12"):
        module.build_wheelhouse(
            tmp_path / "missing.lock",
            tmp_path / "missing-build.lock",
            tmp_path / "wheelhouse",
        )

    sourcehouse = tmp_path / "sourcehouse"
    sourcehouse.mkdir()
    wheelhouse = tmp_path / "native-wheelhouse"
    wheelhouse.mkdir()
    write_fake_wheel(
        wheelhouse / "demo-1.0.0-cp312-cp312-macosx_11_0_arm64.whl"
    )
    with pytest.raises(module.SupplyChainError, match="平台相关 wheel"):
        module._enforce_pure_sdist_build_outputs(sourcehouse, wheelhouse)


def test_install_is_offline_and_requires_release_bound_manifest(
    tmp_path: Path,
    monkeypatch,
):
    module = load_module()
    lock, build_lock, wheelhouse, _wheel, digest = write_complete_wheelhouse(
        module,
        tmp_path,
    )
    calls = []

    def fake_run(command, check, **_kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    module.install_wheelhouse(
        lock,
        build_lock,
        wheelhouse,
        expected_manifest_sha256=digest,
    )
    command = calls[0]
    assert "install" in command
    assert "--no-index" in command
    assert "--require-hashes" in command
    assert "--only-binary=:all:" in command
    assert "--no-deps" in command
    assert "--find-links" in command

    with pytest.raises(
        module.SupplyChainError,
        match="受控发布期望摘要",
    ):
        module.install_wheelhouse(
            lock,
            build_lock,
            wheelhouse,
            expected_manifest_sha256="0" * 64,
        )


def test_dependency_identity_is_stable_and_binds_manifest(tmp_path: Path):
    module = load_module()
    lock, build_lock, wheelhouse, _wheel, digest = write_complete_wheelhouse(
        module,
        tmp_path,
    )
    manifest = module.verify_manifest(
        lock,
        build_lock,
        wheelhouse,
        expected_manifest_sha256=digest,
    )
    first = module.dependency_identity(lock, build_lock, manifest, digest)
    second = module.dependency_identity(lock, build_lock, manifest, digest)
    assert first == second
    unsigned = dict(first)
    identity_digest = unsigned.pop("dependency_identity_sha256")
    assert identity_digest == hashlib.sha256(
        module.canonical_json_bytes(unsigned)
    ).hexdigest()


def test_lock_metadata_binds_inputs_locks_and_generator(tmp_path: Path):
    module = load_module()
    (tmp_path / "requirements.in").write_text(
        "demo==1.0.0\n",
        encoding="utf-8",
    )
    (tmp_path / "requirements-test.in").write_text(
        "-r requirements.in\npytest==8.4.1\n",
        encoding="utf-8",
    )
    (tmp_path / "requirements-build.in").write_text(
        "pip==26.0.1\nsetuptools==83.0.0\nwheel==0.47.0\n",
        encoding="utf-8",
    )
    write_lock(tmp_path / "requirements.lock")
    write_lock(tmp_path / "requirements-test.lock", package="pytest")
    write_lock(tmp_path / "requirements-build.lock", package="wheel")

    metadata_path = module.write_lock_metadata(tmp_path)
    metadata = module.verify_lock_metadata(tmp_path)
    assert metadata_path.name == module.LOCK_METADATA_NAME
    assert metadata["generator"] == {
        "name": "uv",
        "version": module.LOCK_GENERATOR_VERSION,
        "target_python": "3.12",
        "universal": True,
        "generate_hashes": True,
    }

    (tmp_path / "requirements.in").write_text(
        "demo==2.0.0\n",
        encoding="utf-8",
    )
    with pytest.raises(module.SupplyChainError, match="必须重新生成"):
        module.verify_lock_metadata(tmp_path)
