from __future__ import annotations

import hashlib
import json
import sqlite3
from copy import deepcopy
from pathlib import Path
from typing import Mapping, Sequence
from urllib.parse import urlparse

from app.policy_thresholds import validate_threshold_registry


RD_PLATFORM_FAMILY_ID = "municipal-enterprise-rd-platform"


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _family_index(
    registry: Mapping[str, object],
) -> dict[str, dict[str, object]]:
    return {
        str(item.get("family_id") or ""): dict(item)
        for item in registry.get("project_families", [])
        if isinstance(item, Mapping)
        and str(item.get("family_id") or "")
    }


def _threshold_city_index(
    registry: Mapping[str, object],
) -> dict[str, dict[str, object]]:
    return {
        str(item.get("city") or ""): dict(item)
        for item in registry.get("city_variants", [])
        if isinstance(item, Mapping) and str(item.get("city") or "")
    }


def build_policy_transition_snapshot(
    policy_registry: Mapping[str, object],
    threshold_registry: Mapping[str, object],
) -> dict[str, object]:
    """Build city-family hashes so unchanged cells can be reused."""
    threshold_cities = _threshold_city_index(threshold_registry)
    cells: dict[str, dict[str, object]] = {}
    for family_id, family in _family_index(policy_registry).items():
        for variant in family.get("city_variants", []):
            if not isinstance(variant, Mapping):
                continue
            city = str(variant.get("city") or "")
            if not city:
                continue
            threshold_variant = (
                threshold_cities.get(city, {})
                if family_id == RD_PLATFORM_FAMILY_ID
                else {}
            )
            cell_key = f"{family_id}|{city}"
            content = {
                "family_id": family_id,
                "city": city,
                "policy_variant": dict(variant),
                "threshold_variant": threshold_variant,
            }
            cells[cell_key] = {
                "cell_key": cell_key,
                "family_id": family_id,
                "city": city,
                "canonical_name": variant.get("canonical_name"),
                "algorithm_project_id": variant.get(
                    "algorithm_project_id"
                ),
                "route_status": variant.get("route_status"),
                "formal_policy": variant.get("formal_policy"),
                "formal_policy_status": (
                    variant.get("formal_policy_status")
                    or variant.get("policy_status")
                ),
                "prospective_policy": variant.get("prospective_policy"),
                "threshold_track_ids": list(
                    variant.get("threshold_track_ids", [])
                    if isinstance(
                        variant.get("threshold_track_ids"),
                        Sequence,
                    )
                    and not isinstance(
                        variant.get("threshold_track_ids"),
                        (str, bytes),
                    )
                    else []
                ),
                "content_hash": _digest(content),
            }
    return {
        "schema_version": 1,
        "snapshot_type": "four-city-policy-transition-cells",
        "cell_count": len(cells),
        "cells": cells,
        "source_hashes": {
            "policy_registry": _digest(policy_registry),
            "threshold_registry": _digest(threshold_registry),
        },
    }


def diff_policy_transition_snapshots(
    before: Mapping[str, object] | None,
    after: Mapping[str, object],
) -> dict[str, object]:
    before_cells = (
        before.get("cells", {}) if isinstance(before, Mapping) else {}
    )
    after_cells = after.get("cells", {})
    if not isinstance(before_cells, Mapping):
        before_cells = {}
    if not isinstance(after_cells, Mapping):
        after_cells = {}
    changes: list[dict[str, object]] = []
    for cell_key in sorted(set(before_cells) | set(after_cells)):
        old = (
            before_cells.get(cell_key, {})
            if isinstance(before_cells.get(cell_key), Mapping)
            else {}
        )
        new = (
            after_cells.get(cell_key, {})
            if isinstance(after_cells.get(cell_key), Mapping)
            else {}
        )
        if old.get("content_hash") == new.get("content_hash"):
            continue
        changes.append(
            {
                "cell_key": cell_key,
                "family_id": new.get("family_id")
                or old.get("family_id"),
                "city": new.get("city") or old.get("city"),
                "change_type": (
                    "added"
                    if not old
                    else "removed"
                    if not new
                    else "modified"
                ),
                "before_hash": old.get("content_hash"),
                "after_hash": new.get("content_hash"),
                "algorithm_project_id": new.get("algorithm_project_id")
                or old.get("algorithm_project_id"),
                "affected_outputs": [
                    "项目路由",
                    "企业阈值判断",
                    "前瞻预测",
                    "历史回测解释",
                    "政策来源披露",
                ],
            }
        )
    project_ids = sorted(
        {
            str(item.get("algorithm_project_id") or "")
            for item in changes
            if str(item.get("algorithm_project_id") or "")
        }
    )
    return {
        "schema_version": 1,
        "change_count": len(changes),
        "changed_cells": changes,
        "compile_project_ids": project_ids,
        "reused_cell_count": max(
            0,
            len(after_cells)
            - sum(item["change_type"] != "removed" for item in changes),
        ),
        "invariants": [
            "只重编内容哈希发生变化的城市项目族单元及依赖项目",
            "正式名单身份事实不因政策变化被改写",
            "征求意见稿转正式后只替换前瞻政策层并保留历史草案",
        ],
    }


def _official_domain_allowed(
    source_url: str,
    official_domains: Sequence[object],
) -> bool:
    hostname = (urlparse(source_url).hostname or "").casefold()
    return any(
        hostname == str(domain).casefold()
        or hostname.endswith("." + str(domain).casefold())
        for domain in official_domains
        if str(domain).strip()
    )


def _replace_city_tracks(
    threshold_registry: dict[str, object],
    *,
    city: str,
    tracks: Sequence[Mapping[str, object]],
) -> None:
    for variant in threshold_registry.get("city_variants", []):
        if not isinstance(variant, dict):
            continue
        if str(variant.get("city") or "") == city:
            variant["tracks"] = [dict(item) for item in tracks]
            return
    raise ValueError("候选正式政策的城市未登记阈值轨道")


def _find_policy_variant(
    registry: dict[str, object],
    *,
    family_id: str,
    city: str,
) -> dict[str, object] | None:
    for family in registry.get("project_families", []):
        if not isinstance(family, dict):
            continue
        if str(family.get("family_id") or "") != family_id:
            continue
        return next(
            (
                item
                for item in family.get("city_variants", [])
                if isinstance(item, dict)
                and str(item.get("city") or "") == city
            ),
            None,
        )
    return None


def promote_verified_formal_candidate(
    policy_registry: Mapping[str, object],
    threshold_registry: Mapping[str, object],
    candidate: Mapping[str, object],
) -> dict[str, object]:
    """Promote a verified official candidate and preserve the former draft."""
    updated_policy = deepcopy(dict(policy_registry))
    updated_thresholds = deepcopy(dict(threshold_registry))
    family_id = str(candidate.get("family_id") or "")
    city = str(candidate.get("city") or "")
    variant = _find_policy_variant(
        updated_policy,
        family_id=family_id,
        city=city,
    )
    if variant is None:
        return {
            "status": "rejected",
            "reason": "候选文件不属于已登记城市项目族",
        }
    prospective = str(variant.get("prospective_policy") or "").strip()
    if not prospective:
        return {
            "status": "rejected",
            "reason": "该城市项目族没有待替换的征求意见稿",
        }
    monitor = (
        variant.get("monitor", {})
        if isinstance(variant.get("monitor"), Mapping)
        else {}
    )
    source_url = str(candidate.get("source_url") or "")
    verification_status = str(
        candidate.get("verification_status") or ""
    )
    policy_status = str(candidate.get("policy_status") or "")
    if verification_status not in {"verified", "official-verified"}:
        return {
            "status": "rejected",
            "reason": "候选文件尚未完成官方来源核验",
        }
    if policy_status not in {"current", "formal", "current-formal"}:
        return {
            "status": "rejected",
            "reason": "候选文件未标记为正式现行政策",
        }
    official_domains = monitor.get("official_domains", [])
    if not isinstance(official_domains, Sequence) or isinstance(
        official_domains,
        (str, bytes),
    ):
        official_domains = []
    if not _official_domain_allowed(source_url, official_domains):
        return {
            "status": "rejected",
            "reason": "候选文件不在该项目登记的政府官方域名内",
        }
    title = str(candidate.get("title") or "").strip()
    keywords = [
        str(item)
        for item in monitor.get("keywords", [])
        if str(item).strip()
    ]
    if not title or not any(keyword in title for keyword in keywords):
        return {
            "status": "rejected",
            "reason": "候选标题未命中项目族正式文件关键词",
        }
    replacement_target = str(
        candidate.get("replaces_prospective_policy") or ""
    ).strip()
    if replacement_target and replacement_target != prospective:
        return {
            "status": "rejected",
            "reason": "候选文件声明替换的征求意见稿与注册表不一致",
        }
    raw_tracks = candidate.get("threshold_tracks")
    tracks = (
        [dict(item) for item in raw_tracks if isinstance(item, Mapping)]
        if isinstance(raw_tracks, Sequence)
        and not isinstance(raw_tracks, (str, bytes))
        else []
    )
    if not tracks:
        return {
            "status": "rejected",
            "reason": "候选正式文件尚未携带可执行阈值轨道",
        }
    for track in tracks:
        track["policy_status"] = "current"
        track["formal_conclusion_allowed"] = True
    try:
        _replace_city_tracks(
            updated_thresholds,
            city=city,
            tracks=tracks,
        )
    except ValueError as error:
        return {"status": "rejected", "reason": str(error)}
    threshold_errors = validate_threshold_registry(updated_thresholds)
    if threshold_errors:
        return {
            "status": "rejected",
            "reason": "候选阈值轨道未通过结构校验",
            "errors": threshold_errors,
        }

    before_snapshot = build_policy_transition_snapshot(
        policy_registry,
        threshold_registry,
    )
    historical = variant.get("historical_drafts")
    if not isinstance(historical, list):
        historical = []
        variant["historical_drafts"] = historical
    historical.append(
        {
            "title": prospective,
            "status": variant.get("prospective_policy_status"),
            "consultation_period": variant.get("consultation_period"),
            "source_url": variant.get("prospective_url"),
            "retired_role": "historical-draft-after-formal-promotion",
        }
    )
    variant["formal_policy"] = title
    variant["formal_policy_status"] = "current"
    variant["policy_status"] = "current"
    variant["official_url"] = source_url
    variant["source_role"] = str(
        candidate.get("source_role")
        or "经官方来源核验的正式发布文件"
    )
    variant["route_status"] = "active-municipal"
    variant["threshold_track_ids"] = [
        str(item.get("track_id") or "")
        for item in tracks
        if str(item.get("track_id") or "")
    ]
    variant["transition"] = (
        f"{prospective}已由正式文件替换；"
        "旧稿仅保留历史追溯，不再参与未来准备判断。"
    )
    for key in (
        "prospective_policy",
        "prospective_policy_status",
        "consultation_period",
        "prospective_url",
        "evaluation_rule",
    ):
        variant.pop(key, None)
    if isinstance(variant.get("monitor"), dict):
        variant["monitor"]["status"] = "formal-promoted"
        variant["monitor"]["last_promoted_source_url"] = source_url
        variant["monitor"]["last_promoted_title"] = title

    after_snapshot = build_policy_transition_snapshot(
        updated_policy,
        updated_thresholds,
    )
    return {
        "status": "promoted",
        "family_id": family_id,
        "city": city,
        "formal_policy": title,
        "source_url": source_url,
        "policy_registry": updated_policy,
        "threshold_registry": updated_thresholds,
        "change_set": diff_policy_transition_snapshots(
            before_snapshot,
            after_snapshot,
        ),
        "invariants": [
            "征求意见稿已转入历史草案，不作为正式政策事实",
            "官方名单身份事件不改写",
            "只重算受影响城市项目族的评估、预测和历史回测解释",
        ],
    }


def affected_enterprises_for_policy_cell(
    database_path: Path | None,
    *,
    project_names: Sequence[str],
    limit: int = 10000,
) -> list[dict[str, object]]:
    """List matched enterprises without changing identity facts."""
    names = sorted({str(item) for item in project_names if str(item).strip()})
    if not database_path or not database_path.is_file() or not names:
        return []
    results: list[dict[str, object]] = []
    with sqlite3.connect(database_path) as connection:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        placeholders = ",".join("?" for _ in names)
        for table in (
            "enterprise_recognition_events",
            "enterprise_project_identity_twins",
        ):
            if table not in tables:
                continue
            columns = {
                str(row[1])
                for row in connection.execute(f"PRAGMA table_info({table})")
            }
            if "project_name" not in columns:
                continue
            enterprise_column = next(
                (
                    item
                    for item in (
                        "enterprise_name_at_event",
                        "enterprise_name",
                        "current_name",
                        "company_name",
                    )
                    if item in columns
                ),
                None,
            )
            if enterprise_column is None:
                continue
            year_column = next(
                (
                    item
                    for item in (
                        "recognition_year",
                        "event_year",
                        "year",
                    )
                    if item in columns
                ),
                None,
            )
            year_expression = year_column or "NULL"
            rows = connection.execute(
                f"""
                SELECT DISTINCT {enterprise_column},project_name,{year_expression}
                FROM {table}
                WHERE project_name IN ({placeholders})
                ORDER BY {enterprise_column},project_name
                LIMIT ?
                """,
                (*names, max(1, int(limit))),
            )
            for enterprise_name, project_name, year in rows:
                results.append(
                    {
                        "enterprise_name": str(enterprise_name or ""),
                        "project_name": str(project_name or ""),
                        "event_year": year,
                        "source_table": table,
                    }
                )
    unique: dict[tuple[object, ...], dict[str, object]] = {}
    for item in results:
        key = (
            item["enterprise_name"],
            item["project_name"],
            item["event_year"],
        )
        unique[key] = item
    return sorted(
        unique.values(),
        key=lambda item: (
            str(item["enterprise_name"]),
            str(item["project_name"]),
            str(item["event_year"] or ""),
        ),
    )[:limit]
