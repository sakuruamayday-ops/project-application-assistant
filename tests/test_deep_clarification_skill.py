from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "deep-clarification"


def test_deep_clarification_is_business_facing_and_preserves_license():
    skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    interface = (SKILL_DIR / "agents" / "openai.yaml").read_text(encoding="utf-8")
    license_text = (SKILL_DIR / "LICENSE-MIT.txt").read_text(encoding="utf-8")

    assert 'display_name: "深度澄清"' in interface
    assert "开始深度澄清" in skill
    assert "直接继续" in skill
    assert "当前可决定集合中的全部问题" in skill
    assert "每题编号" in skill and "推荐答案" in skill
    assert "事实，由助手自行核验" in skill
    assert "共同理解与执行清单" in skill
    assert "用户尚未确认时，不得进入实质实施" in skill
    assert "普通查询、闲聊、简单改写" in skill
    assert "885e2ca4d842d139e9aef4e48d366c63cb1b8013" in skill
    assert "Copyright (c) 2026 Matt Pocock" in license_text
    assert "MIT License" in license_text


def test_deep_clarification_does_not_bundle_upstream_developer_skills():
    formal = {
        path.parent.name
        for path in (ROOT / "skills").glob("*/SKILL.md")
    }
    assert "deep-clarification" in formal
    assert not {"grill-me", "grilling", "grill-with-docs", "domain-modeling"} & formal
