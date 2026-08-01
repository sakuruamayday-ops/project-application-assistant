#!/usr/bin/env python3
"""Parse the signed 2025 Zhejiang second-batch specialized SME notice.

The PDF is the final provincial notice.  This script keeps the enterprise name
exactly as extracted from the numbered attachment row, verifies every sequence
number, and emits durable supplemental lifecycle events for the timeline build.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd
from pypdf import PdfReader


DEFAULT_SOURCE = Path(
    "/Users/zsh/JiaotangData/知识库/50_名单与对标/企业身份时间轴/浙江省/"
    "用户确认来源/2025年第二批浙江省专精特新中小企业/省级正式通知/"
    "浙经信企业〔2026〕4号_2025年第二批浙江省专精特新中小企业和通过复核企业名单.pdf"
)
DEFAULT_OUTPUT_DIR = Path(
    "/Users/zsh/JiaotangData/知识库/50_名单与对标/企业身份时间轴/浙江省"
)
DEFAULT_EVENTS = DEFAULT_OUTPUT_DIR / "浙江省补充认定事件.jsonl"
DEFAULT_REPORT = DEFAULT_OUTPUT_DIR / "2025年第二批浙江省专精特新中小企业正式名单解析报告.json"
DEFAULT_EXISTING_EVENTS = DEFAULT_OUTPUT_DIR / "浙江省企业认定事件.jsonl"

PROJECT_NAME = "浙江省专精特新中小企业"
SOURCE_TITLE = (
    "浙江省经济和信息化厅关于公布2025年第二批浙江省专精特新中小企业"
    "和通过复核企业名单的通知（浙经信企业〔2026〕4号）"
)
NUMBERED_ROW = re.compile(r"^\s*(\d+)\s+(.+?)\s*$")
BLANK_NUMBERED_ROW = re.compile(r"^\s*(\d+)\s*$")
AIQICE_PUBLICITY_ROOT = Path(
    "/Users/zsh/JiaotangData/知识库/10_政策与目录/政策数据库/企策顾问/"
    "公示公告"
)


def city_publicity_dir(city: str, index_id: str) -> Path:
    return (
        AIQICE_PUBLICITY_ROOT
        / city
        / "优质中小企业梯度培育"
        / (
            "2025-12-30__关于2025年第二批浙江省专精特新中小企业"
            f"认定和复核通过名单的公示__{index_id}"
        )
    )


CITY_ATTACHMENT_SOURCES = [
    {
        "city": "杭州市",
        "event_type": "recognition",
        "index_id": "9ebcd483124740b6aa1a9d8ab56292d0",
        "path": city_publicity_dir(
            "杭州市", "9ebcd483124740b6aa1a9d8ab56292d0"
        )
        / "附件/附件1.2025年第二批专精特新中小企业拟认定名单.xlsx",
    },
    {
        "city": "杭州市",
        "event_type": "review_passed",
        "index_id": "9ebcd483124740b6aa1a9d8ab56292d0",
        "path": city_publicity_dir(
            "杭州市", "9ebcd483124740b6aa1a9d8ab56292d0"
        )
        / "附件/附件2.拟复核通过名单.xlsx",
    },
    {
        "city": "绍兴市",
        "event_type": "recognition",
        "index_id": "78a8ae87ef234a599d6d5ee2047a7efc",
        "path": city_publicity_dir(
            "绍兴市", "78a8ae87ef234a599d6d5ee2047a7efc"
        )
        / "附件/1.2025年第二批专精特新中小企业拟认定名单.xlsx",
    },
    {
        "city": "绍兴市",
        "event_type": "review_passed",
        "index_id": "78a8ae87ef234a599d6d5ee2047a7efc",
        "path": city_publicity_dir(
            "绍兴市", "78a8ae87ef234a599d6d5ee2047a7efc"
        )
        / "附件/2.拟复核通过名单.xlsx",
    },
    {
        "city": "金华市",
        "event_type": "recognition",
        "index_id": "7a3673ea14fa4134b06aa80613efc075",
        "path": city_publicity_dir(
            "金华市", "7a3673ea14fa4134b06aa80613efc075"
        )
        / "附件/附件1：2025年第二批专精特新中小企业拟认定名单.xlsx.xlsx",
    },
    {
        "city": "金华市",
        "event_type": "review_passed",
        "index_id": "7a3673ea14fa4134b06aa80613efc075",
        "path": city_publicity_dir(
            "金华市", "7a3673ea14fa4134b06aa80613efc075"
        )
        / "附件/附件2.拟复核通过名单.xls.xls",
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--existing-events",
        type=Path,
        default=DEFAULT_EXISTING_EVENTS,
    )
    return parser.parse_args()


def normalized_name(value: str) -> str:
    value = re.sub(r"[“”\"'‘’]", "", value or "")
    return re.sub(r"[\s·•（）()\-—_，,。．]+", "", value).lower()


def extract_numbered_rows(
    reader: PdfReader,
    *,
    first_page: int,
    last_page: int,
    expected_count: int,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    rows: list[dict[str, Any]] = []
    blank_rows: list[dict[str, Any]] = []
    unexpected: list[dict[str, Any]] = []
    next_sequence = 1
    for page_number in range(first_page, last_page + 1):
        text = reader.pages[page_number - 1].extract_text() or ""
        for line in text.splitlines():
            match = NUMBERED_ROW.match(line)
            if not match:
                blank_match = BLANK_NUMBERED_ROW.match(line)
                if blank_match and int(blank_match.group(1)) == next_sequence:
                    blank_rows.append(
                        {
                            "sequence_no": next_sequence,
                            "page_number": page_number,
                            "reason": "名单原文只有序号，企业名称栏为空",
                        }
                    )
                    next_sequence += 1
                continue
            sequence = int(match.group(1))
            enterprise_name = match.group(2).strip()
            if sequence == 2025 and enterprise_name.startswith("年"):
                continue
            if sequence == next_sequence:
                rows.append(
                    {
                        "sequence_no": sequence,
                        "enterprise_name": enterprise_name,
                        "page_number": page_number,
                    }
                )
                next_sequence += 1
                continue
            if 1 <= sequence <= expected_count:
                unexpected.append(
                    {
                        "page_number": page_number,
                        "line": line,
                        "expected_sequence": next_sequence,
                        "observed_sequence": sequence,
                    }
                )
    if len(rows) + len(blank_rows) != expected_count or next_sequence != expected_count + 1:
        raise ValueError(
            "numbered attachment is incomplete: "
            f"pages={first_page}-{last_page} expected={expected_count} "
            f"named={len(rows)} blank={len(blank_rows)} "
            f"next_sequence={next_sequence}"
        )
    if unexpected:
        raise ValueError(
            "unexpected in-range numbered rows: "
            + json.dumps(unexpected[:20], ensure_ascii=False)
        )
    return rows, blank_rows, unexpected


def make_event(
    row: dict[str, Any],
    *,
    source: Path,
    event_type: str,
    status: str,
    cohort_year: int | None,
) -> dict[str, Any]:
    return {
        "enterprise_name": row["enterprise_name"],
        "project_name": PROJECT_NAME,
        "event_year": 2025,
        "cohort_year": cohort_year,
        "event_type": event_type,
        "event_scope": "qualification",
        "evidence_status": "official_final_list",
        "batch": "第二批",
        "status": status,
        "recognition_province": "浙江省",
        "recognition_city": "",
        "recognition_county": "",
        "source_title": SOURCE_TITLE,
        "source_path": str(source),
        "source_url": "",
        "sequence_no": str(row["sequence_no"]),
        "source_kind": "official_final_list_user_attachment",
        "source_page": row["page_number"],
    }


def read_city_publicity_rows(source: dict[str, Any]) -> list[dict[str, str]]:
    path = Path(source["path"])
    if not path.is_file():
        return []
    frame = pd.read_excel(path, dtype=str).fillna("")
    name_column = next(
        column for column in frame.columns if "企业名称" in str(column)
    )
    sequence_column = next(
        (column for column in frame.columns if "序号" in str(column)),
        None,
    )
    city_column = next(
        (
            column
            for column in frame.columns
            if str(column).strip() in {"设区市", "地市"}
        ),
        None,
    )
    county_column = next(
        (
            column
            for column in frame.columns
            if "区县" in str(column) or "县（市、区" in str(column)
        ),
        None,
    )
    rows: list[dict[str, str]] = []
    for index, item in frame.iterrows():
        enterprise_name = str(item[name_column]).strip()
        if not enterprise_name:
            continue
        rows.append(
            {
                "enterprise_name": enterprise_name,
                "sequence_no": (
                    str(item[sequence_column]).strip()
                    if sequence_column is not None
                    else str(index + 1)
                ),
                "recognition_city": (
                    str(item[city_column]).strip()
                    if city_column is not None
                    else str(source["city"])
                ),
                "recognition_county": (
                    str(item[county_column]).strip()
                    if county_column is not None
                    else ""
                ),
            }
        )
    return rows


def enrich_events_from_city_publicity(
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    event_index = {
        (str(row["event_type"]), normalized_name(str(row["enterprise_name"]))): row
        for row in events
    }
    audits: list[dict[str, Any]] = []
    for source in CITY_ATTACHMENT_SOURCES:
        path = Path(source["path"])
        rows = read_city_publicity_rows(source)
        matched = 0
        unmatched: list[dict[str, str]] = []
        for row in rows:
            key = (
                str(source["event_type"]),
                normalized_name(row["enterprise_name"]),
            )
            event = event_index.get(key)
            if event is None:
                unmatched.append(row)
                continue
            event["recognition_city"] = row["recognition_city"]
            event["recognition_county"] = row["recognition_county"]
            event["city_publicity_source_path"] = str(path)
            event["city_publicity_index_id"] = str(source["index_id"])
            event["city_publicity_name_at_event"] = row["enterprise_name"]
            matched += 1
        audits.append(
            {
                "city": str(source["city"]),
                "event_type": str(source["event_type"]),
                "index_id": str(source["index_id"]),
                "source_path": str(path),
                "source_available": path.is_file(),
                "source_row_count": len(rows),
                "matched_final_event_count": matched,
                "unmatched_source_rows": unmatched,
            }
        )
    return audits


def read_existing_project_names(path: Path) -> set[str]:
    names: set[str] = set()
    if not path.is_file():
        return names
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("project_name") != PROJECT_NAME:
                continue
            name = str(row.get("enterprise_name_at_event") or "").strip()
            if name:
                names.add(normalized_name(name))
    return names


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    temporary.replace(path)


def main() -> None:
    args = parse_args()
    source = args.source.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    reader = PdfReader(str(source))
    if len(reader.pages) != 114:
        raise ValueError(f"unexpected PDF page count: {len(reader.pages)}")

    recognition_rows, recognition_blank_rows, recognition_unexpected = extract_numbered_rows(
        reader,
        first_page=3,
        last_page=40,
        expected_count=1238,
    )
    review_rows, review_blank_rows, review_unexpected = extract_numbered_rows(
        reader,
        first_page=41,
        last_page=113,
        expected_count=2158,
    )
    recognition_events = [
        make_event(
            row,
            source=source,
            event_type="recognition",
            status="认定",
            cohort_year=None,
        )
        for row in recognition_rows
    ]
    review_events = [
        make_event(
            row,
            source=source,
            event_type="review_passed",
            status="复核通过",
            cohort_year=2022,
        )
        for row in review_rows
    ]
    events = [*recognition_events, *review_events]
    city_publicity_audits = enrich_events_from_city_publicity(events)
    write_jsonl(args.events, events)

    existing_names = read_existing_project_names(args.existing_events)
    formal_names = {normalized_name(row["enterprise_name"]) for row in events}
    report = {
        "schema_version": 1,
        "source_title": SOURCE_TITLE,
        "source_path": str(source),
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "page_count": len(reader.pages),
        "published_at": "2026-01-08",
        "qualification_valid_from": "2025-12",
        "qualification_valid_to": "2028-12",
        "recognition": {
            "event_year": 2025,
            "batch": "第二批",
            "page_range": [3, 40],
            "declared_row_count": 1238,
            "named_row_count": len(recognition_rows),
            "blank_sequence_rows": recognition_blank_rows,
            "first_enterprise": recognition_rows[0]["enterprise_name"],
            "last_enterprise": recognition_rows[-1]["enterprise_name"],
            "sequence_complete": True,
            "unexpected_numbered_rows": recognition_unexpected,
        },
        "review_passed": {
            "event_year": 2025,
            "cohort_year": 2022,
            "batch": "第二批",
            "page_range": [41, 113],
            "declared_row_count": 2158,
            "named_row_count": len(review_rows),
            "blank_sequence_rows": review_blank_rows,
            "first_enterprise": review_rows[0]["enterprise_name"],
            "last_enterprise": review_rows[-1]["enterprise_name"],
            "sequence_complete": True,
            "unexpected_numbered_rows": review_unexpected,
        },
        "formal_event_count": len(events),
        "formal_unique_name_count": len(formal_names),
        "recognition_review_name_overlap": len(
            {normalized_name(row["enterprise_name"]) for row in recognition_rows}
            & {normalized_name(row["enterprise_name"]) for row in review_rows}
        ),
        "new_project_names_before_ingest": len(formal_names - existing_names),
        "city_publicity_attachment_audits": city_publicity_audits,
        "city_publicity_attachment_totals": {
            "source_rows": sum(
                int(row["source_row_count"])
                for row in city_publicity_audits
            ),
            "matched_final_events": sum(
                int(row["matched_final_event_count"])
                for row in city_publicity_audits
            ),
            "unmatched_source_rows": sum(
                len(row["unmatched_source_rows"])
                for row in city_publicity_audits
            ),
        },
        "source_name_anomalies": [
            *[
                {
                    **row,
                    "reason": "名单原文企业名称栏为空，禁止补造主体",
                }
                for row in [*recognition_blank_rows, *review_blank_rows]
            ],
            *[
                {
                    "sequence_no": row["sequence_no"],
                    "enterprise_name": row["enterprise_name"],
                    "page_number": row["page_number"],
                    "reason": "名单原文企业名称以连字符加长数字结尾，禁止自动删除或改名",
                }
                for row in review_rows
                if re.search(r"-\d{4,}$", row["enterprise_name"])
            ],
            *[
                {
                    "sequence_no": row["sequence_no"],
                    "enterprise_name": row["enterprise_name"],
                    "page_number": row["page_number"],
                    "reason": "名单原文单个拉丁字母两侧含空格，禁止自动合并疑似主体",
                }
                for row in review_rows
                if re.search(
                    r"[\u3400-\u9fff]\s+[A-Za-z]\s+[\u3400-\u9fff]",
                    row["enterprise_name"],
                )
            ],
        ],
        "output_events": str(args.events.resolve()),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
