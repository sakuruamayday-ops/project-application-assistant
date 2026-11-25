#!/usr/bin/env python3
"""Upgraded 2021 Industry Chain & Industrial Foundation (工业六基) Catalog Search with Leaf-Weighted Scoring."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def normalize(text: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", text or "").lower()


def ngrams(text: str, size: int = 2) -> set[str]:
    value = normalize(text)
    if len(value) <= size:
        return {value} if value else set()
    return {value[index : index + size] for index in range(len(value) - size + 1)}


def _pair_score(query: str, target: str) -> float:
    nq = normalize(query)
    nt = normalize(target)
    if not nq or not nt:
        return 0.0
    if nq == nt:
        return 100.0
    if nq in nt:
        return 85.0 + min(12.0, len(nq) / max(len(nt), 1) * 12.0)
    if nt in nq and len(nt) >= 3:
        return 76.0 + min(10.0, len(nt) / max(len(nq), 1) * 10.0)
    qg = ngrams(query)
    tg = ngrams(target)
    union = qg | tg
    return 75.0 * len(qg & tg) / len(union) if union else 0.0


def score_leaf_weighted(query: str, full_text: str, leaf_text: str) -> float:
    """Give leaf product/item exact/substring matches decisive priority over broad ancestor categories."""
    s_leaf = _pair_score(query, leaf_text)
    s_full = _pair_score(query, full_text)
    if s_leaf >= 85.0:
        return min(100.0, s_leaf + 2.0)
    return max(s_leaf * 0.72 + s_full * 0.28, s_full * 0.85)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as source:
        return [json.loads(line) for line in source if line.strip()]


def ranked(
    query: str,
    records: list[dict[str, Any]],
    full_builder,
    leaf_builder,
    limit: int,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    results = []
    nq = normalize(query)
    term_matches = 0
    for record in records:
        full_text = full_builder(record)
        leaf_text = leaf_builder(record)
        if nq and (nq in normalize(full_text) or nq in normalize(leaf_text)):
            term_matches += 1
        sc = score_leaf_weighted(query, full_text, leaf_text)
        if sc > 0:
            results.append({"score": round(sc, 2), **record})
    returned = sorted(results, key=lambda item: (-item["score"], item.get("page", 0)))[:limit]
    return returned, {
        "scanned_records": len(records),
        "normalized_term_matches": term_matches,
        "scored_candidates": len(results),
        "returned_candidates": len(returned),
    }


def search_catalogs(query: str, references_dir: Path, limit: int = 10) -> dict[str, Any]:
    chain = load_jsonl(references_dir / "industry-chain-index.jsonl")
    foundation = load_jsonl(references_dir / "industry-foundation-index.jsonl")
    chain_candidates, chain_summary = ranked(
        query,
        chain,
        lambda item: item.get("path", ""),
        lambda item: str(item.get("path", "")).split("/")[-1].split(">")[-1].split("—")[-1],
        limit,
    )
    foundation_candidates, foundation_summary = ranked(
        query,
        foundation,
        lambda item: f'{item.get("field", "")}{item.get("category", "")}{item.get("item", "")}',
        lambda item: str(item.get("item", "")),
        limit,
    )
    return {
        "search_summary": {
            "query": query,
            "industry_chain": chain_summary,
            "industry_foundation": foundation_summary,
        },
        "industry_chain": chain_candidates,
        "industry_foundation": foundation_candidates,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="叶节点加权检索《产业链架构》与《产业基础创新发展目录（2021）》")
    parser.add_argument("query")
    parser.add_argument("--references", type=Path, default=Path(__file__).resolve().parents[1] / "references")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    print(json.dumps(search_catalogs(args.query, args.references, args.limit), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
