from __future__ import annotations

import json
from pathlib import Path

from scripts.build_knowledge_content_index import DEFAULT_PROJECT_INDEX, normalize_match_text


FEATURE_CATEGORIES = {
    "研发": {"technology"},
    "科技": {"technology"},
    "装备": {"industrialization", "investment"},
    "设备": {"industrialization", "investment"},
    "自动化": {"digitalization", "industrialization", "investment"},
    "智能": {"digitalization", "industrialization"},
    "数字化": {"digitalization"},
    "绿色": {"green"},
    "节能": {"green"},
    "专利": {"intellectual-property", "technology"},
    "知识产权": {"intellectual-property"},
    "中小企业": {"small-business"},
    "专精特新": {"small-business"},
    "人才": {"talent"},
    "标准": {"quality-brand"},
    "品牌": {"quality-brand"},
    "质量": {"quality-brand"},
}


def load_project_records(path: Path = DEFAULT_PROJECT_INDEX) -> list[dict[str, object]]:
    if not path.is_file():
        return []
    records: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("canonical_project_name"):
            records.append(record)
    return records


def match_project_records(
    regions: list[str] | None = None,
    keywords: list[str] | None = None,
    limit: int = 20,
    project_index: Path = DEFAULT_PROJECT_INDEX,
) -> dict[str, object]:
    normalized_regions = {str(region).strip() for region in (regions or []) if str(region).strip()}
    normalized_keywords = [
        normalize_match_text(str(keyword))
        for keyword in (keywords or [])
        if str(keyword).strip()
    ]
    if not normalized_regions and not normalized_keywords:
        raise ValueError("项目地图匹配至少需要地区或企业关键词")
    records = load_project_records(project_index)
    expanded_regions = set(normalized_regions)
    if normalized_regions:
        expanded_regions.add("全国")
        for record in records:
            record_regions = {str(region) for region in record.get("regions", [])}
            if normalized_regions.intersection(record_regions):
                expanded_regions.update(region for region in record_regions if region != "待确认")
    scored: list[tuple[int, str, dict[str, object]]] = []
    for record in records:
        record_regions = {
            str(record.get("primary_region") or ""),
            *(str(region) for region in record.get("regions", [])),
        }
        if expanded_regions and not expanded_regions.intersection(record_regions):
            continue
        identity_text = normalize_match_text(" ".join(
            (
                str(record.get("canonical_project_name") or ""),
                *(str(alias) for alias in record.get("aliases", [])),
            )
        ))
        category_text = normalize_match_text(" ".join(
            (str(record.get("category_label") or ""), str(record.get("authority") or ""))
        ))
        identity_matches = [keyword for keyword in normalized_keywords if keyword in identity_text]
        category_matches = [
            keyword for keyword in normalized_keywords
            if keyword not in identity_matches and keyword in category_text
        ]
        category = str(record.get("category") or "")
        feature_matches = [
            keyword for keyword in normalized_keywords
            if category in FEATURE_CATEGORIES.get(keyword, set())
        ]
        score = len(identity_matches) * 4 + len(category_matches) * 2 + len(feature_matches)
        if normalized_keywords and score == 0:
            continue
        result = dict(record)
        result["match_score"] = score
        result["matched_keywords"] = sorted(set(identity_matches + category_matches + feature_matches))
        scored.append((score, str(record["canonical_project_name"]), result))
    scored.sort(key=lambda item: (-item[0], item[1]))
    bounded_limit = max(1, min(int(limit), 50))
    return {
        "regions": sorted(expanded_regions),
        "keywords": normalized_keywords,
        "status": "candidate_only",
        "notice": "项目地图只用于理论候选召回，进入当期可申报前仍须核验政策原文和企业可靠数据。",
        "results": [record for _, _, record in scored[:bounded_limit]],
    }
