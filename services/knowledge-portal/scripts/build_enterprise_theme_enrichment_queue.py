#!/usr/bin/env python3
"""Build a reproducible topic-enrichment queue from the licensed Qice snapshots.

The public projection never exposes the licensed platform name.  Exact
enterprise-name matches may contribute industry/product topics.  Product-name
matches are kept as identity-correction candidates and are never auto-merged.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable


PUBLIC_SOURCE = "共创研究院知识库"
DEFAULT_SOURCE_ROOT = Path(
    "/Users/zsh/JiaotangData/知识库/10_政策与目录/政策数据库/企策顾问/_结构化源"
)
DEFAULT_UNIFIED = Path(
    "/Users/zsh/JiaotangData/知识库/50_名单与对标/企业身份时间轴/统一企业数字身份证.jsonl"
)
DEFAULT_OUTPUT = Path(
    "/Users/zsh/JiaotangData/知识库/50_名单与对标/企业身份时间轴/浙江省/主题补全/"
    "企业主题补全队列_20260811.jsonl"
)
DEFAULT_SUMMARY = DEFAULT_OUTPUT.with_suffix(".summary.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成企业产品与行业主题补全队列")
    parser.add_argument("--unified", type=Path, default=DEFAULT_UNIFIED)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    return parser.parse_args()


def normalize(value: object) -> str:
    return re.sub(
        r"[\s·•・,，。;；:：()（）【】\[\]\\\"“”'‘’\-—_]+",
        "",
        str(value or ""),
    ).lower()


def as_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
        return [item.strip() for item in re.split(r"[;；、]", value) if item.strip()]
    return []


def unique(values: Iterable[object]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        key = normalize(text)
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(text)
    return output


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise RuntimeError(f"{path}:{line_number} 不是JSON对象")
            rows.append(row)
    return rows


def record_names(row: dict[str, Any]) -> list[str]:
    values: list[object] = [row.get("newestEntName"), row.get("entName")]
    values.extend(as_list(row.get("entHisList")))
    values.extend(as_list(row.get("entNameHistory")))
    for item in row.get("entList") or []:
        if isinstance(item, dict):
            values.extend((item.get("newestEntName"), item.get("entName")))
    return unique(values)


def record_products(row: dict[str, Any]) -> list[str]:
    values: list[object] = [row.get("production")]
    subject = str(row.get("subject") or "").strip()
    if subject:
        values.append(subject.split("::", 1)[0])
    return unique(values)


def record_topics(row: dict[str, Any]) -> tuple[list[str], list[str]]:
    products = record_products(row)
    industries = unique((row.get("industryName"), row.get("industryTopName")))
    return products, industries


def load_source_records(source_root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    small_giant = read_json(
        source_root / "企策顾问_国家专精特新小巨人_2019年至今_2026-07-22.json"
    )
    records.extend(row for row in small_giant.get("records", []) if isinstance(row, dict))

    history = read_json(source_root / "qice_three_first_history_full.json")
    for project in history.get("projects", []):
        records.extend(row for row in project.get("records", []) if isinstance(row, dict))

    details = read_json(source_root / "qice_three_first_product_details_merged_20260726.json")
    for project in details.get("projects", []):
        for policy in project.get("policies", []):
            records.extend(row for row in policy.get("records", []) if isinstance(row, dict))
    return records


def is_theme_empty(row: dict[str, Any]) -> bool:
    return not as_list(row.get("main_product_tags")) and not as_list(
        row.get("industry_track_tags")
    )


def suspicious_enterprise_name(value: object) -> bool:
    text = str(value or "").strip()
    normalized = normalize(text)
    if normalized in {"有限公司", "备有限公司"}:
        return True
    return not any(suffix in text for suffix in ("公司", "集团", "研究院", "厂"))


def fuzzy_product_candidates(
    name: str,
    products: dict[str, set[int]],
) -> set[int]:
    normalized = normalize(name)
    if not normalized:
        return set()
    candidates: set[int] = set()
    for product, indexes in products.items():
        if len(normalized) >= 6 and sorted(normalized) == sorted(product):
            candidates.update(indexes)
            continue
        if normalized in product or product in normalized:
            candidates.update(indexes)
            continue
        if SequenceMatcher(None, normalized, product).ratio() >= 0.78:
            candidates.update(indexes)
    return candidates


def build_queue(
    unified_rows: list[dict[str, Any]], source_records: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    name_index: defaultdict[str, set[int]] = defaultdict(set)
    product_index: defaultdict[str, set[int]] = defaultdict(set)
    for index, source in enumerate(source_records):
        for name in record_names(source):
            name_index[normalize(name)].add(index)
        for product in record_products(source):
            product_index[normalize(product)].add(index)

    queue: list[dict[str, Any]] = []
    stats: defaultdict[str, int] = defaultdict(int)
    for profile in unified_rows:
        if not is_theme_empty(profile):
            continue
        stats["initial_theme_empty"] += 1
        names = unique(
            [profile.get("current_name")]
            + as_list(profile.get("former_names"))
            + as_list(profile.get("recognition_names"))
        )
        matched: set[int] = set()
        for name in names:
            matched.update(name_index.get(normalize(name), set()))
        method = "exact_enterprise_name" if matched else "not_found"
        if not matched and suspicious_enterprise_name(profile.get("current_name")):
            matched = fuzzy_product_candidates(str(profile.get("current_name") or ""), product_index)
            if matched:
                method = "product_name_candidate"

        matched_records = [source_records[index] for index in sorted(matched)]
        matched_names = unique(
            name for row in matched_records for name in record_names(row)
        )
        product_topics = unique(
            value
            for row in matched_records
            for value in record_topics(row)[0]
        )
        industry_topics = unique(
            value
            for row in matched_records
            for value in record_topics(row)[1]
        )
        unique_enterprises = {normalize(name) for name in matched_names if normalize(name)}
        if method == "product_name_candidate" and len(unique_enterprises) != 1:
            method = "ambiguous_product_name"
        if method == "exact_enterprise_name":
            stats["qice_name_matched"] += 1
        elif method == "product_name_candidate":
            stats["qice_product_candidate"] += 1
        elif method == "ambiguous_product_name":
            stats["qice_ambiguous"] += 1
        else:
            stats["qice_not_found"] += 1
        if product_topics or industry_topics:
            stats["qice_topics_available"] += 1

        queue.append(
            {
                "identity_key": str(profile.get("identity_key") or ""),
                "unified_social_credit_code": str(
                    profile.get("unified_social_credit_code") or ""
                ),
                "current_name": str(profile.get("current_name") or ""),
                "recognition_projects": as_list(profile.get("recognition_projects")),
                "match_status": method,
                "matched_enterprise_names": matched_names,
                "candidate_main_product_tags": product_topics,
                "candidate_industry_track_tags": industry_topics,
                "requires_qizhidao": int(
                    method in {"not_found", "ambiguous_product_name"}
                    or not (product_topics or industry_topics)
                ),
                "source": PUBLIC_SOURCE,
            }
        )
    stats["requires_qizhidao"] = sum(int(row["requires_qizhidao"]) for row in queue)
    return queue, dict(stats)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def main() -> None:
    args = parse_args()
    queue, stats = build_queue(read_jsonl(args.unified), load_source_records(args.source_root))
    if stats.get("initial_theme_empty") != 155:
        raise RuntimeError(
            f"主题空记录基线漂移，预期155条，实际{stats.get('initial_theme_empty', 0)}条"
        )
    write_jsonl(args.output, queue)
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(
        json.dumps({"stats": stats, "source": PUBLIC_SOURCE}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"output": str(args.output), "stats": stats}, ensure_ascii=False))


if __name__ == "__main__":
    main()
