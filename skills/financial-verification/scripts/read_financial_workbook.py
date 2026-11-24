"""Read source-labelled annual amounts from financial intake workbooks."""

import re
from zipfile import BadZipFile


SUBJECT = re.compile(r"^(?:企业名称|公司名称|单位名称|纳税人名称|编制单位)\s*(?:[:：]\s*(.*))?$")
LABELS = {
    "营业收入": "revenue",
    "主营业务收入": "main_revenue",
    "研发费用": "research_expense",
    "研究开发费用": "research_expense",
    "高新技术产品（服务）收入": "high_tech_income",
    "高新技术产品收入": "high_tech_income",
    "总收入": "total_income",
}


def read_workbook(path):
    from openpyxl import load_workbook

    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
    except BadZipFile as error:
        raise ValueError("财务工作簿无法读取") from error

    subjects, periods, sources = [], {}, []
    unit = None
    try:
        for sheet in workbook:
            years = {}
            for cells in sheet.iter_rows():
                for index, cell in enumerate(cells):
                    if not isinstance(cell.value, str):
                        continue
                    value = cell.value.strip()
                    if match := SUBJECT.fullmatch(value):
                        adjacent = cells[index + 1] if index + 1 < len(cells) else None
                        candidate = match[1] or (adjacent.value if adjacent else "")
                        name = candidate.strip() if isinstance(candidate, str) and not re.search(r"[:：]$", candidate.strip()) else ""
                        location = f"{sheet.title}!{cell.coordinate}"
                        if adjacent and not match[1] and adjacent.value is not None:
                            location += f":{adjacent.coordinate}"
                        subjects.append((name, location))
                    if match := re.fullmatch(r"(?:金额)?单位\s*[:：]\s*(元|万元)", value):
                        unit = {"元": "yuan", "万元": "ten_thousand_yuan"}[match[1]]
                header = {index: match[1] for index, cell in enumerate(cells)
                          if (match := re.fullmatch(r"((?:19|20)\d{2})\s*年?", str(cell.value).strip()))}
                if header and not any(str(cell.value).strip() in LABELS for cell in cells):
                    years = header
                for cell in cells:
                    label = re.sub(r"[（(](?:元|万元)[)）]\s*$", "", str(cell.value).strip())
                    if label not in LABELS:
                        continue
                    field = LABELS[label]
                    for column, year in years.items():
                        amount = cells[column] if column < len(cells) else None
                        if amount is None or amount.value in (None, ""):
                            continue
                        location = f"{sheet.title}!{amount.coordinate}"
                        period = periods.setdefault(year, {"facts": {}, "metrics": {}, "evidence": {},
                                                            "quality": {"status": "unverified"}})
                        if field in period["facts"] and period["facts"][field] != amount.value:
                            previous = period["evidence"][field]["location"]
                            raise ValueError(f"{year}年{label}有不同原值：{previous}、{location}")
                        period["facts"][field] = amount.value
                        period["evidence"][field] = {"path": path.name, "location": location}
    finally:
        workbook.close()

    if not subjects:
        subjects.append(("", "工作簿主体栏"))
    for name, location in subjects:
        sources.append({"path": path.name, "location": location, "company_name": name})
    return {
        "schema": "enterprise-financial-facts/v1",
        "company": {"name": next((name for name, _ in subjects if name), "")},
        "basis": {"currency": "CNY" if unit else None, "unit": unit, "consolidation_scope": "unknown"},
        "periods": periods,
        "source_artifacts": sources,
    }
