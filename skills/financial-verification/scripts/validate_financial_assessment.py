#!/usr/bin/env python3
"""校验财务核验结果的主体、口径、来源和计算可追溯性。"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from decimal import Decimal, DecimalException
from pathlib import Path


STATES = {"verified", "computed", "missing", "conflicting", "not-applicable"}
SHARED_SCHEMA = "enterprise-financial-facts/v1"
CONTRACT = "references/financial-facts-contract.md#结构化核验回执"
FORMULA_REF = "references/reconciliation-and-formulas.md#常用公式"
FORMULAS = {
    "revenue_growth": (2, "（本期营业收入－上期营业收入）÷上期营业收入", lambda values: (values[0] - values[1]) / values[1]),
    "rd_ratio": (2, "研发投入÷营业收入", lambda values: values[0] / values[1]),
    "main_revenue_ratio": (2, "主营业务收入÷营业收入", lambda values: values[0] / values[1]),
    "high_tech_income_ratio": (2, "高新技术产品（服务）收入÷同期总收入", lambda values: values[0] / values[1]),
    "debt_ratio": (2, "负债总额÷资产总额", lambda values: values[0] / values[1]),
    "net_assets": (2, "资产总额－负债总额", lambda values: values[0] - values[1]),
    "sum": (None, "同口径项目合计", sum),
}
BOUNDED_RATIOS = {
    "rd_ratio": "研发费率",
    "main_revenue_ratio": "主营占比",
    "high_tech_income_ratio": "高新收入占比",
}
RATIO_NAMES = {
    "主营业务收入占营业收入比重": "main_revenue_ratio",
    "主营业务收入占比": "main_revenue_ratio",
    "研发费用率": "rd_ratio",
    "研发强度": "rd_ratio",
    "高品收入占比": "high_tech_income_ratio",
    "高新技术产品（服务）收入占比": "high_tech_income_ratio",
}
RATIOS = {"revenue_growth", "debt_ratio", *BOUNDED_RATIOS}
SHARED_METRICS = {
    "debt_ratio": ("debt_ratio", ("liabilities", "assets")),
    "research_to_revenue": ("rd_ratio", ("research_expense", "revenue")),
    "main_revenue_ratio": ("main_revenue_ratio", ("main_revenue", "revenue")),
    "high_tech_income_ratio": ("high_tech_income_ratio", ("high_tech_income", "total_income")),
}


def source_location(row, sources):
    source_ids = row.get("source_ids")
    linked = [source for source in sources if isinstance(source, dict)
              and isinstance(source_ids, list) and source.get("id", source.get("source_id")) in source_ids]
    locations = []
    for source in [row, *linked]:
        location = source.get("source_location") or source.get("location")
        if not location:
            location = " ".join(str(source[key]) for key in ("sheet", "page", "cell", "field") if source.get(key) is not None)
        if location:
            locations.append(" ".join(str(value) for value in (source.get("path"), location) if value))
    return "；".join(dict.fromkeys(locations)) or "缺来源位置"


def issue(field, current, requirement, fix, location="缺来源位置", reference=CONTRACT):
    return {
        "field_location": field, "current_value": current,
        "expected_requirement": {"rule": requirement, "reference": reference},
        "fix": fix, "source_location": location,
    }


def decimal_value(value):
    if isinstance(value, bool) or value is None:
        raise ValueError("输入须为有来源的有限数值")
    try:
        number = Decimal(str(value))
    except DecimalException as error:
        raise ValueError("输入须为有来源的有限数值") from error
    if not number.is_finite():
        raise ValueError("输入须为有来源的有限数值")
    return number


def subject_text(value):
    return value.strip() if isinstance(value, str) else ""


def source_subjects(sources):
    return [(index, subject_text(source.get("company_name")), source)
            for index, source in enumerate(sources)
            if isinstance(source, dict) and "company_name" in source]


def bounded_ratio(value, formula_id):
    if formula_id in BOUNDED_RATIOS and not 0 <= value <= 1:
        raise ValueError(f"{BOUNDED_RATIOS[formula_id]}为 {value:.2%}，超出 0% 到 100%，核对分子、分母和原表单位")


def object_or_empty(value):
    return value if isinstance(value, dict) else {}


def shared_facts_to_assessment(document):
    company = object_or_empty(document.get("company"))
    basis = object_or_empty(document.get("basis"))
    periods = object_or_empty(document.get("periods"))
    artifacts = document.get("source_artifacts")
    sources = [
        artifact if isinstance(artifact, dict) else {"name": artifact}
        for artifact in (artifacts if isinstance(artifacts, list) else [])
        if isinstance(artifact, (dict, str)) and artifact
    ]
    years = sorted(periods)
    period_label = "–".join((years[0], years[-1])) if len(years) > 1 else next(iter(years), None)
    facts, metrics, quality, malformed = [], [], {}, {}
    for year in years:
        period = object_or_empty(periods[year])
        for section in ("facts", "metrics", "quality"):
            if not isinstance(period.get(section), dict):
                malformed[f"periods.{year}.{section}"] = period.get(section)
        annual_quality = quality[year] = object_or_empty(period.get("quality"))
        evidence = object_or_empty(period.get("evidence"))
        source_ids = {}
        annual_facts = object_or_empty(period.get("facts"))
        for field, value in annual_facts.items():
            fact_id = f"{year}/{field}"
            location = evidence.get(field)
            source = {"location": location.strip()} if isinstance(location, str) else object_or_empty(location)
            if source_location(source, ()) != "缺来源位置":
                sources.append({**source, "id": fact_id})
                source_ids[field] = fact_id
            status = "verified" if annual_quality.get("status") == "verified" else "unverified"
            facts.append({"id": fact_id, "value": value, "unit": basis.get("unit"),
                          "status": "missing" if value is None else status,
                          "source_ids": [fact_id] if field in source_ids else []})
        annual_metrics = object_or_empty(period.get("metrics"))
        for field, (formula_id, operands) in SHARED_METRICS.items():
            result = annual_metrics.get(field)
            derive = (result is None and formula_id in BOUNDED_RATIOS
                      and all(annual_facts.get(operand) is not None and operand in source_ids for operand in operands))
            if result is None and not derive:
                continue
            metrics.append({
                "metric": f"{year}/{field}", "formula_id": formula_id, "formula": FORMULAS[formula_id][1],
                "inputs": [{"fact_id": f"{year}/{operand}"} for operand in operands],
                "unit": "ratio", "result": result, "status": "computed", "_derive": derive,
                "source_ids": [source_ids[operand] for operand in operands if operand in source_ids],
            })
    return {
        "identity": {"company_name": company.get("name"), "credit_code": company.get("unified_social_credit_code")},
        "scope": {**basis, "period": period_label},
        "sources": sources, "facts": facts, "metrics": metrics,
        "conflicts": document.get("conflicts", []), "quality": quality,
    }, malformed


def recompute(facts, metrics, scope, add_issue, *, fact_states=("verified", "computed")):
    fact_index, metric_index = defaultdict(list), defaultdict(list)
    for row in facts:
        if isinstance(row, dict) and isinstance(row.get("id"), str):
            fact_index[row["id"]].append(row)
    for row in metrics:
        if isinstance(row, dict) and isinstance(row.get("metric"), str):
            metric_index[row["metric"]].append(row)
    computed = {}

    def resolve_input(entry, trail):
        if not isinstance(entry, dict) or len(entry) != 1:
            raise ValueError("每个输入须引用一个 fact_id 或 metric")
        if isinstance(entry.get("fact_id"), str):
            key = entry["fact_id"]
            matches = fact_index.get(key, [])
            if len(matches) != 1 or matches[0].get("status") not in fact_states or not matches[0].get("source_ids"):
                if "unverified" in fact_states:
                    raise ValueError(f"将 {key} 关联到一条有原表定位的事实")
                raise ValueError(f"将 {key} 关联到一条有来源的已核事实")
            return decimal_value(matches[0].get("value")), matches[0].get("unit") or scope.get("unit")
        if isinstance(entry.get("metric"), str):
            name = entry["metric"]
            matches = metric_index.get(name, [])
            if len(matches) != 1 or not matches[0].get("formula_id"):
                raise ValueError(f"将 {name} 关联到一条具备复算公式的指标")
            return calculate(matches[0], trail), matches[0].get("unit")
        raise ValueError("使用 fact_id 或 metric 指定计算输入")

    def calculate(row, trail=()):
        name = row.get("metric")
        if not isinstance(name, str) or len(metric_index[name]) != 1:
            raise ValueError("为需要复算的指标填写唯一名称")
        if name in trail:
            raise ValueError(f"移除指标 {name} 的循环依赖")
        if name in computed:
            return computed[name]
        formula_id = row["formula_id"]
        if not isinstance(formula_id, str) or formula_id not in FORMULAS:
            raise ValueError("填写契约支持的 formula_id")
        count, _, formula = FORMULAS[formula_id]
        entries = row.get("inputs")
        if not isinstance(entries, list) or not entries or (count is not None and len(entries) != count):
            raise ValueError(f"按公式顺序填写{count or '至少一个'}个输入引用")
        operands = [resolve_input(entry, (*trail, name)) for entry in entries]
        values, units = zip(*operands)
        if not units[0] or any(unit != units[0] for unit in units) or (formula_id not in RATIOS and units[0] != row.get("unit")):
            raise ValueError("将计算输入和金额输出统一到相同单位后再复算")
        if formula_id in RATIOS and values[1] == 0:
            raise ValueError("分母为零，按原报表补正分母或记录为不可计算")
        result = formula(values)
        bounded_ratio(result, formula_id)
        if formula_id in RATIOS and row.get("unit") == "%":
            result *= 100
        places = row.get("round_to")
        if places is not None:
            if type(places) is not int or places < 0:
                raise ValueError("round_to 须为非负整数")
            result = round(result, places)
        computed[name] = result
        return result

    recomputed = []
    for index, row in enumerate(metrics):
        if not isinstance(row, dict) or "formula_id" not in row:
            continue
        location = f"metrics[{index}]"
        formula_id = row["formula_id"]
        formula_text = FORMULAS.get(formula_id, (None, "填写受支持公式", None))[1] if isinstance(formula_id, str) else "填写受支持公式"
        reference = CONTRACT if formula_id == "sum" or formula_text == "填写受支持公式" else FORMULA_REF
        try:
            result = calculate(row)
        except (ValueError, DecimalException) as error:
            add_issue(f"{location}无法复算：{error}", f"{location}.inputs", row.get("inputs"), formula_text, str(error), row, reference)
            continue
        output = format(result, "f")
        recomputed.append({"metric": row["metric"], "formula_id": formula_id, "result": output,
                           "unit": row.get("unit"), "source_ids": row.get("source_ids", []), "status": "computed"})
        if "unverified" in fact_states and row.get("_derive"):
            continue
        try:
            matches = result == decimal_value(row.get("result"))
        except ValueError:
            matches = False
        if not matches:
            add_issue(f"{location}.result与复算值不一致", f"{location}.result", row.get("result"),
                      f"{formula_text} = {output}", f"根据已核输入将 result 改为 {output}", row, reference)
    return recomputed


def assess(document: dict) -> dict:
    errors: list[str] = []
    issues = []
    if not isinstance(document, dict):
        return {"status": "fail", "errors": ["结果须为JSON对象"],
                "issues": [issue("$", document, "结果须为JSON对象", "按输入契约填写主体、口径、来源、事实与指标")],
                "recomputed_metrics": []}
    shared = document.get("schema") == SHARED_SCHEMA
    malformed = {}
    if shared:
        document, malformed = shared_facts_to_assessment(document)
    fact_states = ("verified", "computed", "unverified") if shared else ("verified", "computed")
    allowed_states = STATES.union(fact_states)
    identity = document.get("identity")
    scope_value = document.get("scope")
    scope = scope_value if isinstance(scope_value, dict) else {}
    source_value = document.get("sources")
    sources = source_value if isinstance(source_value, list) else []

    def add_issue(message, field, current, requirement, fix, row=None, reference=CONTRACT):
        errors.append(message)
        issues.append(issue(field, current, requirement, fix, source_location(row or {}, sources), reference))

    for field, value in malformed.items():
        add_issue(f"{field}须为对象", field, value, "按年度登记三表事实、指标和质量",
                  "按共享财务事实契约补齐该年度字段")
    company = subject_text(object_or_empty(identity).get("company_name"))
    credit_code = subject_text(object_or_empty(identity).get("credit_code"))
    missing_identity = not (company or credit_code)
    declared_subjects = source_subjects(sources)
    missing_source = any(not name for _, name, _ in declared_subjects)
    names = {name for _, name, _ in declared_subjects if name} | ({company} if company else set())
    conflicting_subjects = len(names) > 1
    if missing_identity and not missing_source:
        add_issue("缺主体信息", "identity", identity, "企业全称或统一社会信用代码至少填一项",
                  "按报表主体填写 company_name 或 credit_code")
    for index, name, source in declared_subjects:
        if not name:
            add_issue("缺主体信息", f"sources[{index}].company_name", source.get("company_name"),
                      "每份原表须有可核对的主体", "查原表抬头并补同主体财务原件", source)
    if conflicting_subjects:
        details = [f"{source.get('path') or source.get('name') or index + 1}：{name}"
                   for index, name, source in declared_subjects if name]
        if company:
            details.insert(0, f"当前主体：{company}")
        add_issue("主体不一致：" + "、".join(details), "sources", details, "同批原表主体须一致",
                  "按各自主体重新归集并单独核验")
    for field in ("period", "currency", "unit", "consolidation_scope"):
        if not scope.get(field):
            add_issue(f"scope缺少{field}", f"scope.{field}", scope.get(field), f"{field} 须明确填写",
                      f"从原报表口径补录 scope.{field}", scope)
    if not sources:
        add_issue("sources必须为非空列表", "sources", source_value, "至少登记一条原报表或业务表来源",
                  "填写来源 id、文件及表页或单元格位置")
    facts = document.get("facts")
    if not isinstance(facts, list):
        add_issue("facts必须为列表", "facts", facts, "事实按数组逐项登记", "将 facts 改为事实对象数组")
        facts = []
    for index, fact in enumerate(facts):
        position = f"facts[{index}]"
        if not isinstance(fact, dict):
            add_issue(f"{position}须为对象", position, fact, "每条事实须为对象", "填写事实值、质量状态和来源")
            continue
        status = fact.get("status")
        if not isinstance(status, str) or status not in allowed_states:
            add_issue(f"{position}.status无效", f"{position}.status", status, "质量状态取 " + "、".join(sorted(allowed_states)),
                      "按原报表及实际核验结果填写 status", fact)
        if status in fact_states and not fact.get("source_ids"):
            add_issue(f"{position}可用事实缺少来源", f"{position}.source_ids", fact.get("source_ids"),
                      "有值事实须关联原表位置" if shared else "已核或计算事实须关联来源",
                      f"补录 periods 下 {fact.get('id')} 对应的 evidence" if shared else "补登记原报表并将其 id 填入 source_ids", fact)
    metrics = document.get("metrics", [])
    if not isinstance(metrics, list):
        add_issue("metrics必须为列表", "metrics", metrics, "指标按数组登记", "将 metrics 改为指标对象数组")
        metrics = []
    if not facts and not metrics:
        add_issue("未提供财务事实或指标", "facts/metrics", None, "至少登记一项财务事实或指标",
                  "从财务原件补录事实或指标")
    for index, metric in enumerate(metrics):
        position = f"metrics[{index}]"
        if not isinstance(metric, dict):
            add_issue(f"{position}须为对象", position, metric, "每条指标须为对象", "填入公式、输入、单位和结果")
            continue
        required = ("metric", "formula", "inputs", "unit", "result", "status")
        for field in required:
            if field not in metric:
                add_issue(f"{position}缺少{field}", f"{position}.{field}", None, f"指标须包含 {field}",
                          f"按该指标原始计算口径填入 {field}", metric)
        if metric.get("status") == "computed" and not metric.get("source_ids"):
            add_issue(f"{position}计算结果缺少来源", f"{position}.source_ids", metric.get("source_ids"),
                      "计算结果须关联输入来源", "将公式输入所用报表 id 填入 source_ids", metric)
        metric_name = str(metric.get("metric", "")).rsplit("/", 1)[-1]
        ratio_key = next((key for key, label in BOUNDED_RATIOS.items()
                          if metric_name in (key, label)), RATIO_NAMES.get(metric_name))
        if not metric.get("formula_id") and (definition := SHARED_METRICS.get(metric_name)):
            ratio_key = definition[0] if definition[0] in BOUNDED_RATIOS else None
        if not metric.get("formula_id") and ratio_key and metric.get("result") is not None:
            try:
                value = decimal_value(metric["result"])
                bounded_ratio(value / 100 if metric.get("unit") == "%" else value, ratio_key)
            except ValueError as error:
                add_issue(f"{position}.result：{error}", f"{position}.result", metric["result"],
                          "占比须处于 0% 到 100%", str(error), metric, FORMULA_REF)
    for field in ("conflicts", "quality"):
        if field not in document:
            add_issue(f"缺少{field}", field, None, f"结果须登记 {field}", "逐项登记冲突" if field == "conflicts" else "记录本批质量状态")
    recomputed = [] if conflicting_subjects else recompute(facts, metrics, scope, add_issue, fact_states=fact_states)
    if missing_identity or missing_source:
        recomputed = []
    return {"status": "pass" if not errors else "fail", "errors": errors, "issues": issues,
            "identity": identity, "scope": scope_value, "sources": source_value, "quality": document.get("quality"),
            "recomputed_metrics": recomputed}


def validate(document: dict) -> list[str]:
    return assess(document)["errors"]


def assess_file(path):
    if path.suffix.lower() in {".xlsx", ".xlsm"}:
        from read_financial_workbook import read_workbook
        return assess(read_workbook(path))
    content = path.read_text(encoding="utf-8")
    document = json.loads(content)
    if isinstance(document, dict) and document.get("schema") == SHARED_SCHEMA:
        document = json.loads(content, parse_float=Decimal)
    return assess(document)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("assessment", type=Path, nargs="+")
    args = parser.parse_args()
    reports = []
    for path in args.assessment:
        try:
            result = assess_file(path)
        except (OSError, ValueError, ImportError) as exc:
            result = {"status": "fail", "errors": [str(exc)], "issues": [issue(
                "$", str(exc), "输入须为可读的财务工作簿或结构化 JSON", "检查文件与字段", path.name)],
                "recomputed_metrics": []}
        reports.append((path.name, result))
    if len(reports) == 1:
        report = reports[0][1]
    else:
        named_sources = [(name, subject_text(object_or_empty(result.get("identity")).get("company_name")))
                         for name, result in reports]
        names = {name for _, name in named_sources if name}
        errors, issues = [], []
        if len(names) > 1:
            details = "、".join(f"{file}：{name}" for file, name in named_sources if name)
            errors.append(f"主体不一致：{details}")
            issues.append(issue("assessment", details, "同批文件主体须一致", "按各主体重新归集并单独校验", details))
        for filename, result in reports:
            errors.extend(f"{filename}：{error}" for error in result["errors"])
            issues.extend(result["issues"])
        report = {"status": "fail" if errors else "pass", "errors": errors, "issues": issues,
                  "files": [{"file": filename, "identity": result.get("identity")} for filename, result in reports],
                  "recomputed_metrics": [] if errors else [
                      {"file": filename, **metric} for filename, result in reports for metric in result["recomputed_metrics"]
                  ]}
    report["items"] = [
        {"item": finding["field_location"], "gap": error, "action": finding["fix"], "priority": "高",
         "evidence": finding["source_location"]}
        for error, finding in zip(report["errors"], report["issues"], strict=True)
    ]
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
