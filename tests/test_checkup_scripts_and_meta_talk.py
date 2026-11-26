from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "_core"))
sys.path.insert(0, str(ROOT / "skills" / "gov-project-checkup" / "scripts"))

import quality_gate  # noqa: E402
import split_application_sections as sas  # noqa: E402
import checkup_self_review as csr  # noqa: E402

SAMPLE = """一、企业基本情况
企业名称 示例精密传动有限公司
二、经济效益和经营情况
重要指标 2023年 2024年 2025年
三、专业化
四、精细化
五、特色化
上年度主导产品国际或国内细分市场占有率情况介绍：一、细分市场范围界定。产品属于精密传动部件。
主导产品出口额 100 万元
六、创新能力
研究领域已获得成果及应用情况（300字）：2025年由企业研发团队开展渗氮工艺攻关。
相关指标 2023年
七、产业链配套
说明（是否在细分领域实现关键技术首创等情况，300字以内）：示例精密传动通过梯度渗氮工艺突破寿命瓶颈。
主导产品是否为国内外知名大企业直接配套
八、主导产品所属领域
九、其他
企业总体情况简要介绍（2000字以内，不得含有企业名称或简称，请勿另附页）
公司成立于2010年，专注精密传动部件。
真实性声明
"""


def test_split_sections_base_year_and_anonymity(tmp_path: Path) -> None:
    f = tmp_path / "app.txt"
    f.write_text(SAMPLE, encoding="utf-8")
    res = sas.run(f, company="示例精密传动有限公司")
    assert res["base_year"]["Y"] == 2025 and res["base_year"]["Y-2"] == 2023
    assert not res["missing_sections"]
    gap = res["narrative_boxes"]["gap_filling_note"]
    assert gap["found"] and gap["anonymous_required"]
    assert any("示例" in x or "精密" in x for x in gap["name_leaks"])
    intro = res["narrative_boxes"]["summary_intro"]
    assert intro["found"] and not intro["name_leaks"]
    cli = subprocess.run([sys.executable, str(ROOT / "skills/gov-project-checkup/scripts/split_application_sections.py"), str(f), "--no-text"], capture_output=True, text=True)
    assert cli.returncode == 0 and '"Y": 2025' in cli.stdout


def test_checkup_self_review_gate() -> None:
    good = (
        "基准年 Y=2025年，适用工信部企业〔2026〕2号现行办法。\n"
        "壹、硬性指标核查\n近三年营业收入、主营占比、研发费用及有效I类知识产权逐项复算完毕，当前综合判定为达标。\n"
        "贰、财务穿透分析\n对照表内填报比例与绝对值推导比例完成逐年复算，资产负债表平衡且研发费率无明显算术冲突。\n"
        "叁、跨表一致性与知识产权关联\n核对经济效益表、专业化、创新能力与专利清单口径，确认核心发明专利与主导产品存在直接技术支撑关系。\n"
        "肆、双维度产业定位\n明确企业位于国家重点产业链核心基础部件环节，并对应工业六基关键基础零部件领域，未发现跨行业错挂。\n"
        "伍、四大重点文字板块诊断\n主导产品命名较清晰；补短板说明实际 286 字且匿名合规；产学研成果与企业总体情况介绍均已完成字数与逻辑核查。\n"
        "陆、红黄绿三级整改清单\n🔴 必须修改：补齐上年度研发费用专项审计报告；🟡 建议补强：细化细分市场占有率权威协会分母来源；🟢 保持优势：维持现有客户配套。\n"
    )
    assert csr.review(good)["ok"] is True
    shell_only = "基准年 Y=2025年\n壹、硬性指标 达标\n贰、财务穿透 复算\n叁、跨表一致性 知识产权\n肆、产业链 六基\n伍、主导产品 补短板 产学研 企业简介 286 字\n陆、🔴必须修改 🟡建议补强\n"
    assert csr.review(shell_only)["ok"] is False
    bad = good.replace("🟡 建议补强：细化细分市场占有率权威协会分母来源；", "") + "这段写得太致命"
    res = csr.review(bad)
    assert res["ok"] is False
    assert {f["item"] for f in res["failed"]} >= {"tiered_actions", "tone"}


def test_meta_self_talk_is_blocked() -> None:
    txt = "公司是国内领先的除鳞装备供应商。精确分母待行业协会数据核定后填入。本节用钢铁产量与酸洗替代两类依据来刻画规模。"
    res = quality_gate.audit_formal_text(txt)
    assert any(e["rule"] == "meta_self_talk" for e in res["errors"])
    formula_talk = quality_gate.audit_formal_text("占有率数值以经审计主导产品收入与同口径市场规模直接除算，不作估算。分母口径与第一段一致。")
    assert any(e["rule"] == "meta_self_talk" for e in formula_talk["errors"])
    clean = quality_gate.audit_formal_text("公司是国内领先的除鳞装备供应商，已建成数十条产线。")
    assert not any(e["rule"] == "meta_self_talk" for e in clean["errors"])
