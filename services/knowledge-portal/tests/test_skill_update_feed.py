import json

from fastapi.testclient import TestClient

from test_portal import load_app


def test_publish_skill_update_feed_creates_client_manifest(tmp_path):
    from app.skill_update_feed import publish_skill_update_feed

    source = tmp_path / "universal.zip"
    source.write_bytes(b"signed universal suite")
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
        "archiveUrl": "./gongchuang-research-institute-skills-V1.6.6.zip",
        "releaseNotes": "更新共创通用技能包。",
    }


def test_publish_skill_update_feed_rejects_reusing_version_for_other_bytes(tmp_path):
    from app.skill_update_feed import publish_skill_update_feed

    release_dir = tmp_path / "updates"
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
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


def write_skill_update_feed(tmp_path, monkeypatch):
    release_dir = tmp_path / "skill-update-releases"
    release_dir.mkdir()
    monkeypatch.setenv("JIAOTANG_SKILL_UPDATE_RELEASE_DIR", str(release_dir))
    archive_name = "gongchuang-skills-1.6.7.zip"
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
