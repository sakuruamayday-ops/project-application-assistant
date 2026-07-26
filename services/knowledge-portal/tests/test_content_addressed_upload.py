from pathlib import Path

import pytest

from scripts.upload_manifest_to_oss import load_allowed_paths, object_key_for


def test_sha256_layout_uses_one_content_addressed_key(monkeypatch) -> None:
    monkeypatch.setenv("JIAOTANG_OSS_PREFIX", "production")
    digest = "ab" * 32
    first = {
        "relative_path": "10_政策与目录/政策甲.pdf",
        "sha256": digest,
    }
    duplicate = {
        "relative_path": "90_待整理原始资料/政策甲副本.pdf",
        "sha256": digest,
    }

    expected = f"production/knowledge/objects/ab/{digest}"
    assert object_key_for(first, "sha256") == expected
    assert object_key_for(duplicate, "sha256") == expected


def test_relative_layout_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("JIAOTANG_OSS_PREFIX", "production")
    row = {"relative_path": "10_政策与目录/政策甲.pdf", "sha256": "ab" * 32}
    with pytest.raises(ValueError, match="旧相对路径上传已永久停用"):
        object_key_for(row, "relative")


def test_allowlist_only_returns_object_storage_rows(tmp_path: Path) -> None:
    allowlist = tmp_path / "upload_allowlist.csv"
    allowlist.write_text(
        "relative_path,sha256,object_storage_allowed\n"
        "允许.pdf,abc,true\n"
        "阻止.pdf,def,false\n",
        encoding="utf-8",
    )
    assert load_allowed_paths(allowlist) == {("允许.pdf", "abc")}
