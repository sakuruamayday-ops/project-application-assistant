from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.refresh_index_from_oss as refresh_module
import scripts.publish_index_to_oss as publish_module
from scripts.publish_index_to_oss import (
    MANIFEST_SCHEMA,
    POINTER_SCHEMA,
    PRODUCTION_FILES,
    canonical_json,
    put_immutable_bytes,
    sha256_bytes,
    signed_document,
    signing_key_id,
    switch_pointer_cas,
    verify_release_object_whitelist,
)
from scripts.refresh_index_from_oss import (
    REQUIRED_STRUCTURED_TABLES,
    activate_release,
    download_release,
    local_generation_metadata_valid,
    local_generation_valid,
    require_unused_staging,
    release_id_from_link,
    rollback_release,
    verify_pointer,
    verify_release,
)


class FakeRemote:
    def __init__(self, payload: bytes, headers: dict[str, str], etag: str) -> None:
        self.payload = payload
        self.headers = headers
        self.etag = etag
        self.content_length = len(payload)
        self.hash_crc64_ecma = 0


class FakeGet:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return self.payload


class FakeBucket:
    def __init__(self) -> None:
        self.objects: dict[str, FakeRemote] = {}
        self.puts = 0

    def head_object(self, key: str) -> FakeRemote:
        if key not in self.objects:
            import oss2

            raise oss2.exceptions.NoSuchKey(
                404,
                {"x-oss-request-id": "test"},
                b"",
                {"Code": "NoSuchKey", "Message": "missing"},
            )
        return self.objects[key]

    def get_object(self, key: str, byte_range=None) -> FakeGet:
        payload = self.objects[key].payload
        if byte_range:
            payload = payload[byte_range[0] : byte_range[1] + 1]
        return FakeGet(payload)

    def put_object(self, key: str, payload: bytes, headers: dict[str, str]):
        existing = self.objects.get(key)
        if headers.get("x-oss-forbid-overwrite") == "true" and existing:
            raise RuntimeError("forbid overwrite")
        if "If-Match" in headers and (
            not existing or existing.etag != headers["If-Match"]
        ):
            raise RuntimeError("precondition failed")
        self.puts += 1
        self.objects[key] = FakeRemote(
            payload,
            headers,
            etag=f"etag-{self.puts}",
        )
        return SimpleNamespace(etag=f"etag-{self.puts}")

    def put_object_from_file(
        self,
        key: str,
        source: str,
        headers: dict[str, str],
    ):
        return self.put_object(key, Path(source).read_bytes(), headers)


def signed_pointer(
    secret: bytes,
    release_id: str,
    manifest_body: bytes,
    previous: str | None = None,
) -> dict[str, object]:
    pointer: dict[str, object] = {
        "schema": POINTER_SCHEMA,
        "release_id": release_id,
        "release_manifest_key": f"production/index/releases/{release_id}/release.json",
        "release_signature_key": f"production/index/releases/{release_id}/release.sig",
        "release_manifest_sha256": sha256_bytes(manifest_body),
        "previous_release_id": previous,
        "signing_key_id": signing_key_id(secret),
        "switched_at": "2026-07-31T00:00:00Z",
    }
    import hmac

    pointer["pointer_hmac_sha256"] = hmac.new(
        secret,
        canonical_json(pointer),
        hashlib.sha256,
    ).hexdigest()
    return pointer


def test_existing_immutable_document_is_idempotent() -> None:
    bucket = FakeBucket()
    payload = b'{"schema":"test"}\n'
    digest = sha256_bytes(payload)
    bucket.objects["release.json"] = FakeRemote(
        payload,
        {
            "x-oss-meta-sha256": digest,
            "x-oss-meta-source-size": str(len(payload)),
        },
        "etag-existing",
    )

    assert put_immutable_bytes(bucket, "release.json", payload) == "existing"
    assert bucket.puts == 0


def test_existing_immutable_document_conflict_is_rejected() -> None:
    bucket = FakeBucket()
    bucket.objects["release.json"] = FakeRemote(
        b"old",
        {
            "x-oss-meta-sha256": sha256_bytes(b"old"),
            "x-oss-meta-source-size": "3",
        },
        "etag-existing",
    )

    with pytest.raises(RuntimeError, match="大小不一致|SHA-256"):
        put_immutable_bytes(bucket, "release.json", b"new payload")


def test_pointer_cas_rejects_concurrent_release() -> None:
    secret = b"a" * 48
    bucket = FakeBucket()
    initial_manifest = b"{}\n"
    current = signed_pointer(secret, "release-0001", initial_manifest)
    bucket.put_object(
        "production/index/current.json",
        canonical_json(current),
        headers={"x-oss-forbid-overwrite": "true"},
    )
    target = signed_pointer(secret, "release-0002", initial_manifest, "release-0001")

    with pytest.raises(RuntimeError, match="CAS冲突"):
        switch_pointer_cas(
            bucket,
            "production/index/current.json",
            target,
            expected_release_id="release-stale",
            allow_initial=False,
        )


def test_pointer_cas_uses_immutable_transition_claim() -> None:
    secret = b"a" * 48
    bucket = FakeBucket()
    manifest = b"{}\n"
    current = signed_pointer(secret, "release-0001", manifest)
    bucket.put_object(
        "production/index/current.json",
        canonical_json(current),
        headers={"x-oss-forbid-overwrite": "true"},
    )
    target = signed_pointer(secret, "release-0002", manifest, "release-0001")

    assert (
        switch_pointer_cas(
            bucket,
            "production/index/current.json",
            target,
            expected_release_id="release-0001",
            allow_initial=False,
        )
        == "switched"
    )
    transition_key = "production/index/transitions/release-0001.json"
    transition = json.loads(bucket.objects[transition_key].payload)
    assert transition["expected_release_id"] == "release-0001"
    assert transition["target_release_id"] == "release-0002"
    assert all(
        "If-Match" not in remote.headers
        for remote in bucket.objects.values()
    )


def test_pointer_cas_rejects_conflicting_transition_claim() -> None:
    secret = b"a" * 48
    bucket = FakeBucket()
    manifest = b"{}\n"
    current = signed_pointer(secret, "release-0001", manifest)
    bucket.put_object(
        "production/index/current.json",
        canonical_json(current),
        headers={"x-oss-forbid-overwrite": "true"},
    )
    first_target = signed_pointer(
        secret,
        "release-0002",
        manifest,
        "release-0001",
    )
    assert (
        switch_pointer_cas(
            bucket,
            "production/index/current.json",
            first_target,
            expected_release_id="release-0001",
            allow_initial=False,
        )
        == "switched"
    )

    bucket.objects["production/index/current.json"] = FakeRemote(
        canonical_json(current),
        {},
        "etag-restored-for-race",
    )
    other_target = signed_pointer(
        secret,
        "release-0003",
        manifest,
        "release-0001",
    )
    with pytest.raises(RuntimeError, match="转换声明冲突"):
        switch_pointer_cas(
            bucket,
            "production/index/current.json",
            other_target,
            expected_release_id="release-0001",
            allow_initial=False,
        )


def test_release_object_whitelist_rejects_extra_remote_file(monkeypatch) -> None:
    prefix = "production/index/releases/release-0001"
    keys = [
        *(f"{prefix}/{name}" for name in PRODUCTION_FILES),
        f"{prefix}/release.json",
        f"{prefix}/release.sig",
        f"{prefix}/unexpected.bin",
    ]
    monkeypatch.setattr(
        "scripts.publish_index_to_oss.oss2.ObjectIterator",
        lambda bucket, prefix: [SimpleNamespace(key=key) for key in keys],
    )
    with pytest.raises(RuntimeError, match="额外"):
        verify_release_object_whitelist(object(), prefix)


def test_new_release_uploads_signed_documents_before_whitelist_check(
    tmp_path: Path,
    monkeypatch,
) -> None:
    index_dir = tmp_path / "index"
    index_dir.mkdir()
    for name in PRODUCTION_FILES:
        path = index_dir / name
        if path.suffix == ".sqlite3":
            if name == "knowledge_content.sqlite3":
                create_valid_index(path)
            else:
                with sqlite3.connect(path) as connection:
                    connection.execute("CREATE TABLE fixture(id INTEGER PRIMARY KEY)")
        else:
            path.write_bytes(name.encode())
    bucket = FakeBucket()
    checked: list[str] = []

    def assert_complete_release(_bucket, release_prefix: str) -> None:
        assert f"{release_prefix}/release.json" in bucket.objects
        assert f"{release_prefix}/release.sig" in bucket.objects
        checked.append(release_prefix)

    monkeypatch.setattr(publish_module, "build_bucket", lambda: bucket)
    monkeypatch.setattr(
        publish_module,
        "verify_release_object_whitelist",
        assert_complete_release,
    )
    monkeypatch.setenv("JIAOTANG_OSS_RELEASE_SIGNING_SECRET", "s" * 48)
    monkeypatch.setattr(
        "sys.argv",
        [
            "publish_index_to_oss.py",
            "--index-dir",
            str(index_dir),
            "--allow-initial-current",
            "--lock-file",
            str(tmp_path / "publish.lock"),
        ],
    )

    publish_module.main()

    assert len(checked) == 1
    pointer = json.loads(bucket.objects["production/index/current.json"].payload)
    assert pointer["release_id"].startswith("index-")


def test_empty_bucket_first_publish_recovers_from_interrupted_upload(
    tmp_path: Path,
    monkeypatch,
) -> None:
    index_dir = tmp_path / "index"
    index_dir.mkdir()
    for name in PRODUCTION_FILES:
        path = index_dir / name
        if path.suffix == ".sqlite3":
            if name == "knowledge_content.sqlite3":
                create_valid_index(path)
            else:
                with sqlite3.connect(path) as connection:
                    connection.execute("CREATE TABLE fixture(id INTEGER PRIMARY KEY)")
        else:
            path.write_bytes(name.encode())

    class FlakyBucket(FakeBucket):
        def __init__(self) -> None:
            super().__init__()
            self.file_attempts = 0
            self.fail_once = True

        def put_object_from_file(
            self,
            key: str,
            source: str,
            headers: dict[str, str],
        ):
            self.file_attempts += 1
            if self.fail_once and self.file_attempts == 2:
                self.fail_once = False
                raise RuntimeError("simulated interrupted upload")
            return super().put_object_from_file(key, source, headers)

    bucket = FlakyBucket()

    def assert_complete_release(_bucket, release_prefix: str) -> None:
        expected = {
            *(f"{release_prefix}/{name}" for name in PRODUCTION_FILES),
            f"{release_prefix}/release.json",
            f"{release_prefix}/release.sig",
        }
        assert set(bucket.objects) >= expected

    monkeypatch.setattr(publish_module, "build_bucket", lambda: bucket)
    monkeypatch.setattr(
        publish_module,
        "verify_release_object_whitelist",
        assert_complete_release,
    )
    monkeypatch.setenv("JIAOTANG_OSS_RELEASE_SIGNING_SECRET", "s" * 48)
    argv = [
        "publish_index_to_oss.py",
        "--index-dir",
        str(index_dir),
        "--allow-initial-current",
        "--lock-file",
        str(tmp_path / "publish.lock"),
    ]
    monkeypatch.setattr("sys.argv", argv)

    with pytest.raises(RuntimeError, match="simulated interrupted"):
        publish_module.main()
    assert "production/index/current.json" not in bucket.objects

    monkeypatch.setattr("sys.argv", argv)
    publish_module.main()

    pointer = json.loads(bucket.objects["production/index/current.json"].payload)
    assert pointer["release_id"].startswith("index-")


def test_signed_release_supports_key_rotation_and_strict_whitelist() -> None:
    old_secret = b"old-" * 12
    new_secret = b"new-" * 12
    release_id = "release-20260731"
    files = [
        {"name": name, "size": 1, "sha256": "a" * 64, "crc64": "1"}
        for name in PRODUCTION_FILES
    ]
    release = {
        "schema": MANIFEST_SCHEMA,
        "release_id": release_id,
        "created_at": "2026-07-31T00:00:00Z",
        "previous_release_id": "release-20260730",
        "files": files,
        "file_whitelist": list(PRODUCTION_FILES),
    }
    body, signature = signed_document(release, old_secret)
    pointer = signed_pointer(old_secret, release_id, body, "release-20260730")
    verified_pointer = verify_pointer(
        canonical_json(pointer),
        [new_secret, old_secret],
    )
    assert (
        verify_release(
            body,
            signature,
            verified_pointer,
            [new_secret, old_secret],
        )["release_id"]
        == release_id
    )

    altered = dict(release)
    altered["file_whitelist"] = [*PRODUCTION_FILES, "unexpected.bin"]
    altered_body, altered_signature = signed_document(altered, old_secret)
    altered_pointer = verify_pointer(
        canonical_json(signed_pointer(old_secret, release_id, altered_body)),
        [old_secret],
    )
    with pytest.raises(RuntimeError, match="白名单"):
        verify_release(
            altered_body,
            altered_signature,
            altered_pointer,
            [old_secret],
        )


def create_valid_index(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        for table, minimum in REQUIRED_STRUCTURED_TABLES.items():
            connection.execute(f'CREATE TABLE "{table}"(id INTEGER PRIMARY KEY)')
            connection.executemany(
                f'INSERT INTO "{table}"(id) VALUES(?)',
                [(value,) for value in range(1, minimum + 1)],
            )
        connection.commit()
    finally:
        connection.close()


def create_local_release(index_dir: Path, release_id: str) -> None:
    release_dir = index_dir / "releases" / release_id
    release_dir.mkdir(parents=True)
    rows = []
    for name in PRODUCTION_FILES:
        path = release_dir / name
        if name == "knowledge_content.sqlite3":
            create_valid_index(path)
        else:
            path.write_bytes(name.encode())
        rows.append(
            {
                "name": name,
                "size": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "crc64": "0",
            }
        )
    (release_dir / "release.json").write_text(
        json.dumps(
            {
                "schema": MANIFEST_SCHEMA,
                "release_id": release_id,
                "files": rows,
                "file_whitelist": list(PRODUCTION_FILES),
            }
        ),
        encoding="utf-8",
    )


def test_local_current_previous_switch_and_rollback(tmp_path: Path) -> None:
    index_dir = tmp_path / "index"
    index_dir.mkdir()
    create_local_release(index_dir, "release-0001")
    create_local_release(index_dir, "release-0002")

    activate_release(index_dir, "release-0001")
    assert release_id_from_link(index_dir / "current") == "release-0001"
    assert release_id_from_link(index_dir / "previous") is None
    assert local_generation_valid(index_dir, "release-0001")
    activate_release(index_dir, "release-0002")
    assert release_id_from_link(index_dir / "current") == "release-0002"
    assert release_id_from_link(index_dir / "previous") == "release-0001"
    old, restored = rollback_release(index_dir)
    assert (old, restored) == ("release-0002", "release-0001")
    assert release_id_from_link(index_dir / "current") == "release-0001"
    assert os.readlink(index_dir / "knowledge_content.sqlite3") == (
        "current/knowledge_content.sqlite3"
    )


def test_metadata_health_check_avoids_deep_hash_and_sqlite_scan(
    tmp_path: Path,
    monkeypatch,
) -> None:
    index_dir = tmp_path / "index"
    index_dir.mkdir()
    create_local_release(index_dir, "release-0001")

    def unexpected_deep_check(*_args, **_kwargs):
        raise AssertionError("health path must not run deep content validation")

    monkeypatch.setattr(refresh_module, "sha256_file", unexpected_deep_check)
    monkeypatch.setattr(refresh_module, "valid_index", unexpected_deep_check)

    assert local_generation_metadata_valid(index_dir, "release-0001")
    readme = index_dir / "releases" / "release-0001" / "README.md"
    readme.write_bytes(readme.read_bytes() + b"changed-size")
    assert not local_generation_metadata_valid(index_dir, "release-0001")


def test_interrupted_release_download_removes_only_transaction_staging(
    tmp_path: Path,
) -> None:
    class InterruptedBucket:
        def __init__(self) -> None:
            self.calls = 0

        def get_object_to_file(self, key: str, target: str) -> None:
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("network interrupted")
            Path(target).write_bytes(b"partial")

    release = {
        "release_id": "release-interrupted",
        "files": [
            {"name": "README.md", "size": 7, "sha256": "0" * 64, "crc64": "0"},
            {"name": "manifest.jsonl", "size": 7, "sha256": "0" * 64, "crc64": "0"},
        ],
    }
    staging = tmp_path / ".release-interrupted.staging"
    with pytest.raises(RuntimeError):
        download_release(
            InterruptedBucket(),
            "production",
            release,
            staging,
        )
    assert not staging.exists()
    assert len(list(tmp_path.glob(".release-interrupted.staging.failed-download.*"))) == 1


def test_existing_staging_is_not_modified_or_removed(
    tmp_path: Path,
) -> None:
    index_dir = tmp_path / "index"
    releases = index_dir / "releases"
    staging = releases / ".release-stable.123.staging"
    staging.mkdir(parents=True)
    marker = staging / "owner-review-required.txt"
    marker.write_text("do not touch", encoding="utf-8")

    with pytest.raises(RuntimeError, match="未获授权处置"):
        require_unused_staging(staging)

    assert marker.read_text(encoding="utf-8") == "do not touch"
    assert staging.is_dir()


def test_legacy_root_bootstrap_is_read_only_and_blocks_different_release(
    tmp_path: Path,
) -> None:
    index_dir = tmp_path / "index"
    index_dir.mkdir()
    create_local_release(index_dir, "release-0001")
    create_local_release(index_dir, "release-0002")
    source = index_dir / "releases" / "release-0001"
    for name in PRODUCTION_FILES:
        (index_dir / name).write_bytes((source / name).read_bytes())

    activate_release(index_dir, "release-0001")

    assert release_id_from_link(index_dir / "current") == "release-0001"
    assert all(
        (index_dir / name).is_file() and not (index_dir / name).is_symlink()
        for name in PRODUCTION_FILES
    )
    with pytest.raises(RuntimeError, match="未获授权迁移或处置"):
        activate_release(index_dir, "release-0002")


def test_release_link_outside_release_root_is_rejected(tmp_path: Path) -> None:
    link = tmp_path / "current"
    link.symlink_to("../outside/release-0001")
    assert release_id_from_link(link) is None


def test_local_generation_rejects_manifest_with_omitted_files(
    tmp_path: Path,
) -> None:
    index_dir = tmp_path / "index"
    index_dir.mkdir()
    create_local_release(index_dir, "release-0001")
    manifest_path = (
        index_dir / "releases" / "release-0001" / "release.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"] = manifest["files"][:-1]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert not local_generation_valid(index_dir, "release-0001")


def test_refresh_is_fail_closed_unless_allow_stale_is_explicit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    index_dir = tmp_path / "index"
    status = tmp_path / "status.json"
    index_dir.mkdir()
    create_local_release(index_dir, "release-stable")
    activate_release(index_dir, "release-stable")
    monkeypatch.setenv("JIAOTANG_INDEX_DIR", str(index_dir))
    monkeypatch.setenv("JIAOTANG_OSS_INDEX_CACHE_STATUS", str(status))
    monkeypatch.setenv("JIAOTANG_OSS_RELEASE_SIGNING_SECRET", "s" * 48)
    monkeypatch.setattr(
        refresh_module,
        "build_bucket",
        lambda: (_ for _ in ()).throw(RuntimeError("OSS unavailable")),
    )

    monkeypatch.setattr(
        "sys.argv",
        ["refresh_index_from_oss.py"],
    )
    with pytest.raises(RuntimeError, match="OSS unavailable"):
        refresh_module.main()
    assert json.loads(status.read_text())["status"] == "异常"

    monkeypatch.setattr(
        "sys.argv",
        ["refresh_index_from_oss.py", "--allow-stale"],
    )
    assert refresh_module.main() == 0
    assert json.loads(status.read_text())["status"] == "降级"
