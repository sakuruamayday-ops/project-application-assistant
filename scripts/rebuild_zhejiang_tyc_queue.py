#!/usr/bin/env python3
"""Rebuild the five-project Zhejiang Tianyan identity queue from timeline events."""

from __future__ import annotations

import csv
import json
import re
import shutil
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


DATA_DIR = Path("/Users/zsh/JiaotangData/知识库/50_名单与对标/企业身份时间轴/浙江省")
EVENTS = DATA_DIR / "浙江省企业认定事件.jsonl"
QUEUE = DATA_DIR / "浙江省天眼查待核验队列.csv"
MANUAL = DATA_DIR / "天眼查企业身份待人工核验.csv"
SOURCE_MANUAL = DATA_DIR / "五类名单来源待人工核验.csv"
SOURCE_MANUAL_RESOLVED = DATA_DIR / "五类名单来源待人工核验_已解决.csv"
QUEUE_SCOPE_QUARANTINE = DATA_DIR / "浙江省天眼查待核验队列_范围待复核.csv"
QUEUE_SCOPE_RESOLVED = DATA_DIR / "浙江省天眼查待核验队列_范围复核已解决.csv"
MANUAL_RECOVERY = DATA_DIR / "天眼查企业身份待人工核验_队列修复前备份_20260730.csv"
TZ = timezone(timedelta(hours=8))
TARGET_PROJECTS = {
    "国家专精特新“小巨人”企业",
    "浙江省专精特新中小企业",
    "浙江省制造业首台（套）装备",
    "浙江省首批次新材料",
    "浙江省首版次软件产品",
}
TRUSTED_EVIDENCE = {
    "official_final_list",
    "official_final_list_mirror",
    "official_publicity",
    "official_publicity_local_attachment",
    "official_city_publicity_attachment_archive",
    "city_publicity_attachment_mirror",
    "city_publicity_mirror",
    "official_or_archived_list",
}
QUEUE_FIELDS = [
    "priority_no",
    "enterprise_name",
    "identity_key",
    "recognition_projects",
    "recognition_regions",
    "event_count",
    "latest_year",
    "status",
]
MANUAL_FIELDS = [
    "enterprise_name",
    "returned_name",
    "returned_code",
    "reason",
    "first_seen_at",
    "attempt_count",
]
SOURCE_MANUAL_FIELDS = [
    "enterprise_name",
    "reason",
    "recognition_projects",
    "source_titles",
    "first_seen_at",
]
SOURCE_MANUAL_RESOLVED_FIELDS = [
    *SOURCE_MANUAL_FIELDS,
    "resolution",
    "resolved_at",
]
QUEUE_SCOPE_QUARANTINE_FIELDS = [
    *QUEUE_FIELDS,
    "quarantine_reason",
    "quarantined_at",
]
QUEUE_SCOPE_RESOLVED_FIELDS = [
    *QUEUE_SCOPE_QUARANTINE_FIELDS,
    "resolution",
    "resolved_at",
]


def norm(value: str | None) -> str:
    return " ".join((value or "").split()).replace("（", "(").replace("）", ")")


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def iter_events() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with EVENTS.open(encoding="utf-8") as handle:
        for line in handle:
            item = json.loads(line)
            if item.get("project_name") in TARGET_PROJECTS:
                rows.append(item)
    return rows


def invalid_name_reason(name: str) -> str:
    if re.match(r"^t[\u3400-\u9fff]", name):
        return "名单抽取名称含可疑字母t前缀，禁止自动修正"
    if re.search(r"公\s+司", name):
        return "名单抽取名称存在企业类型断词，禁止自动合并"
    if re.search(r"-\d{4,}$", name):
        return "名单原文企业名称以连字符加长数字结尾，禁止自动删除或改名"
    if re.search(r"[\u3400-\u9fff]\s+[A-Za-z]\s+[\u3400-\u9fff]", name):
        return "名单原文企业名称在单个拉丁字母两侧含空格，禁止自动合并疑似主体"
    return ""


def is_traceable(item: dict[str, object]) -> bool:
    paths = item.get("source_paths") or []
    urls = item.get("source_urls") or []
    return (
        str(item.get("evidence_status") or "") in TRUSTED_EVIDENCE
        and bool(item.get("source_title"))
        and bool(paths or urls)
    )


def region_of(item: dict[str, object]) -> str:
    return "/".join(
        str(item.get(key) or "").strip()
        for key in ("recognition_province", "recognition_city", "recognition_county")
        if str(item.get(key) or "").strip()
    )


def main() -> int:
    events = iter_events()
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    manual_reasons: dict[str, str] = {}
    display_names: dict[str, str] = {}

    for item in events:
        name = str(item.get("enterprise_name_at_event") or "").strip()
        if not name:
            continue
        key = norm(name)
        reason = invalid_name_reason(name)
        if reason:
            manual_reasons.setdefault(key, reason)
            display_names.setdefault(key, name)
            continue
        if not is_traceable(item):
            manual_reasons.setdefault(key, "名单事件缺少可追溯的官方或本地原文证据")
            display_names.setdefault(key, name)
            continue
        grouped[key].append(item)
        display_names.setdefault(key, name)

    original_queue_rows = read_csv(QUEUE)
    queue_rows = [
        row
        for row in original_queue_rows
        if norm(row.get("enterprise_name")) in grouped
    ]
    removed_queue_rows = [
        row
        for row in original_queue_rows
        if norm(row.get("enterprise_name")) not in grouped
    ]
    quarantine_rows = read_csv(QUEUE_SCOPE_QUARANTINE)
    resolved_quarantine_rows = [
        row
        for row in quarantine_rows
        if norm(row.get("enterprise_name")) in grouped
    ]
    quarantine_rows = [
        row
        for row in quarantine_rows
        if norm(row.get("enterprise_name")) not in grouped
    ]
    scope_resolved_rows = read_csv(QUEUE_SCOPE_RESOLVED)
    scope_resolved_keys = {
        (
            norm(row.get("enterprise_name")),
            str(row.get("quarantine_reason") or ""),
        )
        for row in scope_resolved_rows
    }
    scope_resolved_at = datetime.now(TZ).isoformat(timespec="seconds")
    scope_resolved_added = 0
    for row in resolved_quarantine_rows:
        key = (
            norm(row.get("enterprise_name")),
            str(row.get("quarantine_reason") or ""),
        )
        if key in scope_resolved_keys:
            continue
        scope_resolved_rows.append(
            {
                **{
                    field: str(row.get(field) or "")
                    for field in QUEUE_SCOPE_QUARANTINE_FIELDS
                },
                "resolution": "来源字段门禁修复后重新满足五类可追溯队列条件",
                "resolved_at": scope_resolved_at,
            }
        )
        scope_resolved_keys.add(key)
        scope_resolved_added += 1
    quarantine_keys = {
        (
            norm(row.get("enterprise_name")),
            str(row.get("quarantine_reason") or ""),
        )
        for row in quarantine_rows
    }
    quarantined = 0
    now = datetime.now(TZ).isoformat(timespec="seconds")
    for row in removed_queue_rows:
        try:
            projects = set(json.loads(row.get("recognition_projects") or "[]"))
        except json.JSONDecodeError:
            projects = set()
        reason = (
            "当前时间轴未找到可追溯的五类名单事件，移出自动核验队列待来源复核"
            if projects & TARGET_PROJECTS
            else "不属于当前五类企业范围，移出自动核验队列"
        )
        key = (norm(row.get("enterprise_name")), reason)
        if key in quarantine_keys:
            continue
        quarantine_rows.append(
            {
                **{field: str(row.get(field) or "") for field in QUEUE_FIELDS},
                "quarantine_reason": reason,
                "quarantined_at": now,
            }
        )
        quarantine_keys.add(key)
        quarantined += 1

    queue_by_name = {norm(row.get("enterprise_name")): row for row in queue_rows}
    added = updated = 0
    for key, items in grouped.items():
        projects = sorted({str(item.get("project_name") or "") for item in items})
        regions = sorted(filter(None, {region_of(item) for item in items}))
        years = [
            int(item["event_year"])
            for item in items
            if isinstance(item.get("event_year"), int)
        ]
        identity_keys = [
            str(item.get("identity_key") or "")
            for item in items
            if str(item.get("identity_key") or "")
        ]
        values = {
            "enterprise_name": display_names[key],
            "identity_key": identity_keys[0] if identity_keys else f"name:{key}",
            "recognition_projects": json.dumps(projects, ensure_ascii=False),
            "recognition_regions": json.dumps(regions, ensure_ascii=False),
            "event_count": str(len(items)),
            "latest_year": str(max(years)) if years else "",
            "status": "pending_tyc_identity",
        }
        if key in queue_by_name:
            row = queue_by_name[key]
            if any(str(row.get(field) or "") != value for field, value in values.items()):
                row.update(values)
                updated += 1
        else:
            row = {"priority_no": str(len(queue_rows) + 1), **values}
            queue_rows.append(row)
            queue_by_name[key] = row
            added += 1

    source_manual_rows = read_csv(SOURCE_MANUAL)
    resolved_source_manual = [
        row
        for row in source_manual_rows
        if norm(row.get("enterprise_name")) in grouped
    ]
    source_manual_rows = [
        row
        for row in source_manual_rows
        if norm(row.get("enterprise_name")) not in grouped
    ]
    source_manual_resolved_rows = read_csv(SOURCE_MANUAL_RESOLVED)
    source_manual_resolved_keys = {
        (
            norm(row.get("enterprise_name")),
            str(row.get("reason") or ""),
        )
        for row in source_manual_resolved_rows
    }
    resolved_at = datetime.now(TZ).isoformat(timespec="seconds")
    source_manual_resolved_added = 0
    for row in resolved_source_manual:
        key = (norm(row.get("enterprise_name")), str(row.get("reason") or ""))
        if key in source_manual_resolved_keys:
            continue
        source_manual_resolved_rows.append(
            {
                **{field: str(row.get(field) or "") for field in SOURCE_MANUAL_FIELDS},
                "resolution": "时间轴事件已具备可追溯来源字段，恢复自动队列资格",
                "resolved_at": resolved_at,
            }
        )
        source_manual_resolved_keys.add(key)
        source_manual_resolved_added += 1
    source_manual_keys = {
        (norm(row.get("enterprise_name")), str(row.get("reason") or ""))
        for row in source_manual_rows
    }
    source_manual_added = 0
    for key, reason in manual_reasons.items():
        if key in grouped or (key, reason) in source_manual_keys:
            continue
        related = [
            item
            for item in events
            if norm(str(item.get("enterprise_name_at_event") or "")) == key
        ]
        source_manual_rows.append(
            {
                "enterprise_name": display_names[key],
                "reason": reason,
                "recognition_projects": json.dumps(
                    sorted({str(item.get("project_name") or "") for item in related}),
                    ensure_ascii=False,
                ),
                "source_titles": json.dumps(
                    sorted(
                        {
                            str(item.get("source_title") or "")
                            for item in related
                            if str(item.get("source_title") or "")
                        }
                    ),
                    ensure_ascii=False,
                ),
                "first_seen_at": datetime.now(TZ).isoformat(timespec="seconds"),
            }
        )
        source_manual_keys.add((key, reason))
        source_manual_added += 1

    manual_rows = read_csv(MANUAL)
    misplaced = [
        row
        for row in manual_rows
        if str(row.get("attempt_count") or "") == "0"
        and not str(row.get("first_seen_at") or "")
    ]
    if misplaced and not MANUAL_RECOVERY.exists():
        shutil.copy2(MANUAL, MANUAL_RECOVERY)
    if misplaced:
        manual_rows = [row for row in manual_rows if row not in misplaced]

    for priority_no, row in enumerate(queue_rows, start=1):
        row["priority_no"] = str(priority_no)
    write_csv(QUEUE, QUEUE_FIELDS, queue_rows)
    write_csv(
        QUEUE_SCOPE_QUARANTINE,
        QUEUE_SCOPE_QUARANTINE_FIELDS,
        quarantine_rows,
    )
    write_csv(
        QUEUE_SCOPE_RESOLVED,
        QUEUE_SCOPE_RESOLVED_FIELDS,
        scope_resolved_rows,
    )
    write_csv(MANUAL, MANUAL_FIELDS, manual_rows)
    write_csv(SOURCE_MANUAL, SOURCE_MANUAL_FIELDS, source_manual_rows)
    write_csv(
        SOURCE_MANUAL_RESOLVED,
        SOURCE_MANUAL_RESOLVED_FIELDS,
        source_manual_resolved_rows,
    )
    print(
        json.dumps(
            {
                "status": "completed",
                "five_project_traceable_names": len(grouped),
                "queue_rows": len(queue_rows),
                "queue_added": added,
                "queue_updated": updated,
                "queue_removed_from_scope": len(removed_queue_rows),
                "queue_quarantined": quarantined,
                "queue_scope_resolved": scope_resolved_added,
                "source_manual_added": source_manual_added,
                "source_manual_resolved": source_manual_resolved_added,
                "misplaced_identity_manual_rows_removed": len(misplaced),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
