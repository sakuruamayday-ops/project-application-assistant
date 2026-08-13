#!/usr/bin/env python3
"""Rebuild replayable twins for the three enterprise-list target families.

The source enterprise profile and the source recognition fact are deliberately
kept separate.  A business-profile row may make an enterprise comparable, but
it must not create a formal project relationship without a recognition record.
The script therefore:

1. resolves recognition rows to unified identities by names, source lineage and
   event-time corporate existence;
2. quarantines profile-only project relationships instead of fabricating an
   award or recognition event;
3. keeps product-less historical three-first clues as explicit residual gaps;
4. replaces only the target-project twins in a candidate database.

The active ``/索引/current`` database is write-protected by default.  Callers
must clone it and pass the clone with ``--database``.  Repeating
``--identity-key`` enables an incremental replay that replaces only those
subjects and verifies that every unselected target twin stays byte-stable at
the trace level.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping


PORTAL_DIR = Path(__file__).resolve().parents[1]
if str(PORTAL_DIR) not in sys.path:
    sys.path.insert(0, str(PORTAL_DIR))

from app.project_identity_twin import (  # noqa: E402
    EVENT_PRECEDENCE,
    build_project_identity_twins,
    digest,
)


PUBLIC_SOURCE = "共创研究院知识库"
TARGET_PROJECTS = (
    "国家专精特新“小巨人”企业",
    "浙江省专精特新中小企业",
    "浙江省制造业首台（套）装备",
    "浙江省首批次新材料",
    "浙江省首版次软件产品",
)
THREE_FIRST_PROJECTS = frozenset(TARGET_PROJECTS[2:])
DEFAULT_RULES = PORTAL_DIR / "references" / "enterprise-lifecycle-rules.json"
DEFAULT_MAX_SYNCED_CANDIDATE_BYTES = 500 * 1024 * 1024
USCC_PATTERN = re.compile(r"^[0-9A-HJ-NPQRTUWXY]{18}$")
EVIDENCE_RANK = {
    "official_final_list": 100,
    "official_final_list_mirror": 95,
    "official_local_fragment_match": 90,
    "official_publicity_local_attachment": 85,
    "official_publicity_fragment_match": 82,
    "official_publicity_attachment_mirror": 80,
    "official_publicity": 78,
    "official_or_archived_list": 75,
    "official_publicity_mirror": 72,
    "product_level": 70,
    "licensed_platform_gap_crosscheck": 55,
    "dynamic_candidate_pending_official_fragment": 50,
    "licensed_platform_pending": 40,
}
IDENTITY_LINEAGE_CORRECTIONS = (
    {
        "alias_name": "浙江华邦安全封条股份有限公司",
        "incorrect_identity_key": "913306815877655972",
        "correct_identity_key": "913303006807061374",
        "source": "1.建议继续支持的专精特新“小巨人”企业名单（第一批第三年）.pdf",
        "reason": (
            "同一主体在2020年认定、2023年复核与2024年继续支持事件连续，"
            "且当前主体荣誉字段包含国家级专精特新重点小巨人；"
            "浙江昂星链条股份有限公司无该荣誉或同主体名称沿革。"
        ),
    },
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="重建全国小巨人、浙江省专精特新与三首企业项目数字孪生"
    )
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--policy-version-database", type=Path)
    parser.add_argument("--lifecycle-rules", type=Path, default=DEFAULT_RULES)
    parser.add_argument(
        "--product-corrections",
        type=Path,
        help="经用户确认或附件交叉核对的三首产品补充证据 JSON",
    )
    parser.add_argument(
        "--knowledge-root",
        type=Path,
        default=Path("/Users/zsh/JiaotangData/知识库"),
        help="用于解析补充证据中的知识库相对附件路径",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--identity-key",
        action="append",
        default=[],
        help=(
            "仅重放指定统一社会信用代码，可重复传入；不提供时保持全量重建。"
            "局部模式只允许写候选数据库。"
        ),
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--allow-active-index-write",
        action="store_true",
        help="仅受控发布器可使用；常规调用禁止直接修改活动索引",
    )
    return parser.parse_args()


def normalize_identity_scope(values: Iterable[object]) -> set[str]:
    identity_keys = {str(value or "").strip().upper() for value in values}
    identity_keys.discard("")
    invalid = sorted(
        identity_key
        for identity_key in identity_keys
        if not USCC_PATTERN.fullmatch(identity_key)
    )
    if invalid:
        raise RuntimeError(
            "局部重放统一社会信用代码无效："
            + "、".join(invalid)
        )
    return identity_keys


def canonical_enterprise_name(value: object) -> str:
    return re.sub(
        r"^t(?=[\u3400-\u9fff])",
        "",
        str(value or "").strip(),
        flags=re.IGNORECASE,
    )


def normalize_name(value: object) -> str:
    cleaned = re.sub(r"[“”\"'‘’]", "", canonical_enterprise_name(value))
    return re.sub(r"[\s·•（）()\-—_，,。．]+", "", cleaned).lower()


def as_list(value: object) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return [value]
        return parsed if isinstance(parsed, list) else [parsed]
    return [value]


def table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone() is not None


def require_tables(connection: sqlite3.Connection) -> None:
    required = {
        "enterprise_identity_names",
        "enterprise_project_identity_twin_steps",
        "enterprise_project_identity_twins",
        "enterprise_unified_digital_identities",
        "recognition_records",
    }
    missing = sorted(name for name in required if not table_exists(connection, name))
    if missing:
        raise RuntimeError("数字孪生重建缺少结构表：" + ", ".join(missing))


def sha256_file(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def load_product_corrections(
    path: Path | None,
    knowledge_root: Path | None = None,
) -> list[dict[str, Any]]:
    if path is None:
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    corrections = payload.get("corrections", [])
    if not isinstance(corrections, list):
        raise RuntimeError("三首产品补充证据 corrections 必须为数组")
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()
    for raw in corrections:
        if not isinstance(raw, Mapping):
            raise RuntimeError("三首产品补充证据必须为对象")
        item = dict(raw)
        identity_key = str(item.get("identity_key") or "").strip()
        project_name = str(item.get("project_name") or "").strip()
        product_name = str(item.get("product_name") or "").strip()
        year = item.get("year")
        source_title = str(item.get("source_title") or "").strip()
        if not USCC_PATTERN.fullmatch(identity_key):
            raise RuntimeError(f"三首产品补充证据统一代码无效：{identity_key}")
        if project_name not in THREE_FIRST_PROJECTS:
            raise RuntimeError(f"三首产品补充证据项目无效：{project_name}")
        if not isinstance(year, int) or year < 2000 or year > 2100:
            raise RuntimeError(f"三首产品补充证据年份无效：{year}")
        if not product_name or not source_title:
            raise RuntimeError(f"三首产品补充证据缺产品名或来源标题：{identity_key}")
        source_path = str(item.get("source_path") or "").strip()
        source_sha256 = str(item.get("source_sha256") or "").strip()
        if source_path:
            source_file = Path(source_path)
            if not source_file.is_absolute():
                if knowledge_root is None:
                    raise RuntimeError(
                        f"三首产品补充证据使用相对附件路径但未提供知识库根目录：{source_path}"
                    )
                source_file = knowledge_root / source_file
            if not source_file.is_file():
                raise RuntimeError(f"三首产品补充证据附件不存在：{source_path}")
            actual_sha256 = sha256_file(source_file)
            if source_sha256 and actual_sha256 != source_sha256:
                raise RuntimeError(f"三首产品补充证据附件哈希不一致：{source_path}")
            item["source_sha256"] = actual_sha256
        key = (identity_key, project_name, year)
        if key in seen:
            raise RuntimeError(f"三首产品补充证据重复：{key}")
        seen.add(key)
        item.update(
            {
                "identity_key": identity_key,
                "project_name": project_name,
                "product_name": product_name,
                "year": year,
                "source_title": source_title,
                "verification_status": str(
                    item.get("verification_status")
                    or "user_confirmed_historical_single_source"
                ),
                "recognition_status": str(
                    item.get("recognition_status")
                    or "historical_single_source_closed"
                ),
            }
        )
        result.append(item)
    return result


def configured_data_root() -> Path:
    configured = os.environ.get("JIAOTANG_DATA_DIR")
    return Path(configured).expanduser() if configured else Path.home() / "JiaotangData"


def configured_index_root() -> Path:
    configured = os.environ.get("JIAOTANG_INDEX_DIR")
    return (
        Path(configured).expanduser()
        if configured
        else configured_data_root() / "索引"
    )


def configured_synced_roots() -> tuple[Path, ...]:
    configured = os.environ.get("JIAOTANG_SYNCED_ROOTS")
    if configured is None:
        return (Path.home() / "Documents", Path.home() / "Desktop")
    return tuple(
        Path(item.strip()).expanduser()
        for item in configured.split(os.pathsep)
        if item.strip()
    )


def configured_max_synced_candidate_bytes() -> int:
    configured = os.environ.get("JIAOTANG_MAX_SYNCED_CANDIDATE_BYTES")
    if configured is None:
        return DEFAULT_MAX_SYNCED_CANDIDATE_BYTES
    try:
        value = int(configured)
    except ValueError as error:
        raise RuntimeError("JIAOTANG_MAX_SYNCED_CANDIDATE_BYTES 必须为正整数") from error
    if value <= 0:
        raise RuntimeError("JIAOTANG_MAX_SYNCED_CANDIDATE_BYTES 必须为正整数")
    return value


def ensure_candidate_database(
    path: Path,
    allow_active: bool,
    *,
    active_root: Path | None = None,
    synced_roots: Iterable[Path] | None = None,
    max_synced_candidate_bytes: int | None = None,
    candidate_root: Path | None = None,
) -> None:
    resolved = path.resolve()
    protected_root = (active_root or configured_index_root() / "current").resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    if not allow_active and (
        resolved == protected_root or protected_root in resolved.parents
    ):
        raise RuntimeError("禁止直接修改活动索引；请先克隆数据库再执行")
    roots = tuple(synced_roots) if synced_roots is not None else configured_synced_roots()
    limit = (
        max_synced_candidate_bytes
        if max_synced_candidate_bytes is not None
        else configured_max_synced_candidate_bytes()
    )
    if limit <= 0:
        raise RuntimeError("同步目录候选库大小阈值必须为正整数")
    if path.stat().st_size > limit and any(
        resolved == root.resolve() or root.resolve() in resolved.parents
        for root in roots
    ):
        safe_root = candidate_root or configured_index_root() / "candidates"
        raise RuntimeError(
            "完整索引候选不得位于配置的同步目录；"
            f"请放到 {safe_root.expanduser()} 或任务专用本地临时目录"
        )


def load_rules(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rules = {
        str(item["project_name"]): dict(item)
        for item in payload.get("projects", [])
        if str(item.get("project_name") or "") in TARGET_PROJECTS
    }
    missing = sorted(set(TARGET_PROJECTS) - set(rules))
    if missing:
        raise RuntimeError("生命周期规则缺少目标项目：" + ", ".join(missing))
    return rules


def load_profiles(
    connection: sqlite3.Connection,
) -> tuple[
    dict[str, dict[str, Any]],
    set[tuple[str, str]],
    dict[str, set[str]],
    dict[tuple[str, str], list[str]],
]:
    profiles: dict[str, dict[str, Any]] = {}
    memberships: set[tuple[str, str]] = set()
    aliases: defaultdict[str, set[str]] = defaultdict(set)
    source_names: defaultdict[tuple[str, str], list[str]] = defaultdict(list)
    rows = connection.execute(
        "SELECT * FROM enterprise_unified_digital_identities"
    ).fetchall()
    for raw in rows:
        row = dict(raw)
        projects = {
            str(item)
            for item in as_list(row.get("recognition_projects_json"))
            if str(item) in TARGET_PROJECTS
        }
        if not projects:
            continue
        identity_key = str(row["identity_key"])
        profiles[identity_key] = row
        memberships.update((identity_key, project) for project in projects)
        names = {
            str(row.get("current_name") or ""),
            *(str(item) for item in as_list(row.get("former_names_json"))),
            *(str(item) for item in as_list(row.get("recognition_names_json"))),
        }
        for name in names:
            normalized = normalize_name(name)
            if normalized:
                aliases[normalized].add(identity_key)
    for raw in connection.execute(
        "SELECT identity_key,alias_name,source FROM enterprise_identity_names"
    ):
        identity_key = str(raw["identity_key"])
        normalized = normalize_name(raw["alias_name"])
        if identity_key in profiles and normalized:
            source_names[(identity_key, normalized)].append(str(raw["source"] or ""))
    return profiles, memberships, dict(aliases), dict(source_names)


def apply_loaded_lineage_corrections(
    profiles: dict[str, dict[str, Any]],
    aliases: dict[str, set[str]],
    source_names: dict[tuple[str, str], list[str]],
) -> None:
    for correction in IDENTITY_LINEAGE_CORRECTIONS:
        alias_name = str(correction["alias_name"])
        normalized = normalize_name(alias_name)
        incorrect = str(correction["incorrect_identity_key"])
        correct = str(correction["correct_identity_key"])
        if correct not in profiles:
            raise RuntimeError(f"身份沿革修正主体不在目标主档：{alias_name}")
        aliases.setdefault(normalized, set()).discard(incorrect)
        aliases[normalized].add(correct)
        source_names.pop((incorrect, normalized), None)
        source_names[(correct, normalized)] = [str(correction["source"])]
        for identity_key, action in ((incorrect, "remove"), (correct, "add")):
            if identity_key not in profiles:
                continue
            names = {
                str(item)
                for item in as_list(profiles[identity_key].get("recognition_names_json"))
                if str(item)
            }
            if action == "remove":
                names.discard(alias_name)
            else:
                names.add(alias_name)
            profiles[identity_key]["recognition_names_json"] = json.dumps(
                sorted(names), ensure_ascii=False
            )


def persist_lineage_corrections(connection: sqlite3.Connection) -> None:
    for correction in IDENTITY_LINEAGE_CORRECTIONS:
        alias_name = str(correction["alias_name"])
        normalized = normalize_name(alias_name)
        incorrect = str(correction["incorrect_identity_key"])
        correct = str(correction["correct_identity_key"])
        source = str(correction["source"])
        connection.execute(
            "DELETE FROM enterprise_identity_names "
            "WHERE identity_key=? AND normalized_alias=? AND alias_type='recognition_name'",
            (incorrect, normalized),
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO enterprise_identity_names(
                identity_key,alias_name,normalized_alias,alias_type,
                valid_from,valid_to,source
            ) VALUES(?,?,?,'recognition_name','','',?)
            """,
            (correct, alias_name, normalized, source),
        )
        for identity_key, action in ((incorrect, "remove"), (correct, "add")):
            raw = connection.execute(
                "SELECT recognition_names_json "
                "FROM enterprise_unified_digital_identities WHERE identity_key=?",
                (identity_key,),
            ).fetchone()
            names = {str(item) for item in as_list(raw[0] if raw else None) if str(item)}
            if action == "remove":
                names.discard(alias_name)
            else:
                names.add(alias_name)
            connection.execute(
                "UPDATE enterprise_unified_digital_identities "
                "SET recognition_names_json=? WHERE identity_key=?",
                (json.dumps(sorted(names), ensure_ascii=False), identity_key),
            )


def candidate_identity_keys(
    row: Mapping[str, Any],
    aliases: Mapping[str, set[str]],
    memberships: set[tuple[str, str]],
    name_fields: Iterable[str],
) -> set[str]:
    project_name = str(row.get("project_name") or "")
    candidates: set[str] = set()
    for field in name_fields:
        candidates.update(aliases.get(normalize_name(row.get(field)), set()))
    return {
        identity_key
        for identity_key in candidates
        if (identity_key, project_name) in memberships
    }


def source_aligned_candidates(
    row: Mapping[str, Any],
    candidates: set[str],
    source_names: Mapping[tuple[str, str], list[str]],
    name_fields: Iterable[str],
) -> set[str]:
    title = str(row.get("source_title") or "").strip()
    if not title:
        return set()
    aligned: set[str] = set()
    for identity_key in candidates:
        for field in name_fields:
            normalized = normalize_name(row.get(field))
            for source in source_names.get((identity_key, normalized), []):
                if source and (source == title or source in title or title in source):
                    aligned.add(identity_key)
    return aligned


def temporally_valid_candidates(
    candidates: set[str],
    profiles: Mapping[str, Mapping[str, Any]],
    event_year: object,
) -> set[str]:
    if len(candidates) <= 1 or not str(event_year or "").isdigit():
        return candidates
    year = int(str(event_year))
    valid = {
        identity_key
        for identity_key in candidates
        if not str(profiles[identity_key].get("founded_date") or "")[:4].isdigit()
        or int(str(profiles[identity_key]["founded_date"])[:4]) <= year
    }
    return valid or candidates


def resolve_record_identity(
    row: Mapping[str, Any],
    *,
    profiles: Mapping[str, Mapping[str, Any]],
    memberships: set[tuple[str, str]],
    aliases: Mapping[str, set[str]],
    source_names: Mapping[tuple[str, str], list[str]],
    name_fields: tuple[str, ...],
) -> tuple[str, str, list[str]]:
    candidates = candidate_identity_keys(row, aliases, memberships, name_fields)
    if not candidates:
        return "", "no_identity_candidate", []
    aligned = source_aligned_candidates(row, candidates, source_names, name_fields)
    if len(aligned) == 1:
        return next(iter(aligned)), "source-linked-name", sorted(candidates)
    candidates = temporally_valid_candidates(candidates, profiles, row.get("year"))
    if len(candidates) == 1:
        return next(iter(candidates)), "event-time-identity", sorted(candidates)
    if len(candidates) > 1:
        return "", "identity_conflict", sorted(candidates)
    return "", "no_identity_candidate", []


def evidence_rank(status: object) -> int:
    text = str(status or "")
    if text in EVIDENCE_RANK:
        return EVIDENCE_RANK[text]
    if text.startswith("official_final"):
        return 95
    if text.startswith("official_"):
        return 75
    if "product_level" in text:
        return 70
    if "licensed" in text:
        return 45
    return 10


def event_type_for(row: Mapping[str, Any]) -> str:
    status = str(row.get("recognition_status") or row.get("event_status") or "")
    title = str(row.get("source_title") or "")
    text = f"{status} {title}"
    if any(term in text for term in ("撤销", "取消资格", "复核不通过", "未通过复核")):
        return "revoked"
    if "建议继续支持" in text or "继续支持" in text:
        return "continued_support"
    if "复核" in text:
        if any(term in text for term in ("公示", "拟复核", "拟推荐")):
            return "review_publicity"
        if "通过" in text:
            return "review_passed"
        return "review_due"
    if status in {"publicity", "publicity_non_reward", "公示名单", "拟认定", "拟认定通过"}:
        return "recognition_publicity"
    if any(term in text for term in ("拟认定", "公示", "拟推荐", "推荐名单")):
        return "recognition_publicity"
    return "recognition"


def weak_three_first_record(row: Mapping[str, Any]) -> bool:
    return bool(
        str(row.get("project_name") or "") in THREE_FIRST_PROJECTS
        and (
            str(row.get("verification_status") or "") == "discovery_only"
            or str(row.get("recognition_status") or "") == "platform_history"
            or not str(row.get("product_name") or "").strip()
        )
    )


def event_key(event: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        str(event["identity_key"]),
        str(event["project_name"]),
        event.get("event_year"),
        str(event.get("batch") or ""),
        str(event["event_type"]),
        str(event.get("subject_key") or "enterprise"),
    )


def add_aggregated_event(
    events: dict[tuple[Any, ...], dict[str, Any]],
    event: dict[str, Any],
) -> None:
    key = event_key(event)
    current = events.get(key)
    if current is None:
        event["source_paths"] = set(event.get("source_paths", []))
        event["source_urls"] = set(event.get("source_urls", []))
        event["source_kinds"] = set(event.get("source_kinds", []))
        event["all_statuses"] = {str(event.get("status") or "")}
        events[key] = event
        return
    current["source_paths"].update(event.get("source_paths", []))
    current["source_urls"].update(event.get("source_urls", []))
    current["source_kinds"].update(event.get("source_kinds", []))
    current["all_statuses"].add(str(event.get("status") or ""))
    if evidence_rank(event.get("evidence_status")) > evidence_rank(
        current.get("evidence_status")
    ):
        for field in ("evidence_status", "source_title", "status"):
            current[field] = event.get(field)


def record_source_kinds(row: Mapping[str, Any]) -> list[str]:
    kinds = [str(row.get("source_table") or "")]
    kinds.extend(str(item) for item in as_list(row.get("source_grade")))
    return sorted({item for item in kinds if item})


def recognition_event(
    row: Mapping[str, Any], identity_key: str, match_method: str
) -> dict[str, Any]:
    project_name = str(row["project_name"])
    product_name = str(row.get("product_name") or "").strip()
    event_type = event_type_for(row)
    source_title = str(row.get("source_title") or "").strip()
    if not source_title:
        source_title = (
            f"共创研究院知识库批次主表记录｜"
            f"{int(row['year']) if row.get('year') is not None else '年度未标注'}｜"
            f"{str(row.get('batch') or '批次未标注')}｜{project_name}"
        )
    return {
        "identity_key": identity_key,
        "enterprise_name_at_event": str(
            row.get("enterprise_name_at_recognition")
            or row.get("enterprise_id")
            or ""
        ),
        "project_name": project_name,
        "event_year": int(row["year"]) if row.get("year") is not None else None,
        "cohort_year": None,
        "event_type": event_type,
        "event_scope": (
            "fiscal_support" if event_type == "continued_support" else "qualification"
        ),
        "evidence_status": str(row.get("verification_status") or ""),
        "batch": str(row.get("batch") or ""),
        "status": str(row.get("recognition_status") or ""),
        "recognition_province": str(row.get("province") or ""),
        "recognition_city": str(row.get("city") or ""),
        "recognition_county": str(row.get("county") or ""),
        "source_title": source_title,
        "source_paths": sorted(
            {
                str(item)
                for item in [
                    *as_list(row.get("source_paths")),
                    str(row.get("source_path") or ""),
                ]
                if str(item)
            }
        ),
        "source_urls": [str(row.get("source_url") or "")]
        if str(row.get("source_url") or "")
        else [],
        "source_kinds": [*record_source_kinds(row), match_method],
        "subject_type": "product" if project_name in THREE_FIRST_PROJECTS else "enterprise",
        "subject_key": normalize_name(product_name) if product_name else "enterprise",
        "subject_name": product_name or str(row.get("enterprise_name_at_recognition") or ""),
        "product_name": product_name,
        "product_category": str(row.get("product_category") or ""),
        "recognition_level": str(row.get("recognition_level") or ""),
    }


def reward_event(
    row: Mapping[str, Any], identity_key: str, match_method: str
) -> dict[str, Any]:
    product_name = str(row.get("product_name") or "").strip()
    return {
        "identity_key": identity_key,
        "enterprise_name_at_event": str(row.get("enterprise_name") or ""),
        "project_name": str(row.get("project_name") or ""),
        "event_year": int(row["year"]) if row.get("year") is not None else None,
        "cohort_year": None,
        "event_type": "award",
        "event_scope": "fiscal_support",
        "evidence_status": str(row.get("confidence") or "confirmed"),
        "batch": "",
        "status": "奖励",
        "recognition_province": "浙江省",
        "recognition_city": "",
        "recognition_county": "",
        "source_title": str(row.get("source_title") or ""),
        "source_paths": [],
        "source_urls": [str(row.get("source_url") or "")]
        if str(row.get("source_url") or "")
        else [],
        "source_kinds": [
            str(row.get("source_tier") or "three_first_reward"),
            match_method,
        ],
        "subject_type": "product",
        "subject_key": normalize_name(product_name),
        "subject_name": product_name,
        "product_name": product_name,
        "product_category": "",
        "recognition_level": "",
    }


def corrected_recognition_row(
    base_row: Mapping[str, Any],
    correction: Mapping[str, Any],
    profile: Mapping[str, Any],
) -> dict[str, Any]:
    row = dict(base_row)
    row.update(
        {
            "enterprise_id": str(profile.get("current_name") or ""),
            "enterprise_name_at_recognition": str(
                correction.get("enterprise_name_at_recognition")
                or profile.get("current_name")
                or ""
            ),
            "product_name": str(correction["product_name"]),
            "product_category": str(
                correction.get("product_category") or row.get("product_category") or ""
            ),
            "recognition_level": str(
                correction.get("recognition_level")
                or row.get("recognition_level")
                or ""
            ),
            "recognition_status": str(correction["recognition_status"]),
            "verification_status": str(correction["verification_status"]),
            "source_title": str(correction["source_title"]),
            "source_url": str(correction.get("source_url") or ""),
            "source_path": str(correction.get("source_path") or ""),
            "source_grade": str(
                correction.get("evidence_semantics")
                or "user_confirmed_product_name"
            ),
            "source_table": "user_confirmed_three_first_product_correction",
            "batch": str(correction.get("batch") or "历史单源闭合"),
        }
    )
    return row


def persist_product_corrections(
    connection: sqlite3.Connection,
    corrections: list[dict[str, Any]],
    profiles: Mapping[str, Mapping[str, Any]],
) -> None:
    for correction in corrections:
        base = dict(correction["_base_row"])
        identity_key = str(correction["identity_key"])
        profile = profiles[identity_key]
        row = corrected_recognition_row(base, correction, profile)
        record_id = digest(
            {
                "identity_key": identity_key,
                "project_name": correction["project_name"],
                "year": correction["year"],
                "product_name": correction["product_name"],
                "source_title": correction["source_title"],
                "source_sha256": correction.get("source_sha256", ""),
            }
        )
        connection.execute(
            """
            INSERT OR REPLACE INTO recognition_records(
                record_id,project_id,project_name,enterprise_id,
                enterprise_name_at_recognition,product_name,product_category,
                region,province,city,county,year,batch,recognition_status,
                recognition_level,source_document_id,source_title,source_url,
                source_grade,verification_status,source_table,source_row_id
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                record_id,
                str(row.get("project_id") or ""),
                str(correction["project_name"]),
                str(profile.get("current_name") or ""),
                str(row.get("enterprise_name_at_recognition") or ""),
                str(correction["product_name"]),
                str(row.get("product_category") or ""),
                str(row.get("region") or ""),
                str(row.get("province") or "浙江省"),
                str(correction.get("city") or row.get("city") or ""),
                str(correction.get("county") or row.get("county") or ""),
                int(correction["year"]),
                str(row.get("batch") or ""),
                str(correction["recognition_status"]),
                str(row.get("recognition_level") or ""),
                None,
                str(correction["source_title"]),
                str(correction.get("source_url") or ""),
                str(correction.get("evidence_semantics") or ""),
                str(correction["verification_status"]),
                "user_confirmed_three_first_product_correction",
                f"{identity_key}|{correction['project_name']}|{correction['year']}",
            ),
        )

        products = [
            dict(item)
            for item in as_list(profile.get("three_first_products_json"))
            if isinstance(item, Mapping)
        ]
        matched = False
        for item in products:
            if (
                str(item.get("project_name") or "")
                == str(correction["project_name"])
                and int(item.get("year") or 0) == int(correction["year"])
            ):
                item.update(
                    {
                        "product_name": str(correction["product_name"]),
                        "recognition_tier": str(
                            correction.get("recognition_level") or ""
                        ),
                        "product_category": str(
                            correction.get("product_category") or ""
                        ),
                        "list_status": str(correction["recognition_status"]),
                        "source": PUBLIC_SOURCE,
                        "verification_status": str(
                            correction["verification_status"]
                        ),
                        "source_title": str(correction["source_title"]),
                    }
                )
                matched = True
        if not matched:
            products.append(
                {
                    "project_name": str(correction["project_name"]),
                    "year": int(correction["year"]),
                    "product_name": str(correction["product_name"]),
                    "recognition_tier": str(
                        correction.get("recognition_level") or ""
                    ),
                    "product_category": str(
                        correction.get("product_category") or ""
                    ),
                    "list_status": str(correction["recognition_status"]),
                    "source": PUBLIC_SOURCE,
                    "verification_status": str(correction["verification_status"]),
                    "source_title": str(correction["source_title"]),
                }
            )
        connection.execute(
            """
            UPDATE enterprise_unified_digital_identities
            SET three_first_products_json=?,three_first_product_enriched=1
            WHERE identity_key=?
            """,
            (json.dumps(products, ensure_ascii=False), identity_key),
        )

        if table_exists(connection, "three_first_status_timeline"):
            timeline_id = digest(
                {
                    "record_id": record_id,
                    "event_type": "recognition",
                    "source": "user_confirmed_three_first_product_correction",
                }
            )
            connection.execute(
                """
                INSERT OR REPLACE INTO three_first_status_timeline(
                    timeline_id,enterprise_key,enterprise_name,project_id,
                    project_name,year,product_name,product_name_status,event_type,
                    event_stage_order,event_status,event_date,source_title,source_url,
                    source_tier,evidence_semantics,confidence,note
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    timeline_id,
                    identity_key,
                    str(profile.get("current_name") or ""),
                    str(row.get("project_id") or ""),
                    str(correction["project_name"]),
                    int(correction["year"]),
                    str(correction["product_name"]),
                    "verified_user_confirmed",
                    "recognition",
                    20,
                    str(correction["recognition_status"]),
                    str(correction.get("verified_at") or "2026-08-12"),
                    str(correction["source_title"]),
                    str(correction.get("source_url") or ""),
                    str(correction["verification_status"]),
                    str(correction.get("evidence_semantics") or ""),
                    "user_confirmed",
                    str(correction.get("note") or ""),
                ),
            )


def freeze_events(
    events: Mapping[tuple[Any, ...], Mapping[str, Any]],
) -> list[dict[str, Any]]:
    frozen: list[dict[str, Any]] = []
    for event in events.values():
        item = dict(event)
        item["source_paths"] = sorted(item.get("source_paths", []))
        item["source_urls"] = sorted(item.get("source_urls", []))
        item["source_kinds"] = sorted(item.get("source_kinds", []))
        statuses = sorted(value for value in item.pop("all_statuses", set()) if value)
        if statuses:
            item["status"] = "、".join(statuses)
        frozen.append(item)
    return sorted(
        frozen,
        key=lambda row: (
            str(row["identity_key"]),
            str(row["project_name"]),
            int(row.get("event_year") or 0),
            EVENT_PRECEDENCE.get(str(row.get("event_type") or ""), 0),
            str(row.get("subject_key") or ""),
        ),
    )


def profile_payloads(
    profiles: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for identity_key, row in profiles.items():
        names = sorted(
            {
                str(row.get("current_name") or ""),
                *(str(item) for item in as_list(row.get("former_names_json"))),
                *(str(item) for item in as_list(row.get("recognition_names_json"))),
            }
            - {""}
        )
        result.append(
            {
                "identity_key": identity_key,
                "unified_social_credit_code": str(
                    row.get("unified_social_credit_code") or ""
                ),
                "current_name": str(row.get("current_name") or ""),
                "recognition_names": names,
                "verification_status": str(
                    row.get("identity_verification_status") or ""
                ),
                "identity_source": PUBLIC_SOURCE,
                "verified_at": str(row.get("profile_updated_at") or ""),
            }
        )
    return result


def preserve_existing_coverage(
    twins: list[dict[str, Any]],
    existing: Mapping[tuple[str, str], Mapping[str, Any]],
) -> None:
    for twin in twins:
        key = (str(twin["identity_key"]), str(twin["project_name"]))
        previous = existing.get(key)
        if previous and not twin.get("coverage_trace"):
            twin["coverage_trace"] = as_list(previous.get("coverage_trace_json"))
        twin["trace_hash"] = digest(
            {
                "identity_match": twin["identity_match"],
                "policy_version": twin["policy_version"],
                "coverage": twin["coverage_trace"],
                "steps": twin["lifecycle_trace"],
            }
        )


def twin_summary(twin: Mapping[str, Any]) -> dict[str, Any]:
    steps = list(twin.get("lifecycle_trace", []))
    latest = steps[-1] if steps else {}
    return {
        "project_name": str(twin["project_name"]),
        "lifecycle_rule_id": str(twin["lifecycle_rule_id"]),
        "cycle_type": str(twin.get("cycle_type") or ""),
        "validity_years": twin.get("validity_years"),
        "event_count": len(steps),
        "latest_known_event_year": latest.get("event_year"),
        "latest_known_event_type": str(latest.get("event_type") or ""),
        "latest_known_status": str(latest.get("event_status") or ""),
        "latest_known_cohort_year": latest.get("cohort_year"),
    }


def current_gap_rows(
    connection: sqlite3.Connection,
    memberships: set[tuple[str, str]],
    profiles: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    existing = {
        (str(row[0]), str(row[1]))
        for row in connection.execute(
            "SELECT identity_key,project_name FROM enterprise_project_identity_twins"
        )
    }
    return [
        {
            "identity_key": identity_key,
            "current_name": str(profiles[identity_key].get("current_name") or ""),
            "project_name": project_name,
            "gap_type": "missing_same_project_twin",
        }
        for identity_key, project_name in sorted(memberships - existing)
    ]


def target_twin_scope_digest(
    connection: sqlite3.Connection,
    identity_keys: set[str],
    *,
    exclude: bool,
) -> tuple[int, str]:
    if not identity_keys:
        raise RuntimeError("孪生摘要至少需要一个统一社会信用代码")
    projects = ",".join("?" for _ in TARGET_PROJECTS)
    keys = ",".join("?" for _ in identity_keys)
    operator = "NOT IN" if exclude else "IN"
    rows = connection.execute(
        "SELECT identity_key,project_name,current_state,current_as_of_year,"
        "trace_hash FROM enterprise_project_identity_twins "
        f"WHERE project_name IN ({projects}) "
        f"AND identity_key {operator} ({keys}) "
        "ORDER BY identity_key,project_name",
        (*TARGET_PROJECTS, *sorted(identity_keys)),
    )
    digest_value = hashlib.sha256()
    count = 0
    for row in rows:
        digest_value.update(
            ("|".join(str(value or "") for value in row) + "\n").encode(
                "utf-8"
            )
        )
        count += 1
    return count, digest_value.hexdigest()


def quick_check_tables(
    connection: sqlite3.Connection,
    tables: Iterable[str],
) -> str:
    for table in tables:
        result = str(
            connection.execute(f"PRAGMA quick_check('{table}')").fetchone()[0]
        )
        if result != "ok":
            return f"{table}:{result}"
    return "ok"


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def replace_target_twins(
    connection: sqlite3.Connection,
    twins: list[dict[str, Any]],
    steps: list[dict[str, Any]],
) -> None:
    placeholders = ",".join("?" for _ in TARGET_PROJECTS)
    connection.execute(
        f"DELETE FROM enterprise_project_identity_twin_steps WHERE project_name IN ({placeholders})",
        TARGET_PROJECTS,
    )
    connection.execute(
        f"DELETE FROM enterprise_project_identity_twins WHERE project_name IN ({placeholders})",
        TARGET_PROJECTS,
    )
    connection.executemany(
        """
        INSERT INTO enterprise_project_identity_twins(
            twin_id,identity_key,project_name,lifecycle_rule_id,policy_version_id,
            current_state,current_as_of_year,trace_hash,identity_match_json,
            policy_version_json,list_attachment_trace_json,coverage_trace_json,
            lifecycle_trace_json,replayable_years_json
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                row["twin_id"],
                row["identity_key"],
                row["project_name"],
                row["lifecycle_rule_id"],
                row["policy_version"]["policy_version_id"],
                row["current_replay"]["state"],
                row["current_replay"]["as_of_year"],
                row["trace_hash"],
                json.dumps(row["identity_match"], ensure_ascii=False),
                json.dumps(row["policy_version"], ensure_ascii=False),
                json.dumps(row["list_attachment_trace"], ensure_ascii=False),
                json.dumps(row["coverage_trace"], ensure_ascii=False),
                json.dumps(row["lifecycle_trace"], ensure_ascii=False),
                json.dumps(row["replayable_years"], ensure_ascii=False),
            )
            for row in twins
        ],
    )
    connection.executemany(
        """
        INSERT INTO enterprise_project_identity_twin_steps(
            twin_id,identity_key,project_name,step,event_year,event_type,
            previous_state,next_state,reason,evidence_hash,payload_json
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                row["twin_id"],
                row["identity_key"],
                row["project_name"],
                row["step"],
                row["event_year"],
                row["event_type"],
                row["previous_state"],
                row["next_state"],
                row["reason"],
                row["evidence_hash"],
                json.dumps(row, ensure_ascii=False),
            )
            for row in steps
        ],
    )


def replace_selected_twins(
    connection: sqlite3.Connection,
    identity_keys: set[str],
    twins: list[dict[str, Any]],
    steps: list[dict[str, Any]],
) -> None:
    if not identity_keys:
        raise RuntimeError("局部重放至少需要一个统一社会信用代码")
    ordered_keys = sorted(identity_keys)
    key_placeholders = ",".join("?" for _ in ordered_keys)
    project_placeholders = ",".join("?" for _ in TARGET_PROJECTS)
    parameters = (*ordered_keys, *TARGET_PROJECTS)
    connection.execute(
        "DELETE FROM enterprise_project_identity_twin_steps "
        f"WHERE identity_key IN ({key_placeholders}) "
        f"AND project_name IN ({project_placeholders})",
        parameters,
    )
    connection.execute(
        "DELETE FROM enterprise_project_identity_twins "
        f"WHERE identity_key IN ({key_placeholders}) "
        f"AND project_name IN ({project_placeholders})",
        parameters,
    )
    connection.executemany(
        """
        INSERT INTO enterprise_project_identity_twins(
            twin_id,identity_key,project_name,lifecycle_rule_id,policy_version_id,
            current_state,current_as_of_year,trace_hash,identity_match_json,
            policy_version_json,list_attachment_trace_json,coverage_trace_json,
            lifecycle_trace_json,replayable_years_json
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                row["twin_id"],
                row["identity_key"],
                row["project_name"],
                row["lifecycle_rule_id"],
                row["policy_version"]["policy_version_id"],
                row["current_replay"]["state"],
                row["current_replay"]["as_of_year"],
                row["trace_hash"],
                json.dumps(row["identity_match"], ensure_ascii=False),
                json.dumps(row["policy_version"], ensure_ascii=False),
                json.dumps(row["list_attachment_trace"], ensure_ascii=False),
                json.dumps(row["coverage_trace"], ensure_ascii=False),
                json.dumps(row["lifecycle_trace"], ensure_ascii=False),
                json.dumps(row["replayable_years"], ensure_ascii=False),
            )
            for row in twins
        ],
    )
    connection.executemany(
        """
        INSERT INTO enterprise_project_identity_twin_steps(
            twin_id,identity_key,project_name,step,event_year,event_type,
            previous_state,next_state,reason,evidence_hash,payload_json
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                row["twin_id"],
                row["identity_key"],
                row["project_name"],
                row["step"],
                row["event_year"],
                row["event_type"],
                row["previous_state"],
                row["next_state"],
                row["reason"],
                row["evidence_hash"],
                json.dumps(row, ensure_ascii=False),
            )
            for row in steps
        ],
    )


def update_unified_profiles(
    connection: sqlite3.Connection,
    profiles: Mapping[str, Mapping[str, Any]],
    quarantined_pairs: set[tuple[str, str]],
    twins: Iterable[Mapping[str, Any]],
) -> None:
    summaries: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for twin in twins:
        summaries[str(twin["identity_key"])].append(twin_summary(twin))
    updates: list[tuple[str, str, str, str]] = []
    for identity_key, row in profiles.items():
        projects = [
            str(item)
            for item in as_list(row.get("recognition_projects_json"))
            if (identity_key, str(item)) not in quarantined_pairs
        ]
        lifecycles = [
            dict(item)
            for item in as_list(row.get("project_lifecycles_json"))
            if isinstance(item, Mapping)
            and str(item.get("project_name") or "") not in TARGET_PROJECTS
        ]
        lifecycles.extend(
            sorted(
                summaries.get(identity_key, []),
                key=lambda item: str(item["project_name"]),
            )
        )
        evidence_status = str(row.get("recognition_evidence_status") or "")
        if quarantined_pairs and not projects and any(
            key == identity_key for key, _ in quarantined_pairs
        ):
            evidence_status = "project_relation_quarantined"
        updates.append(
            (
                json.dumps(projects, ensure_ascii=False),
                json.dumps(lifecycles, ensure_ascii=False),
                evidence_status,
                identity_key,
            )
        )
    connection.executemany(
        """
        UPDATE enterprise_unified_digital_identities
        SET recognition_projects_json=?,project_lifecycles_json=?,
            recognition_evidence_status=?
        WHERE identity_key=?
        """,
        updates,
    )


def refresh_coverage_counts(connection: sqlite3.Connection) -> None:
    if not table_exists(connection, "enterprise_unified_identity_coverage"):
        return
    definitions = {
        "small_giant_peer_comparison": ("国家专精特新“小巨人”企业",),
        "specialized_sme_peer_comparison": ("浙江省专精特新中小企业",),
        "three_first_enterprise_enrichment": tuple(THREE_FIRST_PROJECTS),
    }
    for scope_key, projects in definitions.items():
        placeholders = ",".join("?" for _ in projects)
        total, ready = connection.execute(
            f"""
            SELECT COUNT(*),SUM(peer_comparison_ready)
            FROM enterprise_unified_digital_identities identities
            WHERE EXISTS(
                SELECT 1 FROM json_each(identities.recognition_projects_json)
                WHERE value IN ({placeholders})
            )
            """,
            projects,
        ).fetchone()
        connection.execute(
            """
            UPDATE enterprise_unified_identity_coverage
            SET total_subjects=?,ready_subjects=?,missing_profile_subjects=?
            WHERE scope_key=?
            """,
            (int(total or 0), int(ready or 0), int(total or 0) - int(ready or 0), scope_key),
        )


def write_audit_tables(
    connection: sqlite3.Connection,
    quarantine: list[dict[str, Any]],
    gaps: list[dict[str, Any]],
    product_corrections: list[dict[str, Any]],
    report: Mapping[str, Any],
) -> None:
    connection.executescript(
        """
        DROP TABLE IF EXISTS enterprise_project_relation_quarantine;
        DROP TABLE IF EXISTS enterprise_project_twin_gaps;
        DROP TABLE IF EXISTS enterprise_project_twin_rebuild_audit;
        DROP TABLE IF EXISTS enterprise_project_product_corrections;
        CREATE TABLE enterprise_project_relation_quarantine(
            identity_key TEXT NOT NULL,
            current_name TEXT NOT NULL,
            project_name TEXT NOT NULL,
            reason TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            source TEXT NOT NULL,
            PRIMARY KEY(identity_key,project_name)
        );
        CREATE TABLE enterprise_project_twin_gaps(
            identity_key TEXT NOT NULL,
            current_name TEXT NOT NULL,
            project_name TEXT NOT NULL,
            gap_type TEXT NOT NULL,
            details_json TEXT NOT NULL,
            source TEXT NOT NULL,
            PRIMARY KEY(identity_key,project_name,gap_type)
        );
        CREATE TABLE enterprise_project_twin_rebuild_audit(
            audit_key TEXT PRIMARY KEY,
            audit_value_json TEXT NOT NULL,
            source TEXT NOT NULL
        );
        CREATE TABLE enterprise_project_product_corrections(
            identity_key TEXT NOT NULL,
            current_name TEXT NOT NULL,
            project_name TEXT NOT NULL,
            recognition_year INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            verification_status TEXT NOT NULL,
            source_title TEXT NOT NULL,
            source_path TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            source TEXT NOT NULL,
            PRIMARY KEY(identity_key,project_name,recognition_year)
        );
        """
    )
    connection.executemany(
        "INSERT INTO enterprise_project_relation_quarantine VALUES(?,?,?,?,?,?)",
        [
            (
                row["identity_key"],
                row["current_name"],
                row["project_name"],
                row["reason"],
                json.dumps(row.get("details", {}), ensure_ascii=False),
                PUBLIC_SOURCE,
            )
            for row in quarantine
        ],
    )
    connection.executemany(
        "INSERT INTO enterprise_project_twin_gaps VALUES(?,?,?,?,?,?)",
        [
            (
                row["identity_key"],
                row["current_name"],
                row["project_name"],
                row["gap_type"],
                json.dumps(row.get("details", {}), ensure_ascii=False),
                PUBLIC_SOURCE,
            )
            for row in gaps
        ],
    )
    connection.execute(
        "INSERT INTO enterprise_project_twin_rebuild_audit VALUES(?,?,?)",
        ("rebuild_report", json.dumps(report, ensure_ascii=False), PUBLIC_SOURCE),
    )
    connection.executemany(
        "INSERT INTO enterprise_project_product_corrections VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                str(row["identity_key"]),
                str(row.get("current_name") or ""),
                str(row["project_name"]),
                int(row["year"]),
                str(row["product_name"]),
                str(row["verification_status"]),
                str(row["source_title"]),
                str(row.get("source_path") or ""),
                str(row.get("source_sha256") or ""),
                json.dumps(
                    {
                        key: value
                        for key, value in row.items()
                        if not str(key).startswith("_")
                    },
                    ensure_ascii=False,
                ),
                PUBLIC_SOURCE,
            )
            for row in product_corrections
        ],
    )


def write_incremental_audit_tables(
    connection: sqlite3.Connection,
    identity_keys: set[str],
    quarantine: list[dict[str, Any]],
    gaps: list[dict[str, Any]],
    product_corrections: list[dict[str, Any]],
    report: Mapping[str, Any],
    *,
    replace_product_corrections: bool,
) -> None:
    required = {
        "enterprise_project_relation_quarantine",
        "enterprise_project_twin_gaps",
        "enterprise_project_twin_rebuild_audit",
        "enterprise_project_product_corrections",
    }
    missing = sorted(
        table for table in required if not table_exists(connection, table)
    )
    if missing:
        raise RuntimeError(
            "局部重放缺少全量基线审计表：" + "、".join(missing)
        )
    ordered_keys = sorted(identity_keys)
    placeholders = ",".join("?" for _ in ordered_keys)
    tables_to_replace = [
        "enterprise_project_relation_quarantine",
        "enterprise_project_twin_gaps",
    ]
    if replace_product_corrections:
        tables_to_replace.append("enterprise_project_product_corrections")
    for table in tables_to_replace:
        connection.execute(
            f"DELETE FROM {table} WHERE identity_key IN ({placeholders})",
            ordered_keys,
        )
    connection.executemany(
        "INSERT INTO enterprise_project_relation_quarantine VALUES(?,?,?,?,?,?)",
        [
            (
                row["identity_key"],
                row["current_name"],
                row["project_name"],
                row["reason"],
                json.dumps(row.get("details", {}), ensure_ascii=False),
                PUBLIC_SOURCE,
            )
            for row in quarantine
        ],
    )
    connection.executemany(
        "INSERT INTO enterprise_project_twin_gaps VALUES(?,?,?,?,?,?)",
        [
            (
                row["identity_key"],
                row["current_name"],
                row["project_name"],
                row["gap_type"],
                json.dumps(row.get("details", {}), ensure_ascii=False),
                PUBLIC_SOURCE,
            )
            for row in gaps
        ],
    )
    if replace_product_corrections:
        connection.executemany(
            "INSERT INTO enterprise_project_product_corrections "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    str(row["identity_key"]),
                    str(row.get("current_name") or ""),
                    str(row["project_name"]),
                    int(row["year"]),
                    str(row["product_name"]),
                    str(row["verification_status"]),
                    str(row["source_title"]),
                    str(row.get("source_path") or ""),
                    str(row.get("source_sha256") or ""),
                    json.dumps(
                        {
                            key: value
                            for key, value in row.items()
                            if not str(key).startswith("_")
                        },
                        ensure_ascii=False,
                    ),
                    PUBLIC_SOURCE,
                )
                for row in product_corrections
            ],
        )
    connection.execute(
        "INSERT OR REPLACE INTO enterprise_project_twin_rebuild_audit "
        "VALUES(?,?,?)",
        (
            "last_incremental_replay",
            json.dumps(report, ensure_ascii=False),
            PUBLIC_SOURCE,
        ),
    )


def build_candidate(
    database: Path,
    policy_version_database: Path | None,
    lifecycle_rules: Path,
    product_corrections_path: Path | None,
    knowledge_root: Path | None,
    output: Path,
    *,
    dry_run: bool,
    identity_keys: set[str] | None = None,
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    incremental_identity_keys = set(identity_keys or ())
    before_sha256 = (
        "not_computed_incremental"
        if incremental_identity_keys
        else sha256_file(database)
    )
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    require_tables(connection)
    profiles, memberships, aliases, source_names = load_profiles(connection)
    apply_loaded_lineage_corrections(profiles, aliases, source_names)
    missing_identity_keys = sorted(incremental_identity_keys - set(profiles))
    if missing_identity_keys:
        raise RuntimeError(
            "局部重放主体不在目标主档：" + "、".join(missing_identity_keys)
        )
    scoped_profiles = (
        {
            identity_key: profiles[identity_key]
            for identity_key in sorted(incremental_identity_keys)
        }
        if incremental_identity_keys
        else profiles
    )
    scoped_memberships = (
        {
            (identity_key, project_name)
            for identity_key, project_name in memberships
            if identity_key in incremental_identity_keys
        }
        if incremental_identity_keys
        else memberships
    )
    loaded_product_corrections = load_product_corrections(
        product_corrections_path,
        knowledge_root,
    )
    product_corrections = [
        correction
        for correction in loaded_product_corrections
        if not incremental_identity_keys
        or str(correction["identity_key"]) in incremental_identity_keys
    ]
    correction_by_key: dict[tuple[str, str, int], dict[str, Any]] = {}
    for correction in product_corrections:
        key = (
            str(correction["identity_key"]),
            str(correction["project_name"]),
            int(correction["year"]),
        )
        if key[0] not in profiles or (key[0], key[1]) not in memberships:
            raise RuntimeError(f"三首产品补充证据未命中目标主档关系：{key}")
        correction["current_name"] = str(profiles[key[0]].get("current_name") or "")
        correction_by_key[key] = correction
    before_gaps = current_gap_rows(
        connection,
        scoped_memberships,
        scoped_profiles,
    )
    existing_twins = {
        (str(row["identity_key"]), str(row["project_name"])): dict(row)
        for row in connection.execute(
            "SELECT * FROM enterprise_project_identity_twins"
        )
    }
    unselected_snapshot_before: tuple[int, str] | None = None
    selected_snapshot_before: tuple[int, str] | None = None
    if incremental_identity_keys:
        unselected_snapshot_before = target_twin_scope_digest(
            connection,
            incremental_identity_keys,
            exclude=True,
        )
        selected_snapshot_before = target_twin_scope_digest(
            connection,
            incremental_identity_keys,
            exclude=False,
        )
    events: dict[tuple[Any, ...], dict[str, Any]] = {}
    resolved_pairs: set[tuple[str, str]] = set()
    weak_pairs: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    conflict_pairs: set[tuple[str, str]] = set()
    resolution_counts: defaultdict[str, int] = defaultdict(int)
    ignored_conflicts: list[dict[str, Any]] = []
    unmapped_source_records: list[dict[str, Any]] = []
    applied_correction_keys: set[tuple[str, str, int]] = set()

    placeholders = ",".join("?" for _ in TARGET_PROJECTS)
    record_rows = connection.execute(
        f"SELECT * FROM recognition_records WHERE project_name IN ({placeholders}) "
        "ORDER BY project_name,year,batch,enterprise_name_at_recognition,record_id",
        TARGET_PROJECTS,
    ).fetchall()
    for raw in record_rows:
        row = dict(raw)
        identity_key, method, candidates = resolve_record_identity(
            row,
            profiles=profiles,
            memberships=memberships,
            aliases=aliases,
            source_names=source_names,
            name_fields=("enterprise_id", "enterprise_name_at_recognition"),
        )
        if method == "identity_conflict":
            relevant_candidates = (
                [
                    candidate
                    for candidate in candidates
                    if candidate in incremental_identity_keys
                ]
                if incremental_identity_keys
                else candidates
            )
            if not relevant_candidates:
                continue
            ignored_conflicts.append(
                {
                    "project_name": str(row["project_name"]),
                    "enterprise_name_at_recognition": str(
                        row["enterprise_name_at_recognition"]
                    ),
                    "year": row["year"],
                    "batch": str(row["batch"] or ""),
                    "candidate_identity_keys": relevant_candidates,
                    "record_id": str(row["record_id"]),
                }
            )
            conflict_pairs.update(
                (candidate, str(row["project_name"]))
                for candidate in relevant_candidates
            )
            continue
        if not identity_key:
            if incremental_identity_keys:
                continue
            unmapped_source_records.append(
                {
                    "project_name": str(row.get("project_name") or ""),
                    "enterprise_name_at_recognition": str(
                        row.get("enterprise_name_at_recognition") or ""
                    ),
                    "year": row.get("year"),
                    "batch": str(row.get("batch") or ""),
                    "verification_status": str(
                        row.get("verification_status") or ""
                    ),
                    "recognition_status": str(
                        row.get("recognition_status") or ""
                    ),
                    "source_title": str(row.get("source_title") or ""),
                    "record_id": str(row.get("record_id") or ""),
                    "resolution": "not_in_target_identity_universe",
                }
            )
            continue
        if incremental_identity_keys and identity_key not in incremental_identity_keys:
            continue
        pair = (identity_key, str(row["project_name"]))
        correction_key = (
            identity_key,
            str(row["project_name"]),
            int(row["year"]) if row.get("year") is not None else 0,
        )
        correction = correction_by_key.get(correction_key)
        if correction and weak_three_first_record(row):
            if "_base_row" not in correction:
                correction["_base_row"] = dict(row)
            corrected_row = corrected_recognition_row(
                row,
                correction,
                profiles[identity_key],
            )
            resolved_pairs.add(pair)
            resolution_counts["user-confirmed-product-correction"] += 1
            add_aggregated_event(
                events,
                recognition_event(
                    corrected_row,
                    identity_key,
                    "user-confirmed-product-correction",
                ),
            )
            applied_correction_keys.add(correction_key)
            continue
        if weak_three_first_record(row):
            weak_pairs[pair].append(
                {
                    "year": row["year"],
                    "recognition_status": str(row["recognition_status"] or ""),
                    "verification_status": str(row["verification_status"] or ""),
                    "source_title": str(row["source_title"] or ""),
                    "source_url": str(row["source_url"] or ""),
                }
            )
            continue
        resolved_pairs.add(pair)
        resolution_counts[method] += 1
        add_aggregated_event(events, recognition_event(row, identity_key, method))

    missing_corrections = sorted(set(correction_by_key) - applied_correction_keys)
    if missing_corrections:
        raise RuntimeError(
            "三首产品补充证据未匹配到原弱证据记录："
            + json.dumps(missing_corrections, ensure_ascii=False)
        )

    if table_exists(connection, "three_first_status_timeline"):
        rewards = connection.execute(
            """
            SELECT enterprise_name,project_name,year,product_name,event_status,
                   source_title,source_url,source_tier,confidence
            FROM three_first_status_timeline
            WHERE event_type='reward' AND event_status='confirmed'
              AND product_name<>''
            ORDER BY project_name,year,enterprise_name,product_name
            """
        ).fetchall()
        for raw in rewards:
            row = dict(raw)
            identity_key, method, candidates = resolve_record_identity(
                row,
                profiles=profiles,
                memberships=memberships,
                aliases=aliases,
                source_names=source_names,
                name_fields=("enterprise_name",),
            )
            if method == "identity_conflict":
                relevant_candidates = (
                    [
                        candidate
                        for candidate in candidates
                        if candidate in incremental_identity_keys
                    ]
                    if incremental_identity_keys
                    else candidates
                )
                if not relevant_candidates:
                    continue
                ignored_conflicts.append(
                    {
                        "project_name": str(row["project_name"]),
                        "enterprise_name_at_recognition": str(row["enterprise_name"]),
                        "year": row["year"],
                        "batch": "",
                        "candidate_identity_keys": relevant_candidates,
                        "record_id": "three_first_reward",
                    }
                )
                continue
            if identity_key and (
                not incremental_identity_keys
                or identity_key in incremental_identity_keys
            ):
                add_aggregated_event(events, reward_event(row, identity_key, method))

    event_rows = freeze_events(events)
    rules = load_rules(lifecycle_rules)
    twins, steps = build_project_identity_twins(
        profile_payloads(scoped_profiles),
        event_rows,
        rules,
        {"rows": []},
        policy_version_database,
    )
    preserve_existing_coverage(twins, existing_twins)
    twin_pairs = {
        (str(row["identity_key"]), str(row["project_name"])) for row in twins
    }

    unresolved_pairs = scoped_memberships - twin_pairs
    quarantine: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    for identity_key, project_name in sorted(unresolved_pairs):
        profile = scoped_profiles[identity_key]
        base = {
            "identity_key": identity_key,
            "current_name": str(profile.get("current_name") or ""),
            "project_name": project_name,
        }
        if (identity_key, project_name) in weak_pairs:
            gaps.append(
                {
                    **base,
                    "gap_type": "three_first_product_name_missing",
                    "details": {
                        "weak_evidence": weak_pairs[(identity_key, project_name)],
                        "three_first_products": as_list(
                            profile.get("three_first_products_json")
                        ),
                    },
                }
            )
        elif (identity_key, project_name) in conflict_pairs:
            gaps.append(
                {
                    **base,
                    "gap_type": "identity_conflict",
                    "details": {
                        "registration_status": str(
                            profile.get("registration_status") or ""
                        )
                    },
                }
            )
        else:
            quarantine.append(
                {
                    **base,
                    "reason": "profile_only_project_relation_without_recognition_record",
                    "details": {
                        "recognition_names": as_list(
                            profile.get("recognition_names_json")
                        ),
                        "honors": as_list(profile.get("honors_json")),
                        "recognition_evidence_status": str(
                            profile.get("recognition_evidence_status") or ""
                        ),
                        "registration_status": str(
                            profile.get("registration_status") or ""
                        ),
                    },
                }
            )
    quarantined_pairs = {
        (str(row["identity_key"]), str(row["project_name"])) for row in quarantine
    }
    formal_memberships = scoped_memberships - quarantined_pairs
    residual_pairs = formal_memberships - twin_pairs

    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    report: dict[str, Any] = {
        "schema_version": "target-project-identity-twin-rebuild-v1",
        "generated_at": generated_at,
        "source": PUBLIC_SOURCE,
        "database": str(database),
        "database_sha256_before": before_sha256,
        "dry_run": dry_run,
        "replay_mode": (
            "incremental" if incremental_identity_keys else "full"
        ),
        "requested_identity_keys": sorted(incremental_identity_keys),
        "target_projects": list(TARGET_PROJECTS),
        "input_subjects": len(
            {identity_key for identity_key, _ in scoped_memberships}
        ),
        "input_enterprise_project_memberships": len(scoped_memberships),
        "preexisting_missing_same_project_twins": len(before_gaps),
        "resolved_source_rows": sum(resolution_counts.values()),
        "resolution_counts": dict(sorted(resolution_counts.items())),
        "aggregated_events": len(event_rows),
        "rebuilt_target_twins": len(twins),
        "rebuilt_target_twin_subjects": len(
            {str(row["identity_key"]) for row in twins}
        ),
        "rebuilt_target_twin_steps": len(steps),
        "quarantined_project_relations": len(quarantine),
        "formal_memberships_after_quarantine": len(formal_memberships),
        "residual_project_twin_gaps": len(residual_pairs),
        "residual_gap_subjects": len({identity_key for identity_key, _ in residual_pairs}),
        "ignored_ambiguous_source_rows": len(ignored_conflicts),
        "unmapped_source_rows": len(unmapped_source_records),
        "applied_identity_lineage_corrections": sum(
            1
            for correction in IDENTITY_LINEAGE_CORRECTIONS
            if not incremental_identity_keys
            or {
                str(correction["incorrect_identity_key"]),
                str(correction["correct_identity_key"]),
            }
            & incremental_identity_keys
        ),
        "applied_product_corrections": len(applied_correction_keys),
        "coverage_complete": len(residual_pairs) == 0,
        "truncated": False,
        "production_index_switched": False,
    }
    if selected_snapshot_before and unselected_snapshot_before:
        report.update(
            {
                "selected_target_twins_before": selected_snapshot_before[0],
                "selected_target_digest_before": selected_snapshot_before[1],
                "unselected_target_twins_before": unselected_snapshot_before[0],
                "unselected_target_digest_before": unselected_snapshot_before[1],
            }
        )

    if not dry_run:
        connection.execute("BEGIN IMMEDIATE")
        if incremental_identity_keys:
            replace_selected_twins(
                connection,
                incremental_identity_keys,
                twins,
                steps,
            )
        else:
            replace_target_twins(connection, twins, steps)
        update_unified_profiles(
            connection,
            scoped_profiles,
            quarantined_pairs,
            twins,
        )
        lineage_keys = {
            str(correction[key])
            for correction in IDENTITY_LINEAGE_CORRECTIONS
            for key in ("incorrect_identity_key", "correct_identity_key")
        }
        if not incremental_identity_keys or lineage_keys & incremental_identity_keys:
            persist_lineage_corrections(connection)
        persist_product_corrections(
            connection,
            product_corrections,
            scoped_profiles,
        )
        refresh_coverage_counts(connection)
        if incremental_identity_keys:
            unselected_snapshot_after = target_twin_scope_digest(
                connection,
                incremental_identity_keys,
                exclude=True,
            )
            selected_snapshot_after = target_twin_scope_digest(
                connection,
                incremental_identity_keys,
                exclude=False,
            )
            if unselected_snapshot_after != unselected_snapshot_before:
                connection.rollback()
                raise RuntimeError(
                    "局部重放越界修改了未选中主体，已回滚候选数据库"
                )
            report.update(
                {
                    "selected_target_twins_after": selected_snapshot_after[0],
                    "selected_target_digest_after": selected_snapshot_after[1],
                    "unselected_target_twins_after": unselected_snapshot_after[0],
                    "unselected_target_digest_after": unselected_snapshot_after[1],
                    "unselected_target_invariant": "pass",
                }
            )
        connection.commit()
        if incremental_identity_keys:
            quick_check = quick_check_tables(
                connection,
                tuple(
                    table
                    for table in (
                        "enterprise_project_identity_twins",
                        "enterprise_project_identity_twin_steps",
                        "enterprise_unified_digital_identities",
                        "recognition_records",
                        "three_first_status_timeline",
                    )
                    if table_exists(connection, table)
                ),
            )
            report["sqlite_quick_check_scope"] = "modified_tables"
        else:
            quick_check = str(
                connection.execute("PRAGMA quick_check").fetchone()[0]
            )
            report["sqlite_quick_check_scope"] = "full_database"
        if quick_check != "ok":
            raise RuntimeError(f"SQLite快速检查失败：{quick_check}")
        report["sqlite_quick_check"] = quick_check
        connection.execute("BEGIN IMMEDIATE")
        if incremental_identity_keys:
            write_incremental_audit_tables(
                connection,
                incremental_identity_keys,
                quarantine,
                gaps,
                product_corrections,
                report,
                replace_product_corrections=(
                    product_corrections_path is not None
                ),
            )
        else:
            write_audit_tables(
                connection,
                quarantine,
                gaps,
                product_corrections,
                report,
            )
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    else:
        connection.rollback()
        report["sqlite_quick_check"] = "not_run_dry_run"
    connection.close()
    if incremental_identity_keys:
        report["database_sha256_after"] = "not_computed_incremental"
    elif dry_run:
        report["database_sha256_after"] = before_sha256
    else:
        report["database_sha256_after"] = sha256_file(database)

    (output / "企业项目数字孪生重建报告.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_csv(
        output / "企业项目数字孪生缺口台账_重建前.csv",
        before_gaps,
        ["identity_key", "current_name", "project_name", "gap_type"],
    )
    write_csv(
        output / "企业项目关系隔离清单.csv",
        [
            {
                **row,
                "details_json": json.dumps(row.get("details", {}), ensure_ascii=False),
            }
            for row in quarantine
        ],
        [
            "identity_key",
            "current_name",
            "project_name",
            "reason",
            "details_json",
        ],
    )
    write_csv(
        output / "企业项目数字孪生剩余缺口.csv",
        [
            {
                **row,
                "details_json": json.dumps(row.get("details", {}), ensure_ascii=False),
            }
            for row in gaps
        ],
        [
            "identity_key",
            "current_name",
            "project_name",
            "gap_type",
            "details_json",
        ],
    )
    write_csv(
        output / "企业项目数字孪生歧义来源行.csv",
        [
            {
                **row,
                "candidate_identity_keys": "、".join(row["candidate_identity_keys"]),
            }
            for row in ignored_conflicts
        ],
        [
            "project_name",
            "enterprise_name_at_recognition",
            "year",
            "batch",
            "candidate_identity_keys",
            "record_id",
        ],
    )
    write_csv(
        output / "企业项目数字孪生未映射来源行.csv",
        unmapped_source_records,
        [
            "project_name",
            "enterprise_name_at_recognition",
            "year",
            "batch",
            "verification_status",
            "recognition_status",
            "source_title",
            "record_id",
            "resolution",
        ],
    )
    write_csv(
        output / "三首产品补充证据.csv",
        [
            {
                key: value
                for key, value in row.items()
                if not str(key).startswith("_")
            }
            for row in product_corrections
        ],
        [
            "identity_key",
            "current_name",
            "project_name",
            "year",
            "product_name",
            "product_category",
            "recognition_level",
            "recognition_status",
            "verification_status",
            "source_title",
            "source_path",
            "source_sha256",
            "evidence_semantics",
            "note",
        ],
    )
    return report


def main() -> None:
    args = parse_args()
    ensure_candidate_database(args.database, args.allow_active_index_write)
    identity_keys = normalize_identity_scope(args.identity_key)
    report = build_candidate(
        args.database,
        args.policy_version_database,
        args.lifecycle_rules,
        args.product_corrections,
        args.knowledge_root,
        args.output,
        dry_run=args.dry_run,
        identity_keys=identity_keys,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
