from pathlib import Path

import pytest

import scripts.upload_manifest_to_oss as upload_module
from scripts.upload_manifest_to_oss import (
    head_object_with_network_retry,
    load_allowed_paths,
    object_key_for,
)


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
        f"允许.pdf,{'a' * 64},true\n"
        f"阻止.pdf,{'b' * 64},false\n",
        encoding="utf-8",
    )
    assert load_allowed_paths(allowlist) == {("允许.pdf", "a" * 64)}


def test_verify_head_retries_transient_network_error(monkeypatch) -> None:
    class FakeBucket:
        def __init__(self) -> None:
            self.calls = 0

        def head_object(self, object_key: str) -> object:
            self.calls += 1
            if self.calls < 3:
                raise upload_module.oss2.exceptions.RequestError(
                    RuntimeError("temporary proxy disconnect")
                )
            return {"object_key": object_key}

    fake_bucket = FakeBucket()
    monkeypatch.setattr(upload_module, "bucket", lambda: fake_bucket)
    monkeypatch.setattr(upload_module.time, "sleep", lambda _: None)

    assert head_object_with_network_retry("production/object", attempts=3) == {
        "object_key": "production/object"
    }
    assert fake_bucket.calls == 3
