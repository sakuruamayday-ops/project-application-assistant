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


def test_enterprise_source_protocol_reuses_success_and_preserves_partial_delivery() -> None:
    content = PROTOCOL.read_text(encoding="utf-8")

    for source in ("天眼查", "企查查", "本轮可核验资料", "政府或法定机构"):
        assert source in content
    assert "重试一次" in content
    assert "授权、401/403、额度、限流或工具受限" in content
    assert "直接沿替代来源继续" in content
    assert "成功结果直接复用" in content
    assert "待完善" in content and "未核验" in content
    assert "只复查失败或冲突的环节" in content



def test_every_operational_enterprise_data_skill_uses_shared_protocol() -> None:
    for skill in OPERATIONAL_SKILLS:
        content = (ROOT / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
        assert "enterprise-source-fallback.md" in content, skill
