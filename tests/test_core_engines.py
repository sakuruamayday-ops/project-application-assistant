from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from datetime import date
from pathlib import Path

import openpyxl
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = REPO_ROOT / "skills" / "_core"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

import doc_io  # noqa: E402
import fact_ledger  # noqa: E402
import kb_local  # noqa: E402
import quality_gate  # noqa: E402


def _make_minimal_docx(path: Path, paragraphs: list[str], table_rows: list[list[str]] | None = None) -> None:
    p_xml = "".join(
        f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" for text in paragraphs
    )
    t_xml = ""
    if table_rows:
        rows_xml = []
        for row in table_rows:
            cells_xml = "".join(
                f"<w:tc><w:p><w:r><w:t>{cell}</w:t></w:r></w:p></w:tc>" for cell in row
            )
            rows_xml.append(f"<w:tr>{cells_xml}</w:tr>")
        t_xml = f"<w:tbl>{''.join(rows_xml)}</w:tbl>"
    doc_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{p_xml}{t_xml}</w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("word/document.xml", doc_xml)


def _valid_uscc_from_prefix17(prefix17: str) -> str:
    total = sum(fact_ledger.USCC_CHARSET.index(prefix17[i]) * fact_ledger.USCC_WEIGHTS[i] for i in range(17))
    rem = 31 - (total % 31)
    chk = fact_ledger.USCC_CHARSET[0] if rem == 31 else fact_ledger.USCC_CHARSET[rem]
    return prefix17 + chk


# ---------- 1. kb_local ----------


def test_region_scope_resolution_non_hangzhou():
    r1 = kb_local.resolve_region_scope("宁波市鄞州区")
    assert r1["province"] == "浙江省"
    assert r1["city"] == "宁波市"
    assert r1["district"] == "鄞州区"
    assert r1["scopes"] == ["国家", "浙江省", "宁波市", "鄞州区"]

    r2 = kb_local.resolve_region_scope("浙江省绍兴市柯桥区某新材料企业")
    assert r2["city"] == "绍兴市"
    assert r2["district"] == "柯桥区"

    r3 = kb_local.resolve_region_scope("江苏省苏州市工业园区")
    assert r3["province"] == "江苏省"
    assert "国家" in r3["scopes"]


def test_deduplicate_recognitions_priority():
    raw = [
        {"enterprise_name": "测试公司", "project_name": "国家高新技术企业", "recognition_year": 2024, "product_name": "", "result": "拟认定"},
        {"enterprise_name": "测试公司", "project_name": "国家高新技术企业", "recognition_year": 2024, "product_name": "", "result": "正式认定"},
        {"enterprise_name": "测试公司", "project_name": "专精特新中小企业", "recognition_year": 2023, "product_name": "", "result": "正式认定"},
        {"enterprise_name": "测试公司", "project_name": "专精特新中小企业", "recognition_year": 2023, "product_name": "", "result": "已退出目录"},
    ]
    deduped = kb_local.deduplicate_recognitions(raw)
    assert len(deduped) == 2
    by_proj = {r["project_name"]: r for r in deduped}
    assert by_proj["国家高新技术企业"]["result"] == "正式认定"
    assert by_proj["专精特新中小企业"]["result"] == "已退出目录"


@pytest.mark.skipif(not kb_local.PROJECT_DB.is_file(), reason="local jiaotang.db unavailable")
def test_local_kb_enterprise_and_peers():
    ent = kb_local.query_enterprise("浙江申新新材料包装")
    assert ent["found"] is True
    assert "申新" in ent["enterprise"]["name"]
    assert len(ent["recognitions"]) <= ent["recognitions_raw_count"]

    peers = kb_local.query_peers("专精特新", region="杭州", limit=10)
    assert peers["deduped_count"] > 0
    assert peers["deduped_count"] <= peers["raw_count"]


@pytest.mark.skipif(not kb_local.RAG_QUERY_SH.is_file(), reason="local rag-query.sh unavailable")
def test_local_rag_false_positive_and_privacy_guard():
    fake = kb_local.search_local_rag("XYZ999888_NONEXISTENT_POLICY_TOKEN_42", limit=5)
    assert fake["count"] == 0

    real = kb_local.search_local_rag("高新技术企业认定管理工作指引", limit=5)
    assert real["count"] >= 1
    for item in real["results"]:
        assert not any(p in item["title"] for p in kb_local.PRIVACY_TITLE_TERMS)


# ---------- 2. fact_ledger ----------


def test_uscc_validation():
    valid = _valid_uscc_from_prefix17("91330108MA27X1234")
    ok, _ = fact_ledger.validate_uscc(valid)
    assert ok is True

    bad_check = valid[:-1] + ("0" if valid[-1] != "0" else "1")
    ok2, msg2 = fact_ledger.validate_uscc(bad_check)
    assert ok2 is False and "校验码" in msg2

    ok3, msg3 = fact_ledger.validate_uscc("91330108I123456789")
    assert ok3 is False and "禁止字符" in msg3

    ok4, _ = fact_ledger.validate_uscc("12345")
    assert ok4 is False


def test_financial_and_patent_validators():
    ok, _ = fact_ledger.validate_balance_sheet(1000, 400, 600)
    assert ok is True
    ok_bad, msg = fact_ledger.validate_balance_sheet(1000, 600, 999)
    assert ok_bad is False and "不平" in msg

    rd_high = fact_ledger.calc_rd_ratio(1200, 800)
    assert rd_high["ok"] is True
    assert rd_high["ratio_pct"] == 150.0
    assert len(rd_high["warnings"]) == 1

    gr = fact_ledger.calc_growth_metrics(100, 120, 144)
    assert gr["ok"] is True
    assert gr["cagr_2y_pct"] == 20.0
    assert gr["hightech_avg_growth_pct"] == 20.0

    # Patent checks
    p_mismatch = fact_ledger.validate_patent_item(
        {"patent_no": "ZL202320123456.7", "type": "发明专利", "filing_date": "2023-05-01"},
        as_of=date(2026, 6, 1),
    )
    assert any("倒挂" in i for i in p_mismatch)

    p_expired = fact_ledger.validate_patent_item(
        {"patent_no": "ZL201220123456.7", "type": "实用新型", "filing_date": "2012-03-01"},
        as_of=date(2026, 6, 1),
    )
    assert any("届满" in i for i in p_expired)

    p_transfer = fact_ledger.validate_patent_item(
        {"patent_no": "ZL202210123456.1", "type": "发明专利", "filing_date": "2022-03-01", "acquisition": "受让", "transfer_date": "2026-01-15"},
        as_of=date(2026, 6, 1),
    )
    assert any("不足1年" in i for i in p_transfer)

    p_ok = fact_ledger.validate_patent_item(
        {"patent_no": "ZL202310123456.1", "type": "发明专利", "filing_date": "2023-03-01", "acquisition": "自主研发"},
        as_of=date(2026, 6, 1),
    )
    assert p_ok == []


def test_blackboard_isolation_and_sensitive_blocker(tmp_path: Path):
    valid_uscc = _valid_uscc_from_prefix17("91330108MA27X1234")
    bb = fact_ledger.empty_blackboard("杭州测试科技有限公司", valid_uscc)
    bb["estimatedMetrics"].append({"snippet": "设计控制目标≤0.5ms", "suggestedValue": "0.5ms", "origin": "ai_design_target"})
    saved = fact_ledger.save_blackboard(tmp_path, bb)
    assert saved.is_file()

    # Sensitive write must be blocked
    bb_secret = fact_ledger.empty_blackboard("杭州测试科技有限公司", valid_uscc)
    bb_secret["financialFacts"]["note"] = "联系人手机 13812345678，密钥 sk-1234567890abcdef12345"
    with pytest.raises(ValueError, match="敏感凭据"):
        fact_ledger.save_blackboard(tmp_path, bb_secret)

    # Reconcile pending vs resolved
    r_pending = fact_ledger.reconcile_text_against_estimates(bb, "本系统满足设计控制目标≤0.5ms要求。")
    assert r_pending["pending_count"] == 1
    r_resolved = fact_ledger.reconcile_text_against_estimates(bb, "经第三方测试实测时延0.32ms。")
    assert r_resolved["pending_count"] == 0 and r_resolved["resolved_count"] == 1

    # CLI validate exit 0 vs exit 2
    ok_proc = subprocess.run(
        [sys.executable, str(CORE_DIR / "fact_ledger.py"), "validate", str(saved), "--check-uscc"],
        capture_output=True, text=True,
    )
    assert ok_proc.returncode == 0


# ---------- 3. doc_io ----------


def test_docx_diff_detects_moves_and_numeric_changes(tmp_path: Path):
    old_doc = tmp_path / "v1.docx"
    new_doc = tmp_path / "v2.docx"
    _make_minimal_docx(
        old_doc,
        [
            "一、企业基本情况",
            "公司2024年营业收入为5200万元，研发投入占比6.5%。",
            "二、核心技术与产品优势",
            "三、未来三年发展规划与产能目标",
            "计划新增两条自动化产线。",
        ],
        table_rows=[
            ["序号", "项目名称", "预算(万元)"],
            ["1", "高频多层复合膜研发", "320"],
            ["2", "低能耗涂布工艺改造", "180"],
        ],
    )
    _make_minimal_docx(
        new_doc,
        [
            "一、企业基本情况",
            "公司2024年营业收入为5850万元，研发投入占比7.2%。",
            "二、未来三年发展规划与产能目标",
            "计划新增两条自动化产线。",
            "三、核心技术与产品优势",
        ],
        table_rows=[
            ["序号", "项目名称", "预算(万元)"],
            ["1", "低能耗涂布工艺改造", "180"],
            ["2", "高频多层复合膜研发", "320"],
        ],
    )
    diff = doc_io.diff_docx_versions(old_doc, new_doc)
    assert diff["summary"]["moved_paragraphs"] >= 1
    assert diff["summary"]["moved_table_rows"] >= 2
    assert diff["summary"]["numeric_changes"] >= 1


@pytest.mark.skipif(
    not Path("/Users/zsh/JiaotangData/知识库/60_案例库/技术中心/交科/报告_3.杭州市企业技术中心认定-企业申请报告-修改版20220720.docx").is_file(),
    reason="real Jiaoke docx unavailable",
)
def test_real_kb_docx_diff_jiaoke():
    d1 = Path("/Users/zsh/JiaotangData/知识库/60_案例库/技术中心/交科/报告_3.杭州市企业技术中心认定-企业申请报告-修改版20220720.docx")
    d2 = Path("/Users/zsh/JiaotangData/知识库/60_案例库/技术中心/交科/报告_3.杭州市企业技术中心认定-企业申请报告-修改版20220721.docx")
    diff = doc_io.diff_docx_versions(d1, d2)
    assert diff["summary"]["unchanged_paragraphs"] > 50


def test_tolerant_financial_excel_reader(tmp_path: Path):
    xlsx = tmp_path / "fin.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "利润及资产简表"
    ws.append(["项目", "2023年", "2024年"])
    ws.append(["一、营业总收入", 4800.5, 5620.0])
    ws.append(["其中：研究与开发费用", 260.0, 340.5])
    ws.append(["资产总计", 6000.0, 7100.0])
    ws.append(["负债合计", 2400.0, 2900.0])
    ws.append(["所有者权益合计", 3600.0, 4200.0])
    wb.save(xlsx)

    res = doc_io.read_financial_excel_tolerant(xlsx)
    metrics = {i["metric"] for i in res["items"]}
    assert {"revenue", "rd_expense", "total_assets", "total_liabilities", "total_equity"}.issubset(metrics)


# ---------- 4. quality_gate ----------


def test_quality_gate_hard_blocks_and_whitelists(tmp_path: Path):
    # Bad lazy text with placeholders, hedge, cross-company contamination, editorial paren
    bad_text = (
        "本项目由宁波串户有限公司开展[待补充]，仅供参考，不构成专业建议（待核实）。"
    )
    res_bad = quality_gate.audit_formal_text(
        bad_text,
        expected_company="杭州中焯信息技术股份有限公司",
        min_chars=180,
        required_keywords=["立项背景", "组织实施方式"],
    )
    assert res_bad["ok"] is False
    rules = {e["rule"] for e in res_bad["errors"]}
    assert {"min_density", "required_element", "placeholder", "defensive_hedge", "cross_enterprise_contamination", "suspicious_parentheses"}.issubset(rules)

    # Good dense formal text with scientific & legal parentheses should PASS
    good_text = (
        "立项背景与研发目的：杭州中焯信息技术股份有限公司针对证券移动端公网通信抗篡改与弱网断链重连痛点，"
        "结合国密SM2/SM3/SM4算法体系与既有高频接入网关底座，立项攻关低时延高并发加密传输框架。"
        "组织实施方式：公司采用自主研发模式，由技术总监牵头组建架构设计、密码协议、接入网关与自动化测试四个专项小组，"
        "按需求评审、模块编码、联调压测与第三方鉴定测试四个阶段推进里程碑管控，并在关键节点执行代码审计与性能回归。"
        "经第三方检测验证，核心模块单节点并发响应达2021次/秒，阻隔膜配套测试透氧量≤0.5 cm³/(m²·24h·0.1MPa)，满足《高新技术企业认定管理工作指引（修订）》技术要求。"
    )
    res_good = quality_gate.audit_formal_text(
        good_text,
        expected_company="杭州中焯信息技术股份有限公司",
        min_chars=180,
        max_chars=400,
        required_keywords=["立项背景", "组织实施方式"],
    )
    assert res_good["ok"] is True, res_good["errors"]

    # CLI exit code check (exit 2 on fail, exit 0 on pass)
    bad_file = tmp_path / "bad.txt"
    bad_file.write_text(bad_text, encoding="utf-8")
    p = subprocess.run(
        [sys.executable, str(CORE_DIR / "quality_gate.py"), "check-text", str(bad_file), "--min-chars", "180"],
        capture_output=True, text=True,
    )
    assert p.returncode == 2


def test_rewrite_fidelity_and_calc_gate(tmp_path: Path):
    src = "产品耐压强度达2.5MPa，杂质含量低于15ppm，噪音控制在58dB(A)以内。"
    tampered = "产品耐压强度达3.0MPa，实现国际领先水平，噪音控制在58dB(A)以内。"
    r_bad = quality_gate.audit_rewrite_fidelity(src, tampered)
    assert r_bad["ok"] is False
    bad_rules = {e["rule"] for e in r_bad["errors"]}
    assert {"dropped_numbers", "fabricated_numbers", "inflated_claim"}.issubset(bad_rules)

    faithful = "经实测，该产品耐压强度稳定在2.5MPa，杂质含量严格低于15ppm，运行噪音不超过58dB(A)。"
    r_ok = quality_gate.audit_rewrite_fidelity(src, faithful)
    assert r_ok["ok"] is True, r_ok["errors"]

    c_ok = quality_gate.verify_calculation_claim("350 / 5000 * 100", 7.0)
    assert c_ok["ok"] is True
    c_bad = quality_gate.verify_calculation_claim("350 / 5000 * 100", 99.99)
    assert c_bad["ok"] is False
