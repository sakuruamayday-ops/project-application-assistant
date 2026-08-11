#!/usr/bin/env python3
"""Build the disclosure-safe unified enterprise digital identity projection.

Identity resolution, business-profile evidence and recognition evidence remain
separate.  A commercial profile candidate can enrich peer-comparison fields,
but it never upgrades an enterprise's official-list or registry status.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_DB = Path("/Users/zsh/JiaotangData/索引/current/knowledge_content.sqlite3")
DEFAULT_IDENTITIES = Path(
    "/Users/zsh/JiaotangData/知识库/50_名单与对标/企业身份时间轴/浙江省/三类名单基础数字身份证"
)
DEFAULT_BUSINESS_PROFILE_CANDIDATES = Path(
    "/Users/zsh/JiaotangData/知识库/50_名单与对标/企业身份时间轴/浙江省/企业画像补采归并/"
    "企业统一数字身份证_画像补采归并_903家_20260810.jsonl"
)
DEFAULT_THEME_ENRICHMENT_CANDIDATES = Path(
    "/Users/zsh/JiaotangData/知识库/50_名单与对标/企业身份时间轴/浙江省/主题补全/"
    "企业主题补全队列_20260811.jsonl"
)
DEFAULT_BATCH_PROFILE_PROVENANCE = Path(
    "/Users/zsh/JiaotangData/知识库/50_名单与对标/企业身份时间轴/企业画像批量回传血缘/"
    "企业画像批量回传主体血缘_current.jsonl"
)
DEFAULT_BATCH_PROFILE_REVIEW = Path(
    "/Users/zsh/JiaotangData/知识库/50_名单与对标/企业身份时间轴/企业画像批量回传血缘/"
    "企业画像批量回传人工裁决_current.jsonl"
)
DEFAULT_IDENTITY_CLOSURE_PATCHES = Path(
    "/Users/zsh/JiaotangData/知识库/50_名单与对标/企业身份时间轴/企业身份闭环增量/"
    "三类数字身份证非110闭环增量候选_20260811.jsonl"
)
DEFAULT_QIZHIDAO_QUEUE_REUSE_CANDIDATES = Path(
    "/Users/zsh/JiaotangData/知识库/50_名单与对标/企业身份时间轴/企业身份闭环增量/"
    "企知道110家队列归并增量候选_20260811.jsonl"
)
DEFAULT_OUTPUT = Path(
    "/Users/zsh/JiaotangData/知识库/50_名单与对标/企业身份时间轴/统一企业数字身份证.jsonl"
)
PUBLIC_SOURCE = "共创研究院知识库"
USCC_PATTERN = re.compile(r"^[0-9A-HJ-NPQRTUWXY]{18}$")
PEER_PROJECTS = frozenset(
    {
        "浙江省专精特新中小企业",
        "专精特新中小企业",
        "国家专精特新“小巨人”企业",
    }
)
SPECIALIZED_PROJECTS = frozenset(
    {"浙江省专精特新中小企业", "专精特新中小企业"}
)
SMALL_GIANT_PROJECT = "国家专精特新“小巨人”企业"
IDENTITY_VERIFICATION_EXEMPT_PROJECTS = frozenset(
    {
        "浙江制造精品",
        "地方科技小巨人企业",
    }
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="构建企业统一数字身份证与同行对比画像")
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--knowledge-identities", type=Path, default=DEFAULT_IDENTITIES)
    parser.add_argument(
        "--business-profile-candidates",
        type=Path,
        default=DEFAULT_BUSINESS_PROFILE_CANDIDATES,
    )
    parser.add_argument(
        "--theme-enrichment-candidates",
        type=Path,
        default=DEFAULT_THEME_ENRICHMENT_CANDIDATES,
    )
    parser.add_argument(
        "--batch-profile-provenance",
        type=Path,
        default=DEFAULT_BATCH_PROFILE_PROVENANCE,
    )
    parser.add_argument(
        "--batch-profile-review",
        type=Path,
        default=DEFAULT_BATCH_PROFILE_REVIEW,
    )
    parser.add_argument(
        "--identity-closure-patches",
        type=Path,
        default=DEFAULT_IDENTITY_CLOSURE_PATCHES,
    )
    parser.add_argument(
        "--qizhidao-queue-reuse-candidates",
        type=Path,
        default=DEFAULT_QIZHIDAO_QUEUE_REUSE_CANDIDATES,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def normalize_name(value: object) -> str:
    return re.sub(
        r"[\s·•・,，。;；:：()（）【】\[\]\\\"“”'‘’\-—_]",
        "",
        str(value or ""),
    ).lower()


def normalize_term(value: object) -> str:
    return normalize_name(value)


def sanitize_public_text(value: object) -> str:
    text = str(value or "")
    text = re.sub(r"企知道|企查查|天眼查|焦糖知识库|焦糖", PUBLIC_SOURCE, text)
    return re.sub(r"jiaotang", "共创研究院", text, flags=re.IGNORECASE)


def canonical_project_name(value: object) -> str:
    text = sanitize_public_text(value).strip()
    normalized = normalize_name(text)
    if normalized in {
        normalize_name("国家专精特新小巨人"),
        normalize_name("国家专精特新“小巨人”企业"),
    }:
        return "国家专精特新“小巨人”企业"
    return text


def as_list(value: object) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        parsed = None
    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]
    return [
        item.strip()
        for item in re.split(r"[;；、]", str(value))
        if item.strip()
    ]


def as_dict(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    try:
        parsed = json.loads(str(value or ""))
    except (TypeError, json.JSONDecodeError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def merge_unique(*values: object) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        for item in as_list(value):
            item = sanitize_public_text(item).strip()
            normalized = normalize_name(item)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(item)
    return result


def merge_projects(*values: object) -> list[str]:
    return merge_unique(
        [canonical_project_name(item) for value in values for item in as_list(value)]
    )


def first_text(*values: object) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return sanitize_public_text(text)
    return ""


def read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise RuntimeError(f"{path}:{line_number} 不是JSON对象")
            rows.append(row)
    return rows


def resolve_snapshot(path: Path) -> Path | None:
    if path.is_file():
        return path
    candidates = sorted(path.glob("浙江省三类名单企业基础数字身份证_*.jsonl"))
    return candidates[-1] if candidates else None


def table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return bool(
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
    )


def empty_profile(identity_key: str, current_name: str = "") -> dict[str, Any]:
    return {
        "identity_key": identity_key,
        "unified_social_credit_code": "",
        "current_name": current_name,
        "former_names": [],
        "recognition_names": [],
        "province": "",
        "city": "",
        "county": "",
        "registration_status": "",
        "founded_date": "",
        "registered_capital": "",
        "company_type": "",
        "industry_level_1": "",
        "industry_level_2": "",
        "industry_level_3": "",
        "company_introduction": "",
        "business_scope": "",
        "main_product_tags": [],
        "industry_track_tags": [],
        "ip_statistics": {},
        "honors": [],
        "recognition_projects": [],
        "project_lifecycles": [],
        "three_first_products": [],
        "identity_verification_status": "pending_business_identity",
        "business_profile_evidence_status": "not_collected",
        "recognition_evidence_status": "not_linked",
        "profile_updated_at": "",
    }


def profile_key(row: dict[str, Any]) -> str:
    code = str(row.get("unified_social_credit_code") or "").strip().upper()
    if USCC_PATTERN.fullmatch(code):
        return code
    supplied = str(row.get("identity_key") or row.get("master_identity_key") or "").strip()
    if supplied:
        return supplied
    return "name:" + normalize_name(row.get("current_name"))


def has_business_profile_data(row: dict[str, Any]) -> bool:
    return bool(
        str(row.get("company_introduction") or "").strip()
        or str(row.get("business_scope") or "").strip()
        or as_list(row.get("main_product_tags"))
        or as_list(row.get("industry_track_tags"))
        or str(row.get("industry_level_3") or "").strip()
    )


def qcc_requirement(profile: dict[str, Any]) -> tuple[int, list[str]]:
    """Project whether this profile genuinely needs QCC follow-up.

    Evidence-grade statuses deliberately remain independent from this
    operational flag.  In particular, an audited single-source profile is not
    a gap when its identity is closed and peer-comparison fields are ready.
    """

    reasons: list[str] = []
    projects = set(as_list(profile.get("recognition_projects")))
    actionable_projects = projects - IDENTITY_VERIFICATION_EXEMPT_PROJECTS
    if (
        str(profile.get("identity_verification_status") or "")
        == "pending_business_identity"
        and bool(actionable_projects)
    ):
        reasons.append("identity_resolution_pending")
    if (
        bool(projects & PEER_PROJECTS)
        and not bool(profile.get("peer_comparison_ready"))
    ):
        reasons.append("peer_profile_incomplete")
    return int(bool(reasons)), reasons


def overlay_profile(
    target: dict[str, Any],
    source: dict[str, Any],
    *,
    business_status: str | None = None,
) -> None:
    code = str(source.get("unified_social_credit_code") or "").strip().upper()
    if USCC_PATTERN.fullmatch(code):
        target["unified_social_credit_code"] = code
    target["current_name"] = first_text(source.get("current_name"), target["current_name"])
    target["former_names"] = merge_unique(target["former_names"], source.get("former_names"))
    target["recognition_names"] = merge_unique(
        target["recognition_names"], source.get("recognition_names")
    )
    for target_key, source_keys in {
        "province": ("current_province", "province"),
        "city": ("current_city", "city"),
        "county": ("current_county", "county"),
        "registration_status": ("registration_status",),
        "founded_date": ("founded_date",),
        "registered_capital": ("registered_capital",),
        "company_type": ("company_type",),
        "industry_level_1": ("industry_level_1",),
        "industry_level_2": ("industry_level_2",),
        "industry_level_3": ("industry_level_3",),
        "company_introduction": ("company_introduction",),
        "business_scope": ("business_scope",),
    }.items():
        target[target_key] = first_text(
            *(source.get(key) for key in source_keys), target[target_key]
        )
    target["main_product_tags"] = merge_unique(
        target["main_product_tags"], source.get("main_product_tags")
    )
    target["industry_track_tags"] = merge_unique(
        target["industry_track_tags"], source.get("industry_track_tags")
    )
    target["honors"] = merge_unique(target["honors"], source.get("honors"))
    target["recognition_projects"] = merge_projects(
        target["recognition_projects"],
        source.get("recognition_projects"),
        source.get("category_groups"),
    )
    if source.get("project_lifecycles"):
        target["project_lifecycles"] = source.get("project_lifecycles")
    if source.get("ip_statistics"):
        target["ip_statistics"] = as_dict(source.get("ip_statistics"))
    target["profile_updated_at"] = first_text(
        source.get("generated_at"), source.get("captured_at"), target["profile_updated_at"]
    )
    if business_status:
        target["business_profile_evidence_status"] = business_status


def merge_three_first_products(*values: object) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, list):
            continue
        for raw in value:
            if not isinstance(raw, dict):
                continue
            item = {
                "project_name": canonical_project_name(raw.get("project_name")),
                "year": raw.get("year"),
                "product_name": sanitize_public_text(raw.get("product_name")).strip(),
                "recognition_tier": sanitize_public_text(
                    raw.get("recognition_tier")
                ).strip(),
                "product_category": sanitize_public_text(
                    raw.get("product_category")
                ).strip(),
                "list_status": sanitize_public_text(raw.get("list_status")).strip(),
                "source": PUBLIC_SOURCE,
            }
            fingerprint = json.dumps(item, ensure_ascii=False, sort_keys=True)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            result.append(item)
    return result


def overlay_business_profile_candidates(
    profiles: dict[str, dict[str, Any]],
    path: Path,
    stats: defaultdict[str, int],
) -> None:
    """Promote an audited candidate delta without weakening identity boundaries."""

    if not path.is_file():
        stats["business_profile_candidate_source_missing"] += 1
        return
    seen_codes: set[str] = set()
    for row in read_jsonl(path):
        code = str(row.get("unified_social_credit_code") or "").strip().upper()
        if not USCC_PATTERN.fullmatch(code):
            raise RuntimeError(f"企业画像补采候选缺少有效统一社会信用代码：{code!r}")
        if code in seen_codes:
            raise RuntimeError(f"企业画像补采候选存在重复统一社会信用代码：{code}")
        seen_codes.add(code)
        if str(row.get("source") or "").strip() != PUBLIC_SOURCE:
            raise RuntimeError(f"企业画像补采候选来源未统一投影为{PUBLIC_SOURCE}：{code}")
        candidate_status = str(
            row.get("business_profile_evidence_status") or ""
        ).strip()
        if candidate_status not in {
            "candidate_profile_complete",
            "candidate_profile_partial",
        }:
            raise RuntimeError(f"企业画像补采候选状态不受支持：{code}/{candidate_status}")
        peer_ready = int(row.get("peer_comparison_ready") or 0)
        if peer_ready not in {0, 1}:
            raise RuntimeError(f"企业画像补采候选同行状态不合法：{code}")
        if candidate_status == "candidate_profile_partial" and peer_ready:
            raise RuntimeError(f"部分画像不得标记为同行对比就绪：{code}")

        candidate_key = profile_key(row)
        existing_keys = {
            key
            for key, profile in profiles.items()
            if str(profile.get("unified_social_credit_code") or "").upper() == code
        }
        existing_keys.update(
            str(key)
            for key in as_list(row.get("merged_source_identity_keys"))
            if str(key) in profiles
        )
        if len(
            {
                str(profiles[key].get("unified_social_credit_code") or "").upper()
                for key in existing_keys
                if str(profiles[key].get("unified_social_credit_code") or "").strip()
            }
            - {code}
        ):
            raise RuntimeError(f"企业画像补采候选命中不同信用代码主体：{code}")

        target = profiles.get(candidate_key) or empty_profile(
            candidate_key, str(row.get("current_name") or "")
        )
        for key in sorted(existing_keys):
            existing = profiles[key]
            overlay_profile(target, existing)
            target["recognition_evidence_status"] = first_text(
                existing.get("recognition_evidence_status"),
                target["recognition_evidence_status"],
            )
            target["three_first_products"] = merge_three_first_products(
                target["three_first_products"], existing.get("three_first_products")
            )
        overlay_profile(
            target,
            row,
            business_status=(
                "knowledge_profile_complete"
                if candidate_status == "candidate_profile_complete"
                else "knowledge_profile_partial"
            ),
        )
        target["identity_key"] = candidate_key
        target["identity_verification_status"] = (
            "knowledge_alias_closed"
            if str(row.get("identity_verification_status") or "")
            == "candidate_alias_closed"
            else "knowledge_verified"
        )
        target["recognition_evidence_status"] = first_text(
            row.get("recognition_evidence_status"),
            target["recognition_evidence_status"],
        )
        target["three_first_products"] = merge_three_first_products(
            target["three_first_products"], row.get("three_first_products")
        )
        target["_peer_comparison_ready_override"] = peer_ready
        for key in existing_keys:
            if key != candidate_key:
                profiles.pop(key, None)
        profiles[candidate_key] = target
        stats[
            "promoted_complete_business_profiles"
            if peer_ready
            else "promoted_partial_business_profiles"
        ] += 1
    stats["promoted_business_profile_candidates"] += len(seen_codes)


def overlay_theme_enrichment_candidates(
    profiles: dict[str, dict[str, Any]],
    path: Path,
    stats: defaultdict[str, int],
) -> None:
    """Apply only deterministic exact-name topics from the licensed-source queue."""

    if not path.is_file():
        stats["theme_enrichment_candidate_source_missing"] += 1
        return
    for row in read_jsonl(path):
        if str(row.get("source") or "").strip() != PUBLIC_SOURCE:
            raise RuntimeError("企业主题补全候选未统一投影为共创研究院知识库")
        if str(row.get("match_status") or "") != "exact_enterprise_name":
            continue
        key = str(row.get("identity_key") or "")
        target = profiles.get(key)
        if target is None:
            stats["theme_enrichment_target_missing"] += 1
            continue
        if normalize_name(target.get("current_name")) != normalize_name(row.get("current_name")):
            raise RuntimeError(f"企业主题补全候选主体名称冲突：{key}")
        products = as_list(row.get("candidate_main_product_tags"))
        industries = as_list(row.get("candidate_industry_track_tags"))
        if not products and not industries:
            stats["theme_enrichment_exact_without_topics"] += 1
            continue
        target["main_product_tags"] = merge_unique(
            target["main_product_tags"], products
        )
        target["industry_track_tags"] = merge_unique(
            target["industry_track_tags"], industries
        )
        stats["theme_enrichment_profiles"] += 1


def profile_names(profile: dict[str, Any]) -> list[str]:
    return merge_unique(
        [profile.get("current_name")],
        profile.get("former_names"),
        profile.get("recognition_names"),
    )


def overlay_batch_profile_provenance(
    profiles: dict[str, dict[str, Any]],
    path: Path,
    stats: defaultdict[str, int],
) -> None:
    """Merge accepted licensed batch profiles without creating recognition facts."""

    if not path.is_file():
        stats["batch_profile_provenance_source_missing"] += 1
        return
    name_index: defaultdict[str, set[str]] = defaultdict(set)
    for key, profile in profiles.items():
        for name in profile_names(profile):
            normalized = normalize_name(name)
            if normalized:
                name_index[normalized].add(key)

    seen_codes: set[str] = set()
    for row in read_jsonl(path):
        code = str(row.get("unified_social_credit_code") or "").strip().upper()
        if not USCC_PATTERN.fullmatch(code):
            raise RuntimeError(f"批量画像血缘包含无效统一社会信用代码：{code!r}")
        if code in seen_codes:
            raise RuntimeError(f"批量画像血缘包含重复统一社会信用代码：{code}")
        seen_codes.add(code)
        if str(row.get("source") or "").strip() != PUBLIC_SOURCE:
            raise RuntimeError(f"批量画像血缘来源未统一投影为{PUBLIC_SOURCE}：{code}")
        candidate_status = str(row.get("identity_candidate_status") or "")
        if candidate_status not in {
            "accepted_exact_current_name",
            "accepted_reviewed_alias",
            "excluded_unrelated_return",
            "manual_review_name_mismatch",
        }:
            raise RuntimeError(f"批量画像血缘候选状态不受支持：{code}/{candidate_status}")
        if not candidate_status.startswith("accepted_"):
            stats["batch_profile_manual_or_excluded_subjects"] += 1
            continue

        incoming_names = merge_unique(
            row.get("imported_names"), row.get("observed_current_names")
        )
        existing_keys: set[str] = set()
        if code in profiles:
            existing_keys.add(code)
        for name in incoming_names:
            for matched_key in name_index.get(normalize_name(name), set()):
                matched_code = str(
                    profiles[matched_key].get("unified_social_credit_code") or ""
                ).strip().upper()
                if USCC_PATTERN.fullmatch(matched_code) and matched_code != code:
                    stats["batch_profile_name_collisions_with_other_codes"] += 1
                    continue
                existing_keys.add(matched_key)
        for matched_key in as_list(row.get("matched_master_identity_keys")):
            if matched_key not in profiles:
                continue
            matched_code = str(
                profiles[matched_key].get("unified_social_credit_code") or ""
            ).strip().upper()
            if USCC_PATTERN.fullmatch(matched_code) and matched_code != code:
                stats["batch_profile_name_collisions_with_other_codes"] += 1
                continue
            existing_keys.add(matched_key)

        target = profiles.get(code) or empty_profile(
            code, str(row.get("current_name") or "")
        )
        strongest_identity_status = str(target.get("identity_verification_status") or "")
        strongest_business_status = str(target.get("business_profile_evidence_status") or "")
        strongest_recognition_status = str(target.get("recognition_evidence_status") or "")
        canonical_name = str(target.get("current_name") or row.get("current_name") or "")
        merged_alias_keys = 0
        for key in sorted(existing_keys):
            existing = profiles[key]
            source = dict(existing)
            existing_name = str(source.get("current_name") or "")
            source["current_name"] = ""
            overlay_profile(target, source)
            target["recognition_names"] = merge_unique(
                target["recognition_names"], [existing_name]
            )
            if str(existing.get("identity_verification_status") or "") not in {
                "", "pending_business_identity", "licensed_batch_identity_candidate",
            }:
                strongest_identity_status = str(existing["identity_verification_status"])
            if str(existing.get("business_profile_evidence_status") or "") not in {
                "", "not_collected", "knowledge_identity_only",
                "licensed_batch_profile_candidate", "licensed_batch_profile_complete",
                "licensed_batch_profile_partial",
            }:
                strongest_business_status = str(existing["business_profile_evidence_status"])
            if str(existing.get("recognition_evidence_status") or "") not in {
                "", "not_linked",
            }:
                strongest_recognition_status = str(existing["recognition_evidence_status"])
            if key != code:
                merged_alias_keys += 1

        incoming = dict(row)
        incoming["current_name"] = canonical_name or str(row.get("current_name") or "")
        incoming["former_names"] = merge_unique(
            row.get("former_names"),
            [
                name
                for name in as_list(row.get("imported_names"))
                if normalize_name(name) != normalize_name(row.get("current_name"))
            ],
        )
        overlay_profile(
            target,
            incoming,
            business_status=(
                strongest_business_status
                if strongest_business_status
                not in {"", "not_collected", "knowledge_identity_only"}
                else (
                    "licensed_batch_profile_complete"
                    if has_business_profile_data(row)
                    else "licensed_batch_profile_partial"
                )
            ),
        )
        target["identity_key"] = code
        target["unified_social_credit_code"] = code
        target["identity_verification_status"] = (
            strongest_identity_status
            if strongest_identity_status
            not in {"", "pending_business_identity"}
            else "licensed_batch_identity_candidate"
        )
        target["recognition_evidence_status"] = first_text(
            strongest_recognition_status,
            target.get("recognition_evidence_status"),
            "not_linked",
        )
        for key in existing_keys:
            if key != code:
                profiles.pop(key, None)
                for normalized_keys in name_index.values():
                    normalized_keys.discard(key)
        profiles[code] = target
        for name in profile_names(target):
            normalized = normalize_name(name)
            if normalized:
                name_index[normalized].add(code)
        stats["batch_profile_accepted_subjects"] += 1
        stats["batch_profile_alias_rows_merged"] += merged_alias_keys
        if not existing_keys:
            stats["batch_profile_new_subjects"] += 1
    stats["batch_profile_provenance_subjects"] += len(seen_codes)


def exclude_reviewed_non_enterprise_profiles(
    profiles: dict[str, dict[str, Any]],
    path: Path,
    stats: defaultdict[str, int],
) -> None:
    """Remove reviewed extraction noise from the enterprise master only."""

    if not path.is_file():
        stats["batch_profile_review_source_missing"] += 1
        return
    excluded_names = {
        normalize_name(row.get("master_name") or row.get("imported_name"))
        for row in read_jsonl(path)
        if bool(row.get("exclude_from_unified_master"))
    }
    excluded_names.discard("")
    for key, profile in list(profiles.items()):
        code = str(profile.get("unified_social_credit_code") or "").strip().upper()
        if USCC_PATTERN.fullmatch(code):
            continue
        matched = {
            normalize_name(name) for name in profile_names(profile)
        } & excluded_names
        if not matched:
            continue
        profiles.pop(key)
        stats["reviewed_non_enterprise_master_rows_excluded"] += 1


def collapse_unambiguous_name_only_profiles(
    profiles: dict[str, dict[str, Any]],
    stats: defaultdict[str, int],
) -> None:
    """Collapse a code-less alias only when exactly one coded subject owns it."""

    coded_name_index: defaultdict[str, set[str]] = defaultdict(set)
    for key, profile in profiles.items():
        code = str(profile.get("unified_social_credit_code") or "").strip().upper()
        if not USCC_PATTERN.fullmatch(code):
            continue
        for name in profile_names(profile):
            normalized = normalize_name(name)
            if normalized:
                coded_name_index[normalized].add(key)

    for key, profile in list(profiles.items()):
        code = str(profile.get("unified_social_credit_code") or "").strip().upper()
        if USCC_PATTERN.fullmatch(code):
            continue
        candidates: set[str] = set()
        for name in profile_names(profile):
            candidates.update(coded_name_index.get(normalize_name(name), set()))
        if len(candidates) != 1:
            if len(candidates) > 1:
                stats["ambiguous_name_only_profiles_retained"] += 1
            continue
        target_key = next(iter(candidates))
        target = profiles[target_key]
        alias_name = str(profile.get("current_name") or "")
        source = dict(profile)
        source["current_name"] = ""
        overlay_profile(target, source)
        target["recognition_names"] = merge_unique(
            target["recognition_names"], [alias_name]
        )
        if str(profile.get("recognition_evidence_status") or "") not in {
            "", "not_linked",
        }:
            target["recognition_evidence_status"] = str(
                profile["recognition_evidence_status"]
            )
        target["three_first_products"] = merge_three_first_products(
            target["three_first_products"], profile.get("three_first_products")
        )
        profiles.pop(key)
        for name in profile_names(target):
            normalized = normalize_name(name)
            if normalized:
                coded_name_index[normalized].add(target_key)
        stats["unambiguous_name_only_profiles_collapsed"] += 1


def temporal_identity_candidates(
    profiles: dict[str, dict[str, Any]],
    candidates: set[str],
    event_year: object,
) -> set[str]:
    """Discard subjects founded after a dated recognition event."""

    if len(candidates) <= 1 or not str(event_year or "").isdigit():
        return candidates
    temporal_candidates = {
        key
        for key in candidates
        if not str(profiles[key].get("founded_date") or "")[:4].isdigit()
        or int(str(profiles[key]["founded_date"])[:4]) <= int(str(event_year))
    }
    return temporal_candidates or candidates


def patch_target(
    profiles: dict[str, dict[str, Any]],
    row: dict[str, Any],
    *,
    label: str,
) -> tuple[str, dict[str, Any]]:
    code = str(
        row.get("unified_social_credit_code")
        or row.get("master_identity_key")
        or row.get("identity_key")
        or ""
    ).strip().upper()
    if not USCC_PATTERN.fullmatch(code):
        raise RuntimeError(f"{label}缺少有效统一社会信用代码：{code!r}")
    target = profiles.get(code)
    if target is None:
        raise RuntimeError(f"{label}未命中统一主档：{code}")
    expected_name = str(row.get("current_name") or "").strip()
    if expected_name and normalize_name(expected_name) != normalize_name(
        target.get("current_name")
    ):
        raise RuntimeError(
            f"{label}主体名称冲突：{code}/{expected_name}/{target.get('current_name')}"
        )
    return code, target


def validate_promotion_candidate(row: dict[str, Any], *, label: str) -> None:
    if str(row.get("source") or "").strip() != PUBLIC_SOURCE:
        raise RuntimeError(f"{label}来源未统一投影为{PUBLIC_SOURCE}")
    if row.get("candidate_only") is not True or row.get("production_promoted") is not False:
        raise RuntimeError(f"{label}不是待正式归并的候选记录")


def promote_identity_status(target: dict[str, Any], candidate_status: object) -> None:
    status = str(candidate_status or "").strip()
    if not status:
        return
    if str(target.get("identity_verification_status") or "") in {
        "",
        "pending_business_identity",
        "licensed_batch_identity_candidate",
        "audited_single_source_candidate",
    }:
        target["identity_verification_status"] = status


def overlay_identity_closure_patches(
    profiles: dict[str, dict[str, Any]],
    path: Path,
    stats: defaultdict[str, int],
) -> None:
    if not path.is_file():
        stats["identity_closure_patch_source_missing"] += 1
        return
    rows = read_jsonl(path)
    allowed_types = {
        "small_giant_recognition_closure",
        "peer_comparison_ready_flag_repair",
        "profile_topic_inference",
        "false_recognition_quarantine",
    }
    seen: set[tuple[str, str, str, str, str]] = set()
    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        validate_promotion_candidate(row, label="企业身份闭环增量")
        patch_type = str(row.get("patch_type") or "")
        if patch_type not in allowed_types:
            raise RuntimeError(f"企业身份闭环增量类型不受支持：{patch_type}")
        identity_key = str(row.get("identity_key") or "").strip().upper()
        fingerprint = (
            patch_type,
            identity_key,
            str(row.get("recognition_name") or ""),
            str(row.get("recognition_year") or ""),
            str(row.get("recognition_region") or ""),
        )
        if fingerprint in seen:
            raise RuntimeError(f"企业身份闭环增量存在重复补丁：{patch_type}/{identity_key}")
        seen.add(fingerprint)
        grouped[patch_type].append(row)

    for patch_type in (
        "small_giant_recognition_closure",
        "profile_topic_inference",
        "peer_comparison_ready_flag_repair",
        "false_recognition_quarantine",
    ):
        for row in grouped[patch_type]:
            code, target = patch_target(
                profiles, row, label=f"企业身份闭环增量/{patch_type}"
            )
            if patch_type == "small_giant_recognition_closure":
                recognition_name = str(row.get("recognition_name") or "")
                recognition_project = str(row.get("recognition_project") or "")
                project_already_linked = recognition_project in set(
                    target["recognition_projects"]
                )
                if project_already_linked:
                    target["recognition_names"] = merge_unique(
                        target["recognition_names"], [recognition_name]
                    )
                    target["recognition_evidence_status"] = str(
                        row.get("recognition_evidence_status")
                        or "knowledge_list_linked"
                    )
                    stats["small_giant_closure_existing_project_rows"] += 1
                else:
                    target["candidate_recognition_names"] = merge_unique(
                        target.get("candidate_recognition_names"),
                        [recognition_name],
                    )
                    target["candidate_recognition_projects"] = merge_unique(
                        target.get("candidate_recognition_projects"),
                        [recognition_project],
                    )
                    target["candidate_recognition_evidence_status"] = str(
                        row.get("recognition_evidence_status")
                        or "knowledge_list_linked"
                    )
                    stats["small_giant_closure_candidate_only_project_rows"] += 1
                promote_identity_status(target, row.get("identity_verification_status"))
                existing_promotions = target.get("identity_closure_promotions") or []
                if not isinstance(existing_promotions, list):
                    raise RuntimeError(f"企业身份闭环提升记录结构非法：{code}")
                target["identity_closure_promotions"] = [
                    *existing_promotions,
                    {
                        "recognition_name": recognition_name,
                        "recognition_project": recognition_project,
                        "recognition_region": str(row.get("recognition_region") or ""),
                        "recognition_year": str(row.get("recognition_year") or ""),
                        "closure_basis": str(row.get("closure_basis") or ""),
                        "lineage_verification_method": str(
                            row.get("lineage_verification_method") or ""
                        ),
                        "lineage_evidence_urls": as_list(
                            row.get("lineage_evidence_urls")
                        ),
                        "project_scope_included": int(project_already_linked),
                        "source": PUBLIC_SOURCE,
                    },
                ]
                stats["small_giant_recognition_closure_patches_promoted"] += 1
            elif patch_type == "profile_topic_inference":
                if str(row.get("inference_scope") or "") != "产品主题，不生成具体产品型号":
                    raise RuntimeError(f"企业主题推断边界不受支持：{code}")
                target["main_product_tags"] = merge_unique(
                    target["main_product_tags"], row.get("main_product_tags")
                )
                target["business_profile_evidence_status"] = str(
                    row.get("business_profile_evidence_status")
                    or "knowledge_profile_inferred"
                )
                target["_peer_comparison_ready_override"] = 1
                stats["profile_topic_inference_patches_promoted"] += 1
            elif patch_type == "peer_comparison_ready_flag_repair":
                if int(row.get("peer_comparison_ready") or 0) != 1:
                    raise RuntimeError(f"同行对比就绪补丁值不合法：{code}")
                if not has_business_profile_data(target):
                    raise RuntimeError(f"同行对比就绪补丁缺少企业画像：{code}")
                target["_peer_comparison_ready_override"] = 1
                stats["peer_comparison_ready_patches_promoted"] += 1
            else:
                if row.get("preserve_enterprise_identity") is not True:
                    raise RuntimeError(f"错误认定关系隔离不允许删除主体：{code}")
                remove_names = {
                    normalize_name(value)
                    for value in as_list(row.get("remove_recognition_names"))
                }
                remove_projects = set(as_list(row.get("remove_recognition_projects")))
                target["recognition_names"] = [
                    value
                    for value in target["recognition_names"]
                    if normalize_name(value) not in remove_names
                ]
                target["recognition_projects"] = [
                    value
                    for value in target["recognition_projects"]
                    if value not in remove_projects
                ]
                target["three_first_products"] = [
                    value
                    for value in target["three_first_products"]
                    if str(value.get("project_name") or "") not in remove_projects
                ]
                if not target["recognition_projects"]:
                    target["recognition_evidence_status"] = "not_linked"
                stats["false_recognition_relationships_quarantined"] += 1
    stats["identity_closure_patch_records_promoted"] += len(rows)


def overlay_qizhidao_queue_reuse_candidates(
    profiles: dict[str, dict[str, Any]],
    path: Path,
    stats: defaultdict[str, int],
) -> None:
    if not path.is_file():
        stats["qizhidao_queue_reuse_candidate_source_missing"] += 1
        return
    seen_targets: set[str] = set()
    for row in read_jsonl(path):
        validate_promotion_candidate(row, label="企知道队列本地主档复用增量")
        if str(row.get("patch_type") or "") != "deferred_qizhidao_queue_local_master_reuse":
            raise RuntimeError("企知道队列本地主档复用增量类型不受支持")
        if row.get("qizhidao_requery_required") is not False:
            raise RuntimeError("企知道队列归并候选仍要求重拉")
        code, target = patch_target(
            profiles, row, label="企知道队列本地主档复用增量"
        )
        if code in seen_targets:
            raise RuntimeError(f"企知道队列存在重复主档映射：{code}")
        seen_targets.add(code)
        if int(row.get("peer_comparison_ready") or 0) != 1:
            raise RuntimeError(f"企知道队列复用主体未就绪：{code}")
        if not has_business_profile_data(target):
            raise RuntimeError(f"企知道队列复用主体缺少完整画像：{code}")
        promote_identity_status(target, row.get("identity_verification_status"))
        target["_peer_comparison_ready_override"] = 1
        target["qizhidao_requery_required"] = False
        target["qizhidao_queue_resolution_status"] = "local_master_reused"
        target["qizhidao_queue_match_method"] = str(row.get("match_method") or "")
        target["qizhidao_business_profile_reuse_status"] = str(
            row.get("business_profile_reuse_status") or "knowledge_verified"
        )
        target["qizhidao_source_identity_keys"] = merge_unique(
            target.get("qizhidao_source_identity_keys"),
            row.get("source_identity_keys"),
        )
        target["qizhidao_source_enterprise_names"] = merge_unique(
            target.get("qizhidao_source_enterprise_names"),
            [row.get("source_enterprise_name")],
        )
        stats["qizhidao_queue_local_master_reuse_promoted"] += 1


def build_profiles(
    connection: sqlite3.Connection,
    knowledge_identities: Path,
    business_profile_candidates: Path | None,
    theme_enrichment_candidates: Path | None,
    batch_profile_provenance: Path | None,
    batch_profile_review: Path | None,
    identity_closure_patches: Path | None,
    qizhidao_queue_reuse_candidates: Path | None,
) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    profiles: dict[str, dict[str, Any]] = {}
    stats: defaultdict[str, int] = defaultdict(int)

    if table_exists(connection, "enterprise_identity_profiles"):
        for raw in connection.execute("SELECT * FROM enterprise_identity_profiles"):
            row = dict(raw)
            key = profile_key(row)
            target = profiles.setdefault(key, empty_profile(key, str(row.get("current_name") or "")))
            overlay_profile(target, row)
            target["identity_verification_status"] = str(
                row.get("verification_status") or "pending_business_identity"
            )
            target["recognition_projects"] = merge_projects(
                target["recognition_projects"], row.get("recognition_projects_json")
            )
            lifecycles = row.get("project_lifecycles_json")
            if lifecycles:
                try:
                    parsed = json.loads(str(lifecycles))
                except json.JSONDecodeError:
                    parsed = []
                if isinstance(parsed, list):
                    target["project_lifecycles"] = parsed
            if target["recognition_projects"]:
                target["recognition_evidence_status"] = "knowledge_list_linked"
            stats["timeline_profiles"] += 1

    snapshot = resolve_snapshot(knowledge_identities)
    if snapshot:
        for row in read_jsonl(snapshot):
            key = profile_key(row)
            target = profiles.setdefault(key, empty_profile(key, str(row.get("current_name") or "")))
            overlay_profile(
                target,
                row,
                business_status=(
                    "knowledge_verified"
                    if has_business_profile_data(row)
                    else "knowledge_identity_only"
                ),
            )
            target["identity_verification_status"] = str(
                row.get("knowledge_verification_status") or "knowledge_verified"
            )
            if target["recognition_projects"]:
                target["recognition_evidence_status"] = "knowledge_list_linked"
            stats["knowledge_verified_business_profiles"] += 1

    if table_exists(connection, "small_giant_enterprise_identity_profiles"):
        for raw in connection.execute(
            "SELECT identity_key,unified_social_credit_code,current_name,verification_status,"
            "profile_json,captured_at FROM small_giant_enterprise_identity_profiles"
        ):
            row = dict(raw)
            profile = as_dict(row.get("profile_json"))
            profile.update(
                {
                    "identity_key": row.get("identity_key"),
                    "unified_social_credit_code": row.get("unified_social_credit_code"),
                    "current_name": row.get("current_name"),
                    "captured_at": row.get("captured_at"),
                }
            )
            key = profile_key(profile)
            target = profiles.setdefault(key, empty_profile(key, str(row.get("current_name") or "")))
            existing_business_status = target["business_profile_evidence_status"]
            overlay_profile(
                target,
                profile,
                business_status=(
                    existing_business_status
                    if existing_business_status == "knowledge_verified"
                    else str(row.get("verification_status") or "audited_single_source_candidate")
                ),
            )
            if target["identity_verification_status"] == "pending_business_identity":
                target["identity_verification_status"] = str(
                    row.get("verification_status") or "audited_single_source_candidate"
                )
            target["recognition_projects"] = merge_projects(
                target["recognition_projects"], ["国家专精特新“小巨人”企业"]
            )
            target["recognition_evidence_status"] = "knowledge_list_linked"
            stats["small_giant_business_profiles"] += 1

    if business_profile_candidates is not None:
        overlay_business_profile_candidates(
            profiles,
            business_profile_candidates,
            stats,
        )

    if batch_profile_provenance is not None:
        overlay_batch_profile_provenance(
            profiles,
            batch_profile_provenance,
            stats,
        )

    if theme_enrichment_candidates is not None:
        overlay_theme_enrichment_candidates(
            profiles,
            theme_enrichment_candidates,
            stats,
        )

    name_index: defaultdict[str, set[str]] = defaultdict(set)
    for key, profile in profiles.items():
        for name in merge_unique(
            [profile["current_name"]], profile["former_names"], profile["recognition_names"]
        ):
            normalized = normalize_name(name)
            if normalized:
                name_index[normalized].add(key)

    if table_exists(connection, "three_first_project_awards"):
        award_rows = connection.execute(
            "SELECT enterprise_key,enterprise_name,enterprise_aliases,province,city,county,"
            "project_name,year,product_name,recognition_tier,product_category,list_status "
            "FROM three_first_project_awards ORDER BY enterprise_name,project_name,year,product_name"
        ).fetchall()
        for raw in award_rows:
            row = dict(raw)
            candidates = set(
                name_index.get(normalize_name(row["enterprise_name"]), set())
            )
            if not candidates:
                for name in merge_unique(row["enterprise_aliases"]):
                    candidates.update(name_index.get(normalize_name(name), set()))
            candidates = temporal_identity_candidates(
                profiles, candidates, row["year"]
            )
            if len(candidates) == 1:
                key = next(iter(candidates))
            else:
                key = "three-first:" + str(row["enterprise_key"] or normalize_name(row["enterprise_name"]))
            target = profiles.setdefault(key, empty_profile(key, str(row["enterprise_name"] or "")))
            target["current_name"] = first_text(target["current_name"], row["enterprise_name"])
            target["province"] = first_text(target["province"], row["province"])
            target["city"] = first_text(target["city"], row["city"])
            target["county"] = first_text(target["county"], row["county"])
            target["recognition_names"] = merge_unique(
                target["recognition_names"], [row["enterprise_name"]], row["enterprise_aliases"]
            )
            target["recognition_projects"] = merge_projects(
                target["recognition_projects"], [row["project_name"]]
            )
            target["recognition_evidence_status"] = "official_product_list_linked"
            product = {
                "project_name": str(row["project_name"] or ""),
                "year": row["year"],
                "product_name": str(row["product_name"] or ""),
                "recognition_tier": str(row["recognition_tier"] or ""),
                "product_category": str(row["product_category"] or ""),
                "list_status": str(row["list_status"] or ""),
                "source": PUBLIC_SOURCE,
            }
            target["three_first_products"] = merge_three_first_products(
                target["three_first_products"], [product]
            )
            stats["three_first_product_records"] += 1

    collapse_unambiguous_name_only_profiles(profiles, stats)

    if batch_profile_review is not None:
        exclude_reviewed_non_enterprise_profiles(
            profiles,
            batch_profile_review,
            stats,
        )

    if identity_closure_patches is not None:
        overlay_identity_closure_patches(
            profiles,
            identity_closure_patches,
            stats,
        )

    if qizhidao_queue_reuse_candidates is not None:
        overlay_qizhidao_queue_reuse_candidates(
            profiles,
            qizhidao_queue_reuse_candidates,
            stats,
        )

    for profile in profiles.values():
        has_business_data = bool(
            profile["company_introduction"]
            or profile["business_scope"]
            or profile["main_product_tags"]
            or profile["industry_track_tags"]
        )
        project_set = set(profile["recognition_projects"])
        profile["peer_comparison_ready"] = int(
            profile.pop(
                "_peer_comparison_ready_override",
                int(has_business_data and bool(project_set & PEER_PROJECTS)),
            )
        )
        profile["three_first_product_enriched"] = int(
            has_business_data and bool(profile["three_first_products"])
        )
        profile["requires_qcc"], profile["qcc_requirement_reasons"] = (
            qcc_requirement(profile)
        )
        profile["source"] = PUBLIC_SOURCE
    return profiles, dict(stats)


def write_database(
    connection: sqlite3.Connection,
    profiles: dict[str, dict[str, Any]],
) -> tuple[int, int, dict[str, dict[str, int]]]:
    connection.executescript(
        """
        DROP TABLE IF EXISTS enterprise_peer_comparison_terms;
        DROP TABLE IF EXISTS enterprise_profile_enrichment_queue;
        DROP TABLE IF EXISTS enterprise_qizhidao_queue_resolutions;
        DROP TABLE IF EXISTS enterprise_identity_closure_promotions;
        DROP TABLE IF EXISTS enterprise_unified_identity_coverage;
        DROP TABLE IF EXISTS enterprise_unified_digital_identities;
        CREATE TABLE enterprise_unified_digital_identities(
            identity_key TEXT PRIMARY KEY,
            unified_social_credit_code TEXT NOT NULL DEFAULT '',
            current_name TEXT NOT NULL,
            former_names_json TEXT NOT NULL DEFAULT '[]',
            recognition_names_json TEXT NOT NULL DEFAULT '[]',
            province TEXT NOT NULL DEFAULT '',
            city TEXT NOT NULL DEFAULT '',
            county TEXT NOT NULL DEFAULT '',
            registration_status TEXT NOT NULL DEFAULT '',
            founded_date TEXT NOT NULL DEFAULT '',
            registered_capital TEXT NOT NULL DEFAULT '',
            company_type TEXT NOT NULL DEFAULT '',
            industry_level_1 TEXT NOT NULL DEFAULT '',
            industry_level_2 TEXT NOT NULL DEFAULT '',
            industry_level_3 TEXT NOT NULL DEFAULT '',
            company_introduction TEXT NOT NULL DEFAULT '',
            business_scope TEXT NOT NULL DEFAULT '',
            main_product_tags_json TEXT NOT NULL DEFAULT '[]',
            industry_track_tags_json TEXT NOT NULL DEFAULT '[]',
            ip_statistics_json TEXT NOT NULL DEFAULT '{}',
            honors_json TEXT NOT NULL DEFAULT '[]',
            recognition_projects_json TEXT NOT NULL DEFAULT '[]',
            project_lifecycles_json TEXT NOT NULL DEFAULT '[]',
            three_first_products_json TEXT NOT NULL DEFAULT '[]',
            identity_verification_status TEXT NOT NULL,
            business_profile_evidence_status TEXT NOT NULL,
            recognition_evidence_status TEXT NOT NULL,
            peer_comparison_ready INTEGER NOT NULL DEFAULT 0,
            three_first_product_enriched INTEGER NOT NULL DEFAULT 0,
            requires_qcc INTEGER NOT NULL DEFAULT 0,
            qcc_requirement_reasons_json TEXT NOT NULL DEFAULT '[]',
            source TEXT NOT NULL,
            profile_updated_at TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX enterprise_unified_identity_code_idx
            ON enterprise_unified_digital_identities(unified_social_credit_code);
        CREATE INDEX enterprise_unified_identity_name_idx
            ON enterprise_unified_digital_identities(current_name);
        CREATE INDEX enterprise_unified_identity_peer_idx
            ON enterprise_unified_digital_identities(peer_comparison_ready);
        CREATE INDEX enterprise_unified_identity_qcc_idx
            ON enterprise_unified_digital_identities(requires_qcc);
        CREATE TABLE enterprise_peer_comparison_terms(
            identity_key TEXT NOT NULL,
            term_type TEXT NOT NULL,
            term TEXT NOT NULL,
            normalized_term TEXT NOT NULL,
            source TEXT NOT NULL,
            PRIMARY KEY(identity_key,term_type,normalized_term)
        );
        CREATE INDEX enterprise_peer_term_lookup_idx
            ON enterprise_peer_comparison_terms(normalized_term,term_type);
        CREATE TABLE enterprise_unified_identity_coverage(
            scope_key TEXT PRIMARY KEY,
            scope_label TEXT NOT NULL,
            total_subjects INTEGER NOT NULL,
            ready_subjects INTEGER NOT NULL,
            missing_profile_subjects INTEGER NOT NULL,
            note TEXT NOT NULL,
            source TEXT NOT NULL
        );
        CREATE TABLE enterprise_profile_enrichment_queue(
            identity_key TEXT NOT NULL,
            target_scope TEXT NOT NULL,
            current_name TEXT NOT NULL,
            identity_verification_status TEXT NOT NULL,
            business_profile_evidence_status TEXT NOT NULL,
            reason TEXT NOT NULL,
            source TEXT NOT NULL,
            PRIMARY KEY(identity_key,target_scope)
        );
        CREATE TABLE enterprise_qizhidao_queue_resolutions(
            identity_key TEXT PRIMARY KEY,
            unified_social_credit_code TEXT NOT NULL,
            current_name TEXT NOT NULL,
            source_identity_keys_json TEXT NOT NULL DEFAULT '[]',
            source_enterprise_names_json TEXT NOT NULL DEFAULT '[]',
            match_method TEXT NOT NULL,
            business_profile_reuse_status TEXT NOT NULL,
            qizhidao_requery_required INTEGER NOT NULL,
            resolution_status TEXT NOT NULL,
            source TEXT NOT NULL
        );
        CREATE TABLE enterprise_identity_closure_promotions(
            identity_key TEXT NOT NULL,
            unified_social_credit_code TEXT NOT NULL,
            current_name TEXT NOT NULL,
            recognition_name TEXT NOT NULL,
            recognition_project TEXT NOT NULL,
            recognition_region TEXT NOT NULL,
            recognition_year TEXT NOT NULL,
            closure_basis TEXT NOT NULL,
            lineage_verification_method TEXT NOT NULL,
            lineage_evidence_urls_json TEXT NOT NULL DEFAULT '[]',
            project_scope_included INTEGER NOT NULL,
            source TEXT NOT NULL,
            PRIMARY KEY(
                identity_key, recognition_name, recognition_project,
                recognition_region, recognition_year
            )
        );
        """
    )
    rows = []
    qizhidao_resolution_rows = []
    closure_promotion_rows = []
    terms: list[tuple[str, str, str, str, str]] = []
    for key, profile in sorted(profiles.items()):
        promotions = profile.get("identity_closure_promotions") or []
        if not isinstance(promotions, list):
            raise RuntimeError(f"企业身份闭环提升记录结构非法：{key}")
        for promotion in promotions:
            if not isinstance(promotion, dict):
                raise RuntimeError(f"企业身份闭环提升记录结构非法：{key}")
            closure_promotion_rows.append(
                (
                    key,
                    profile["unified_social_credit_code"],
                    profile["current_name"],
                    str(promotion.get("recognition_name") or ""),
                    str(promotion.get("recognition_project") or ""),
                    str(promotion.get("recognition_region") or ""),
                    str(promotion.get("recognition_year") or ""),
                    str(promotion.get("closure_basis") or ""),
                    str(promotion.get("lineage_verification_method") or ""),
                    json.dumps(
                        as_list(promotion.get("lineage_evidence_urls")),
                        ensure_ascii=False,
                    ),
                    int(promotion.get("project_scope_included") or 0),
                    PUBLIC_SOURCE,
                )
            )
        if profile.get("qizhidao_queue_resolution_status") == "local_master_reused":
            qizhidao_resolution_rows.append(
                (
                    key,
                    profile["unified_social_credit_code"],
                    profile["current_name"],
                    json.dumps(
                        profile.get("qizhidao_source_identity_keys", []),
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        profile.get("qizhidao_source_enterprise_names", []),
                        ensure_ascii=False,
                    ),
                    str(profile.get("qizhidao_queue_match_method") or ""),
                    str(
                        profile.get("qizhidao_business_profile_reuse_status")
                        or ""
                    ),
                    int(bool(profile.get("qizhidao_requery_required"))),
                    "local_master_reused",
                    PUBLIC_SOURCE,
                )
            )
        rows.append(
            (
                key,
                profile["unified_social_credit_code"],
                profile["current_name"],
                json.dumps(profile["former_names"], ensure_ascii=False),
                json.dumps(profile["recognition_names"], ensure_ascii=False),
                profile["province"], profile["city"], profile["county"],
                profile["registration_status"], profile["founded_date"],
                profile["registered_capital"], profile["company_type"],
                profile["industry_level_1"], profile["industry_level_2"],
                profile["industry_level_3"], profile["company_introduction"],
                profile["business_scope"],
                json.dumps(profile["main_product_tags"], ensure_ascii=False),
                json.dumps(profile["industry_track_tags"], ensure_ascii=False),
                json.dumps(profile["ip_statistics"], ensure_ascii=False),
                json.dumps(profile["honors"], ensure_ascii=False),
                json.dumps(profile["recognition_projects"], ensure_ascii=False),
                json.dumps(profile["project_lifecycles"], ensure_ascii=False),
                json.dumps(profile["three_first_products"], ensure_ascii=False),
                profile["identity_verification_status"],
                profile["business_profile_evidence_status"],
                profile["recognition_evidence_status"],
                profile["peer_comparison_ready"],
                profile["three_first_product_enriched"],
                profile["requires_qcc"],
                json.dumps(profile["qcc_requirement_reasons"], ensure_ascii=False),
                PUBLIC_SOURCE,
                profile["profile_updated_at"],
            )
        )
        if not profile["peer_comparison_ready"]:
            continue
        term_groups = {
            "main_product": profile["main_product_tags"],
            "industry_track": profile["industry_track_tags"],
            "industry_level": [
                profile["industry_level_3"],
            ],
        }
        for term_type, values in term_groups.items():
            seen: set[str] = set()
            for term in as_list(values):
                normalized = normalize_term(term)
                if len(normalized) < 2 or normalized in seen:
                    continue
                seen.add(normalized)
                terms.append((key, term_type, term, normalized, PUBLIC_SOURCE))
    connection.executemany(
        "INSERT INTO enterprise_unified_digital_identities VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    connection.executemany(
        "INSERT INTO enterprise_qizhidao_queue_resolutions VALUES(?,?,?,?,?,?,?,?,?,?)",
        qizhidao_resolution_rows,
    )
    connection.executemany(
        "INSERT INTO enterprise_identity_closure_promotions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        closure_promotion_rows,
    )
    connection.executemany(
        "INSERT INTO enterprise_peer_comparison_terms VALUES(?,?,?,?,?)", terms
    )
    coverage_specifications = (
        (
            "specialized_sme_peer_comparison",
            "专精特新中小企业同行对比",
            lambda profile: bool(
                set(profile["recognition_projects"]) & SPECIALIZED_PROJECTS
            ),
            lambda profile: bool(profile["peer_comparison_ready"]),
            "仅企业身份或名单记录不足以生成同行对比，必须同时具备经营或产品画像与主题词。",
        ),
        (
            "small_giant_peer_comparison",
            "国家专精特新小巨人企业同行对比",
            lambda profile: SMALL_GIANT_PROJECT in profile["recognition_projects"],
            lambda profile: bool(profile["peer_comparison_ready"]),
            "企业画像候选等级与名单认定证据分别保留，不因可比较而自动升级证据等级。",
        ),
        (
            "three_first_enterprise_enrichment",
            "三首认定产品企业信息增强",
            lambda profile: bool(profile["three_first_products"]),
            lambda profile: bool(profile["three_first_product_enriched"]),
            "三首认定产品保持原名单锚点；企业画像只作附加信息，不覆盖产品名称与认定状态。",
        ),
        (
            "topic_enrichment",
            "企业产品与行业主题补全",
            lambda profile: True,
            lambda profile: bool(
                profile["main_product_tags"] or profile["industry_track_tags"]
            ),
            "产品与行业主题均为空的主体进入补全队列；来源等级与是否需要商业信息复核分别记录。",
        ),
    )
    coverage: dict[str, dict[str, int]] = {}
    coverage_rows: list[tuple[str, str, int, int, int, str, str]] = []
    queue_rows: list[tuple[str, str, str, str, str, str, str]] = []
    for scope_key, label, included, ready, note in coverage_specifications:
        scoped_profiles = [profile for profile in profiles.values() if included(profile)]
        ready_count = sum(ready(profile) for profile in scoped_profiles)
        missing_count = len(scoped_profiles) - ready_count
        coverage[scope_key] = {
            "total_subjects": len(scoped_profiles),
            "ready_subjects": ready_count,
            "missing_profile_subjects": missing_count,
        }
        coverage_rows.append(
            (
                scope_key,
                label,
                len(scoped_profiles),
                ready_count,
                missing_count,
                note,
                PUBLIC_SOURCE,
            )
        )
        for profile in scoped_profiles:
            if ready(profile):
                continue
            if scope_key == "topic_enrichment":
                reason = "产品与行业主题均为空"
            else:
                reason = (
                    "缺少企业经营与产品画像"
                    if profile["business_profile_evidence_status"]
                    in {"not_collected", "knowledge_identity_only"}
                    else "企业画像缺少可用于同口径比较的主营产品或行业主题词"
                )
            queue_rows.append(
                (
                    profile["identity_key"],
                    scope_key,
                    profile["current_name"],
                    profile["identity_verification_status"],
                    profile["business_profile_evidence_status"],
                    reason,
                    PUBLIC_SOURCE,
                )
            )
    connection.executemany(
        "INSERT INTO enterprise_unified_identity_coverage VALUES(?,?,?,?,?,?,?)",
        coverage_rows,
    )
    connection.executemany(
        "INSERT INTO enterprise_profile_enrichment_queue VALUES(?,?,?,?,?,?,?)",
        queue_rows,
    )
    connection.commit()
    return len(rows), len(terms), coverage


def write_projection(path: Path, profiles: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for _, profile in sorted(profiles.items()):
            stream.write(json.dumps(profile, ensure_ascii=False, sort_keys=True) + "\n")


def build(
    database: Path,
    knowledge_identities: Path,
    output: Path | None,
    business_profile_candidates: Path | None = None,
    theme_enrichment_candidates: Path | None = None,
    batch_profile_provenance: Path | None = None,
    batch_profile_review: Path | None = None,
    identity_closure_patches: Path | None = None,
    qizhidao_queue_reuse_candidates: Path | None = None,
) -> dict[str, Any]:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        profiles, stats = build_profiles(
            connection,
            knowledge_identities,
            business_profile_candidates,
            theme_enrichment_candidates,
            batch_profile_provenance,
            batch_profile_review,
            identity_closure_patches,
            qizhidao_queue_reuse_candidates,
        )
        profile_count, term_count, coverage = write_database(connection, profiles)
    finally:
        connection.close()
    if output:
        write_projection(output, profiles)
    result = {
        **stats,
        "unified_profiles": profile_count,
        "peer_ready_profiles": sum(
            int(profile["peer_comparison_ready"]) for profile in profiles.values()
        ),
        "three_first_enriched_profiles": sum(
            int(profile["three_first_product_enriched"]) for profile in profiles.values()
        ),
        "qcc_required_profiles": sum(
            int(profile["requires_qcc"]) for profile in profiles.values()
        ),
        "peer_terms": term_count,
        "coverage": coverage,
        "source": PUBLIC_SOURCE,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    return result


def main() -> None:
    args = parse_args()
    print(
        json.dumps(
            build(
                args.database,
                args.knowledge_identities,
                args.output,
                args.business_profile_candidates,
                args.theme_enrichment_candidates,
                args.batch_profile_provenance,
                args.batch_profile_review,
                args.identity_closure_patches,
                args.qizhidao_queue_reuse_candidates,
            ),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
