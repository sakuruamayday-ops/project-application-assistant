import base64
import hashlib
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor
from threading import Event, local

import pytest
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from test_portal import load_app


def make_desktop_projection(
    path,
    *,
    version="1.6.6",
    private_key=None,
    description="Fixture skill.",
):
    from app import skill_update_feed

    key = private_key or Ed25519PrivateKey.generate()
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    skill_update_feed.CLIENT_SKILL_UPDATE_PUBLIC_KEY_SHA256 = hashlib.sha256(
        public_pem
    ).hexdigest()
    suite = {
        "release": {"version": version, "tag": f"V{version}"},
        "skills": ["fixture-skill"],
    }
    suite_bytes = (json.dumps(suite, ensure_ascii=False) + "\n").encode("utf-8")
    skill_bytes = (
        "---\nname: fixture-skill\ndescription: " + description + "\n---\n"
    ).encode("utf-8")
    declared = {
        "fixture-skill/SKILL.md": hashlib.sha256(skill_bytes).hexdigest(),
        "suite-manifest.json": hashlib.sha256(suite_bytes).hexdigest(),
    }
    index_bytes = (
        json.dumps(
            {
                "schemaVersion": 1,
                "productId": "cn.gongchuang.enterprise-assistant",
                "skillBundleVersion": version,
                "sourceReleaseTag": f"V{version}",
                "signingTier": "formal",
                "skills": ["fixture-skill"],
                "files": declared,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")
    receipt = {
        "schemaVersion": 1,
        "skillBundleVersion": version,
        "projectionPurpose": "independent-update",
        "signingTier": "formal",
        "indexSha256": hashlib.sha256(index_bytes).hexdigest(),
        "publicKeySha256": hashlib.sha256(public_pem).hexdigest(),
        "fileCount": len(declared),
        "skillCount": 1,
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("skill-bundle-index.json", index_bytes)
        archive.writestr(
            "skill-bundle-index.sig",
            base64.b64encode(key.sign(index_bytes)).decode("ascii") + "\n",
        )
        archive.writestr("skill-bundle-index.pub.pem", public_pem)
        archive.writestr("staging-receipt.json", json.dumps(receipt))
        archive.writestr("skills/suite-manifest.json", suite_bytes)
        archive.writestr("skills/fixture-skill/SKILL.md", skill_bytes)
    return key


def test_publish_skill_update_feed_creates_client_manifest(tmp_path):
    from app.skill_update_feed import publish_skill_update_feed

    source = tmp_path / "desktop-projection.zip"
    make_desktop_projection(source)
    release_dir = tmp_path / "updates"

    receipt = publish_skill_update_feed(
        release_directory=release_dir,
        archive=source,
        version="V1.6.6",
        release_notes="更新共创通用技能包。",
    )

    assert receipt.version == "1.6.6"
    assert receipt.archive_path.read_bytes() == source.read_bytes()
    manifest = json.loads(receipt.manifest_path.read_text(encoding="utf-8"))
    assert manifest == {
        "schemaVersion": 1,
        "productId": "cn.gongchuang.enterprise-assistant",
        "skillBundleVersion": "1.6.6",
        "sourceReleaseTag": "V1.6.6",
        "archiveUrl": "./Gongchuang-Enterprise-Assistant-Skills-V1.6.6.zip",
        "releaseNotes": "更新共创通用技能包。",
    }


def test_publish_skill_update_feed_rejects_reusing_version_for_other_bytes(tmp_path):
    from app.skill_update_feed import publish_skill_update_feed

    release_dir = tmp_path / "updates"
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    key = make_desktop_projection(first)
    make_desktop_projection(second, private_key=key)
    with zipfile.ZipFile(second, "a") as archive:
        archive.comment = b"different valid archive bytes"
    publish_skill_update_feed(
        release_directory=release_dir,
        archive=first,
        version="1.6.6",
        release_notes="第一版",
    )

    try:
        publish_skill_update_feed(
            release_directory=release_dir,
            archive=second,
            version="1.6.6",
            release_notes="不应覆盖",
        )
    except ValueError as error:
        assert "不同内容" in str(error)
    else:
        raise AssertionError("同版本不同内容必须被拒绝")


def test_publish_skill_update_feed_rejects_downgrade_and_generic_zip(tmp_path):
    from app.skill_update_feed import publish_skill_update_feed

    release_dir = tmp_path / "updates"
    current = tmp_path / "current.zip"
    key = make_desktop_projection(current, version="1.6.7")
    publish_skill_update_feed(
        release_directory=release_dir,
        archive=current,
        version="1.6.7",
        release_notes="current",
    )
    old = tmp_path / "old.zip"
    make_desktop_projection(old, version="1.6.6", private_key=key)
    try:
        publish_skill_update_feed(
            release_directory=release_dir,
            archive=old,
            version="1.6.6",
            release_notes="old",
        )
    except ValueError as error:
        assert "降级" in str(error)
    else:
        raise AssertionError("older client update must not replace latest.json")

    generic = tmp_path / "generic.zip"
    with zipfile.ZipFile(generic, "w") as archive:
        archive.writestr("bundle/skills/suite-manifest.json", "{}")
    try:
        publish_skill_update_feed(
            release_directory=tmp_path / "generic-feed",
            archive=generic,
            version="1.6.8",
            release_notes="wrong package type",
        )
    except ValueError as error:
        assert "skill-bundle-index.json" in str(error)
    else:
        raise AssertionError("generic skill ZIP must not enter the client feed")


def test_concurrent_versions_cannot_overwrite_a_newer_latest(tmp_path, monkeypatch):
    from app import skill_update_feed

    newer = tmp_path / "newer.zip"
    older = tmp_path / "older.zip"
    key = make_desktop_projection(newer, version="1.6.18")
    make_desktop_projection(older, version="1.6.17", private_key=key)
    release_dir = tmp_path / "updates"
    newer_at_commit = Event()
    allow_commit = Event()
    older_contended = Event()
    publisher = local()
    original_write = skill_update_feed._atomic_json
    original_validate = skill_update_feed.validate_skill_update_archive
    original_lock = skill_update_feed.fcntl.flock

    def pause_newer(payload, destination):
        if payload["skillBundleVersion"] == "1.6.18":
            newer_at_commit.set()
            assert allow_commit.wait(5), "test did not release newer publisher"
        original_write(payload, destination)

    def observe_validation(archive, version):
        result = original_validate(archive, version)
        publisher.version = version
        return result

    def observe_contention(descriptor, operation):
        if publisher.version == "1.6.17":
            # The loser must reach a held lock before the winner is released.
            # Merely observing validation leaves the downgrade race untested.
            with pytest.raises(BlockingIOError):
                original_lock(descriptor, operation | skill_update_feed.fcntl.LOCK_NB)
            older_contended.set()
        return original_lock(descriptor, operation)

    monkeypatch.setattr(skill_update_feed, "_atomic_json", pause_newer)
    monkeypatch.setattr(skill_update_feed, "validate_skill_update_archive", observe_validation)
    monkeypatch.setattr(skill_update_feed.fcntl, "flock", observe_contention)

    def publish(archive, version):
        return skill_update_feed.publish_skill_update_feed(
            release_directory=release_dir, archive=archive,
            version=version, release_notes=version,
        )

    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(publish, newer, "1.6.18")
        try:
            assert newer_at_commit.wait(5)
            second = workers.submit(publish, older, "1.6.17")
            assert older_contended.wait(5), "older publisher did not contend for latest"
        finally:
            allow_commit.set()
        assert first.result(timeout=5).version == "1.6.18"
        with pytest.raises(ValueError, match="降级"):
            second.result(timeout=5)

    manifest = json.loads((release_dir / "latest.json").read_text())
    assert manifest["skillBundleVersion"] == "1.6.18"
    # A rejected contender must release the lock; retrying the winner remains valid.
    assert publish(newer, "1.6.18").version == "1.6.18"


def test_validate_skill_update_archive_rejects_unsigned_packaging_resources(
    tmp_path,
):
    from app.skill_update_feed import validate_skill_update_archive

    archive_path = tmp_path / "desktop-projection.zip"
    make_desktop_projection(archive_path)
    # The V0.4.1 updater permits only four signed root companions and
    # `skills/**`. Bundled-only resources must never enter an update archive.
    with zipfile.ZipFile(archive_path, "a") as archive:
        archive.writestr("config/common.yaml", "provider: bundled-only\n")

    with pytest.raises(ValueError, match="签名索引文件集合"):
        validate_skill_update_archive(archive_path, "1.6.6")


def write_skill_update_feed(tmp_path, monkeypatch):
    release_dir = tmp_path / "skill-update-releases"
    release_dir.mkdir()
    monkeypatch.setenv("JIAOTANG_SKILL_UPDATE_RELEASE_DIR", str(release_dir))
    archive_name = "Gongchuang-Enterprise-Assistant-Skills-V1.6.7.zip"
    archive = b"signed-skill-suite-fixture"
    manifest = {
        "schemaVersion": 1,
        "productId": "cn.gongchuang.enterprise-assistant",
        "skillBundleVersion": "1.6.7",
        "sourceReleaseTag": "V1.6.7",
        "archiveUrl": f"./{archive_name}",
        "releaseNotes": "技能包独立更新测试。",
    }
    (release_dir / archive_name).write_bytes(archive)
    (release_dir / "latest.json").write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )
    return release_dir, archive_name, archive, manifest


def test_skill_update_feed_and_archive_are_public(tmp_path, monkeypatch):
    _, archive_name, archive, manifest = write_skill_update_feed(tmp_path, monkeypatch)
    module = load_app(tmp_path)

    with TestClient(module.app) as client:
        latest = client.get("/skill-updates/latest.json")
        assert latest.status_code == 200
        assert latest.json() == manifest
        assert latest.headers["cache-control"] == "public, no-cache"
        assert latest.headers["x-content-type-options"] == "nosniff"

        downloaded = client.get(f"/skill-updates/{archive_name}")
        assert downloaded.status_code == 200
        assert downloaded.content == archive
        assert downloaded.headers["content-type"] == "application/zip"
        assert "immutable" in downloaded.headers["cache-control"]


def test_skill_update_missing_assets_return_404_without_redirect(tmp_path, monkeypatch):
    release_dir = tmp_path / "skill-update-releases"
    release_dir.mkdir()
    old_release_dir = tmp_path / "skill-releases"
    old_release_dir.mkdir()
    (old_release_dir / "latest.json").write_text("{}", encoding="utf-8")
    (old_release_dir / "missing.zip").write_bytes(b"wrong release directory")
    monkeypatch.setenv("JIAOTANG_SKILL_UPDATE_RELEASE_DIR", str(release_dir))
    module = load_app(tmp_path)

    assert module.SKILL_UPDATE_RELEASE_DIR == release_dir
    assert module.SKILL_UPDATE_RELEASE_DIR != module.SKILL_RELEASE_DIR

    with TestClient(module.app) as client:
        for path in (
            "/skill-updates/latest.json",
            "/skill-updates/missing.zip",
        ):
            response = client.get(path, follow_redirects=False)
            assert response.status_code == 404
            assert "location" not in response.headers
            assert response.headers["content-type"].startswith("application/json")


def test_skill_update_feed_rejects_traversal_symlinks_and_other_types(
    tmp_path,
    monkeypatch,
):
    release_dir, _, _, _ = write_skill_update_feed(tmp_path, monkeypatch)
    outside_archive = tmp_path / "outside.zip"
    outside_archive.write_bytes(b"outside")
    (release_dir / "linked.zip").symlink_to(outside_archive)
    module = load_app(tmp_path)

    with TestClient(module.app) as client:
        for path in (
            "/skill-updates/release.json",
            "/skill-updates/package.exe",
            "/skill-updates/subdir/package.zip",
            "/skill-updates/%2e%2e%2foutside.zip",
            "/skill-updates/linked.zip",
        ):
            response = client.get(path, follow_redirects=False)
            assert response.status_code == 404
            assert "location" not in response.headers

        manifest_path = release_dir / "latest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["archiveUrl"] = "../outside.zip"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        assert client.get("/skill-updates/latest.json").status_code == 503
