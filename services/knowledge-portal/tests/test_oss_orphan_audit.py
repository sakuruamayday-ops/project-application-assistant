from types import SimpleNamespace

import scripts.audit_oss_orphans as audit_module
from scripts.audit_oss_orphans import (
    UNMAPPED_ORPHAN_LABEL,
    classify,
    list_objects_page_with_network_retry,
    list_remote_objects,
)


def test_orphan_with_historical_path_is_auditable() -> None:
    assert classify([], [], ["50_名单与对标/历史名单.pdf"]) == (
        "历史清单路径已退出当前版本"
    )


def test_orphan_without_local_evidence_is_unmapped() -> None:
    assert classify([], [], []) == UNMAPPED_ORPHAN_LABEL


def test_old_content_version_is_auditable() -> None:
    assert classify(
        [],
        ["50_名单与对标/名单.json -> replacement-sha"],
        ["50_名单与对标/名单.json"],
    ) == "当前文件的旧内容版本"


def test_list_objects_page_retries_transient_network_error(monkeypatch) -> None:
    class FakeBucket:
        def __init__(self) -> None:
            self.calls = 0

        def list_objects(self, **kwargs: object) -> object:
            self.calls += 1
            if self.calls < 3:
                raise audit_module.oss2.exceptions.RequestError(
                    RuntimeError("temporary proxy disconnect")
                )
            return kwargs

    fake_bucket = FakeBucket()
    monkeypatch.setattr(audit_module, "oss_bucket", lambda: fake_bucket)
    monkeypatch.setattr(audit_module.time, "sleep", lambda _: None)

    result = list_objects_page_with_network_retry(
        "production/knowledge/objects/",
        "marker",
        attempts=3,
    )
    assert result["marker"] == "marker"
    assert result["max_keys"] == 1000
    assert fake_bucket.calls == 3


def test_remote_object_listing_resumes_from_next_marker(monkeypatch) -> None:
    pages = {
        "": SimpleNamespace(
            object_list=[
                SimpleNamespace(key="prefix/aa", size=10, last_modified=1)
            ],
            is_truncated=True,
            next_marker="prefix/aa",
        ),
        "prefix/aa": SimpleNamespace(
            object_list=[
                SimpleNamespace(key="prefix/bb", size=20, last_modified=2)
            ],
            is_truncated=False,
            next_marker="",
        ),
    }
    monkeypatch.setattr(
        audit_module,
        "list_objects_page_with_network_retry",
        lambda prefix, marker: pages[marker],
    )

    assert list_remote_objects("prefix/") == [
        {
            "object_key": "prefix/aa",
            "sha256": "aa",
            "size_bytes": 10,
            "last_modified_epoch": 1,
        },
        {
            "object_key": "prefix/bb",
            "sha256": "bb",
            "size_bytes": 20,
            "last_modified_epoch": 2,
        },
    ]
