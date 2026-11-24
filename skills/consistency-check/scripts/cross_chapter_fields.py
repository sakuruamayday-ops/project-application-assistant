"""Compare named, located observations with the same business scope."""

from collections import defaultdict
from decimal import Decimal
import re


AMOUNTS = {"元": Decimal(1), "万元": Decimal(10_000), "亿元": Decimal(100_000_000)}
FINANCIAL = {
    "营收": "营业收入", "营业收入": "营业收入", "主营业务收入": "主营业务收入",
    "研发费用": "研发费用", "研究开发费用": "研发费用", "销售收入": "销售收入",
}
ANNUAL_AMOUNT = re.compile(
    r"(?P<period>(?:19|20)\d{2})\s*年\s*(?P<field>" + "|".join(FINANCIAL) + r")"
    r"\s*[:：为是=]?\s*(?P<value>-?\d+(?:\.\d+)?)\s*(?P<unit>亿元|万元|元)"
)
LOCATION = re.compile(r"^(T\d+R\d+|P\d+)\s+")
HEADING = re.compile(r"^(?:#{1,6}\s+.+|[一二三四五六七八九十]+、[^|。]{1,45})$")


def text_observations(text, source):
    chapter, context = "正文", ""
    for line_number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if match := LOCATION.match(line):
            position, line = match[1], line[match.end():]
        else:
            position = f"第{line_number}行"
        if HEADING.fullmatch(line):
            chapter, context = line.lstrip("# "), ""
            continue
        label, _, content = line.partition(" | ")
        if position.startswith("T") and not content and len(label) <= 30 and not re.search(r"\d", label):
            context = label
        location = {"source": source, "chapter": "／".join(filter(None, (chapter, context))),
                    "position": position}
        for match in ANNUAL_AMOUNT.finditer(line):
            row = match.groupdict()
            row["field"] = FINANCIAL[row["field"]]
            yield {**location, **row}
        if label.startswith("主导产品名称") and content:
            yield {**location, "field": "主导产品名称", "value": content.split(" | ", 1)[0]}
        elif label == "主要产品1" and (match := re.search(r"名称[：:]\s*(.+?)(?:收入[：:]|\s*\||$)", content)):
            yield {**location, "field": "主导产品名称", "value": match[1]}
        elif label.startswith("主导产品类别") and content:
            yield {**location, "field": "主导产品类别", "value": content}
        elif (match := re.search(r"替代进口的国外企业（或产品）名称[：:]\s*(.+?)(?:说明[（(]|\s*\||$)", content)):
            yield {**location, "field": "国产替代对象", "value": match[1]}


def validate_observations(rows):
    required = ("source", "chapter", "position", "field")
    if not isinstance(rows, list):
        raise ValueError("跨章字段须为 JSON 数组")
    for index, row in enumerate(rows, 1):
        if (not isinstance(row, dict) or any(not isinstance(row.get(key), str) or not row[key].strip()
                                            for key in required)
                or isinstance(row.get("value"), bool) or not isinstance(row.get("value"), (str, int, float))):
            raise ValueError(f"第{index}条字段须填写来源、章节、位置、字段和值")
        if any(key in row and not isinstance(row[key], str) for key in ("subject", "period", "scope", "unit")):
            raise ValueError(f"第{index}条记录的主体、期间、口径和单位须为文字")
    return rows


def comparable_value(row):
    unit = row.get("unit", "")
    value = str(row["value"]).strip()
    if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", value):
        return Decimal(value) * AMOUNTS.get(unit, 1)
    return re.sub(r"\s+", "", value)


def product_form(value):
    if re.search(r"挞皮|饼[胚坯]|半成品", value):
        return "半成品"
    if re.search(r"包馅|成品", value):
        return "成品"
    return ""


def field_findings(rows):
    groups, products = defaultdict(list), defaultdict(list)
    for row in rows:
        subject = row.get("subject") or row["source"]
        period, scope = row.get("period", ""), row.get("scope", "")
        field = FINANCIAL.get(row["field"], row["field"])
        unit = row.get("unit", "")
        if field not in FINANCIAL.values() or period:
            groups[(subject, period, scope, field, "金额" if unit in AMOUNTS else unit)].append(row)
        if field in {"主导产品名称", "主导产品类别", "国产替代对象"}:
            products[(subject, period, scope)].append(row)
    for (_, period, scope, field, _), entries in groups.items():
        if len({comparable_value(row) for row in entries}) > 1:
            yield {"rule": "field-conflict", "field": field, "period": period, "scope": scope,
                   "observations": entries, "action": "对照所列原表，统一同期间、同口径的填报值"}
    for entries in products.values():
        anchors = [row for row in entries if row["field"] == "主导产品名称"]
        forms = {product_form(str(row["value"])) for row in anchors}
        if len(forms) != 1 or "" in forms:
            continue
        for row in entries:
            form = product_form(str(row["value"]))
            if row["field"] != "主导产品名称" and form and form not in forms:
                yield {"rule": "product-scope-review", "field": row["field"], "observations": [*anchors, row],
                       "action": "按主导产品实际交付形态核对分类目录或替代对象"}
