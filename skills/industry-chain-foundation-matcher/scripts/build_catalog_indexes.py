#!/usr/bin/env python3
import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

import pdfplumber


CHAIN_ROOTS = [
    "集成电路", "新能源汽车", "太阳能", "风能", "数控机床", "工业机器人", "手机",
    "新型显示", "服务器", "基站", "光通信设备", "软件", "人工智能", "农业机械",
    "医疗器械", "生物医药", "新材料", "纺织", "汽车", "工程机械", "船舶",
    "航空装备", "核电装备", "特高压输变电装备", "轨道交通", "其他",
]

FOUNDATION_FIELDS = [
    "信息通信设备", "基础软件及工业软件", "机床与基础制造装备及机器人", "先进轨道交通",
    "智能网联汽车", "节能与新能源汽车", "电力装备", "新材料", "高性能医疗器械",
    "仪器仪表", "工程机械", "农业装备", "钢铁", "有色", "石化", "建材", "食品",
    "纺织", "家用电器", "环保、低碳及资源综合利用装备", "能源电子",
]

FOUNDATION_CATEGORIES = [
    "基础零部件和元器件", "基础材料", "工业基础软件", "基础制造工艺及装备", "产业技术基础",
]

EXPECTED_CATEGORY_COUNTS = {
    "基础零部件和元器件": 289,
    "基础材料": 269,
    "工业基础软件": 100,
    "基础制造工艺及装备": 260,
    "产业技术基础": 129,
}


def page_lines(page):
    text = page.extract_text(x_tolerance=1, y_tolerance=3) or ""
    return [" ".join(line.split()) for line in text.splitlines() if line.strip()]


def write_jsonl(path, records):
    path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_chain(path):
    roots = sorted(CHAIN_ROOTS, key=len, reverse=True)
    records = []
    with pdfplumber.open(path) as document:
        page_count = len(document.pages)
        for page_number, page in enumerate(document.pages, 1):
            for line in page_lines(page):
                starts_path = any(line == root or line.startswith(f"{root}->") for root in roots)
                if starts_path:
                    records.append({"path": line, "page": page_number})
                elif records:
                    records[-1]["path"] += line
                else:
                    raise ValueError(f"产业链目录第 {page_number} 页存在无法归属的文本：{line}")

    unique = []
    seen = set()
    for record in records:
        if record["path"] not in seen:
            seen.add(record["path"])
            unique.append(record)

    paths = {record["path"] for record in unique}
    missing_parents = [
        record["path"]
        for record in unique
        if "->" in record["path"] and record["path"].rsplit("->", 1)[0] not in paths
    ]
    if missing_parents:
        raise ValueError(f"产业链索引存在缺失父节点：{missing_parents[:5]}")
    if len(unique) != 2128 or sum("->" not in record["path"] for record in unique) != 26:
        raise ValueError(f"产业链索引统计异常：{len(unique)} 条")
    return unique, page_count


def parse_foundation(path):
    records = []
    field = None
    category = None
    with pdfplumber.open(path) as document:
        page_count = len(document.pages)
        for page_number in range(14, 93):
            lines = page_lines(document.pages[page_number - 1])
            wrapped_rows = {}
            consumed = set()
            for index, line in enumerate(lines):
                if not line.isdigit() or index == 0 or index + 1 >= len(lines):
                    continue
                if re.match(r"^\d+\s+", lines[index - 1]):
                    continue
                number = int(line)
                if 1 <= number <= 200:
                    wrapped_rows[index] = (number, f"{lines[index - 1]} {lines[index + 1]}")
                    consumed.update({index - 1, index + 1})

            for index, line in enumerate(lines):
                compact = line.replace(" ", "")
                matched_field = next(
                    (candidate for candidate in FOUNDATION_FIELDS if compact == f"{candidate}领域"), None
                )
                if matched_field:
                    field = matched_field
                    continue
                matched_category = next(
                    (candidate for candidate in FOUNDATION_CATEGORIES if compact == candidate), None
                )
                if matched_category:
                    category = matched_category
                    continue
                if index in consumed:
                    continue
                if index in wrapped_rows:
                    number, item = wrapped_rows[index]
                    records.append(
                        {"field": field, "category": category, "number": number, "item": item, "page": page_number}
                    )
                    continue
                if compact in {"序号产品和技术名称", "序号产品和技术名"}:
                    continue
                if "产业基础创新发展目录" in compact or re.match(r"^\S+领域\|\d+$", compact):
                    continue
                match = re.match(r"^(\d+)\s+(.+)$", line)
                if match and field and category:
                    records.append(
                        {
                            "field": field,
                            "category": category,
                            "number": int(match.group(1)),
                            "item": match.group(2),
                            "page": page_number,
                        }
                    )
                elif records and not compact.isdigit():
                    records[-1]["item"] += f" {line}"

    counts = Counter(record["category"] for record in records)
    if len(records) != 1047 or dict(counts) != EXPECTED_CATEGORY_COUNTS:
        raise ValueError(f"产业基础索引统计异常：总数 {len(records)}，分类 {dict(counts)}")
    return records, page_count


def main():
    parser = argparse.ArgumentParser(description="从两份用户合法持有的 PDF 重建分类索引")
    parser.add_argument("--chain-pdf", required=True, type=Path)
    parser.add_argument("--foundation-pdf", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    chain, chain_pages = parse_chain(args.chain_pdf)
    foundation, foundation_pages = parse_foundation(args.foundation_pdf)
    write_jsonl(args.output / "industry-chain-index.jsonl", chain)
    write_jsonl(args.output / "industry-foundation-index.jsonl", foundation)
    result = {
        "chain": {"sha256": sha256(args.chain_pdf), "pages": chain_pages, "paths": len(chain)},
        "foundation": {
            "sha256": sha256(args.foundation_pdf),
            "pages": foundation_pages,
            "items": len(foundation),
            "category_counts": dict(Counter(record["category"] for record in foundation)),
        },
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
