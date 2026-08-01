#!/usr/bin/env python3
"""Reconstruct the missing 2022 first Zhejiang specialized-SME attachment.

The official notice establishes a 185-enterprise cohort, but the original
attachment is not present in the local archive.  The 2025 official review list
provides 176 entity-level survivors from that cohort.  Nine independently
cross-checked Qice/current-library records complete the 185 names.  The output
is intentionally marked as a reconstruction, never as the original attachment.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


SUPPLEMENTAL_ENTITIES = [
    ("浙江金固股份有限公司", "杭州市", "富阳区"),
    ("杭州士兰明芯科技有限公司", "杭州市", "钱塘区"),
    ("浙江威罗德汽配股份有限公司", "台州市", "三门县"),
    ("乐清市西街塑料制品有限公司", "温州市", "乐清市"),
    ("浙江福莱新材料股份有限公司", "嘉兴市", "嘉善县"),
    ("浙江昀丰新材料科技股份有限公司", "金华市", "金东区"),
    ("鑫磊压缩机股份有限公司", "台州市", "温岭市"),
    ("大福泵业有限公司", "台州市", "温岭市"),
    ("浙江锐亿智能科技股份有限公司", "金华市", "武义县"),
]


EXCLUDED_QICE_FALSE_DIFFERENCES = [
    "杭州图软科技有限公司",
    "杭州褐果生物科技有限公司",
    "至晟（临海）微电子技术有限公司",
    "阜时科技有限公司",
    "浙江迦美信芯通讯技术有限公司",
    "浙江苍南县金乡徽章厂有限公司",
    "湖州机床厂有限公司",
    "浙江斯乾智驾科技有限公司",
    "玉环仪表机床制造厂",
]


def normalize_name(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", value).lower()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review-subset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    review_payload = json.loads(args.review_subset.read_text(encoding="utf-8"))
    review_entities = list(review_payload.get("entities") or [])
    if len(review_entities) != 176:
        raise ValueError(
            f"2025 official review subset must contain 176 rows, got {len(review_entities)}"
        )

    entities: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entity in review_entities:
        name = str(entity.get("enterprise_name") or "").strip()
        normalized = normalize_name(name)
        if not name or normalized in seen:
            raise ValueError(f"blank or duplicate review-subset entity: {name}")
        seen.add(normalized)
        entities.append(
            {
                "sequence_no": len(entities) + 1,
                "enterprise_name": name,
                "province": "浙江省",
                "city": str(entity.get("city") or ""),
                "county": str(entity.get("county") or ""),
                "binding_basis": "official_2025_first_review_passed_subset",
            }
        )

    for name, city, county in SUPPLEMENTAL_ENTITIES:
        normalized = normalize_name(name)
        if normalized in seen:
            raise ValueError(f"supplement already present in review subset: {name}")
        seen.add(normalized)
        entities.append(
            {
                "sequence_no": len(entities) + 1,
                "enterprise_name": name,
                "province": "浙江省",
                "city": city,
                "county": county,
                "binding_basis": "current_library_plus_qice_gap_crosscheck",
            }
        )

    if len(entities) != 185:
        raise ValueError(f"reconstructed cohort must contain 185 rows, got {len(entities)}")
    city_counts: dict[str, int] = {}
    for entity in entities:
        city = str(entity["city"] or "")
        city_counts[city] = city_counts.get(city, 0) + 1

    payload = {
        "schema_version": 1,
        "source_id": "zhejiang-specialized-sme-2022-first-reconstructed",
        "document_title": "2022年度第一批浙江省专精特新中小企业名单—185家重建表",
        "project_name": "浙江省专精特新中小企业",
        "event_year": 2022,
        "batch": "第一批",
        "coverage_status": "reconstructed_original_attachment_missing",
        "coverage_basis": [
            "official_notice_announced_count_185",
            "official_2025_first_review_passed_subset_176",
            "current_library_plus_qice_crosschecked_gap_9",
        ],
        "city_counts": city_counts,
        "supplemental_entities": [name for name, _, _ in SUPPLEMENTAL_ENTITIES],
        "excluded_qice_false_differences": EXCLUDED_QICE_FALSE_DIFFERENCES,
        "entities": entities,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "entities": len(entities),
                "city_counts": city_counts,
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
