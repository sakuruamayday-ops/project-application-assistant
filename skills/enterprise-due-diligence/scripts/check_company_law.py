#!/usr/bin/env python3
"""
2024 New Company Law (新公司法) 5-Year Paid-In Capital Transition Calculator & Local Legal KB Search.
Policy basis:
  - 《中华人民共和国公司法》（2023年修订，2024-07-01施行）第四十七条（有限责任公司）、第九十八条（股份有限公司）
  - 《国务院关于实施〈中华人民共和国公司法〉注册资本登记管理制度的规定》（国令第784号，2024-07-01施行）
"""
from __future__ import annotations

import argparse
import calendar
import json
import math
import sys
from datetime import date
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
for cand in (SCRIPT_DIR, SKILL_ROOT.parent / "_core", SKILL_ROOT / "scripts" / "_core"):
    if cand.is_dir() and str(cand) not in sys.path:
        sys.path.insert(0, str(cand))

import kb_local  # noqa: E402

EFFECTIVE_DATE = date(2024, 7, 1)
TRANSITION_ADJUST_DEADLINE = date(2027, 6, 30)
MAX_TRANSITION_PAIDIN_DEADLINE = date(2032, 6, 30)
VALID_COMPANY_TYPES = {"llc", "jsc"}  # llc=有限责任公司, jsc=股份有限公司


def _add_calendar_years(d: date, years: int) -> date:
    """Exact calendar anniversary (preserves 29/30/31; only Feb 29 -> Feb 28 in non-leap years)."""
    target_year = d.year + years
    last_day = calendar.monthrange(target_year, d.month)[1]
    return date(target_year, d.month, min(d.day, last_day))


def check_paid_in_schedule(
    founded_date: str,
    subscribed_deadline: str,
    registered_capital_wan: float,
    paid_in_capital_wan: float,
    *,
    company_type: str = "llc",
    as_of: date | None = None,
) -> dict[str, Any]:
    if company_type not in VALID_COMPANY_TYPES:
        raise ValueError(f"company_type 须为 llc(有限责任公司) 或 jsc(股份有限公司)，实际为：{company_type}")
    for lbl, val in (("registered_capital_wan", registered_capital_wan), ("paid_in_capital_wan", paid_in_capital_wan)):
        if not isinstance(val, (int, float)) or isinstance(val, bool) or not math.isfinite(val) or val < 0:
            raise ValueError(f"{lbl} 必须为非负有限数值：{val}")
    if registered_capital_wan <= 0:
        raise ValueError("registered_capital_wan 必须大于 0")
    if paid_in_capital_wan > registered_capital_wan * 1.0001:
        raise ValueError(f"实缴资本({paid_in_capital_wan}万)大于注册资本({registered_capital_wan}万)，请核对工商实缴口径")

    ref = as_of or date.today()
    fdate = date.fromisoformat(founded_date[:10])
    sdate = date.fromisoformat(subscribed_deadline[:10])
    unpaid = round(max(0.0, registered_capital_wan - paid_in_capital_wan), 4)
    paid_ratio = round((paid_in_capital_wan / registered_capital_wan * 100.0), 2)

    is_legacy = fdate < EFFECTIVE_DATE
    risks: list[str] = []
    if company_type == "jsc":
        # 股份有限公司：国令第784号第二条 — 存量股份公司须在 2027-06-30 前缴足认购股份股款；新设股份公司成立前足额缴纳
        if is_legacy:
            rule = "存量股份有限公司（2024-07-01前设立）：发起人须于2027-06-30前全额缴足认购股份股款（国令第784号第二条）。"
            max_deadline = TRANSITION_ADJUST_DEADLINE
            needs_adjustment = unpaid > 0 and sdate > TRANSITION_ADJUST_DEADLINE
            if needs_adjustment:
                risks.append(f"存量股份有限公司认缴截止日 {sdate.isoformat()} 超过法定最晚缴足日 {TRANSITION_ADJUST_DEADLINE.isoformat()}，尚有 {unpaid} 万元未实缴。")
        else:
            rule = "新设股份有限公司（2024-07-01及以后设立）：发起人须在公司成立前全额缴纳认购股款（《公司法》第九十八条）。"
            max_deadline = fdate
            needs_adjustment = unpaid > 0
            if needs_adjustment:
                risks.append(f"新设股份有限公司尚有 {unpaid} 万元未缴足，不符合成立前全额实缴要求。")
    else:
        if is_legacy:
            rule = "存量有限责任公司（2024-07-01前设立）：须于2027-06-30前完成章程认缴期限调整，剩余认缴出资期限自2027-07-01起不得超过5年（最晚2032-06-30实缴到位）。"
            max_deadline = MAX_TRANSITION_PAIDIN_DEADLINE
            needs_adjustment = unpaid > 0 and sdate > MAX_TRANSITION_PAIDIN_DEADLINE
            if needs_adjustment:
                days_to_adjust = (TRANSITION_ADJUST_DEADLINE - ref).days
                risks.append(
                    f"认缴截止日 {sdate.isoformat()} 超过法定最晚实缴日 {MAX_TRANSITION_PAIDIN_DEADLINE.isoformat()}，"
                    f"须在 {TRANSITION_ADJUST_DEADLINE.isoformat()}（距基准日 {days_to_adjust} 天）前办理减资或缩短认缴期限变更登记。"
                )
        else:
            rule = "新设有限责任公司（2024-07-01及以后设立）：全体股东认缴的出资额自公司成立之日起5年内缴足（《公司法》第四十七条）。"
            max_deadline = _add_calendar_years(fdate, 5)
            needs_adjustment = unpaid > 0 and sdate > max_deadline
            if needs_adjustment:
                risks.append(f"认缴截止日 {sdate.isoformat()} 超过成立满5年法定红线 {max_deadline.isoformat()}。")

    if unpaid > 0 and sdate < ref:
        risks.append(f"认缴出资已逾期：约定日 {sdate.isoformat()} 已过，尚有 {unpaid} 万元未实缴（存在股东失权/加速到期与政府项目信用扣分风险）。")

    return {
        "ok": len(risks) == 0,
        "company_type": company_type,
        "is_legacy_company": is_legacy,
        "founded_date": fdate.isoformat(),
        "subscribed_deadline": sdate.isoformat(),
        "statutory_max_paidin_deadline": max_deadline.isoformat(),
        "transition_adjust_deadline": TRANSITION_ADJUST_DEADLINE.isoformat() if is_legacy else None,
        "paid_ratio_pct": paid_ratio,
        "unpaid_capital_wan": unpaid,
        "needs_adjustment": needs_adjustment,
        "rule": rule,
        "risks": risks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="新《公司法》实缴过渡期核验与本地法规检索 CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_cap = sub.add_parser("paid-in", help="核算公司注册资本实缴合规期限（区分有限责任公司/股份有限公司）")
    p_cap.add_argument("--founded", required=True, help="成立日期 YYYY-MM-DD")
    p_cap.add_argument("--subscribed-deadline", required=True, help="章程约定认缴截止日 YYYY-MM-DD")
    p_cap.add_argument("--registered-wan", type=float, required=True)
    p_cap.add_argument("--paid-in-wan", type=float, required=True)
    p_cap.add_argument("--company-type", choices=("llc", "jsc"), default="llc", help="llc=有限责任公司(默认), jsc=股份有限公司")
    p_cap.add_argument("--strict", action="store_true")

    p_law = sub.add_parser("search-law", help="本地知识库检索合规法规（零 MCP 依赖，后端错误返回退出码2）")
    p_law.add_argument("query")
    p_law.add_argument("--limit", type=int, default=6)

    args = parser.parse_args()
    if args.cmd == "paid-in":
        try:
            res = check_paid_in_schedule(
                args.founded, args.subscribed_deadline, args.registered_wan, args.paid_in_wan,
                company_type=args.company_type,
            )
        except ValueError as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
            return 2
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if (res["ok"] or not args.strict) else 2
    if args.cmd == "search-law":
        res = kb_local.search_local_rag(args.query, limit=args.limit)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if not res.get("error") else 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
