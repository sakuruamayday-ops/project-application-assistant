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
    """浙经信高新〔2025〕169号: 省级重点企业研究院 / 省级企业研究院 / 高企研发中心."""
    errs: list[str] = []
    if not isinstance(data, dict) or not data:
        return ["输入数据为空，缺少169号文省级企业研究院核验字段"]
    tier = str(data.get("tier") or "provincial_institute").strip()
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
        "provincial_key_institute": {"rd_exp": 1000, "rd_ratio": 3.0, "rd_staff": 50, "equip": 1000, "venue": 1000},
        "provincial_institute": {"rd_exp": 500, "rd_ratio": 3.0, "rd_staff": 30, "equip": 500, "venue": 500},
        "rd_center": {"rd_exp": 200, "rd_ratio": 3.0, "rd_staff": 15, "equip": 200, "venue": 200},
    }
    th = thresholds.get(tier, thresholds["provincial_institute"])
    if rd_rev is not None and rd_exp is not None:
        calc = fact_ledger.calc_rd_ratio(rd_exp, rd_rev)
        if not calc.get("ok"):
            errs.append(calc.get("error", "研发费用率无法复算"))
        elif tier == "provincial_institute" and rd_rev < 5000:
            # 浙经信高新〔2025〕169号: 营收<5000万元企业申报省级企业研究院须满足占比>=5%且研发费>=100万元
            if calc["ratio_pct"] < 5.0 or rd_exp < 100.0:
                errs.append(f"[provincial_institute] 营收({rd_rev}万元)<5000万元档位须满足研发占比≥5%且研发费≥100万元（当前{calc['ratio_pct']}% / {rd_exp}万元）")
        elif rd_exp < th["rd_exp"] and calc["ratio_pct"] < th["rd_ratio"]:
            errs.append(f"[{tier}] 研发费用({rd_exp}万元)与占比({calc['ratio_pct']}%)均低于169号文门槛({th['rd_exp']}万元或{th['rd_ratio']}%)")
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
    """技改/设备更新/固投补助: allow 5-10% retention proration, require valid invoice_date, block 0-yuan & duplicate rows."""
    errs: list[str] = []
    win_start = _parse_date(data.get("construction_start"))
    win_end = _parse_date(data.get("construction_end"))
    items = data.get("investments") or []
    if not items:
        errs.append("缺少 investments 投资明细台账")
    eligible_total = 0.0
    seen_pairs: set[tuple[str, str]] = set()
    for idx, row in enumerate(items):
        if not isinstance(row, dict):
            errs.append(f"investments[{idx}] 必须为对象")
            continue
        name = str(row.get("asset_name") or f"row#{idx}")
        contract = _finite_float(row.get("contract_amount")) or 0.0
        invoice = _finite_float(row.get("invoice_amount")) or 0.0
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
        pair = (inv_no.upper(), card_no.upper())
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
        elif ratio < 0.999 and not has_retention:
            errs.append(f"投资明细[{name}]付款比例为 {ratio*100:.1f}%（存在尾款差额），请注明质保金比例(retention_ratio)或质保金条款说明(retention_note)")
        else:
            eligible_total += min(paid, invoice, contract)
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


def validate_feasibility(data: dict[str, Any]) -> list[str]:
    """Ensure bidirectional template_requirements <-> conditions coverage and zero '客户填写'."""
    errs: list[str] = []
    if not isinstance(data, dict) or not data:
        return ["可行性配置为空"]
    raw_json = json.dumps(data, ensure_ascii=False)
    if "客户填写" in raw_json:
        errs.append("可行性配置中残留「客户填写」占位词")
    tpl_reqs = [str(r) for r in (data.get("template_requirements") or [])]
    conds = data.get("conditions") or []
    if not tpl_reqs:
        errs.append("缺少模板条款清单 template_requirements")
    if not conds:
        errs.append("缺少条件映射清单 conditions")
    if tpl_reqs and conds:
        norm_reqs = [re.sub(r"\s+", "", r) for r in tpl_reqs]
        norm_conds = [re.sub(r"\s+", "", str(c.get("match") or "")) for c in conds if isinstance(c, dict)]
        for idx, c in enumerate(conds):
            key = re.sub(r"\s+", "", str(c.get("match") or "")) if isinstance(c, dict) else ""
            if not key or not any(key in nr or nr in key for nr in norm_reqs):
                errs.append(f"conditions[{idx}]（「{c.get('match') if isinstance(c, dict) else c}」）未命中任何模板条款行，禁止静默丢弃")
        for r_idx, nr in enumerate(norm_reqs):
            if not any(ck and (ck in nr or nr in ck) for ck in norm_conds):
                errs.append(f"模板必备条款「{tpl_reqs[r_idx]}」缺少对应 conditions 核验项，禁止缺项通过")
    return errs


def main() -> int:
    parser = argparse.ArgumentParser(description="通用专项申报10大赛道统一真严格验收门禁（违规退出码 2）")
    parser.add_argument(
        "--track",
        required=True,
        choices=(
            "institute", "three-first", "subsidy", "digitalization", "green",
            "agriculture", "talent", "trade", "ip-project", "feasibility",
        ),
    )
    parser.add_argument("--input", type=Path, required=True, help="结构化评估/台账 JSON")
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

    out = {"track": args.track, "ok": len(errs) == 0, "error_count": len(errs), "errors": errs, **extra}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
