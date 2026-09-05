#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


def normalize(text):
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", text).lower()


def ngrams(text, size=2):
    value = normalize(text)
    if len(value) <= size:
        return {value} if value else set()
    return {value[index:index + size] for index in range(len(value) - size + 1)}


def score(query, candidate):
    normalized_query = normalize(query)
    normalized_candidate = normalize(candidate)
    if not normalized_query or not normalized_candidate:
        return 0.0
    if normalized_query == normalized_candidate:
        return 100.0
    if normalized_query in normalized_candidate:
        return 85.0 + min(10.0, len(normalized_query) / max(len(normalized_candidate), 1) * 10)
    query_grams = ngrams(query)
    candidate_grams = ngrams(candidate)
    union = query_grams | candidate_grams
    return 80.0 * len(query_grams & candidate_grams) / len(union) if union else 0.0


def load_jsonl(path):
    with path.open(encoding="utf-8") as source:
        return [json.loads(line) for line in source if line.strip()]


def ranked(query, records, text_builder, limit):
    results = []
    normalized_query = normalize(query)
    term_matches = 0
    for record in records:
        candidate = text_builder(record)
        if normalized_query and normalized_query in normalize(candidate):
            term_matches += 1
        candidate_score = score(query, candidate)
        if candidate_score > 0:
            results.append({"score": round(candidate_score, 2), **record})
    returned = sorted(results, key=lambda item: (-item["score"], item.get("page", 0)))[:limit]
    # 检索计数不随返回条数或后续业务排除改变，避免把“不适用”写成“未检出”。
    return returned, {
        "scanned_records": len(records),
        "normalized_term_matches": term_matches,
        "scored_candidates": len(results),
        "returned_candidates": len(returned),
    }


def main():
    parser = argparse.ArgumentParser(description="检索产业链和产业基础候选项")
    parser.add_argument("query")
    parser.add_argument("--references", type=Path, default=Path(__file__).resolve().parents[1] / "references")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    chain = load_jsonl(args.references / "industry-chain-index.jsonl")
    foundation = load_jsonl(args.references / "industry-foundation-index.jsonl")
    chain_candidates, chain_summary = ranked(args.query, chain, lambda item: item["path"], args.limit)
    foundation_candidates, foundation_summary = ranked(
        args.query,
        foundation,
        lambda item: f'{item["field"]}{item["category"]}{item["item"]}',
        args.limit,
    )
    output = {
        "notice": "候选分数仅用于召回，精确匹配必须按 SKILL.md 的六要素人工核验。normalized_term_matches 是忽略标点、空白和英文大小写后的整词包含数，不是业务匹配数；排除不适用候选不得改写检索计数。",
        "search_summary": {
            "query": args.query,
            "industry_chain": chain_summary,
            "industry_foundation": foundation_summary,
        },
        "industry_chain": chain_candidates,
        "industry_foundation": foundation_candidates,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
