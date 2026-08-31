import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SLOT = (
    ROOT
    / "reports"
    / "evolution"
    / "V1.6.6-hightech-innovation-capability"
    / "merge-slot.json"
)


def historical_sha256(commit: str, relative: str) -> str:
    """Hash the immutable release blob instead of today's mutable working tree."""
    payload = subprocess.run(
        ["git", "show", f"{commit}:{relative}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    return hashlib.sha256(payload).hexdigest()


def test_v166_hightech_innovation_capability_merge_is_complete_and_hash_bound():
    slot = json.loads(SLOT.read_text(encoding="utf-8"))

    assert slot["release_tag"] == "V1.6.6"
    assert slot["target_skill"] == "high-tech-enterprise-application-drafting"
    assert slot["required_section_order"] == [
        "知识产权对竞争力",
        "科技成果转化",
        "研究开发组织管理",
        "管理与科技人员",
    ]
    assert slot["status"] == "merged", "等待当前任务返回脱敏差异路径和哈希，V1.6.6 禁止签名"
    assert slot["merged_commit"]
    assert slot["sanitized_diff"]
    assert slot["expected_files"]
    assert set(slot["expected_files"]) == set(slot["expected_sha256"])

    for relative in slot["expected_files"]:
        # 历史发布必须绑定当时的 Git 对象；核对当前文件会让每次正常演进都破坏旧版门禁。
        assert historical_sha256(slot["merged_commit"], relative) == slot["expected_sha256"][relative]

    acceptance = slot["acceptance"]
    assert acceptance == {
        "machine_regression": "pass",
        "full_suite_regression": "pass",
        "impact_graph_regenerated": True,
    }
