from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "deep-clarification"


def test_deep_clarification_is_business_facing_and_preserves_license():
    skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    interface = (SKILL_DIR / "agents" / "openai.yaml").read_text(encoding="utf-8")
    license_text = (SKILL_DIR / "LICENSE-MIT.txt").read_text(encoding="utf-8")

    assert 'display_name: "深度澄清"' in interface
    assert "用户显式选择本技能时进入访谈" in skill
    assert "allow_implicit_invocation: false" in interface
    assert "每轮集中提出当前能够决定的问题" in skill
    assert "每题编号" in skill and "推荐及理由" in skill
    assert "按推荐继续" in skill and "跳过澄清" in skill and "取消任务" in skill
    assert "低影响默认值继续" in skill
    assert "其他部分照常完成" in skill
    assert "事实优先从当前会话、工作区和可用工具核验" in skill
    assert "共同理解与执行清单" in skill
    assert "按用户当前指令及已有授权推进" in skill
    assert "客户端建议和选择状态由客户端管理" in skill
    assert "普通任务沿当前目标继续" in skill
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
