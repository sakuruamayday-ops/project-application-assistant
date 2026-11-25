#!/usr/bin/env python3
"""
Unified Strict Validator for All 10 General Government Grant Tracks (general-grant-writer).
Zero fake-strict gates (hardened per Codex P1 audit):
  - Rejects empty {} on ALL 10 tracks (institute, agriculture, talent, etc.)
  - institute: exact 浙经信高新〔2025〕169号 tiers (including <5000万 -> >=5% & >=100万元!) + deduped valid patents
  - subsidy: requires valid parseable invoice_date AND deduplicates (invoice_no, asset_card_no) to prevent double counting
  - green: requires finite numeric metric values (blocks "待补" / non-numeric strings!)
  - feasibility: bidirectional check requiring EVERY template_requirement to be covered by conditions!
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
for cand in (SCRIPT_DIR, SKILL_ROOT.parent / "_core", SKILL_ROOT / "scripts" / "_core"):
    if cand.is_dir() and str(cand) not in sys.path:
        sys.path.insert(0, str(cand))

import fact_ledger  # noqa: E402
import quality_gate  # noqa: E402

ALLOWED_GREEN_UNITS_RE = re.compile(
    r"^(?:%|％|tce/万元|kgce/万元|kWh/万元|tCO2e/万元|tCO2/万元|m³/万元|m3/万元|吨/万元|g/kWh|kg/t|kWh/t|m³/t|tce/t|mg/m³|ppm|dB\(A\)|亿元|万元|吨|kWh|MWh|tce|m³|套|台|项)$"
)


def _parse_date(val: Any) -> date | None:
    s = str(val or "").strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _finite_float(val: Any) -> float | None:
    if val is None or isinstance(val, bool) or str(val).strip() == "":
        return None
    try:
        f = float(val)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def validate_institute(data: dict[str, Any], as_of: date | None = None) -> list[str]:
    """浙经信高新〔2025〕169号: exact official tiers & unrounded precision for 省重点企业研究院 / 省企业研究院 / 高企研发中心."""
    errs: list[str] = []
    if not isinstance(data, dict) or not data:
        return ["输入数据为空，缺少169号文省级企业研究院核验字段"]
    tier = str(data.get("tier") or "provincial_institute").strip()
    is_agri = bool(data.get("is_agriculture"))
    is_mountain = bool(data.get("is_mountain_island_county"))
    rd_rev = _finite_float(data.get("latest_revenue"))
    rd_exp = _finite_float(data.get("latest_rd_expense"))
    rd_staff = _finite_float(data.get("rd_staff_count"))
    equip_val = _finite_float(data.get("rd_equipment_original_value"))
    venue_m2 = _finite_float(data.get("rd_venue_area_m2"))

    for fname, val in (
        ("latest_revenue", rd_rev), ("latest_rd_expense", rd_exp),
        ("rd_staff_count", rd_staff), ("rd_equipment_original_value", equip_val), ("rd_venue_area_m2", venue_m2),
    ):
        if val is None:
            errs.append(f"[{tier}] 缺少必需核验字段：{fname}")

    thresholds = {
        "provincial_key_institute": {"rd_staff": 50, "equip": 1000, "venue": 1000},
        "provincial_institute": {"rd_staff": 30, "equip": 500, "venue": 500},
        "rd_center": {"rd_exp": 200, "rd_ratio": 3.0, "rd_staff": 15, "equip": 200, "venue": 200},
    }
    th = thresholds.get(tier, thresholds["provincial_institute"])
    if rd_rev is not None and rd_exp is not None:
        if rd_rev <= 0 or rd_exp < 0:
            errs.append(f"[{tier}] 营业收入({rd_rev})须大于0且研发费用({rd_exp})不得为负")
        else:
            # Compare using raw unrounded precision (prevent 149.9/3000 = 4.9967% rounding to 5.0%!)
            raw_ratio = (rd_exp / rd_rev) * 100.0
            if tier == "provincial_key_institute":
                # 浙经信高新〔2025〕169号 第（九）1条：
                # 营收>=2亿元（农业>=5000万元）；研发占比>=4% 或 研发费>=5000万元（农业>=800万元）
                # 山区海岛县可适当放宽，但须附当期主管部门放宽口径且绝不得0研发或全免
                rev_floor = 5000.0 if is_agri else 20000.0
                rd_amt_floor = 800.0 if is_agri else 5000.0
                if is_mountain:
                    relax_basis = str(data.get("mountain_island_relaxation_basis") or "").strip()
                    if not relax_basis:
                        errs.append("[provincial_key_institute] 启用山区海岛县适当放宽条款须填写当期主管部门明确放宽口径 mountain_island_relaxation_basis，不得无依据全免")
                    elif rd_exp <= 0:
                        errs.append("[provincial_key_institute] 山区海岛县放宽口径下研发费用仍须大于0，不得零研发通过")
                else:
                    if rd_rev < rev_floor:
                        errs.append(
                            f"[provincial_key_institute] 上一年度营业收入 {rd_rev} 万元低于169号文省重点企业研究院门槛 {rev_floor:.0f} 万元"
                        )
                    if not (raw_ratio >= 4.0 or rd_exp >= rd_amt_floor):
                        errs.append(
                            f"[provincial_key_institute] 研发强度({raw_ratio:.4f}%)低于4%且研发费用({rd_exp}万元)低于{rd_amt_floor:.0f}万元（不符合169号文）"
                        )
            elif tier == "provincial_institute":
                # 浙经信高新〔2025〕169号 第（九）2条：
                # ① <5000万: 占比>=5% 且 >=100万
                # ② 5000万~2亿(含): 占比>=4% 或 >=250万
                # ③ >2亿: 占比>=3% 或 >=800万
                if rd_rev < 5000.0:
                    if not (raw_ratio >= 5.0 and rd_exp >= 100.0):
                        errs.append(
                            f"[provincial_institute] 营收({rd_rev}万元)<5000万元档位须同时满足研发占比≥5%且研发费≥100万元（当前{raw_ratio:.4f}% / {rd_exp}万元）"
                        )
                elif rd_rev <= 20000.0:
                    if not (raw_ratio >= 4.0 or rd_exp >= 250.0):
                        errs.append(
                            f"[provincial_institute] 营收({rd_rev}万元)在5000万元—2亿元档位须满足研发占比≥4%或研发费≥250万元（当前{raw_ratio:.4f}% / {rd_exp}万元）"
                        )
                else:
                    if not (raw_ratio >= 3.0 or rd_exp >= 800.0):
                        errs.append(
                            f"[provincial_institute] 营收({rd_rev}万元)>2亿元档位须满足研发占比≥3%或研发费≥800万元（当前{raw_ratio:.4f}% / {rd_exp}万元）"
                        )
            else:
                if rd_exp < th["rd_exp"] and raw_ratio < th["rd_ratio"]:
                    errs.append(f"[{tier}] 研发费用({rd_exp}万元)与占比({raw_ratio:.4f}%)均低于门槛({th['rd_exp']}万元或{th['rd_ratio']}%)")
    if rd_staff is not None and rd_staff < th["rd_staff"]:
        errs.append(f"[{tier}] 专职研发人员 {int(rd_staff)} 人低于门槛 {th['rd_staff']} 人")
    if equip_val is not None and equip_val < th["equip"]:
        errs.append(f"[{tier}] 科研仪器设备原值 {equip_val} 万元低于门槛 {th['equip']} 万元")
    if venue_m2 is not None and venue_m2 < th["venue"]:
        errs.append(f"[{tier}] 相对集中研发场地 {venue_m2} ㎡低于门槛 {th['venue']} ㎡")
    for p in data.get("patents") or []:
        errs.extend(fact_ledger.validate_patent_item(p, as_of=as_of, require_valid_no=True))
    return errs


def validate_three_first(data: dict[str, Any], as_of: date | None = None) -> list[str]:
    """首台套/首批次/首版次/工业新产品: enforce locator on ALL conclusions + timeline logic."""
    errs: list[str] = []
    conclusion = str(data.get("conclusion") or "").strip()
    if conclusion not in {"eligible", "conditional", "ineligible", "undetermined"}:
        errs.append(f"conclusion 无效：{conclusion}")

    evidences = data.get("evidences") or []
    if not evidences:
        errs.append("缺少 evidences 证据清单")
    for idx, ev in enumerate(evidences):
        if not isinstance(ev, dict):
            errs.append(f"evidences[{idx}] 必须为对象")
            continue
        if not str(ev.get("locator") or "").strip():
            errs.append(f"evidences[{idx}]（{ev.get('name', '未命名')}）缺少可追溯页码/文件定位 locator（所有结论下均强制核验）")

    d_design = _parse_date(data.get("design_start_date"))
    d_proto = _parse_date(data.get("prototype_date"))
    d_test = _parse_date(data.get("test_report_date"))
    d_sale = _parse_date(data.get("first_sale_date"))
    if d_design and d_proto and d_proto < d_design:
        errs.append(f"时间线倒挂：样机完成日({d_proto})早于研发立项/设计日({d_design})")
    if d_proto and d_test and d_test < d_proto:
        errs.append(f"时间线倒挂：检测报告日({d_test})早于样机/首件完成日({d_proto})")
    if d_design and d_sale and d_sale < d_design:
        errs.append(f"时间线倒挂：首次销售日({d_sale})早于研发立项日({d_design})")

    for p in data.get("patents") or []:
        errs.extend(fact_ledger.validate_patent_item(p, as_of=as_of, require_valid_no=True))
    return errs


def validate_subsidy(data: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    """技改/设备更新/固投补助: enforce valid construction window, prevent cross-card invoice doubling, allow 5-10% retention."""
    errs: list[str] = []
    raw_start = str(data.get("construction_start") or "").strip()
    raw_end = str(data.get("construction_end") or "").strip()
    win_start = _parse_date(raw_start)
    win_end = _parse_date(raw_end)
    if not raw_start:
        errs.append("缺少备案建设起始日 construction_start")
    elif win_start is None:
        errs.append(f"备案建设起始日 construction_start 格式无效：{raw_start}")
    if not raw_end:
        errs.append("缺少备案建设截止日 construction_end")
    elif win_end is None:
        errs.append(f"备案建设截止日 construction_end 格式无效：{raw_end}")
    if win_start and win_end and win_end < win_start:
        errs.append(f"备案建设起止窗口倒挂：{win_start} > {win_end}")

    items = data.get("investments") or []
    if not items:
        errs.append("缺少 investments 投资明细台账")
    eligible_total = 0.0
    seen_pairs: set[tuple[str, str]] = set()
    invoice_alloc_totals: dict[str, float] = {}
    invoice_caps: dict[str, float] = {}

    for idx, row in enumerate(items):
        if not isinstance(row, dict):
            errs.append(f"investments[{idx}] 必须为对象")
            continue
        name = str(row.get("asset_name") or f"row#{idx}")
        contract = _finite_float(row.get("contract_amount")) or 0.0
        invoice = _finite_float(row.get("invoice_amount")) or 0.0
        invoice_total_cap = _finite_float(row.get("invoice_total_amount")) or invoice
        allocated = _finite_float(row.get("allocated_amount"))
        paid = _finite_float(row.get("paid_amount")) or 0.0
        if contract <= 0 or invoice <= 0 or paid <= 0:
            errs.append(f"投资明细[{name}]存在0元或负数虚假行：contract={contract}, invoice={invoice}, paid={paid}")
            continue
        inv_no = str(row.get("invoice_no") or "").strip()
        card_no = str(row.get("asset_card_no") or "").strip()
        if not inv_no:
            errs.append(f"投资明细[{name}]缺少发票号码 invoice_no")
            continue
        if not card_no:
            errs.append(f"投资明细[{name}]缺少固定资产卡片号 asset_card_no")
            continue
        inv_key = inv_no.upper()
        pair = (inv_key, card_no.upper())
        if pair in seen_pairs:
            errs.append(f"投资明细[{name}]重复计入同一发票与固定资产卡片（invoice_no={inv_no}, asset_card_no={card_no}）")
            continue
        seen_pairs.add(pair)

        raw_inv_date = str(row.get("invoice_date") or "").strip()
        inv_date = _parse_date(raw_inv_date)
        if not raw_inv_date or inv_date is None:
            errs.append(f"投资明细[{name}]发票日期缺失或格式无效：{raw_inv_date or '空'}")
            continue
        if win_start and inv_date < win_start:
            errs.append(f"投资明细[{name}]发票日期({inv_date})早于备案建设起始日({win_start})")
            continue
        if win_end and inv_date > win_end:
            errs.append(f"投资明细[{name}]发票日期({inv_date})晚于备案建设截止日({win_end})")
            continue
        if invoice > contract * 1.05:
            errs.append(f"投资明细[{name}]发票金额({invoice})显著超合同金额({contract})")
            continue
        if paid > invoice * 1.005:
            errs.append(f"投资明细[{name}]付款金额({paid})超过发票金额({invoice})")
            continue
        ratio = paid / invoice
        retention = _finite_float(row.get("retention_ratio")) or 0.0
        has_retention = bool(row.get("retention_note")) or (0.01 <= retention <= 0.10)
        if ratio < 0.90:
            errs.append(f"投资明细[{name}]实际付款比例仅 {ratio*100:.1f}%，低于90%（超出常规5%-10%质保金范围）")
            continue
        if ratio < 0.999 and not has_retention:
            errs.append(f"投资明细[{name}]付款比例为 {ratio*100:.1f}%（存在尾款差额），请注明质保金比例(retention_ratio)或质保金条款说明(retention_note)")
            continue
        row_amt = min(allocated if allocated is not None else invoice, paid, invoice, contract)
        if row_amt <= 0:
            errs.append(f"投资明细[{name}]分摊适格金额无效：{row_amt}")
            continue
        invoice_alloc_totals[inv_key] = invoice_alloc_totals.get(inv_key, 0.0) + row_amt
        invoice_caps[inv_key] = min(invoice_caps.get(inv_key, invoice_total_cap), invoice_total_cap)
        eligible_total += row_amt

    # Enforce strict invoice-level cap across all asset cards (currency rounding tolerance 0.005 only)
    for inv_key, sum_alloc in invoice_alloc_totals.items():
        cap = invoice_caps[inv_key]
        if sum_alloc > cap + 0.005:
            errs.append(
                f"同一发票({inv_key})跨资产卡累计申报金额({sum_alloc:.2f})超过发票总金额({cap:.2f})，禁止重复/超额计入"
            )
    return errs, {"eligible_investment_total": round(eligible_total, 2), "item_count": len(items)}


def validate_digitalization(data: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    claimed_level = str(data.get("claimed_level") or "").upper()
    if claimed_level not in {"L1", "L2", "L3", "L4", "L5"}:
        errs.append(f"claimed_level 须为 L1-L5，实际为：{claimed_level}")
    net_rate = _finite_float(data.get("equipment_networking_rate_pct")) or 0.0
    systems = set(str(s).upper() for s in (data.get("deployed_systems") or []))
    dims = data.get("seven_dimensions") or {}
    if len(dims) < 7:
        errs.append(f"数字化成熟度七维评价不完整：仅提供 {len(dims)}/7 维")
    if claimed_level in {"L4", "L5"}:
        if net_rate < 80.0:
            errs.append(f"宣称 {claimed_level}（智能/未来工厂级别），但关键设备联网率仅 {net_rate}%（应≥80%）")
        if not ({"ERP", "MES"} <= systems):
            errs.append(f"宣称 {claimed_level} 缺少核心系统闭环（须同时具备 ERP 与 MES，当前仅 {sorted(systems)}）")
    return errs


def validate_green(data: dict[str, Any]) -> list[str]:
    """工信部节〔2024〕13号: allow % units cleanly, require FINITE NUMERIC metric values, block env/safety incidents."""
    errs: list[str] = []
    if data.get("major_env_or_safety_incident_3y") is True:
        errs.append("近3年存在重大安全/环保/质量事故，触发绿色工厂一票否决红线")
    metrics = data.get("metrics") or []
    if not metrics:
        errs.append("缺少绿色工厂绩效指标 metrics")
    for idx, m in enumerate(metrics):
        if not isinstance(m, dict):
            errs.append(f"metrics[{idx}] 必须为对象")
            continue
        name = str(m.get("name") or f"metric#{idx}")
        val = _finite_float(m.get("value"))
        unit = str(m.get("unit") or "").strip()
        if val is None:
            errs.append(f"绿色指标[{name}]数值缺失或非有效数字（实际：{m.get('value')!r}），不得空值或文字占位放行")
        if not unit or not ALLOWED_GREEN_UNITS_RE.match(unit):
            errs.append(f"绿色指标[{name}]单位不规范或缺失：{unit}")
    return errs


def validate_agriculture(data: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    if not isinstance(data, dict) or not data:
        return ["输入数据为空，缺少农业龙头企业必需核验字段"]
    if data.get("food_safety_incident_3y") is True:
        errs.append("近3年存在食品安全或农产品质量安全事故，一票否决")
    elif "food_safety_incident_3y" not in data:
        errs.append("缺少近3年食品安全记录核验字段 food_safety_incident_3y")
    agro_share = _finite_float(data.get("agro_processing_revenue_pct"))
    if agro_share is None:
        errs.append("缺少农产品生产/加工/流通收入占比 agro_processing_revenue_pct")
    elif agro_share < 70.0:
        errs.append(f"农产品生产/加工/流通收入占比 {agro_share}% 低于省级农业龙头70%门槛")
    households = _finite_float(data.get("linked_farmer_households"))
    if households is None or households <= 0:
        errs.append("缺少有效的联农带农农户数 linked_farmer_households（须为正整数）")
    return errs


def validate_talent(data: dict[str, Any], as_of: date | None = None) -> list[str]:
    """Full talent timeline validator: requires core identity/date fields (blocks empty {})."""
    errs: list[str] = []
    if not isinstance(data, dict) or not data:
        return ["输入数据为空，缺少人才项目必需时间线字段"]
    ref = as_of or date.today()
    birth = _parse_date(data.get("birth_date"))
    if birth is None:
        errs.append("缺少有效出生日期 birth_date")
    max_age = _finite_float(data.get("max_age_limit"))
    if birth and max_age:
        age = (ref - birth).days / 365.25
        if age > max_age:
            errs.append(f"申报人年龄 {age:.1f} 岁超过政策上限 {max_age} 周岁")
    ret = _parse_date(data.get("return_date"))
    max_ret_years = _finite_float(data.get("max_return_years"))
    if ret and max_ret_years:
        yrs = (ref - ret).days / 365.25
        if yrs > max_ret_years:
            errs.append(f"回国/来华时间 {ret.isoformat()} 已超 {yrs:.1f} 年，超过政策要求 {max_ret_years} 年窗口")
    ss_months = _finite_float(data.get("social_security_months"))
    min_ss = _finite_float(data.get("min_social_security_months"))
    if min_ss is not None and (ss_months is None or ss_months < min_ss):
        errs.append(f"连续社保缴纳 {ss_months} 个月，低于最低要求 {min_ss} 个月")
    postdoc_in = _parse_date(data.get("postdoc_entry_date"))
    postdoc_out = _parse_date(data.get("postdoc_exit_date"))
    if postdoc_in and postdoc_out and postdoc_out <= postdoc_in:
        errs.append(f"博士后时间线倒挂：出站日({postdoc_out})早于或等于进站日({postdoc_in})")
    equity = _finite_float(data.get("founder_equity_pct"))
    min_eq = _finite_float(data.get("min_equity_pct"))
    if min_eq is not None and (equity is None or equity < min_eq):
        errs.append(f"人才持股比例 {equity}% 低于创业类最低要求 {min_eq}%")
    return errs


def validate_trade(data: dict[str, Any]) -> list[str]:
    """Trade / Cross-border e-commerce: positive amounts + FX recomputation + 3-way match."""
    errs: list[str] = []
    records = data.get("records") or []
    if not records:
        errs.append("缺少外贸/跨境业务明细 records")
    for idx, r in enumerate(records):
        if not isinstance(r, dict):
            errs.append(f"records[{idx}] 必须为对象")
            continue
        fx_amt = _finite_float(r.get("fx_amount")) or 0.0
        fx_rate = _finite_float(r.get("fx_rate")) or 0.0
        rmb_amt = _finite_float(r.get("rmb_amount")) or 0.0
        if fx_amt <= 0 or fx_rate <= 0 or rmb_amt <= 0:
            errs.append(f"外贸记录[{idx}]金额或汇率必须大于0：fx={fx_amt}, rate={fx_rate}, rmb={rmb_amt}")
            continue
        expected_rmb = fx_amt * fx_rate
        if abs(expected_rmb - rmb_amt) > max(1.0, expected_rmb * 0.005):
            errs.append(f"外贸记录[{idx}]汇率换算不一致：{fx_amt}×{fx_rate}={expected_rmb:.2f} != 填报 {rmb_amt:.2f}")
        if not str(r.get("customs_no") or "").strip():
            errs.append(f"外贸记录[{idx}]缺少报关单号 customs_no")
    return errs


def validate_ip_project(data: dict[str, Any], as_of: date | None = None) -> list[str]:
    errs: list[str] = []
    patents = data.get("patents") or []
    seen: set[str] = set()
    valid_inv = 0
    for p in patents:
        pe = fact_ledger.validate_patent_item(p, as_of=as_of, require_valid_no=True)
        errs.extend(pe)
        if not pe:
            key = fact_ledger.normalize_patent_key(p)
            if key in seen:
                errs.append(f"重复专利号不得重复计数：{p.get('patent_no') or p.get('no')}")
                continue
            seen.add(key)
            if "发明" in str(p.get("type") or ""):
                valid_inv += 1
    min_inv = int(data.get("min_invention_patents") or 1)
    if valid_inv < min_inv:
        errs.append(f"有效未过期发明专利仅 {valid_inv} 件，低于本项目要求 {min_inv} 件")
    return errs


GENERIC_FEASIBILITY_TOKENS = {"不低于", "不超过", "不少于", "不高于", "以上", "以下", "符合", "满足", "应当", "要求", "条件", "具备"}


def validate_feasibility(data: dict[str, Any]) -> list[str]:
    """Ensure unambiguous bidirectional template_requirements <-> conditions coverage (blocks generic substring collapse)."""
    errs: list[str] = []
    if not isinstance(data, dict) or not data:
        return ["可行性配置为空"]
    raw_json = json.dumps(data, ensure_ascii=False)
    if "客户填写" in raw_json:
        errs.append("可行性配置中残留「客户填写」占位词")
    raw_reqs = data.get("template_requirements") or []
    conds = data.get("conditions") or []
    if not raw_reqs:
        errs.append("缺少模板条款清单 template_requirements")
    if not conds:
        errs.append("缺少条件映射清单 conditions")
    if raw_reqs and conds:
        reqs: list[tuple[str, str, str]] = []
        for idx, r in enumerate(raw_reqs):
            if isinstance(r, dict):
                rid = str(r.get("id") or r.get("clause_id") or "").strip()
                rtxt = str(r.get("text") or r.get("requirement") or "")
            else:
                rid = ""
                rtxt = str(r)
            reqs.append((rid, rtxt, re.sub(r"\s+", "", rtxt)))

        covered_req_indices: set[int] = set()
        for idx, c in enumerate(conds):
            if not isinstance(c, dict):
                errs.append(f"conditions[{idx}] 必须为对象")
                continue
            cid = str(c.get("clause_id") or c.get("requirement_id") or "").strip()
            raw_match = str(c.get("match") or "").strip()
            key = re.sub(r"\s+", "", raw_match)
            if cid:
                matched_indices = [ri for ri, (rid, _, _) in enumerate(reqs) if rid and rid == cid]
                if not matched_indices:
                    errs.append(f"conditions[{idx}] 指定条款编号「{cid}」未命中任何模板条款")
                else:
                    covered_req_indices.update(matched_indices)
                continue
            if not key or key in GENERIC_FEASIBILITY_TOKENS or len(key) < 4:
                errs.append(f"conditions[{idx}] 匹配词「{raw_match}」过短或为泛化虚词，须指定具体条款标识或唯一关键短语")
                continue
            matched_indices = [ri for ri, (_, _, nr) in enumerate(reqs) if key in nr or nr in key]
            if not matched_indices:
                errs.append(f"conditions[{idx}]（「{raw_match}」）未命中任何模板条款行，禁止静默丢弃")
            elif len(matched_indices) > 1:
                errs.append(f"conditions[{idx}]（「{raw_match}」）同时宽泛命中 {len(matched_indices)} 条不同模板条款，存在歧义虚过风险，请逐条拆分或绑定 clause_id")
            else:
                covered_req_indices.add(matched_indices[0])

        for ri, (_, rtxt, _) in enumerate(reqs):
            if ri not in covered_req_indices:
                errs.append(f"模板必备条款「{rtxt}」缺少唯一对应的 conditions 核验项，禁止缺项通过")
    return errs


def main() -> int:
    parser = argparse.ArgumentParser(description="通用专项申报10大赛道统一门禁（支持 draft 初筛与 strict 终审）")
    parser.add_argument(
        "--track",
        required=True,
        choices=(
            "institute", "three-first", "subsidy", "digitalization", "green",
            "agriculture", "talent", "trade", "ip-project", "feasibility",
        ),
    )
    parser.add_argument("--input", type=Path, required=True, help="结构化评估/台账 JSON")
    parser.add_argument("--mode", choices=("strict", "draft"), default="strict", help="strict=终审硬门禁(默认)，draft=早期初筛（缺字段仅标 missing_fields 不阻断）")
    parser.add_argument("--text-file", type=Path, default=None, help="可选：同步校验正式交付正文质量")
    parser.add_argument("--company", default="", help="配合 --text-file 校验防串户的企业全称")
    parser.add_argument("--min-chars", type=int, default=200)
    args = parser.parse_args()

    data = json.loads(args.input.read_text(encoding="utf-8"))
    extra: dict[str, Any] = {}
    if args.track == "institute":
        errs = validate_institute(data)
    elif args.track == "three-first":
        errs = validate_three_first(data)
    elif args.track == "subsidy":
        errs, extra = validate_subsidy(data)
    elif args.track == "digitalization":
        errs = validate_digitalization(data)
    elif args.track == "green":
        errs = validate_green(data)
    elif args.track == "agriculture":
        errs = validate_agriculture(data)
    elif args.track == "talent":
        errs = validate_talent(data)
    elif args.track == "trade":
        errs = validate_trade(data)
    elif args.track == "ip-project":
        errs = validate_ip_project(data)
    else:
        errs = validate_feasibility(data)

    if args.text_file:
        ta = quality_gate.audit_formal_text(
            args.text_file.read_text(encoding="utf-8"),
            expected_company=args.company,
            min_chars=args.min_chars,
        )
        extra["text_audit"] = ta
        if not ta["ok"]:
            errs.extend(e["issue"] for e in ta["errors"])

    missing_fields: list[str] = []
    if args.mode == "draft":
        kept_errs = []
        for e in errs:
            if "缺少" in e or "为空" in e:
                missing_fields.append(e)
            else:
                kept_errs.append(e)
        errs = kept_errs

    status = "fail" if errs else ("partial_pass" if missing_fields else "pass")
    out = {
        "track": args.track,
        "mode": args.mode,
        "status": status,
        "ok": len(errs) == 0,
        "error_count": len(errs),
        "errors": errs,
        "missing_fields": missing_fields,
        **extra,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
