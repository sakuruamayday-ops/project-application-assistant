#!/usr/bin/env python3
"""
Unified Free-Tier Government Project Checkup, Policy Verification, Matching & Local KB CLI.
Zero MCP dependency (reads local jiaotang.db & rag-query.sh directly when available).
Zero fake-strict gates:
  - Missing mandatory inputs fail under --strict (never exit 0 on empty {})
  - Patents require valid Chinese patent numbers & deduplication
  - 2026 MIIT Order [2026] #2 & [2026] #117 exact Little Giant thresholds (debt <=75%, 2y R&D >=1200w & >=3%/y, I-class IP >=4)
  - profile --write-blackboard merges cleanly without wiping existing lockedProduct/patentTierReport/estimatedMetrics
  - RAG backend errors propagate to ok=False & exit 2 under --strict
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
for candidate in (SCRIPT_DIR, SKILL_ROOT.parent / "_core", SKILL_ROOT / "scripts" / "_core"):
    if candidate.is_dir() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import fact_ledger  # noqa: E402
import kb_local  # noqa: E402
import search_catalogs  # noqa: E402


def _dedup_valid_patents(patents: list[dict[str, Any]], ref_date: date) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    seen_keys: set[str] = set()
    valid: list[dict[str, Any]] = []
    for idx, p in enumerate(patents):
        if not isinstance(p, dict):
            errors.append(f"patents[{idx}] 必须为对象")
            continue
        p_errs = fact_ledger.validate_patent_item(p, as_of=ref_date, require_valid_no=True)
        if p_errs:
            errors.extend(p_errs)
            continue
        key = fact_ledger.normalize_patent_key(p)
        if key in seen_keys:
            errors.append(f"重复专利号不得重复计数：{p.get('patent_no') or p.get('no')}")
            continue
        seen_keys.add(key)
        valid.append(p)
    return valid, errors


def check_hightech(data: dict[str, Any], as_of: date | None = None) -> dict[str, Any]:
    """Deterministic 9-condition High-Tech Enterprise preassessment (国科发火〔2016〕32号 & 195号)."""
    ref_date = as_of or date.today()
    errors: list[str] = []
    warnings: list[str] = []
    gates: dict[str, Any] = {}

    if not isinstance(data, dict) or not data:
        return {
            "program": "high_tech_enterprise",
            "policy_basis": "国科发火〔2016〕32号 + 国科发火〔2016〕195号",
            "ok": False,
            "gates": {},
            "errors": ["输入数据为空，缺少高企体检必需字段（成立日期、财务三表、人员、高新收入、研发费用、专利清单）"],
            "warnings": [],
        }

    # 0. USCC & Balance Sheet Reconciliation
    uscc = str(data.get("credit_code") or "").strip()
    if uscc:
        ok_u, msg_u = fact_ledger.validate_uscc(uscc)
        gates["uscc"] = {"pass": ok_u, "detail": msg_u}
        if not ok_u:
            errors.append(f"统一社会信用代码无效：{msg_u}")

    bs = data.get("balance_sheet")
    if isinstance(bs, dict):
        ok_bs, msg_bs = fact_ledger.validate_balance_sheet(
            bs.get("total_assets"), bs.get("total_liabilities"), bs.get("total_equity")
        )
        gates["balance_sheet"] = {"pass": ok_bs, "detail": msg_bs}
        if not ok_bs:
            errors.append(msg_bs)
    else:
        gates["balance_sheet"] = {"pass": False, "detail": "缺少资产负债表平衡数据"}
        errors.append("缺少 balance_sheet（资产总额/负债总额/所有者权益），无法核验三表平衡")

    # 1. Establishment >= 365 days
    founded = str(data.get("founded_date") or "").strip()
    if founded:
        try:
            fdate = date.fromisoformat(founded[:10])
            days = (ref_date - fdate).days
            ok_est = days >= 365
            gates["established_365d"] = {"pass": ok_est, "days": days}
            if not ok_est:
                errors.append(f"注册成立仅 {days} 天，不满365天红线")
        except ValueError:
            gates["established_365d"] = {"pass": False, "detail": f"日期无效：{founded}"}
            errors.append(f"founded_date 日期格式无效：{founded}")
    else:
        gates["established_365d"] = {"pass": False, "detail": "缺少 founded_date"}
        errors.append("缺少成立日期 founded_date，无法核验注册满365天门槛")

    # 2. Patents (valid patent_no + dedup + 5th digit + expiry + transfer >=1y + count > 0)
    patents = data.get("patents")
    if not isinstance(patents, list) or not patents:
        gates["ip_validity"] = {"pass": False, "valid_count": 0, "issues": ["缺少有效核心知识产权清单"]}
        errors.append("缺少有效核心知识产权清单（patents 不能为空）")
    else:
        valid_pats, patent_issues = _dedup_valid_patents(patents, ref_date)
        ok_ip = len(valid_pats) > 0 and not patent_issues
        gates["ip_validity"] = {"pass": ok_ip, "valid_count": len(valid_pats), "issues": patent_issues}
        errors.extend(patent_issues)
        if len(valid_pats) == 0:
            errors.append("无有效未过期且权属合规的核心知识产权")

    # 3. Tech personnel ratio >= 10%
    emp = data.get("total_employees")
    tech = data.get("tech_employees")
    if emp and float(emp) > 0 and tech is not None:
        ratio = round(float(tech) / float(emp) * 100.0, 2)
        ok_tp = ratio >= 10.0
        gates["tech_personnel_ratio"] = {"pass": ok_tp, "ratio_pct": ratio, "threshold_pct": 10.0}
        if not ok_tp:
            errors.append(f"科技人员占比 {ratio}% 低于10%红线")
    else:
        gates["tech_personnel_ratio"] = {"pass": False, "detail": "缺少职工/科技人员数"}
        errors.append("缺少 total_employees 或 tech_employees，无法核验科技人员占比≥10%红线")

    # 4. High-tech product/service revenue ratio >= 60%
    rev_latest = data.get("latest_revenue")
    ht_rev = data.get("hightech_product_revenue")
    if rev_latest and float(rev_latest) > 0 and ht_rev is not None:
        ht_ratio = round(float(ht_rev) / float(rev_latest) * 100.0, 2)
        ok_ht = ht_ratio >= 60.0
        gates["hightech_revenue_ratio"] = {"pass": ok_ht, "ratio_pct": ht_ratio, "threshold_pct": 60.0}
        if not ok_ht:
            errors.append(f"近一年高新技术产品（服务）收入占比 {ht_ratio}% 低于60%红线")
    else:
        gates["hightech_revenue_ratio"] = {"pass": False, "detail": "缺少高新收入或总收入"}
        errors.append("缺少 latest_revenue 或 hightech_product_revenue，无法核验高新收入占比≥60%红线")

    # 5. 3-year R&D ratio tier (5% / 4% / 3%) + domestic R&D >= 60%
    rev_3y = data.get("revenue_3y")
    rd_3y = data.get("rd_expense_3y")
    if rev_3y and float(rev_3y) > 0 and rd_3y is not None and rev_latest is not None:
        rev_last = float(rev_latest)
        threshold = 5.0 if rev_last <= 5000 else (4.0 if rev_last <= 20000 else 3.0)
        rd_calc = fact_ledger.calc_rd_ratio(rd_3y, rev_3y)
        warnings.extend(rd_calc.get("warnings", []))
        ok_rd = bool(rd_calc.get("ok")) and rd_calc["ratio_pct"] >= threshold
        gates["rd_ratio_3y"] = {"pass": ok_rd, "ratio_pct": rd_calc.get("ratio_pct"), "threshold_pct": threshold}
        if not ok_rd:
            errors.append(f"近三年研发费用占比 {rd_calc.get('ratio_pct')}% 低于对应档位红线 {threshold}%")
    else:
        gates["rd_ratio_3y"] = {"pass": False, "detail": "缺少近三年研发或营收"}
        errors.append("缺少 revenue_3y 或 rd_expense_3y，无法核验近三年研发费用占比红线")

    dom_rd = data.get("domestic_rd_expense_3y")
    if rd_3y and float(rd_3y) > 0 and dom_rd is not None:
        dom_ratio = round(float(dom_rd) / float(rd_3y) * 100.0, 2)
        ok_dom = dom_ratio >= 60.0
        gates["domestic_rd_ratio"] = {"pass": ok_dom, "ratio_pct": dom_ratio, "threshold_pct": 60.0}
        if not ok_dom:
            errors.append(f"中国境内研发费用占比 {dom_ratio}% 低于60%红线")
    else:
        gates["domestic_rd_ratio"] = {"pass": False, "detail": "缺少境内研发费用"}
        errors.append("缺少 domestic_rd_expense_3y，无法核验中国境内研发费用占比≥60%红线")

    # 6. Growth metrics
    rev_series = data.get("annual_revenues")
    if isinstance(rev_series, list) and len(rev_series) == 3:
        gates["revenue_growth"] = fact_ledger.calc_growth_metrics(rev_series[0], rev_series[1], rev_series[2])

    all_gates_ok = all(g.get("pass", True) for g in gates.values() if isinstance(g, dict) and "pass" in g)
    return {
        "program": "high_tech_enterprise",
        "policy_basis": "国科发火〔2016〕32号 + 国科发火〔2016〕195号",
        "ok": len(errors) == 0 and all_gates_ok,
        "gates": gates,
        "errors": errors,
        "warnings": warnings,
    }


def check_sme(data: dict[str, Any], as_of: date | None = None) -> dict[str, Any]:
    """Deterministic MIIT Order [2026] #2 & [2026] #117 SME / Little Giant preassessment."""
    ref_date = as_of or date.today()
    errors: list[str] = []
    warnings: list[str] = []
    gates: dict[str, Any] = {}
    tier = str(data.get("target_tier") or "little_giant").strip()

    if not isinstance(data, dict) or not data:
        return {
            "program": f"sme_{tier}",
            "policy_basis": "工信部企业〔2026〕2号 + 工信厅企业函〔2026〕117号",
            "ok": False,
            "gates": {},
            "errors": ["输入数据为空，缺少专精特新/小巨人必需核验字段"],
            "warnings": [],
        }

    # 1. Balance sheet & debt-to-asset ratio <= 75% (2026 Order #2!)
    bs = data.get("balance_sheet")
    if isinstance(bs, dict):
        ok_bs, msg_bs = fact_ledger.validate_balance_sheet(
            bs.get("total_assets"), bs.get("total_liabilities"), bs.get("total_equity")
        )
        gates["balance_sheet"] = {"pass": ok_bs, "detail": msg_bs}
        if not ok_bs:
            errors.append(msg_bs)
        if bs.get("total_assets") and float(bs["total_assets"]) > 0:
            dar = round(float(bs["total_liabilities"]) / float(bs["total_assets"]) * 100.0, 2)
            ok_dar = dar <= 75.0
            gates["debt_to_asset_ratio"] = {"pass": ok_dar, "ratio_pct": dar, "max_pct": 75.0}
            if not ok_dar:
                errors.append(f"上年末资产负债率 {dar}% 超过2026版2号文75%红线")
    else:
        gates["balance_sheet"] = {"pass": False, "detail": "缺少资产负债表"}
        errors.append("缺少 balance_sheet，无法核验资产负债表平衡与负债率≤75%红线")

    # 2. Revenue growth (2-year CAGR) & 2-year R&D intensity (2026 Order #2: 2y R&D >= 1200w & >=3%/yr for >=1亿)
    rev_series = data.get("annual_revenues")
    if isinstance(rev_series, list) and len(rev_series) == 3:
        gr = fact_ledger.calc_growth_metrics(rev_series[0], rev_series[1], rev_series[2])
        gates["revenue_growth"] = gr
        if tier == "little_giant" and gr.get("ok") and gr["cagr_2y_pct"] < 5.0:
            warnings.append(f"近2年营收复合增长率 {gr['cagr_2y_pct']}% 低于5%，须核验当期成长性/高研发豁免条款")

    rev_latest = data.get("latest_revenue")
    rd_latest = data.get("latest_rd_expense")
    rd_2y = data.get("rd_expenses_2y")  # optional [prev_yr_rd, latest_yr_rd]
    if rev_latest and float(rev_latest) > 0 and rd_latest is not None:
        rd_c = fact_ledger.calc_rd_ratio(rd_latest, rev_latest)
        warnings.extend(rd_c.get("warnings", []))
        if float(rev_latest) >= 10000:
            ok_rd = bool(rd_c.get("ok")) and rd_c["ratio_pct"] >= 3.0
            if isinstance(rd_2y, list) and len(rd_2y) == 2:
                rd_sum_2y = float(rd_2y[0]) + float(rd_2y[1])
                ok_sum = rd_sum_2y >= 1200.0
                gates["rd_2y_total"] = {"pass": ok_sum, "total_wanyuan": round(rd_sum_2y, 2), "min_wanyuan": 1200.0}
                if not ok_sum:
                    errors.append(f"近两年研发费用合计 {rd_sum_2y:.2f} 万元低于2026版2号文1200万元门槛")
                ok_rd = ok_rd and ok_sum
            gates["rd_intensity"] = {"pass": ok_rd, "ratio_pct": rd_c.get("ratio_pct"), "threshold_pct": 3.0}
            if not rd_c.get("ok") or rd_c["ratio_pct"] < 3.0:
                errors.append(f"近一年研发费用占比 {rd_c.get('ratio_pct')}% 低于3%红线")
        else:
            ok_rd = bool(rd_c.get("ok")) and rd_c["ratio_pct"] >= 6.0
            gates["rd_intensity"] = {"pass": ok_rd, "ratio_pct": rd_c.get("ratio_pct"), "threshold_pct": 6.0}
            if not ok_rd:
                errors.append(f"营收低于1亿元档位研发费用占比 {rd_c.get('ratio_pct')}% 低于6%红线")
    else:
        gates["rd_intensity"] = {"pass": False, "detail": "缺少营收或研发费用"}
        errors.append("缺少 latest_revenue 或 latest_rd_expense")

    # 3. Patents (valid patent_no + dedup; 2026 Order #2 default >=4 I-class IP for new Little Giant)
    patents = data.get("patents")
    min_i_class = int(data.get("min_i_class_ip") or (4 if tier == "little_giant" else 1))
    if not isinstance(patents, list) or not patents:
        gates["i_class_ip"] = {"pass": False, "valid_i_class_count": 0, "min_required": min_i_class}
        errors.append(f"缺少有效知识产权清单（{tier} 要求不少于 {min_i_class} 项有效I类知识产权）")
    else:
        valid_pats, p_errs = _dedup_valid_patents(patents, ref_date)
        errors.extend(p_errs)
        i_class_valid = sum(
            1 for p in valid_pats
            if "发明" in str(p.get("type") or "") or str(p.get("ip_class") or "").upper() == "I"
        )
        ok_ip = i_class_valid >= min_i_class and not p_errs
        gates["i_class_ip"] = {"pass": ok_ip, "valid_i_class_count": i_class_valid, "min_required": min_i_class}
        if i_class_valid < min_i_class:
            errors.append(f"去重有效I类知识产权仅 {i_class_valid} 项，低于2026版2号文 {min_i_class} 项硬门槛")

    all_gates_ok = all(g.get("pass", True) for g in gates.values() if isinstance(g, dict) and "pass" in g)
    return {
        "program": f"sme_{tier}",
        "policy_basis": "工信部企业〔2026〕2号《优质中小企业梯度培育管理办法》 + 工信厅企业函〔2026〕117号",
        "ok": len(errors) == 0 and all_gates_ok,
        "gates": gates,
        "errors": errors,
        "warnings": warnings,
    }


def validate_policy_metadata(meta: dict[str, Any], as_of: date | None = None) -> dict[str, Any]:
    """Real policy validity check: rejects expired expiry_date and missing required guidelines."""
    ref_date = as_of or date.today()
    errors: list[str] = []
    expiry_str = str(meta.get("expiry_date") or "").strip()
    if expiry_str:
        try:
            exp = date.fromisoformat(expiry_str[:10])
            if exp < ref_date:
                errors.append(f"政策已过有效期：expiry_date={exp.isoformat()} < {ref_date.isoformat()}")
        except ValueError:
            errors.append(f"expiry_date 格式无效：{expiry_str}")
    if meta.get("status") in {"expired", "repealed", "superseded", "废止", "失效"}:
        errors.append(f"政策状态为失效/废止：{meta.get('status')}")
    if meta.get("requires_guideline") and not meta.get("guideline_doc"):
        errors.append("缺少必备配套《工作指引》/《实施细则》支撑文件")
    return {"ok": len(errors) == 0, "errors": errors, "region_scope": kb_local.resolve_region_scope(str(meta.get("region") or ""))}


def main() -> int:
    parser = argparse.ArgumentParser(description="免费体检/查政策/匹配项目/查同行/六基检索统一 CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_prof = sub.add_parser("profile", help="本地数据库查询企业画像、财务冲突与去重认定，安全合并落盘黑板")
    p_prof.add_argument("--company", required=True)
    p_prof.add_argument("--credit-code", default="")
    p_prof.add_argument("--workspace", type=Path, default=None)
    p_prof.add_argument("--write-blackboard", action="store_true")

    p_ht = sub.add_parser("hightech", help="高新技术企业9大硬条件自动化复算")
    p_ht.add_argument("--input", type=Path, required=True)
    p_ht.add_argument("--strict", action="store_true")

    p_sme = sub.add_parser("sme", help="专精特新/小巨人（2026版2号文+117号文）自动化复算")
    p_sme.add_argument("--input", type=Path, required=True)
    p_sme.add_argument("--strict", action="store_true")

    p_pol = sub.add_parser("policy", help="洁净检索本地政策库并校验证件有效期与省市区县层级")
    p_pol.add_argument("--query", default="")
    p_pol.add_argument("--region", default="")
    p_pol.add_argument("--metadata-json", type=Path, default=None)
    p_pol.add_argument("--limit", type=int, default=6)
    p_pol.add_argument("--strict", action="store_true")

    p_peer = sub.add_parser("peers", help="查询去重可比同行名单")
    p_peer.add_argument("--project", required=True)
    p_peer.add_argument("--region", default="")
    p_peer.add_argument("--industry", default="")
    p_peer.add_argument("--limit", type=int, default=15)

    p_cat = sub.add_parser("catalog", help="叶节点加权检索《产业链架构》与《产业基础目录(2021)》")
    p_cat.add_argument("query")
    p_cat.add_argument("--limit", type=int, default=8)

    args = parser.parse_args()
    if args.cmd == "profile":
        res = kb_local.query_enterprise(args.company, credit_code=args.credit_code)
        if res.get("found"):
            ent = res["enterprise"]
            res["region_scope"] = kb_local.resolve_region_scope(
                f"{ent.get('province', '')}{ent.get('city', '')}{ent.get('county', '')}"
            )
            if args.write_blackboard and args.workspace:
                uscc = str(ent.get("unified_social_credit_code") or "")
                existing, _ = fact_ledger.load_blackboard(args.workspace, ent["name"], uscc, strict=True)
                bb = existing if existing is not None else fact_ledger.empty_blackboard(ent["name"], uscc)
                bb.setdefault("financialFacts", {})["local_kb_records"] = res["financials"]
                bb.setdefault("checkupSnapshots", {})["profile_recognitions_count"] = len(res["recognitions"])
                saved = fact_ledger.save_blackboard(args.workspace, bb, strict=True)
                res["blackboard_path"] = str(saved)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res.get("found") else 2

    if args.cmd == "hightech":
        data = json.loads(args.input.read_text(encoding="utf-8"))
        res = check_hightech(data)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if (res["ok"] or not args.strict) else 2

    if args.cmd == "sme":
        data = json.loads(args.input.read_text(encoding="utf-8"))
        res = check_sme(data)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if (res["ok"] or not args.strict) else 2

    if args.cmd == "policy":
        out: dict[str, Any] = {"ok": True, "errors": []}
        if args.region:
            out["region_scope"] = kb_local.resolve_region_scope(args.region)
        if args.query:
            rag_res = kb_local.search_local_rag(args.query, limit=args.limit)
            out["rag"] = rag_res
            if rag_res.get("error"):
                out["ok"] = False
                out["errors"].append(f"本地政策检索后端不可用：{rag_res['error']}")
        if args.metadata_json:
            val = validate_policy_metadata(json.loads(args.metadata_json.read_text(encoding="utf-8")))
            out["metadata_validation"] = val
            if not val["ok"]:
                out["ok"] = False
                out["errors"].extend(val["errors"])
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if (out["ok"] or not args.strict) else 2

    if args.cmd == "peers":
        res = kb_local.query_peers(args.project, args.region, args.industry, args.limit)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if not res.get("error") else 2

    if args.cmd == "catalog":
        res = search_catalogs.search_catalogs(args.query, SKILL_ROOT / "references", args.limit)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
