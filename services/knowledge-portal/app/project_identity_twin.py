from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Mapping, Sequence


EVENT_PRECEDENCE = {
    "recognition_publicity": 10,
    "recognition": 20,
    "review_due": 30,
    "review_publicity": 40,
    "continued_support": 45,
    "award": 50,
    "annual_evaluation": 50,
    "review_passed": 60,
    "re_recognition": 70,
    "directory_exit": 80,
    "changed": 80,
    "revoked": 90,
}
ACTIVE_EVENT_TYPES = {
    "recognition",
    "review_passed",
    "re_recognition",
    "annual_evaluation",
}


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def policy_version_fallback(rule: Mapping[str, object]) -> dict[str, object]:
    rule_payload = dict(rule)
    return {
        "policy_version_id": f"lifecycle-policy-{digest(rule_payload)[:20]}",
        "version_group_id": str(rule.get("rule_id") or ""),
        "version_status": str(rule.get("current_rule_state") or "unknown"),
        "policy_status": "current",
        "detected_date": "",
        "source": str((rule.get("local_rule_sources") or [""])[0]),
        "latest_source": str((rule.get("local_rule_sources") or [""])[0]),
        "official_urls": list(rule.get("official_rule_urls", [])),
        "resolution": "lifecycle-rule-content-hash",
    }


def resolve_policy_versions(
    lifecycle_rules: Mapping[str, Mapping[str, object]],
    policy_version_database: Path | None,
) -> dict[str, dict[str, object]]:
    results = {
        project_name: policy_version_fallback(rule)
        for project_name, rule in lifecycle_rules.items()
    }
    if not policy_version_database or not policy_version_database.is_file():
        return results
    connection = sqlite3.connect(
        f"file:{policy_version_database}?mode=ro",
        uri=True,
    )
    connection.row_factory = sqlite3.Row
    for project_name, rule in lifecycle_rules.items():
        candidates: list[sqlite3.Row] = []
        for source in rule.get("local_rule_sources", []):
            source_text = str(source or "")
            if not source_text:
                continue
            candidates.extend(
                connection.execute(
                    """
                    SELECT source,title,version_group_id,version_status,policy_status,
                           detected_date,latest_source,confidence,
                           lifecycle_evidence_type,lifecycle_evidence_quote
                    FROM policy_versions
                    WHERE source=? OR source LIKE ?
                    ORDER BY policy_status='current' DESC,
                             version_status='latest' DESC,
                             detected_year DESC,id DESC
                    LIMIT 3
                    """,
                    (source_text, f"%/{source_text}"),
                ).fetchall()
            )
        if not candidates:
            continue
        row = candidates[0]
        results[project_name] = {
            "policy_version_id": (
                f"policy-version-{digest({'source': row['source'], 'group': row['version_group_id']})[:20]}"
            ),
            "version_group_id": str(row["version_group_id"] or ""),
            "version_status": str(row["version_status"] or ""),
            "policy_status": str(row["policy_status"] or ""),
            "detected_date": str(row["detected_date"] or ""),
            "source": str(row["source"] or ""),
            "latest_source": str(row["latest_source"] or ""),
            "title": str(row["title"] or ""),
            "confidence": str(row["confidence"] or ""),
            "lifecycle_evidence_type": str(
                row["lifecycle_evidence_type"] or ""
            ),
            "lifecycle_evidence_quote": str(
                row["lifecycle_evidence_quote"] or ""
            ),
            "official_urls": list(rule.get("official_rule_urls", [])),
            "resolution": "policy-version-index",
        }
    connection.close()
    return results


def coverage_trace_index(
    coverage_matrix: Mapping[str, object],
) -> dict[tuple[str, int | None, str, str], list[dict[str, object]]]:
    index: dict[
        tuple[str, int | None, str, str],
        list[dict[str, object]],
    ] = defaultdict(list)
    for row in coverage_matrix.get("rows", []):
        if not isinstance(row, Mapping):
            continue
        key = (
            str(row.get("project_name") or ""),
            (
                int(row["event_year"])
                if row.get("event_year") is not None
                else None
            ),
            str(row.get("batch") or ""),
            str(row.get("event_type") or ""),
        )
        index[key].append(dict(row))
    return index


def next_state(
    previous_state: str,
    event_type: str,
) -> tuple[str, str]:
    if event_type == "recognition_publicity":
        return (
            ("publicity_pending" if previous_state == "not_recorded" else previous_state),
            "拟认定或推荐公示不等同正式资格",
        )
    if event_type in {"recognition", "re_recognition"}:
        return "active", "正式认定或重新认定使资格生效"
    if event_type == "annual_evaluation":
        return "active", "年度评价入库仅在该年度生效"
    if event_type == "review_due":
        return "review_due", "进入到期复核范围，尚未形成复核结论"
    if event_type == "review_publicity":
        return "review_pending", "拟复核通过公示不等同正式复核结论"
    if event_type == "review_passed":
        return "active", "复核通过延续资格并重算有效期"
    if event_type == "revoked":
        return "revoked", "撤销、取消或复核未通过终止资格"
    if event_type == "changed":
        return previous_state, "主体变更只更新身份链，不自动改变资格状态"
    if event_type == "continued_support":
        return previous_state, "继续支持属于支持事件，不覆盖认定批次"
    if event_type == "award":
        return previous_state, "奖励事件不等同于新增认定，不覆盖历史资格状态"
    if event_type == "directory_exit":
        return "directory_exited", "目录退出仅更新产品目录状态，不删除历史认定事实"
    return previous_state, "未知事件类型不自动改变资格状态"


def replay_steps(
    events: Sequence[Mapping[str, object]],
    rule: Mapping[str, object],
) -> list[dict[str, object]]:
    state = "not_recorded"
    valid_through_year: int | None = None
    validity_years = (
        int(rule["validity_years"])
        if rule.get("validity_years") is not None
        else None
    )
    steps: list[dict[str, object]] = []
    ordered = sorted(
        events,
        key=lambda event: (
            int(event.get("event_year") or 0),
            EVENT_PRECEDENCE.get(str(event.get("event_type") or ""), 0),
            str(event.get("status") or ""),
        ),
    )
    for index, event in enumerate(ordered, start=1):
        event_type = str(event.get("event_type") or "")
        previous = state
        state, reason = next_state(previous, event_type)
        event_year = (
            int(event["event_year"])
            if event.get("event_year") is not None
            else None
        )
        if event_type in ACTIVE_EVENT_TYPES and event_year is not None:
            valid_through_year = (
                event_year + validity_years
                if validity_years is not None
                else None
            )
        if event_type == "revoked":
            valid_through_year = event_year
        steps.append(
            {
                "step": index,
                "event_year": event_year,
                "event_type": event_type,
                "event_status": str(event.get("status") or ""),
                "previous_state": previous,
                "next_state": state,
                "reason": reason,
                "valid_through_year": valid_through_year,
                "cohort_year": event.get("cohort_year"),
                "batch": str(event.get("batch") or ""),
                "event_scope": str(event.get("event_scope") or ""),
                "subject_type": str(event.get("subject_type") or "enterprise"),
                "subject_key": str(event.get("subject_key") or "enterprise"),
                "subject_name": str(event.get("subject_name") or ""),
                "product_name": str(event.get("product_name") or ""),
                "product_category": str(event.get("product_category") or ""),
                "recognition_level": str(event.get("recognition_level") or ""),
                "enterprise_name_at_event": str(
                    event.get("enterprise_name_at_event") or ""
                ),
                "recognition_region": "/".join(
                    str(event.get(field) or "")
                    for field in (
                        "recognition_province",
                        "recognition_city",
                        "recognition_county",
                    )
                    if str(event.get(field) or "")
                ),
                "source_title": str(event.get("source_title") or ""),
                "source_paths": list(event.get("source_paths", [])),
                "source_urls": list(event.get("source_urls", [])),
                "source_kinds": list(event.get("source_kinds", [])),
                "evidence_status": str(event.get("evidence_status") or ""),
                "evidence_hash": digest(
                    {
                        "title": event.get("source_title"),
                        "paths": event.get("source_paths", []),
                        "urls": event.get("source_urls", []),
                        "event": event_type,
                        "year": event_year,
                        "name": event.get("enterprise_name_at_event"),
                        "subject_key": event.get("subject_key"),
                        "product_name": event.get("product_name"),
                    }
                ),
            }
        )
    return steps


def state_as_of(
    steps: Sequence[Mapping[str, object]],
    as_of_year: int | None,
) -> dict[str, object]:
    selected = [
        step
        for step in steps
        if as_of_year is None
        or step.get("event_year") is None
        or int(step["event_year"]) <= as_of_year
    ]
    if not selected:
        return {
            "as_of_year": as_of_year,
            "state": "not_recorded",
            "valid_through_year": None,
            "last_step": None,
        }
    last = selected[-1]
    state = str(last.get("next_state") or "not_recorded")
    valid_through = last.get("valid_through_year")
    if (
        as_of_year is not None
        and valid_through is not None
        and as_of_year > int(valid_through)
        and state == "active"
    ):
        state = "expired_pending_review"
    return {
        "as_of_year": as_of_year,
        "state": state,
        "valid_through_year": valid_through,
        "last_step": int(last.get("step") or 0),
    }


def build_project_identity_twins(
    profiles: Sequence[Mapping[str, object]],
    events: Sequence[Mapping[str, object]],
    lifecycle_rules: Mapping[str, Mapping[str, object]],
    coverage_matrix: Mapping[str, object],
    policy_version_database: Path | None = None,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    profiles_by_id = {
        str(profile.get("identity_key") or ""): profile
        for profile in profiles
    }
    events_by_key: dict[
        tuple[str, str],
        list[Mapping[str, object]],
    ] = defaultdict(list)
    for event in events:
        events_by_key[
            (
                str(event.get("identity_key") or ""),
                str(event.get("project_name") or ""),
            )
        ].append(event)
    policy_versions = resolve_policy_versions(
        lifecycle_rules,
        policy_version_database,
    )
    coverage_index = coverage_trace_index(coverage_matrix)
    twins: list[dict[str, object]] = []
    all_steps: list[dict[str, object]] = []
    for (identity_key, project_name), project_events in sorted(events_by_key.items()):
        rule = dict(lifecycle_rules.get(project_name, {}))
        if not rule:
            continue
        profile = profiles_by_id.get(identity_key, {})
        steps = replay_steps(project_events, rule)
        event_years = [
            int(event["event_year"])
            for event in project_events
            if event.get("event_year") is not None
        ]
        as_of_year = max(event_years) if event_years else None
        current = state_as_of(steps, as_of_year)
        twin_id = f"twin-{digest({'identity': identity_key, 'project': project_name})[:24]}"
        coverage_evidence: dict[str, dict[str, object]] = {}
        for event in project_events:
            key = (
                project_name,
                (
                    int(event["event_year"])
                    if event.get("event_year") is not None
                    else None
                ),
                str(event.get("batch") or ""),
                str(event.get("event_type") or ""),
            )
            rows = coverage_index.get(key, [])
            if not rows:
                continue
            group_id = str(rows[0].get("coverage_group_id") or "")
            coverage_evidence[group_id] = {
                "coverage_group_id": group_id,
                "event_year": rows[0].get("event_year"),
                "batch": str(rows[0].get("batch") or ""),
                "event_type": str(rows[0].get("event_type") or ""),
                "complete": all(
                    str(row.get("coverage_state") or "") != "missing_source"
                    for row in rows
                ),
                "city_states": {
                    str(row.get("city") or ""): str(
                        row.get("coverage_state") or ""
                    )
                    for row in rows
                },
                "content_fingerprints": sorted(
                    {
                        str(row.get("content_fingerprint") or "")
                        for row in rows
                        if row.get("content_fingerprint")
                    }
                ),
            }
        identity_match = {
            "method": (
                "unified-social-credit-code"
                if profile.get("unified_social_credit_code")
                else "normalized-name-provisional"
            ),
            "verification_status": str(
                profile.get("verification_status") or ""
            ),
            "identity_key": identity_key,
            "unified_social_credit_code": str(
                profile.get("unified_social_credit_code") or ""
            ),
            "current_name": str(profile.get("current_name") or ""),
            "recognition_names": list(profile.get("recognition_names", [])),
            "identity_source": str(profile.get("identity_source") or ""),
            "verified_at": str(profile.get("verified_at") or ""),
        }
        twin = {
            "schema_version": 1,
            "twin_id": twin_id,
            "identity_key": identity_key,
            "project_name": project_name,
            "lifecycle_rule_id": str(rule.get("rule_id") or ""),
            "cycle_type": str(rule.get("cycle_type") or ""),
            "validity_years": rule.get("validity_years"),
            "identity_match": identity_match,
            "policy_version": policy_versions.get(
                project_name,
                policy_version_fallback(rule),
            ),
            "list_attachment_trace": [
                {
                    "event_year": event.get("event_year"),
                    "event_type": str(event.get("event_type") or ""),
                    "batch": str(event.get("batch") or ""),
                    "subject_type": str(event.get("subject_type") or "enterprise"),
                    "subject_key": str(event.get("subject_key") or "enterprise"),
                    "subject_name": str(event.get("subject_name") or ""),
                    "product_name": str(event.get("product_name") or ""),
                    "product_category": str(event.get("product_category") or ""),
                    "recognition_level": str(event.get("recognition_level") or ""),
                    "source_title": str(event.get("source_title") or ""),
                    "source_paths": list(event.get("source_paths", [])),
                    "source_urls": list(event.get("source_urls", [])),
                    "source_kinds": list(event.get("source_kinds", [])),
                }
                for event in sorted(
                    project_events,
                    key=lambda event: (
                        int(event.get("event_year") or 0),
                        EVENT_PRECEDENCE.get(
                            str(event.get("event_type") or ""),
                            0,
                        ),
                    ),
                )
            ],
            "coverage_trace": list(coverage_evidence.values()),
            "lifecycle_trace": steps,
            "current_replay": current,
            "replayable_years": sorted(set(event_years)),
            "trace_hash": digest(
                {
                    "identity_match": identity_match,
                    "policy_version": policy_versions.get(project_name, {}),
                    "coverage": coverage_evidence,
                    "steps": steps,
                }
            ),
        }
        twins.append(twin)
        all_steps.extend(
            {
                **step,
                "twin_id": twin_id,
                "identity_key": identity_key,
                "project_name": project_name,
            }
            for step in steps
        )
    return twins, all_steps


def replay_twin(twin: Mapping[str, object], as_of_year: int) -> dict[str, object]:
    return {
        "twin_id": str(twin.get("twin_id") or ""),
        "identity_key": str(twin.get("identity_key") or ""),
        "project_name": str(twin.get("project_name") or ""),
        "identity_match": dict(twin.get("identity_match", {})),
        "policy_version": dict(twin.get("policy_version", {})),
        "as_of": state_as_of(
            [
                step
                for step in twin.get("lifecycle_trace", [])
                if isinstance(step, Mapping)
            ],
            as_of_year,
        ),
        "events": [
            dict(step)
            for step in twin.get("lifecycle_trace", [])
            if isinstance(step, Mapping)
            and (
                step.get("event_year") is None
                or int(step["event_year"]) <= as_of_year
            )
        ],
        "coverage_trace": list(twin.get("coverage_trace", [])),
        "trace_hash": str(twin.get("trace_hash") or ""),
    }
