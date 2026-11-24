#!/usr/bin/env python3
import argparse
import json
import unicodedata
from pathlib import Path


def project_name(record):
    for field in ("canonical_project_name", "title", "name"):
        value = record.get(field)
        if isinstance(value, str) and value.strip():
            return value
    raise ValueError("缺少项目名称（canonical_project_name、title、name 均无有效值）")


def normalize_identity_part(value):
    text = "" if value is None else str(value)
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def derive_project_id(name, record):
    region = normalize_identity_part(record.get("primary_region"))
    year = normalize_identity_part(record.get("year")).removesuffix("年度").removesuffix("年").strip()
    identity = [normalize_identity_part(name), region, year]
    return "project:" + json.dumps(identity, ensure_ascii=False, separators=(",", ":"))


def relevance(record, name, keywords):
    if not keywords:
        return 1
    text = " ".join(
        [
            name,
            record.get("category_label") or "",
            record.get("authority") or "",
            *(record.get("aliases") or []),
        ]
    ).lower()
    return sum(1 for keyword in keywords if keyword.lower() in text)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("index", type=Path)
    parser.add_argument("--scope", action="append", required=True, help="限定 primary_region，可重复，任一值匹配即保留")
    parser.add_argument("--scope-match", choices=("exact", "contains"), default="exact",
                        help="exact 要求地区全等（默认），contains 匹配地区中的连续子串")
    parser.add_argument("--keyword", action="append", default=[])
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    scopes = set(args.scope)
    matches = []
    with args.index.open(encoding="utf-8-sig") as index:
        for line_number, line in enumerate(index, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError("索引记录必须是 JSON 对象")
                name = project_name(record)
            except ValueError as error:
                parser.error(f"{args.index}:{line_number} {error}")
            region = record.get("primary_region")
            if not isinstance(region, str):
                continue
            in_scope = (
                region in scopes if args.scope_match == "exact"
                else any(scope in region for scope in scopes)
            )
            if not in_scope:
                continue
            score = relevance(record, name, args.keyword)
            if args.keyword and score == 0:
                continue
            matches.append((score, name, record))
    matches.sort(key=lambda item: (-item[0], item[1]))
    for _, name, record in matches[:args.limit]:
        output = {**record, "project_id": derive_project_id(name, record)}
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
