#!/usr/bin/env python3
"""Upgraded 2021 Industry Chain & Industrial Foundation (工业六基) Catalog Search with Leaf-Weighted & IDF-Adjusted Scoring."""
from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

# Domain-neutral boilerplate suffixes/bigrams that cause false matches across unrelated industries
GENERIC_BIGRAMS = {
    "成套", "套装", "装备", "设备", "配套", "套设", "套备", "系统", "技术", "工艺",
    "产品", "材料", "制造", "工业", "通用", "专用", "关键", "核心", "新型", "高端",
    "智能", "自动", "基础", "其他", "及其", "及成", "与成", "化装", "化设", "高性",
    "性能", "高精", "精密", "复合", "功能", "应用", "服务", "解决", "方案", "部件",
    "零件", "元件", "器件", "装置", "机组", "产线", "生产", "加工",
}


def normalize(text: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", text or "").lower()


def ngrams(text: str, size: int = 2) -> set[str]:
    value = normalize(text)
    if len(value) <= size:
        return {value} if value else set()
    return {value[index : index + size] for index in range(len(value) - size + 1)}


def _build_idf(records: list[dict[str, Any]], text_builder) -> dict[str, float]:
    df: Counter[str] = Counter()
    total = max(len(records), 1)
    for rec in records:
        for g in ngrams(text_builder(rec)):
            df[g] += 1
    idf: dict[str, float] = {}
    for g, count in df.items():
        base = math.log((total + 1.0) / (count + 1.0)) + 0.5
        if g in GENERIC_BIGRAMS:
            base *= 0.12
        idf[g] = base
    return idf


def _bigram_weight(g: str, idf: dict[str, float] | None) -> float:
    if g in GENERIC_BIGRAMS:
        return (idf.get(g, 1.0) if idf else 0.12)
    return idf.get(g, 3.5) if idf else 1.0


def _pair_score(query: str, target: str, idf: dict[str, float] | None = None) -> float:
    nq = normalize(query)
    nt = normalize(target)
    if not nq or not nt:
        return 0.0
    if nq == nt:
        return 100.0
    if nq in nt:
        if len(nq) <= 3 and all(g in GENERIC_BIGRAMS for g in ngrams(nq)):
            return 14.0
        return 85.0 + min(12.0, len(nq) / max(len(nt), 1) * 12.0)
    if nt in nq and len(nt) >= 3:
        # Guard against short generic leaf terms like "主装备" dominating specific queries
        if len(nt) <= 4 and all(g in GENERIC_BIGRAMS for g in ngrams(nt)):
            return 12.0
        return 76.0 + min(10.0, len(nt) / max(len(nq), 1) * 10.0)
    qg = ngrams(query)
    tg = ngrams(target)
    overlap = qg & tg
    if not overlap:
        return 0.0
    # Require at least one non-generic bigram if query has specific bigrams
    specific_q = {g for g in qg if g not in GENERIC_BIGRAMS}
    specific_overlap = overlap & specific_q
    union = qg | tg
    num = sum(_bigram_weight(g, idf) for g in overlap)
    den = sum(_bigram_weight(g, idf) for g in union)
    raw = 75.0 * num / den if den > 0 else 0.0
    if specific_q and not specific_overlap:
        raw = min(raw * 0.25, 4.0)
    return raw


def score_leaf_weighted(
    query: str,
    full_text: str,
    leaf_text: str,
    idf: dict[str, float] | None = None,
) -> float:
    """Give leaf product/item exact/substring matches decisive priority over broad ancestor categories."""
    s_leaf = _pair_score(query, leaf_text, idf)
    s_full = _pair_score(query, full_text, idf)
    if s_leaf >= 85.0:
        return min(100.0, s_leaf + 2.0)
    return max(s_leaf * 0.72 + s_full * 0.28, s_full * 0.85)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as source:
        return [json.loads(line) for line in source if line.strip()]


def _confidence_label(top_score: float) -> str:
    if top_score >= 40.0:
        return "high"
    if top_score >= 18.0:
        return "medium"
    return "low"


def ranked(
    query: str,
    records: list[dict[str, Any]],
    full_builder,
    leaf_builder,
    limit: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    idf = _build_idf(records, full_builder)
    results = []
    nq = normalize(query)
    term_matches = 0
    for record in records:
        full_text = full_builder(record)
        leaf_text = leaf_builder(record)
        if nq and (nq in normalize(full_text) or nq in normalize(leaf_text)):
            term_matches += 1
        sc = score_leaf_weighted(query, full_text, leaf_text, idf)
        if sc > 0:
            results.append({"score": round(sc, 2), **record})
    returned = sorted(results, key=lambda item: (-item["score"], item.get("page", 0)))[:limit]
    top_score = returned[0]["score"] if returned else 0.0
    conf = _confidence_label(top_score)
    summary: dict[str, Any] = {
        "scanned_records": len(records),
        "normalized_term_matches": term_matches,
        "scored_candidates": len(results),
        "returned_candidates": len(returned),
        "top_score": top_score,
        "match_confidence": conf,
    }
    if conf == "low":
        summary["warning"] = "未在2021版目录中找到高置信度精确词条，建议结合企业主营工艺实质与最新产业链目录人工/联网核定，勿硬套低分条目。"
    return returned, summary


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
