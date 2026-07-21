from pathlib import Path
from types import SimpleNamespace

from scripts.oss_incremental_sync import open_state, sync_group


class FakeBucket:
    bucket_name = "test-bucket"

    def __init__(self) -> None:
        self.uploaded: list[str] = []
        self.copied: list[tuple[str, str]] = []

    def put_object_from_file(self, object_key: str, source: str, headers: dict[str, str]):
        self.uploaded.append(object_key)
        return SimpleNamespace(etag=f"upload-{Path(source).stat().st_size}")

    def copy_object(
        self,
        source_bucket_name: str,
        source_key: str,
        target_key: str,
        headers=None,
        params=None,
    ):
        assert source_bucket_name == self.bucket_name
        self.copied.append((source_key, target_key))
        return SimpleNamespace(etag="server-side-copy")


def test_sync_reuses_hash_and_prunes_missing_local_state(tmp_path: Path) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    staging = tmp_path / "staging"
    first_root.mkdir()
    second_root.mkdir()
    staging.mkdir()
    (first_root / "shared.txt").write_text("same content", encoding="utf-8")
    (second_root / "shared-copy.txt").write_text("same content", encoding="utf-8")
    bucket = FakeBucket()
    connection = open_state(tmp_path / "sync.sqlite3")
    try:
        first = sync_group(connection, bucket, "first", first_root, "archive/first", staging)
        second = sync_group(connection, bucket, "second", second_root, "archive/second", staging)
        assert first == (1, 0, 12)
        assert second == (1, 0, 0)
        assert bucket.uploaded == ["archive/first/shared.txt"]
        assert bucket.copied == [
            ("archive/first/shared.txt", "archive/second/shared-copy.txt")
        ]

        (first_root / "shared.txt").rename(tmp_path / "moved-shared.txt")
        assert sync_group(connection, bucket, "first", first_root, "archive/first", staging) == (0, 0, 0)
        remaining = connection.execute(
            "SELECT source_group, relative_path FROM synced_files ORDER BY source_group"
        ).fetchall()
        assert [(row["source_group"], row["relative_path"]) for row in remaining] == [
            ("second", "shared-copy.txt")
        ]
    finally:
        connection.close()
