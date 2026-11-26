"""Apply the 2026 hard requirements to sourced company facts."""

from decimal import Decimal, InvalidOperation


COMMON_EVIDENCE = {
    "designation": "前置称号",
    "market_duration": "细分市场从业时长",
    "intellectual_property": "知识产权或政策豁免",
    "market_position": "主导产品细分市场位置",
    "compliance": "主体与排除项",
}


def number(value, *, nonnegative=True):
    if value is None or isinstance(value, bool):
        return None
    try:
        numeric = Decimal(str(value))
    except InvalidOperation:
        return None
    return numeric if numeric.is_finite() and (not nonnegative or numeric >= 0) else None


def present(value):
    return isinstance(value, str) and bool(value.strip())


def assess_company(profile, policy):
    items = []

    def add(item, gap, action):
        items.append({"item": item, "gap": gap, "action": action, "priority": "高"})

    def result(status):
        return {"status": status, "items": items}

    year = profile.get("year") if isinstance(profile, dict) else None
    if type(year) is not int or year < 2026 or not present(profile.get("enterprise_id")):
        add("申报主体与评估年度", "缺企业身份或管理办法适用的评估年度",
            "补同主体登记信息和评估年度，历史期间由客户确认依据")
        return result("needs-evidence")

    review = policy["application_type"] == "review"
    special_review = review and (present(profile.get("review_group")) or present(profile.get("review_rule_locator")))
    national = policy["project_id"] == "little-giant"
    evidence = profile.get("evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    required = dict(COMMON_EVIDENCE)
    if national:
        required["industry_chain"] = "主导产品产业链定位"
    for key, label in required.items():
        row = evidence.get(key)
        if not isinstance(row, dict) or not present(row.get("locator")) or row.get("met") is not True:
            reason = row.get("gap") if isinstance(row, dict) else None
            add(label, reason if present(reason) else "缺满足条件的可回查证据",
                "按适用规则及证明材料逐项核对并登记原件位置")

    if special_review:
        add("专项复核口径", "一般管理办法评估与客户指定的专项复核口径需分别处理",
            "由客户提供适用规则和对象证明，按原文逐项核对专项条件")
        return result("review-transition")

    financials = profile.get("financials")
    financials = financials if isinstance(financials, dict) else {}
    revenue_rd = {}
    for accounting_year in (str(year - 2), str(year - 1)):
        row = financials.get(accounting_year)
        row = row if isinstance(row, dict) else {}
        revenue, rd = number(row.get("revenue_wan")), number(row.get("rd_wan"), nonnegative=False)
        if not present(row.get("locator")) or revenue is None or revenue == 0 or rd is None:
            add(f"{accounting_year} 年研发投入", "缺同口径收入、研发金额或原件", "从审计报告、研发辅助账补年度数据及出处")
            continue
        if not 0 <= rd <= revenue:
            add(f"{accounting_year} 年研发强度", f"原表复算为 {rd / revenue:.2%}，超出 0% 到 100%",
                "复核当年研发费用、营业收入及单位")
            continue
        revenue_rd[accounting_year] = revenue, rd
        if rd < revenue * Decimal("0.03"):
            add(f"{accounting_year} 年研发强度", f"低于当年要求，差 {(3 - rd / revenue * 100):.2f} 个百分点",
                "复核当年研发归集和营业收入口径，列真实补强动作")
        if not national and rd < 100:
            add(f"{accounting_year} 年研发费用", f"距门槛 {100 - rd:f} 万元", "核对该年度研发费用及科目明细")

    if national and len(revenue_rd) == 2:
        total = sum(rd for revenue, rd in revenue_rd.values())
        if total < 1200:
            add("两年研发费用", f"距门槛 {1200 - total:f} 万元", "按两年审计口径核对项目及费用明细")

    last = financials.get(str(year - 1))
    last = last if isinstance(last, dict) else {}
    revenue = number(last.get("revenue_wan"))
    main = number(last.get("main_revenue_wan"), nonnegative=False)
    assets = number(last.get("assets_wan"))
    liabilities = number(last.get("liabilities_wan"))
    investment = number(profile.get("qualified_equity_investment_wan"))
    investment_met = (not national and investment is not None and investment >= 2000
                      and present(profile.get("equity_investment_locator")))
    threshold = 5000 if national else 1500
    if not present(last.get("locator")) or revenue in (None, 0):
        add("上年度财务条件", "缺会计年度收入或报表出处", "按审计报告补入营业收入、主营收入和资产负债")
    else:
        if revenue < threshold and not investment_met:
            gap = f"营业收入距门槛 {threshold - revenue:f} 万元"
            if not national:
                gap += "，缺满足股权投资路径的证据"
            add("经营规模", gap, "核对营业收入；省级适用时核对合格机构实缴记录")
        main_threshold = Decimal("0.9") if national else Decimal("0.8")
        if main is None:
            add("主营占比", "缺同口径主营收入", "核对主营业务收入与总额的报表科目")
        elif not 0 <= main <= revenue:
            add("主营占比", f"原表复算为 {main / revenue:.2%}，超出 0% 到 100%",
                "核对主营业务收入与总额的报表科目")
        elif main < revenue * main_threshold:
            add("主营占比", f"距门槛 {(main_threshold - main / revenue) * 100:.2f} 个百分点",
                "核对主营收入归集与审计口径")
        debt_limit = Decimal("0.75") if national else Decimal("0.8")
        if assets in (None, 0) or liabilities is None:
            add("资产负债率", "缺可复算的资产或负债原值", "补上年末同口径资产负债表")
        elif liabilities > assets * debt_limit:
            add("资产负债率", f"超出门槛 {(liabilities / assets - debt_limit) * 100:.2f} 个百分点",
                "核对负债和资产期末余额及合并口径")
        if national and not review:
            older = financials.get(str(year - 3))
            older = older if isinstance(older, dict) else {}
            older_revenue = number(older.get("revenue_wan"))
            if older_revenue in (None, 0) or not present(older.get("locator")):
                add("营收复合增长", "缺两年比较所需营收基数和原件", f"补{year - 3}年审计口径营业收入")
            elif revenue < older_revenue * Decimal("1.05") ** 2:
                add("营收复合增长", "低于适用的两年增长要求", "按同口径营业收入复算两年增长")

    # Subjective / platform scores are not scored or blocked (strengthen-only, no pass guarantee)
    return result("needs-evidence" if items else "checked")
