#!/usr/bin/env python3
import argparse
import hashlib
import json
import re
import unicodedata
import zipfile
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET

from build_project_map import classify, infer_regions


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
EXCLUDED = re.compile("专精特新|小巨人|研发中心|研究开发中心|企业研究院|重点研究院")
CONDITION_FIELDS = [
    ("region", re.compile("注册地|登记注册|行政区域|财政级次|税务登记|在杭|在浙江|余杭区|临平区|西湖区|萧山区|钱塘区|拱墅区|滨江区|上城区|临安区|富阳区")),
    ("applicant", re.compile("申报主体|申报对象|独立法人|企事业单位|企业法人|运行主体|承担单位|联合体|自然人")),
    ("establishment", re.compile("成立|设立|注册时间|迁入时间|存续|年限")),
    ("finance", re.compile("营业收入|主营业务收入|销售收入|销售额|产值|资产负债|注册资本|实收资本|融资|利润|纳税|增值税|财务|资金到位")),
    ("employees", re.compile("职工|从业人员|人员|团队|社保|研发人员|专职人员")),
    ("research_development", re.compile("研发|研究开发|技术开发|创新能力|科技计划|技术合同|产学研|科技成果")),
    ("intellectual_property", re.compile("知识产权|发明专利|专利权|专利|软件著作权|软著|商标|版权|I类|II类")),
    ("qualification", re.compile("资质|认定|入库|高新技术企业|科技型中小企业|专精特新|小巨人|单项冠军|技术中心|研究院|证书")),
    ("industry_product", re.compile("产业|行业|主导产品|产品|细分市场|制造业|农业|服务业|生物医药|软件|人工智能|新材料|低空经济")),
    ("investment", re.compile("投资|设备|技术改造|技改|项目投入|研发投入|固定资产|购置|租金")),
    ("exclusions", re.compile("不得|不予|不纳入|不可|排除|失信|违法|安全事故|环保|重复申报|未发生|限制类|淘汰类")),
]


def column_index(reference):
    letters = re.match(r"[A-Z]+", reference).group(0)
    result = 0
    for letter in letters:
        result = result * 26 + ord(letter) - 64
    return result - 1


def load_shared_strings(archive):
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return ["".join(node.text or "" for node in item.iter(f"{{{MAIN_NS}}}t")) for item in root]


def cell_value(cell, shared_strings):
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.iter(f"{{{MAIN_NS}}}t"))
    value = cell.find(f"{{{MAIN_NS}}}v")
    if value is None or value.text is None:
        return ""
    if cell_type == "s":
        return shared_strings[int(value.text)]
    return value.text


def read_workbook(path):
    with zipfile.ZipFile(path) as archive:
        shared_strings = load_shared_strings(archive)
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {
            item.attrib["Id"]: item.attrib["Target"]
            for item in relationships.findall(f"{{{PKG_REL_NS}}}Relationship")
        }
        sheets = []
        for sheet in workbook.find(f"{{{MAIN_NS}}}sheets"):
            name = sheet.attrib["name"]
            relation_id = sheet.attrib[f"{{{REL_NS}}}id"]
            target = targets[relation_id].lstrip("/")
            if not target.startswith("xl/"):
                target = f"xl/{target}"
            root = ET.fromstring(archive.read(target))
            rows = []
            for row in root.iter(f"{{{MAIN_NS}}}row"):
                values = {}
                for cell in row.findall(f"{{{MAIN_NS}}}c"):
                    values[column_index(cell.attrib["r"])] = cell_value(cell, shared_strings)
                rows.append(values)
            sheets.append((name, rows))
        return sheets


def normalize_title(value):
    value = unicodedata.normalize("NFKC", value).lower()
    value = re.sub(r"20\d{2}(?:年度|年)?|第[一二三四五六七八九十0-9]+批", "", value)
    value = re.sub(r"关于|组织|开展|申报|推荐|认定|复核|工作的|工作|通知|公告|征集|项目|政策兑现|\s+", "", value)
    return re.sub(r"[【】\[\]（）()“”\"《》、，,:;.。/\\\-—_]", "", value)


def canonicalize_title(value):
    original = re.sub(r"\s+", "", value.strip())
    value = original
    value = re.sub(
        r"^[【\[](.*?)[】\]]",
        lambda match: match.group(1) if re.search(r"国家|省|市|区|县|高新区|开发区", match.group(1)) else "",
        value,
    )
    if "关于" in value[:40]:
        prefix, remainder = value.split("关于", 1)
        region = re.search(r"国家|[一-鿿]{2,8}省|[一-鿿]{2,8}市|[一-鿿]{2,8}区|[一-鿿]{2,8}县", prefix)
        value = (region.group(0) if region else "") + remainder
    value = re.sub(r"20\d{2}(?:年度|年)?|第[一二三四五六七八九十0-9]+批", "", value)
    value = re.sub(r"^(组织)?(开展|申报|征集|做好|推荐|启动)+", "", value)
    value = re.sub(r"(的)?(申报|认定|推荐|复核|评审|征集|兑现|填报|入库)*(工作)?(预)?通知.*$", "", value)
    value = re.sub(r"(申报|认定|推荐|复核|评审|征集|兑现|填报|工作|启动|开始|正式启动)[!！。？?]*$", "", value)
    value = re.sub(r"（\s*）|\(\s*\)", "", value)
    value = value.strip("：:—- ")
    return value or original


def split_clauses(text):
    chunks = re.split(r"\n+|(?<=[。；;])|(?=\(?[一二三四五六七八九十]+\)?[、.])|(?=\d+[、.])", text)
    return [re.sub(r"\s+", " ", chunk).strip() for chunk in chunks if re.sub(r"\s+", " ", chunk).strip()]


def structure_conditions(text):
    fields = defaultdict(list)
    uncategorized = []
    for clause in split_clauses(text):
        matched = False
        for field, pattern in CONDITION_FIELDS:
            if pattern.search(clause):
                fields[field].append(clause)
                matched = True
        if not matched:
            uncategorized.append(clause)
    if uncategorized:
        fields["other"].extend(uncategorized)
    return dict(fields)


def load_project_map(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def map_candidates(title, project_map):
    normalized = normalize_title(canonicalize_title(title))
    if len(normalized) < 4:
        return []
    matches = []
    for record in project_map:
        candidate = normalize_title(record["title"])
        similarity = min(len(candidate), len(normalized)) / max(len(candidate), len(normalized)) if candidate else 0
        if len(candidate) >= 4 and similarity >= 0.55 and (candidate in normalized or normalized in candidate):
            matches.append(record["title"])
    return sorted(set(matches), key=lambda item: (-len(normalize_title(item)), item))


def relate_card(card, project_map):
    matches = map_candidates(card["project_name"], project_map)
    if len(matches) == 1:
        canonical_name = matches[0]
        relation = "base-map"
    else:
        canonical_name = canonicalize_title(card["project_name"])
        relation = "high-frequency-extension"
    card["canonical_project_name"] = canonical_name
    card["canonical_relation"] = relation
    card["matched_project_map"] = matches
    matched_record = next((record for record in project_map if record["title"] == canonical_name), None)
    card["regions"] = matched_record["regions"] if matched_record else infer_regions(card["project_name"])
    card["primary_region"] = matched_record["primary_region"] if matched_record else card["regions"][0]
    if "requirements_text" in card:
        card["condition_fields"] = structure_conditions(card["requirements_text"])
    elif "requirements" in card:
        card["condition_fields"] = structure_conditions("\n".join(f'{item["condition"]}：{item["requirement"]}' for item in card["requirements"]))
    card["condition_schema_version"] = 1
    return card


def historical_cards(workbook_path, project_map):
    grouped = defaultdict(list)
    for sheet_name, rows in read_workbook(workbook_path):
        year_match = re.search(r"20\d{2}", sheet_name)
        source_year = int(year_match.group(0)) if year_match else None
        for row_number, row in enumerate(rows, 1):
            if row_number <= 2:
                continue
            title = str(row.get(2, "")).strip()
            requirements = str(row.get(3, "")).strip()
            if not title or not requirements or EXCLUDED.search(title):
                continue
            source_url = next((str(row.get(index, "")).strip() for index in range(5, 12) if "http" in str(row.get(index, ""))), "")
            grouped[normalize_title(title)].append({
                "title": title,
                "requirements_text": requirements,
                "source_url": source_url,
                "source_year": source_year,
                "source_sheet": sheet_name,
                "source_row": row_number,
            })
    cards = []
    for records in grouped.values():
        records.sort(key=lambda item: (item["source_year"] or 0, item["source_row"]))
        latest = records[-1]
        cards.append({
            "project_name": latest["title"],
            "aliases": sorted({record["title"] for record in records if record["title"] != latest["title"]}),
            "requirements_text": latest["requirements_text"],
            "rule_status": "historical-reference",
            "source_year": latest["source_year"],
            "source_url": latest["source_url"],
            "official_verification_required": True,
        })
    return sorted(cards, key=lambda item: item["project_name"])


def parse_table_after_heading(text, heading):
    start = text.index(heading)
    lines = text[start:].splitlines()[1:]
    table = []
    started = False
    for line in lines:
        if line.startswith("|"):
            started = True
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if cells and not all(re.fullmatch(r"-+", cell) for cell in cells):
                table.append(cells)
        elif started:
            break
    return table[1:]


def current_cards(sme_path, institute_path):
    sme = sme_path.read_text(encoding="utf-8")
    institute = institute_path.read_text(encoding="utf-8")
    sme_url = re.search(r"^source_url:\s*(.+)$", sme, re.MULTILINE).group(1).strip()
    cards = []
    for heading, name in [
        ("## 二、专精特新中小企业（省级）六大指标", "专精特新中小企业"),
        ("## 三、专精特新\"小巨人\"七项指标", "专精特新小巨人企业"),
    ]:
        cards.append({
            "project_name": name,
            "aliases": [],
            "requirements": [{"condition": row[0], "requirement": row[1]} for row in parse_table_after_heading(sme, heading)],
            "rule_status": "current",
            "version": "2026",
            "source_url": sme_url,
            "official_verification_required": True,
        })
    institute_source = re.search(r"- 来源：(https?://\S+)", institute).group(1)
    for heading, name, status in [
        ("## 省企业研究院条件（169号）", "浙江省企业研究院", "current"),
        ("## 省重点企业研究院条件（169号）", "浙江省重点企业研究院", "current"),
        ("## 市企业研究院条件（杭州征求意见稿）", "杭州市企业研究院", "draft-not-effective"),
    ]:
        cards.append({
            "project_name": name,
            "aliases": [],
            "requirements": [{"condition": row[0], "requirement": row[1]} for row in parse_table_after_heading(institute, heading)],
            "rule_status": status,
            "version": "2025-2026",
            "source_url": institute_source if status == "current" else "",
            "official_verification_required": True,
        })
    return cards


def build_canonical_index(project_map, cards):
    records = {
        record["title"]: {
            "canonical_project_name": record["title"],
            "aliases": [],
            "category": record["category"],
            "category_label": record["category_label"],
            "level": record["level"],
            "authority": record["authority"],
            "regions": record["regions"],
            "primary_region": record["primary_region"],
            "relation": "base-map",
        }
        for record in project_map
    }
    for card in cards:
        name = card["canonical_project_name"]
        if name not in records:
            category, category_label = classify(name)
            records[name] = {
                "canonical_project_name": name,
                "aliases": [],
                "category": category,
                "category_label": category_label,
                "level": "",
                "authority": "",
                "regions": list(card["regions"]),
                "primary_region": card["primary_region"],
                "relation": "high-frequency-extension",
            }
        aliases = set(records[name]["aliases"])
        aliases.update(card.get("aliases", []))
        if card["project_name"] != name:
            aliases.add(card["project_name"])
        records[name]["aliases"] = sorted(aliases)
        records[name]["regions"] = sorted(set(records[name]["regions"]) | set(card["regions"]))
    return sorted(records.values(), key=lambda item: item["canonical_project_name"])


def record_identity(item):
    canonical_name = item.get("canonical_project_name") or canonicalize_title(item.get("project_name", ""))
    if "project_name" in item:
        return "|".join((canonical_name, item["project_name"], item.get("rule_status", "")))
    return canonical_name


def load_existing(path):
    if not path.exists():
        return {}
    records = {}
    for item in (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()):
        key = record_identity(item)
        if key:
            records[key] = item
    return records


def content_digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def update_stats(previous, current):
    previous_keys = set(previous)
    current_by_key = {record_identity(item): item for item in current}
    current_keys = set(current_by_key)
    return {
        "added": len(current_keys - previous_keys),
        "updated": sum(content_digest(previous[key]) != content_digest(current_by_key[key]) for key in previous_keys & current_keys),
        "unchanged": sum(content_digest(previous[key]) == content_digest(current_by_key[key]) for key in previous_keys & current_keys),
        "removed": len(previous_keys - current_keys),
    }


def write_jsonl_atomic(path, records):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("workbook", type=Path)
    parser.add_argument("sme_rules", type=Path)
    parser.add_argument("institute_rules", type=Path)
    parser.add_argument("project_map", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--canonical-output", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    project_map = load_project_map(args.project_map)
    cards = historical_cards(args.workbook, project_map)
    cards.extend(current_cards(args.sme_rules, args.institute_rules))
    cards = sorted((relate_card(card, project_map) for card in cards), key=lambda item: item["canonical_project_name"])
    canonical_output = args.canonical_output or args.output.with_name("canonical-project-index.jsonl")
    canonical_records = build_canonical_index(project_map, cards)
    previous_cards = load_existing(args.output)
    previous_canonical = load_existing(canonical_output)
    report = {
        "rules": update_stats(previous_cards, cards),
        "canonical_index": update_stats(previous_canonical, canonical_records),
        "rule_count": len(cards),
        "canonical_count": len(canonical_records),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl_atomic(args.output, cards)
    write_jsonl_atomic(canonical_output, canonical_records)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
