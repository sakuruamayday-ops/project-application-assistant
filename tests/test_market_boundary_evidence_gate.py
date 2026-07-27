import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
GATE = (
    SKILLS
    / "industry-positioning"
    / "references"
    / "market-boundary-and-substitution-gate.md"
)


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_project_thresholds_remain_distinct() -> None:
    text = GATE.read_text(encoding="utf-8")

    assert "10%以上，或国内细分市场占有率排名前三" in text
    assert "2025年浙江省隐形冠军" in text
    assert "全球细分市场占有率前十或全国前三" in text
    assert "2025年浙江省制造业单项冠军" in text
    assert "全球前五或全国前三" in text
    assert "国家制造业单项冠军现行管理基线" in text
    assert "全球市场占有率前三" in text
    assert "不采用“全球前三或国内第一”的全国统一门槛" in text


def test_classification_sources_have_explicit_roles() -> None:
    text = GATE.read_text(encoding="utf-8")

    assert "优先采用当期申请表要求的《国民经济行业分类》或《统计用产品分类目录》" in text
    assert "海关商品编码用于核对进出口统计口径" in text
    assert "不能代替项目指定的行业或产品分类" in text
    assert "行业标准和协会分类可用于解释行业惯例" in text
    assert "人为缩窄" in text


def test_substitution_evidence_is_strong_but_not_universally_mandatory() -> None:
    text = GATE.read_text(encoding="utf-8")

    for phrase in (
        "国外企业、产品或具体型号",
        "同口径性能矩阵",
        "客户验收",
        "第三方检测",
        "不得把第三方检测设为企业自述成立的前提",
        "不得反推日期",
    ):
        assert phrase in text
    assert "补短板" in text
    assert "锻长板" in text
    assert "填空白" in text
    assert "国产替代" in text


def test_2026_small_giant_does_not_require_third_party_market_share_proof() -> None:
    text = GATE.read_text(encoding="utf-8")

    assert "不再接收第三方证明材料" in text
    assert "《统计用产品分类目录》十位代码" in text
    assert "8ecbc1accb7b40fb9efa34bd62001259.pdf" in text


def test_project_skills_route_through_the_canonical_gate() -> None:
    industry = read("skills/industry-positioning/SKILL.md")
    sme = read("skills/sme-development-projects/SKILL.md")
    quality = read("skills/quality-brand-projects/SKILL.md")

    assert "references/market-boundary-and-substitution-gate.md" in industry
    assert "industry-positioning" in sme and "evidence-ledger" in sme
    assert "industry-positioning" in quality and "evidence-ledger" in quality


def test_manifest_and_call_graph_require_the_gate_dependencies() -> None:
    manifest = json.loads(read("skills/suite-manifest.json"))
    graph = json.loads(read("skills/skill-call-graph.json"))

    assert set(manifest["dependencies"]["sme-development-projects"]["required_skills"]) == {
        "industry-chain-foundation-matcher",
        "industry-positioning",
        "evidence-ledger",
    }
    assert set(manifest["dependencies"]["quality-brand-projects"]["required_skills"]) == {
        "industry-positioning",
        "evidence-ledger",
    }
    edges = {
        (item["from"], item["to"], item["type"])
        for item in graph["relations"]
    }
    for edge in (
        ("industry-positioning", "evidence-ledger", "requires"),
        ("sme-development-projects", "industry-positioning", "requires"),
        ("sme-development-projects", "evidence-ledger", "requires"),
        ("quality-brand-projects", "industry-positioning", "requires"),
        ("quality-brand-projects", "evidence-ledger", "requires"),
    ):
        assert edge in edges
