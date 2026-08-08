from pathlib import Path


SCRIPT = (
    Path(__file__).parents[1]
    / "scripts"
    / "release_policy_increment.sh"
)


def test_policy_increment_release_immediately_syncs_local_index() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "[8/8] 即时同步本机活动索引并核验知识源完整性" in source
    assert '"${local_sync_script}" --apply --index-only' in source
    assert source.index("policy_increment_release.py\" finalize") < source.index(
        '"${local_sync_script}" --apply --index-only'
    )
    assert source.index("release_completed=1") < source.index(
        '"${local_sync_script}" --apply --index-only'
    )
    assert "launchctl" not in source
