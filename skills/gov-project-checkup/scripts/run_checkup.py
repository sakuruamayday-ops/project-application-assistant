#!/usr/bin/env python3
"""
Unified Free-Tier Government Project Checkup, Policy Verification, Matching & Local KB CLI.
Balanced anti-blocking design:
  - Separates hard `errors` (provided data clearly fails thresholds / invalid math / expired patent)
    from `missing_inputs` (partial checkup / early consultation where client hasn't sent every doc yet).
  - Default mode: computes every available gate & outputs status="pass"|"partial_pass"|"fail" (exits 0 unless hard DB/IO error),
    allowing partial checkups and early patent drafts (marking uncertified patents as pending_certificates).
  - --strict mode (final submission gate): blocks on ANY error, ANY missing_input, or ANY unverified patent number (exit 2).
  - profile ambiguous short-name hit: prevents cross-company leak without crashing CLI (returns exit 0 + status="ambiguous" + candidates).
"""
from __future__ import annotations

import argparse
import json
import math
import re
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
import timeline_cache  # noqa: E402


def _finite_float(val: Any) -> float | None:
    if val is None or isinstance(val, bool) or str(val).strip() == "":
        return None
    try:
        f = float(val)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _eval_patents(
    patents: list[dict[str, Any]],
    ref_date: date,
    *,
    strict: bool,
    exclude_transferred: bool = False,
    require_dominant_link: bool = False,
    require_transfer_holding_1y: bool = False,
    stat_cutoff: date | None = None,
    business_type: str = "",
) -> tuple[list[dict[str, Any]], list[str], list[str], list[str]]:
    errors: list[str] = []
    pending_certs: list[str] = []
    warnings: list[str] = []
    seen_keys: set[str] = set()
    valid: list[dict[str, Any]] = []
    is_equipment_maker = business_type.strip().lower() in {
        "equipment_or_mold_maker", "equipment", "mold", "装备制造", "设备制造", "模具制造",
    }
    for idx, p in enumerate(patents):
        if not isinstance(p, dict):
            errors.append(f"patents[{idx}] 必须为对象")
            continue
        raw_no = str(p.get("patent_no") or p.get("no") or "").strip()
        acq = str(p.get("acquisition") or p.get("acquisition_method") or "")
        if exclude_transferred and any(k in acq for k in ("受让", "转让", "转入", "并购")):
            errors.append(f"patents[{idx}]({raw_no or '未编号'}) 为转入/受让取得，按2026版2号文不得计入自主研发I类知识产权")
            continue
        if not exclude_transferred and not require_transfer_holding_1y and any(k in acq for k in ("受让", "转让", "并购")):
            if not str(p.get("transfer_date") or "").strip():
                warnings.append(f"patents[{idx}]({raw_no or '未编号'}) 为受让专利且未填转让登记生效日，高企不设满1年限制但建议附国知局著录项目变更通知书确认权属")
        rank = p.get("applicant_rank")
        if rank is not None:
            r_num = _finite_float(rank)
            if r_num is None or r_num > 3:
                errors.append(f"patents[{idx}]({raw_no or '未编号'}) 权利人排名({rank})未进入前三，不得计入")
                continue
        if require_dominant_link:
            if p.get("linked_to_dominant_product") is False:
                errors.append(f"patents[{idx}]({raw_no or '未编号'}) 未关联主导产品，不得计入")
                continue
            role_text = " ".join(
                str(p.get(k) or "") for k in ("role", "support_tier", "usage", "category")
            ).lower()
            is_self_use_tooling = any(
                k in role_text
                for k in ("production_support", "weak_or_unrelated", "自用工装", "自用设备", "生产工装", "自用模具", "制造辅助", "内部生产设备")
            )
            if is_self_use_tooling and not is_equipment_maker:
                warnings.append(
                    f"patents[{idx}]({raw_no or '未编号'}) 标为自用工装/生产工艺支撑，非设备制造企业不计入主导产品直挂有效I类知产"
                )
                continue
        if stat_cutoff is not None:
            gdate_str = str(p.get("grant_date") or "").strip()
            if gdate_str:
                try:
                    gd = date.fromisoformat(gdate_str[:10])
                    if gd > stat_cutoff:
                        errors.append(
                            f"patents[{idx}]({raw_no or '未编号'}) 授权公告日 {gd.isoformat()} 晚于批次统计截止日 {stat_cutoff.isoformat()}，不得计入该时点有效知识产权（须以当批采信口径核定）"
                        )
                        continue
                except ValueError:
                    errors.append(f"patents[{idx}]({raw_no or '未编号'}) grant_date 日期格式无效：{gdate_str}")
                    continue
        p_errs = fact_ledger.validate_patent_item(
            p,
            as_of=ref_date,
            require_valid_no=True,
            require_transfer_holding_1y=require_transfer_holding_1y,
        )
        only_missing_no = (
            len(p_errs) == 1
            and "专利号缺失或不符合中国专利号规范" in p_errs[0]
        )
        if only_missing_no and not strict:
            pending_certs.append(f"patents[{idx}]({raw_no or '未提供ZL号'}) 缺正式ZL授权号，须补证书核验后方可正式计入")
            continue
        if p_errs:
            errors.extend(p_errs)
            continue
        key = fact_ledger.normalize_patent_key(p)
        if key in seen_keys:
            errors.append(f"重复专利号不得重复计数：{raw_no}")
            continue
        seen_keys.add(key)
        valid.append(p)
    return valid, errors, pending_certs, warnings


def check_hightech(data: dict[str, Any], as_of: date | None = None, *, strict: bool = False) -> dict[str, Any]:
    """Deterministic 9-condition High-Tech Enterprise preassessment (国科发火〔2016〕32号 & 195号)."""
    ref_date = as_of or date.today()
    errors: list[str] = []
    missing_inputs: list[str] = []
    warnings: list[str] = []
    gates: dict[str, Any] = {}

    if not isinstance(data, dict) or not data:
        return {
            "program": "high_tech_enterprise",
            "policy_basis": "国科发火〔2016〕32号 + 国科发火〔2016〕195号",
            "status": "fail",
            "ok": False,
            "gates": {},
            "errors": ["输入数据为空，缺少高企体检必需字段"],
            "missing_inputs": ["founded_date", "balance_sheet", "patents", "total_employees", "latest_revenue", "revenue_3y", "rd_expense_3y"],
            "warnings": [],
        }

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
        gates["balance_sheet"] = {"pass": None, "detail": "暂缺资产负债表数据（待补）"}
        missing_inputs.append("balance_sheet（资产负债表平衡核验）")

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
        gates["established_365d"] = {"pass": None, "detail": "暂缺 founded_date"}
        missing_inputs.append("founded_date（成立满365天核验）")

    patents = data.get("patents")
    if not isinstance(patents, list) or not patents:
        gates["ip_validity"] = {"pass": None if not strict else False, "valid_count": 0}
        missing_inputs.append("patents（有效核心知识产权清单）")
    else:
        valid_pats, patent_issues, pending_certs, patent_warnings = _eval_patents(
            patents, ref_date, strict=strict, require_transfer_holding_1y=False
        )
        warnings.extend(pending_certs)
        warnings.extend(patent_warnings)
        errors.extend(patent_issues)
        if pending_certs:
            missing_inputs.append(f"patents（{len(pending_certs)}项待补正式ZL授权证书核验）")
        if len(valid_pats) == 0 and not pending_certs:
            ok_ip: bool | None = False
            errors.append("无有效未过期且权属合规的核心知识产权")
        elif len(valid_pats) == 0 and pending_certs:
            ok_ip = False if strict else None
        else:
            ok_ip = not patent_issues
        gates["ip_validity"] = {
            "pass": ok_ip,
            "valid_count": len(valid_pats),
            "pending_certificate_count": len(pending_certs),
            "issues": patent_issues,
        }

    raw_emp, raw_tech = data.get("total_employees"), data.get("tech_employees")
    emp = _finite_float(raw_emp)
    tech = _finite_float(raw_tech)
    if raw_emp in (None, "") or raw_tech in (None, ""):
        if (raw_emp not in (None, "") and (emp is None or emp <= 0)) or (raw_tech not in (None, "") and (tech is None or tech < 0)):
            gates["tech_personnel_ratio"] = {"pass": False, "detail": "已提供的职工或科技人员数无效"}
            errors.append("total_employees / tech_employees 存在无效、负数或非有限数值")
        else:
            gates["tech_personnel_ratio"] = {"pass": None, "detail": "暂缺职工总数或科技人员数"}
            missing_inputs.append("total_employees / tech_employees（科技人员占比≥10%）")
    elif emp is None or emp <= 0 or tech is None:
        gates["tech_personnel_ratio"] = {"pass": False, "detail": "职工总数或科技人员数非有效正数"}
        errors.append("total_employees / tech_employees 存在无效、负数或非有限数值")
    elif tech < 0 or tech > emp:
        gates["tech_personnel_ratio"] = {"pass": False, "detail": f"科技人员数({tech})大于职工总数({emp})或为负数"}
        errors.append(f"科技人员数({tech})不得大于职工总数({emp})或为负数")
    else:
        ratio_raw = tech / emp * 100.0
        ok_tp = ratio_raw >= 10.0
        gates["tech_personnel_ratio"] = {"pass": ok_tp, "ratio_pct": round(ratio_raw, 2), "threshold_pct": 10.0}
        if not ok_tp:
            errors.append(f"科技人员占比 {ratio_raw:.4f}% 低于10%红线")

    raw_rev, raw_ht = data.get("latest_revenue"), data.get("hightech_product_revenue")
    rev_latest = _finite_float(raw_rev)
    ht_rev = _finite_float(raw_ht)
    if raw_rev in (None, "") or raw_ht in (None, ""):
        if (raw_rev not in (None, "") and (rev_latest is None or rev_latest <= 0)) or (raw_ht not in (None, "") and (ht_rev is None or ht_rev < 0)):
            gates["hightech_revenue_ratio"] = {"pass": False, "detail": "已提供的总收入或高新收入无效"}
            errors.append("latest_revenue / hightech_product_revenue 存在无效或非有限数值")
        else:
            gates["hightech_revenue_ratio"] = {"pass": None, "detail": "暂缺高新收入或总收入"}
            missing_inputs.append("latest_revenue / hightech_product_revenue（高新收入占比≥60%）")
    elif rev_latest is None or rev_latest <= 0 or ht_rev is None:
        gates["hightech_revenue_ratio"] = {"pass": False, "detail": "总收入或高新收入非有效数值"}
        errors.append("latest_revenue / hightech_product_revenue 存在无效或非有限数值")
    elif ht_rev < 0 or ht_rev > rev_latest:
        gates["hightech_revenue_ratio"] = {"pass": False, "detail": f"高新收入({ht_rev})大于同期总收入({rev_latest})或为负数"}
        errors.append(f"高新技术产品（服务）收入({ht_rev})不得大于同期总收入({rev_latest})或为负数")
    else:
        ht_raw = ht_rev / rev_latest * 100.0
        ok_ht = ht_raw >= 60.0
        gates["hightech_revenue_ratio"] = {"pass": ok_ht, "ratio_pct": round(ht_raw, 2), "threshold_pct": 60.0}
        if not ok_ht:
            errors.append(f"近一年高新技术产品（服务）收入占比 {ht_raw:.4f}% 低于60%红线")

    rev_3y = _finite_float(data.get("revenue_3y"))
    rd_3y = _finite_float(data.get("rd_expense_3y"))
    if rev_3y is not None and rev_3y > 0 and rd_3y is not None and rev_latest is not None and rev_latest > 0:
        if rd_3y < 0:
            gates["rd_ratio_3y"] = {"pass": False, "detail": "近三年研发费用不得为负数"}
            errors.append("rd_expense_3y 不得为负数")
        else:
            threshold = 5.0 if rev_latest <= 5000 else (4.0 if rev_latest <= 20000 else 3.0)
            rd_calc = fact_ledger.calc_rd_ratio(rd_3y, rev_3y)
            warnings.extend(rd_calc.get("warnings", []))
            raw_rd_pct = rd_3y / rev_3y * 100.0
            ok_rd = bool(rd_calc.get("ok")) and raw_rd_pct >= threshold
            gates["rd_ratio_3y"] = {"pass": ok_rd, "ratio_pct": round(raw_rd_pct, 2), "threshold_pct": threshold}
            if not ok_rd:
                errors.append(f"近三年研发费用占比 {raw_rd_pct:.4f}% 低于对应档位红线 {threshold}%")
    else:
        gates["rd_ratio_3y"] = {"pass": None, "detail": "暂缺近三年研发或营收"}
        missing_inputs.append("revenue_3y / rd_expense_3y（近三年研发占比）")

    dom_rd = _finite_float(data.get("domestic_rd_expense_3y"))
    if rd_3y is not None and rd_3y > 0 and dom_rd is not None:
        if dom_rd < 0 or dom_rd > rd_3y:
            gates["domestic_rd_ratio"] = {"pass": False, "detail": f"境内研发费用({dom_rd})大于研发费用总额({rd_3y})或为负数"}
            errors.append(f"中国境内研发费用({dom_rd})不得大于近三年研发费用总额({rd_3y})或为负数")
        else:
            dom_raw = dom_rd / rd_3y * 100.0
            ok_dom = dom_raw >= 60.0
            gates["domestic_rd_ratio"] = {"pass": ok_dom, "ratio_pct": round(dom_raw, 2), "threshold_pct": 60.0}
            if not ok_dom:
                errors.append(f"中国境内研发费用占比 {dom_raw:.4f}% 低于60%红线")
    elif data.get("domestic_rd_expense_3y") is not None:
        gates["domestic_rd_ratio"] = {"pass": False, "detail": "境内研发费用非有效数值"}
        errors.append("domestic_rd_expense_3y 存在无效或非有限数值")
    else:
        gates["domestic_rd_ratio"] = {"pass": None, "detail": "暂缺境内研发费用"}
        missing_inputs.append("domestic_rd_expense_3y（境内研发占比≥60%）")

    rev_series = data.get("annual_revenues")
    if isinstance(rev_series, list) and len(rev_series) == 3:
        gates["revenue_growth"] = fact_ledger.calc_growth_metrics(rev_series[0], rev_series[1], rev_series[2])

    # Additional High-Tech statutory hard gates when explicitly provided (field, innovation score >70, no major accident)
    if "in_supported_field" in data and data.get("in_supported_field") is not None:
        ok_field = bool(data.get("in_supported_field"))
        gates["supported_field"] = {"pass": ok_field}
        if not ok_field:
            errors.append("主要产品（服务）发挥核心支持作用的技术不属于《国家重点支持的高新技术领域》规定范围")
    if "innovation_score" in data and data.get("innovation_score") not in (None, ""):
        inn_score = _finite_float(data.get("innovation_score"))
        ok_inn = inn_score is not None and inn_score > 70.0
        gates["innovation_score"] = {"pass": ok_inn, "score": inn_score, "min_score_exclusive": 70.0}
        if not ok_inn:
            errors.append(f"企业创新能力评价得分({inn_score})未达到高于70分合格要求")
    if "major_safety_quality_env_accident" in data and data.get("major_safety_quality_env_accident") is not None:
        has_acc = bool(data.get("major_safety_quality_env_accident"))
        gates["no_major_accident"] = {"pass": not has_acc}
        if has_acc:
            errors.append("申请认定前一年内发生重大安全、重大质量事故或严重环境违法行为（一票否决）")

    strict_ok = len(errors) == 0 and len(missing_inputs) == 0
    if errors:
        status = "fail"
    elif missing_inputs:
        status = "fail" if strict else "partial_pass"
    else:
        status = "pass"
    return {
        "program": "high_tech_enterprise",
        "policy_basis": "国科发火〔2016〕32号 + 国科发火〔2016〕195号",
        "status": status,
        "ok": strict_ok if strict else (len(errors) == 0),
        "gates": gates,
        "errors": errors,
        "missing_inputs": missing_inputs,
        "warnings": warnings,
    }


def check_sme(data: dict[str, Any], as_of: date | None = None, *, strict: bool = False) -> dict[str, Any]:
    """Deterministic MIIT Order [2026] #2 & [2026] #117 SME / Little Giant preassessment (exact unrounded precision)."""
    ref_date = as_of or date.today()
    errors: list[str] = []
    missing_inputs: list[str] = []
    warnings: list[str] = []
    gates: dict[str, Any] = {}
    tier_raw = str(data.get("target_tier") or "little_giant").strip().lower()
    is_little_giant = tier_raw not in {"provincial_sme", "specialized_sme", "sme", "省专", "专精特新中小企业"}
    tier = "little_giant" if is_little_giant else "provincial_sme"
    app_type = str(data.get("application_type") or "recognition").strip().lower()
    is_review = app_type in {"review", "复核", "recheck"}

    if not isinstance(data, dict) or not data:
        return {
            "program": f"sme_{tier}",
            "policy_basis": "工信部企业〔2026〕2号 + 工信厅企业函〔2026〕117号",
            "status": "fail",
            "ok": False,
            "gates": {},
            "errors": ["输入数据为空，缺少专精特新/小巨人必需核验字段"],
            "missing_inputs": ["balance_sheet", "latest_revenue", "rd_expenses_2y", "patents"],
            "warnings": [],
        }

    # 1. Balance sheet & debt-to-asset ratio (raw unrounded comparison!)
    max_dar = 75.0 if is_little_giant else 80.0
    bs = data.get("balance_sheet")
    if isinstance(bs, dict):
        ok_bs, msg_bs = fact_ledger.validate_balance_sheet(
            bs.get("total_assets"), bs.get("total_liabilities"), bs.get("total_equity")
        )
        gates["balance_sheet"] = {"pass": ok_bs, "detail": msg_bs}
        if not ok_bs:
            errors.append(msg_bs)
        assets = _finite_float(bs.get("total_assets"))
        liab = _finite_float(bs.get("total_liabilities"))
        if assets is not None and assets > 0 and liab is not None:
            dar_raw = liab / assets * 100.0
            ok_dar = dar_raw <= max_dar
            gates["debt_to_asset_ratio"] = {"pass": ok_dar, "ratio_pct": round(dar_raw, 4), "max_pct": max_dar}
            if not ok_dar:
                errors.append(f"上年末资产负债率 {dar_raw:.4f}% 超过2026版2号文 {max_dar:.0f}% 红线")
    else:
        gates["balance_sheet"] = {"pass": None, "detail": "暂缺资产负债表"}
        missing_inputs.append(f"balance_sheet（资产负债表平衡与负债率≤{int(max_dar)}%）")

    # 2. Revenue floor & 2-year CAGR growth (exact MIIT Order [2026] #2)
    rev_latest = _finite_float(data.get("latest_revenue"))
    rev_series_raw = data.get("annual_revenues")
    rev_series = [_finite_float(x) for x in rev_series_raw] if isinstance(rev_series_raw, list) else []
    if rev_latest is None and len(rev_series) >= 1 and rev_series[-1] is not None:
        rev_latest = rev_series[-1]

    if is_little_giant:
        if rev_latest is None:
            gates["revenue_floor"] = {"pass": None, "min_wanyuan": 5000.0}
            missing_inputs.append("latest_revenue（小巨人上年度营收≥5000万元）")
        else:
            ok_rev = rev_latest >= 5000.0
            gates["revenue_floor"] = {"pass": ok_rev, "latest_revenue": rev_latest, "min_wanyuan": 5000.0}
            if not ok_rev:
                errors.append(f"上年度营业收入 {rev_latest} 万元低于2026版2号文小巨人5000万元门槛")
    else:
        eq_inv = _finite_float(data.get("equity_investment_2y")) or 0.0
        if rev_latest is None and not eq_inv:
            gates["revenue_floor"] = {"pass": None, "min_wanyuan": 1500.0}
            missing_inputs.append("latest_revenue（省专上年度营收≥1500万元或股权投资≥2000万元）")
        else:
            ok_rev = (rev_latest is not None and rev_latest >= 1500.0) or eq_inv >= 2000.0
            gates["revenue_floor"] = {"pass": ok_rev, "latest_revenue": rev_latest, "min_wanyuan": 1500.0}
            if not ok_rev:
                errors.append(f"上年度营业收入 {rev_latest} 万元低于1500万元且股权投资不足2000万元")

    if len(rev_series) == 3 and all(v is not None and v > 0 for v in rev_series):
        v1, v2, v3 = float(rev_series[0]), float(rev_series[1]), float(rev_series[2])  # type: ignore[arg-type]
        gr = fact_ledger.calc_growth_metrics(v1, v2, v3)
        cagr_raw = ((v3 / v1) ** 0.5 - 1.0) * 100.0
        gr["cagr_2y_raw_pct"] = round(cagr_raw, 4)
        gates["revenue_growth"] = gr
        if is_little_giant and not is_review:
            ok_gr = cagr_raw >= 5.0 or bool(data.get("growth_exemption_verified"))
            gates["revenue_growth"]["pass"] = ok_gr
            if not ok_gr:
                errors.append(f"新申报小巨人近2年营收复合增长率 {cagr_raw:.4f}% 低于2026版2号文5%硬门槛")
    elif is_little_giant and not is_review:
        gates["revenue_growth"] = {"pass": None, "detail": "暂缺连续三年营业收入（annual_revenues）"}
        missing_inputs.append("annual_revenues（近两年营收复合增长率≥5%）")

    # 3. R&D intensity & 2-year total (exact MIIT Order [2026] #2: NO legacy 6% rule!)
    #    - Little Giant: 2-year total >= 1200万元 AND BOTH years' R&D ratio >= 3%
    #    - Provincial SME: BOTH years' R&D >= 100万元 AND BOTH years' R&D ratio >= 3%
    rd_latest = _finite_float(data.get("latest_rd_expense"))
    rd_2y_raw = data.get("rd_expenses_2y")
    rd_2y = [_finite_float(x) for x in rd_2y_raw] if isinstance(rd_2y_raw, list) and len(rd_2y_raw) == 2 else None
    if rd_latest is None and rd_2y and rd_2y[1] is not None:
        rd_latest = rd_2y[1]

    prev_rev = rev_series[-2] if len(rev_series) >= 2 and rev_series[-2] is not None and rev_series[-2] > 0 else _finite_float(data.get("prior_revenue"))
    if is_little_giant and rd_2y is not None and rd_2y[0] is not None and rd_2y[1] is not None:
        rd_sum_early = float(rd_2y[0]) + float(rd_2y[1])
        ok_sum_early = rd_sum_early >= 1200.0
        gates["rd_2y_total"] = {"pass": ok_sum_early, "total_wanyuan": round(rd_sum_early, 4), "min_wanyuan": 1200.0}
        if not ok_sum_early:
            errors.append(f"近两年研发费用合计 {rd_sum_early:.4f} 万元低于2026版2号文1200万元硬门槛")

    if rd_2y is None or rd_2y[0] is None or rd_2y[1] is None or rev_latest is None or rev_latest <= 0 or prev_rev is None or prev_rev <= 0:
        # Compute whatever single-year ratio is available for partial checkup visibility, but record missing_inputs so --strict blocks!
        if rev_latest is not None and rev_latest > 0 and rd_latest is not None:
            latest_ratio_raw = rd_latest / rev_latest * 100.0
            gates["rd_intensity"] = {"pass": None if latest_ratio_raw >= 3.0 else False, "latest_ratio_pct": round(latest_ratio_raw, 4), "threshold_pct": 3.0}
            if latest_ratio_raw < 3.0:
                errors.append(f"最近一年研发费用占比 {latest_ratio_raw:.4f}% 低于2026版2号文3%硬门槛")
        else:
            gates["rd_intensity"] = {"pass": None, "detail": "暂缺近两年研发费用与同期营业收入"}
        if rd_2y is None or rd_2y[0] is None or rd_2y[1] is None:
            missing_inputs.append("rd_expenses_2y（近两年研发费用明细）")
        if prev_rev is None or prev_rev <= 0:
            missing_inputs.append("prior_revenue / annual_revenues（前一年营业收入，用于逐年复算研发强度≥3%）")
    else:
        rd_prev, rd_curr = float(rd_2y[0]), float(rd_2y[1])
        ratio_prev_raw = rd_prev / float(prev_rev) * 100.0
        ratio_curr_raw = rd_curr / float(rev_latest) * 100.0
        if is_little_giant:
            rd_sum = rd_prev + rd_curr
            ok_sum = rd_sum >= 1200.0
            ok_prev = ratio_prev_raw >= 3.0
            ok_curr = ratio_curr_raw >= 3.0
            gates["rd_2y_total"] = {"pass": ok_sum, "total_wanyuan": round(rd_sum, 4), "min_wanyuan": 1200.0}
            gates["rd_intensity"] = {
                "pass": ok_sum and ok_prev and ok_curr,
                "prior_ratio_pct": round(ratio_prev_raw, 4),
                "latest_ratio_pct": round(ratio_curr_raw, 4),
                "threshold_pct": 3.0,
            }
            if not ok_prev:
                errors.append(f"前一年研发强度 {ratio_prev_raw:.4f}% 低于2026版2号文3%硬门槛")
            if not ok_curr:
                errors.append(f"近一年研发强度 {ratio_curr_raw:.4f}% 低于2026版2号文3%硬门槛")
        else:
            ok_amt = rd_prev >= 100.0 and rd_curr >= 100.0
            ok_rat = ratio_prev_raw >= 3.0 and ratio_curr_raw >= 3.0
            gates["rd_intensity"] = {
                "pass": ok_amt and ok_rat,
                "prior_rd_wanyuan": rd_prev,
                "latest_rd_wanyuan": rd_curr,
                "prior_ratio_pct": round(ratio_prev_raw, 4),
                "latest_ratio_pct": round(ratio_curr_raw, 4),
                "min_annual_wanyuan": 100.0,
                "threshold_pct": 3.0,
            }
            if not ok_amt:
                errors.append(f"专精特新中小企业近两年研发费用({rd_prev}万 / {rd_curr}万)须每年均不低于100万元")
            if not ok_rat:
                errors.append(f"专精特新中小企业近两年研发强度({ratio_prev_raw:.4f}% / {ratio_curr_raw:.4f}%)须每年均不低于3%")

    # 4. I-Class IP: policy-fixed threshold (cannot be bypassed by caller input without verified statutory exemption)
    policy_min_i_class = 4 if is_little_giant else 1
    exempt_reason = str(data.get("ip_exemption_reason") or "").strip()
    exempt_evidence = str(data.get("ip_exemption_evidence") or "").strip()
    valid_exempt_keywords = (
        ("国家级", "科技奖", "科技进步奖", "技术发明奖", "自然科学奖")
        if is_little_giant
        else ("国家级", "省部级", "省级", "科技奖", "研发机构", "企业研究院", "重点实验室", "技术中心", "工程研究中心")
    )
    exemption_ok = bool(exempt_reason) and bool(exempt_evidence) and any(k in exempt_reason for k in valid_exempt_keywords)
    if (exempt_reason or exempt_evidence) and not exemption_ok:
        errors.append("ip_exemption_reason 须写明法定免除事由（如国家级/省部级科技奖排名前三或省级以上研发机构）并附证明材料，不得用任意文本触发豁免")
    effective_min_ip = 0 if exemption_ok else policy_min_i_class
    business_type = str(
        data.get("business_type")
        or (data.get("lockedProduct") or {}).get("businessType")
        or ""
    ).strip()
    patents = data.get("patents")
    if exemption_ok:
        gates["i_class_ip"] = {"pass": True, "exempted": True, "reason": exempt_reason, "min_required": policy_min_i_class}
    elif not isinstance(patents, list) or not patents:
        gates["i_class_ip"] = {"pass": None if not strict else False, "valid_i_class_count": 0, "min_required": policy_min_i_class}
        missing_inputs.append(f"patents（自主研发I类知识产权≥{policy_min_i_class}项核验）")
    else:
        cutoff_raw = str(data.get("stat_cutoff_date") or data.get("cutoff_date") or "").strip()
        stat_cutoff: date | None = None
        if cutoff_raw:
            try:
                stat_cutoff = date.fromisoformat(cutoff_raw[:10])
            except ValueError:
                errors.append(f"stat_cutoff_date 日期格式无效：{cutoff_raw}")
        valid_pats, p_errs, pending_certs, patent_warnings = _eval_patents(
            patents,
            ref_date,
            strict=strict,
            exclude_transferred=True,
            require_dominant_link=True,
            require_transfer_holding_1y=True,
            stat_cutoff=stat_cutoff,
            business_type=business_type,
        )
        warnings.extend(pending_certs)
        warnings.extend(patent_warnings)
        errors.extend(p_errs)
        if pending_certs:
            missing_inputs.append(f"patents（{len(pending_certs)}项待补正式ZL授权证书核验）")
        def _is_true_i_class(p: dict[str, Any]) -> bool:
            ptype = str(p.get("type") or "")
            # Utility models / design patents are strictly II-class even if caller labels ip_class="I"!
            if any(k in ptype for k in ("实用", "外观", "软著", "软件著作权")):
                return False
            pno = re.sub(r"\s+", "", str(p.get("patent_no") or p.get("no") or "")).upper()
            m_no = re.search(r"(?:ZL|CN)?((?:19|20)\d{2})(\d)\d{7}", pno)
            if m_no and m_no.group(2) in {"2", "3", "9"}:
                return False
            if "发明" in ptype or (m_no and m_no.group(2) in {"1", "8"}):
                return True
            if any(k in ptype for k in ("集成电路布图", "植物新品种", "国家级农作物", "国家新药", "国家一级中药")):
                return True
            return str(p.get("ip_class") or "").upper() == "I" and not ptype

        i_class_valid = sum(1 for p in valid_pats if _is_true_i_class(p))
        ok_ip_sme: bool | None = (i_class_valid >= effective_min_ip and not p_errs) if not pending_certs else (False if strict else None)
        gates["i_class_ip"] = {
            "pass": ok_ip_sme,
            "valid_i_class_count": i_class_valid,
            "pending_certificate_count": len(pending_certs),
            "min_required": policy_min_i_class,
        }
        if i_class_valid < effective_min_ip and (strict or not pending_certs):
            errors.append(f"去重有效自主研发I类知识产权仅 {i_class_valid} 项，低于2026版2号文 {policy_min_i_class} 项硬门槛")

    # 5. Platform quality score & explicit prerequisite / specialization / market-position hard gates
    qscore = _finite_float(data.get("quality_score"))
    score_floor = 60.0 if is_little_giant else 50.0
    if qscore is not None:
        ok_qs = qscore >= score_floor
        gates["quality_score"] = {"pass": ok_qs, "score": qscore, "min_score": score_floor}
        if not ok_qs:
            errors.append(f"发展质量评价得分 {qscore} 低于2026版2号文 {int(score_floor)} 分合格线")

    if "has_prerequisite_title" in data and data.get("has_prerequisite_title") is not None:
        ok_pre = bool(data.get("has_prerequisite_title"))
        gates["prerequisite_title"] = {"pass": ok_pre}
        if not ok_pre:
            need = "省级专精特新中小企业" if is_little_giant else "科技和创新型中小企业"
            errors.append(f"未取得前置梯度称号（{need}），不满足申报条件")

    mb_ratio = _finite_float(data.get("main_business_ratio_pct"))
    if mb_ratio is None and data.get("main_business_revenue") is not None and rev_latest and rev_latest > 0:
        mb_rev = _finite_float(data.get("main_business_revenue"))
        if mb_rev is not None:
            mb_ratio = mb_rev / rev_latest * 100.0
    mb_floor = 90.0 if is_little_giant else 80.0
    if mb_ratio is not None:
        ok_mb = mb_ratio >= mb_floor
        gates["main_business_ratio"] = {"pass": ok_mb, "ratio_pct": round(mb_ratio, 4), "min_pct": mb_floor}
        if not ok_mb:
            errors.append(f"主营业务收入占比 {mb_ratio:.2f}% 低于2026版2号文 {int(mb_floor)}% 红线")

    niche_years = _finite_float(data.get("niche_years"))
    if niche_years is not None:
        ok_ny = niche_years >= 3.0
        gates["niche_years"] = {"pass": ok_ny, "years": niche_years, "min_years": 3}
        if not ok_ny:
            errors.append(f"从事特定细分市场仅 {niche_years:g} 年，不满3年红线")

    if is_little_giant and (data.get("market_share_pct") is not None or data.get("domestic_rank") is not None):
        ms_pct = _finite_float(data.get("market_share_pct"))
        d_rank = _finite_float(data.get("domestic_rank"))
        ok_ms = (ms_pct is not None and ms_pct >= 10.0) or (d_rank is not None and 1.0 <= d_rank <= 3.0)
        gates["market_position"] = {"pass": ok_ms, "market_share_pct": ms_pct, "domestic_rank": d_rank}
        if not ok_ms:
            errors.append(f"细分市场占有率({ms_pct}%)低于10%且国内排名({d_rank})未进入前三，不满足小巨人市场地位门槛")

    strict_ok = len(errors) == 0 and len(missing_inputs) == 0
    if errors:
        status = "fail"
    elif missing_inputs:
        status = "fail" if strict else "partial_pass"
    else:
        status = "pass"
    return {
        "program": f"sme_{tier}",
        "application_type": "review" if is_review else "recognition",
        "policy_basis": "工信部企业〔2026〕2号《优质中小企业梯度培育管理办法》 + 工信厅企业函〔2026〕117号",
        "status": status,
        "ok": strict_ok if strict else (len(errors) == 0),
        "gates": gates,
        "errors": errors,
        "missing_inputs": missing_inputs,
        "warnings": warnings,
    }


def validate_policy_metadata(meta: dict[str, Any], as_of: date | None = None) -> dict[str, Any]:
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

    p_ht = sub.add_parser("hightech", help="高新技术企业9大硬条件自动化复算（默认允许部分体检，--strict 终审阻断缺项）")
    p_ht.add_argument("--input", type=Path, required=True)
    p_ht.add_argument("--strict", action="store_true")

    p_sme = sub.add_parser("sme", help="专精特新/小巨人（2026版2号文+117号文）自动化复算")
    p_sme.add_argument("--input", type=Path, required=True)
    p_sme.add_argument("--stat-cutoff", default="", help="可选：批次统计截止日（如 2025-12-31），用于过滤期后授权专利")
    p_sme.add_argument("--strict", action="store_true")

    p_pol = sub.add_parser("policy", help="洁净检索本地政策库并校验证件有效期与省市区县层级")
    p_pol.add_argument("--query", default="")
    p_pol.add_argument("--region", default="")
    p_pol.add_argument("--metadata-json", type=Path, default=None)
    p_pol.add_argument("--limit", type=int, default=6)
    p_pol.add_argument("--strict", action="store_true")

    p_peer = sub.add_parser("peers", help="查询去重可比同行名单，支持按申报当年回溯统计与侧挂时间轴缓存关联")
    p_peer.add_argument("--project", required=True)
    p_peer.add_argument("--region", default="")
    p_peer.add_argument("--industry", default="")
    p_peer.add_argument("--year", type=int, default=None, help="可选：按认定年度过滤（防止跨届混算）")
    p_peer.add_argument("--exclude-review", action="store_true", help="可选：剔除到期复核，仅保留新认定")
    p_peer.add_argument("--apply-date", default="", help="可选：显式指定申报基准日（如 2025-12-28）")
    p_peer.add_argument("--benchmark", action="store_true", help="可选：输出按批次拆分的事前/事后时点对齐汇总")
    p_peer.add_argument("--cache-db", type=Path, default=None, help="可选：指定侧挂时间轴缓存库路径")
    p_peer.add_argument("--limit", type=int, default=15)

    p_ci = sub.add_parser("cache-ingest", help="将外部接口拉取的专利/荣誉明细写入侧挂懒加载时间轴缓存库")
    p_ci.add_argument("--type", choices=["patent", "honor"], required=True)
    p_ci.add_argument("--uscc", required=True, help="18位统一社会信用代码")
    p_ci.add_argument("--company", default="", help="可选：企业全称")
    p_ci.add_argument("--dimension", default="patent_granted_inv", help="专利缓存维度（默认 patent_granted_inv）")
    p_ci.add_argument("--source", default="qcc", help="数据来源标记（默认 qcc）")
    p_ci.add_argument("--fetched-at", default="", help="可选：拉取时间 ISO8601（默认当前时间）")
    p_ci.add_argument("--input", required=True, help="JSON 文件路径，或传 - 从标准输入读取")
    p_ci.add_argument("--cache-db", type=Path, default=None)

    p_cq = sub.add_parser("cache-query", help="按指定申报基准日从侧挂缓存库回溯单家企业当年有效专利与荣誉")
    p_cq.add_argument("--uscc", required=True)
    p_cq.add_argument("--as-of", required=True, help="回溯基准日 YYYY-MM-DD")
    p_cq.add_argument("--cache-db", type=Path, default=None)

    p_cat = sub.add_parser("catalog", help="叶节点加权检索《产业链架构》与《产业基础目录(2021)》")
    p_cat.add_argument("query")
    p_cat.add_argument("--limit", type=int, default=8)

    args = parser.parse_args()
    if args.cmd == "profile":
        res = kb_local.query_enterprise(args.company, credit_code=args.credit_code)
        if res.get("found"):
            res["status"] = "found"
            ent = res["enterprise"]
            res["region_scope"] = kb_local.resolve_region_scope(
                f"{ent.get('province', '')}{ent.get('city', '')}{ent.get('county', '')}"
            )
            if args.write_blackboard and args.workspace:
                uscc = str(ent.get("unified_social_credit_code") or "")
                def _merge_profile(bb: dict[str, Any]) -> None:
                    bb.setdefault("financialFacts", {})["local_kb_records"] = res["financials"]
                    bb.setdefault("checkupSnapshots", {})["profile_recognitions_count"] = len(res["recognitions"])
                saved = fact_ledger.update_blackboard(args.workspace, ent["name"], uscc, _merge_profile, strict=True)
                res["blackboard_path"] = str(saved)
        elif res.get("subject_conflict"):
            res["status"] = "subject_conflict"
        elif res.get("ambiguous"):
            res["status"] = "ambiguous"
        elif res.get("credit_code_not_found"):
            res["status"] = "credit_code_not_found"
        else:
            res["status"] = "not_found" if not res.get("error") else "error"
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 2 if res.get("status") in {"error", "subject_conflict"} else 0

    if args.cmd == "hightech":
        data = json.loads(args.input.read_text(encoding="utf-8"))
        res = check_hightech(data, strict=args.strict)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if (res["ok"] or not args.strict) else 2

    if args.cmd == "sme":
        data = json.loads(args.input.read_text(encoding="utf-8"))
        if getattr(args, "stat_cutoff", ""):
            data = dict(data)
            data["stat_cutoff_date"] = args.stat_cutoff
        res = check_sme(data, strict=args.strict)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if (res["ok"] or not args.strict) else 2

    if args.cmd == "policy":
        out: dict[str, Any] = {"ok": True, "status": "matched", "errors": []}
        region_scope = kb_local.resolve_region_scope(args.region) if args.region else None
        if region_scope:
            out["region_scope"] = region_scope
        if args.query:
            rag_res = kb_local.search_local_rag(args.query, limit=args.limit)
            out["rag"] = rag_res
            if rag_res.get("error"):
                out["ok"] = False
                out["status"] = "backend_error"
                out["errors"].append(f"本地政策检索后端不可用：{rag_res['error']}")
            else:
                invalid_statuses = {"expired", "repealed", "superseded", "invalid", "historical_reference", "废止", "失效"}
                valid_hits = []
                dropped_region = 0
                dropped_invalid = 0
                target_scopes = set(region_scope["scopes"]) if region_scope else set()
                target_prov = region_scope.get("province", "") if region_scope else ""
                target_city = region_scope.get("city", "") if region_scope else ""
                for item in rag_res.get("results", []):
                    vstat = str(item.get("validity_status") or "").strip().lower()
                    if vstat in invalid_statuses:
                        dropped_invalid += 1
                        continue
                    if region_scope:
                        item_region_text = f"{item.get('region') or ''} {item.get('title') or ''}"
                        item_scope = kb_local.resolve_region_scope(item_region_text)
                        is_national = ("国家" in item_region_text or "全国" in item_region_text or "工信部" in item_region_text or "科技部" in item_region_text) and not item_scope["province"]
                        if not is_national and item_scope["province"]:
                            if target_prov and item_scope["province"] != target_prov:
                                dropped_region += 1
                                continue
                            if target_city and item_scope["city"] and item_scope["city"] != target_city:
                                dropped_region += 1
                                continue
                            if region_scope.get("district") and item_scope["district"] and item_scope["district"] != region_scope["district"]:
                                dropped_region += 1
                                continue
                    valid_hits.append(item)
                out["matched_policies"] = valid_hits
                out["matched_count"] = len(valid_hits)
                out["filtered_out"] = {"region_mismatch": dropped_region, "invalid_status": dropped_invalid}
                if not valid_hits:
                    out["status"] = "no_match"
                    if args.strict:
                        out["ok"] = False
                        out["errors"].append(f"未检索到匹配辖区({args.region or '不限'})且现行有效的政策原文（跨区剔除{dropped_region}条，失效剔除{dropped_invalid}条）")
        if args.metadata_json:
            val = validate_policy_metadata(json.loads(args.metadata_json.read_text(encoding="utf-8")))
            out["metadata_validation"] = val
            if not val["ok"]:
                out["ok"] = False
                out["status"] = "invalid_metadata"
                out["errors"].extend(val["errors"])
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if (out["ok"] or not args.strict) else 2

    if args.cmd == "peers":
        res = kb_local.query_peers(
            args.project,
            args.region,
            args.industry,
            args.limit,
            year=args.year,
            exclude_review=args.exclude_review,
            apply_date=args.apply_date,
            benchmark=args.benchmark,
            cache_path=args.cache_db,
        )
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if not res.get("error") else 2

    if args.cmd == "cache-ingest":
        raw_text = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8")
        payload = json.loads(raw_text)
        if args.type == "patent":
            res = timeline_cache.ingest_patents(
                args.uscc,
                payload,
                enterprise_name=args.company,
                dimension=args.dimension,
                source=args.source,
                fetched_at=args.fetched_at or None,
                cache_path=args.cache_db,
            )
        else:
            res = timeline_cache.ingest_honors(
                args.uscc,
                payload,
                enterprise_name=args.company,
                source=args.source,
                fetched_at=args.fetched_at or None,
                cache_path=args.cache_db,
            )
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res.get("ok") else 2

    if args.cmd == "cache-query":
        res = timeline_cache.query_at_date(args.uscc, args.as_of, cache_path=args.cache_db)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "catalog":
        res = search_catalogs.search_catalogs(args.query, SKILL_ROOT / "references", args.limit)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
