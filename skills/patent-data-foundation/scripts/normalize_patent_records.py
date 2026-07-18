#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


def normalize_number(value):
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def normalize_name(value):
    return re.sub(r"[\s·•,，。()（）]", "", str(value or "")).upper()


def normalize_record(record):
    normalized = dict(record)
    for field in ("publication_number", "application_number"):
        normalized[field] = normalize_number(record.get(field))
    for field in ("applicants_original", "owners_current", "inventors"):
        values = record.get(field) or []
        if isinstance(values, str):
            values = [values]
        normalized[field] = [
            {"original": value, "normalized": normalize_name(value)} for value in values
        ]
    normalized.setdefault("status_sources", [])
    normalized.setdefault("legal_status", "无法确认")
    return normalized


def main():
    parser = argparse.ArgumentParser(description="规范化JSONL专利记录")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    with arguments.input.open(encoding="utf-8") as source, arguments.output.open("w", encoding="utf-8") as target:
        for line in source:
            if line.strip():
                target.write(json.dumps(normalize_record(json.loads(line)), ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
