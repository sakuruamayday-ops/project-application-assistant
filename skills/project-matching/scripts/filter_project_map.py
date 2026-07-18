#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


def relevance(record, keywords):
    if not keywords:
        return 1
    text = " ".join(
        [
            record["canonical_project_name"],
            record.get("category_label", ""),
            record.get("authority", ""),
            *record.get("aliases", []),
        ]
    ).lower()
    return sum(1 for keyword in keywords if keyword.lower() in text)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("index", type=Path)
    parser.add_argument("--scope", action="append", required=True)
    parser.add_argument("--keyword", action="append", default=[])
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    scope = set(args.scope)
    matches = []
    for line in args.index.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("primary_region") not in scope:
            continue
        score = relevance(record, args.keyword)
        if args.keyword and score == 0:
            continue
        matches.append((score, record))
    matches.sort(key=lambda item: (-item[0], item[1]["canonical_project_name"]))
    for _, record in matches[: args.limit]:
        print(json.dumps(record, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
