from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "skills/_runtime/enterprise-source-fallback.md"
OPERATIONAL_SKILLS = (
    "project-application-assistant",
    "project-task-router",
    "enterprise-profile",
    "enterprise-panorama-analysis",
    "project-feasibility",
    "peer-benchmarking",
    "high-tech-enterprise-application-drafting",
    "patent-router",
    "local-knowledge-retrieval",
)


def test_enterprise_source_protocol_is_finite_and_preserves_partial_delivery() -> None:
    content = PROTOCOL.read_text(encoding="utf-8")

    assert "天眼查 → 企查查 → 用户当前提供且可核验的资料 → 政府或法定机构官方来源" in content
    assert "最多重试一次" in content
    assert "取消授权" in content
    assert "不重试" in content
    assert "待完善" in content
    assert "未核验" in content
    assert "不得因校验失败自动重新开始整条采集链" in content


def test_every_operational_enterprise_data_skill_uses_shared_protocol() -> None:
    for skill in OPERATIONAL_SKILLS:
        content = (ROOT / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
        assert "enterprise-source-fallback.md" in content, skill
