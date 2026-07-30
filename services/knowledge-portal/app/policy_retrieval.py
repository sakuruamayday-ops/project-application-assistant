from __future__ import annotations

from datetime import date
from typing import Mapping, Sequence
from urllib.parse import urlparse


ANNUAL_FACT_CLAIMS = frozenset(
    {
        "application_batch",
        "application_deadline",
        "application_system",
        "application_materials",
        "review_schedule",
        "eligible_cohort",
    }
)
STABLE_RULE_CLAIMS = frozenset(
    {
        "eligibility_threshold",
        "evaluation_method",
        "validity_period",
        "preparation_direction",
    }
)
SOURCE_ROLE_PRIORITY = {
    "issuing-authority-original": 0,
    "subordinate-official-citation": 1,
    "management-basis": 2,
}
RETRIEVAL_CHANNEL_PRIORITY = {
    "direct-url": 0,
    "issuing-authority-listing": 1,
    "department-site-search": 2,
    "province-wide-search": 3,
    "subordinate-official-search": 4,
    "latest-notice-citation": 5,
}


def _official_url(url: object) -> bool:
    host = (urlparse(str(url or "")).hostname or "").lower()
    return host == "gov.cn" or host.endswith(".gov.cn")


def _year(value: object) -> int:
    try:
        return int(str(value or "")[:4])
    except ValueError:
        return 0


def _normalized_candidate(
    candidate: Mapping[str, object],
) -> dict[str, object]:
    normalized = dict(candidate)
    role = str(normalized.get("source_role") or "").strip()
    channel = str(normalized.get("retrieval_channel") or "").strip()
    normalized["source_role"] = role
    normalized["retrieval_channel"] = channel
    normalized["official"] = bool(
        normalized.get("official")
        or _official_url(normalized.get("source_url"))
    )
    normalized["year"] = _year(
        normalized.get("year") or normalized.get("issued_at")
    )
    normalized["source_role_priority"] = SOURCE_ROLE_PRIORITY.get(role, 99)
    normalized["retrieval_channel_priority"] = RETRIEVAL_CHANNEL_PRIORITY.get(
        channel, 99
    )
    return normalized


def select_policy_evidence(
    candidates: Sequence[Mapping[str, object]],
    *,
    target_year: int,
    requested_claims: Sequence[str] = (),
    as_of: date | None = None,
) -> dict[str, object]:
    """Select official policy evidence without turning fallback into false facts.

    Retrieval channel and evidentiary role are intentionally separate. A direct
    department page remains first-party evidence even when a search engine has
    not indexed it. A subordinate government citation can recover quoted annual
    facts. A management measure can recover stable thresholds only.
    """

    requested = {
        str(claim).strip() for claim in requested_claims if str(claim).strip()
    }
    normalized = [
        _normalized_candidate(candidate)
        for candidate in candidates
        if isinstance(candidate, Mapping)
    ]
    eligible = [
        candidate
        for candidate in normalized
        if candidate["official"]
        and str(candidate.get("verification_status") or "verified")
        in {"verified", "official-page-verified", "official-citation-verified"}
    ]
    annual = [
        candidate
        for candidate in eligible
        if candidate["source_role"]
        in {"issuing-authority-original", "subordinate-official-citation"}
        and candidate["year"] == target_year
    ]
    stable = [
        candidate
        for candidate in eligible
        if candidate["source_role"] == "management-basis"
        and str(candidate.get("policy_status") or "current") == "current"
    ]
    annual.sort(
        key=lambda candidate: (
            candidate["source_role_priority"],
            candidate["retrieval_channel_priority"],
            str(candidate.get("source_url") or ""),
        )
    )
    stable.sort(
        key=lambda candidate: (
            -candidate["year"],
            candidate["retrieval_channel_priority"],
            str(candidate.get("source_url") or ""),
        )
    )

    selected_annual = annual[0] if annual else None
    selected_stable = stable[0] if stable else None
    selected = [
        dict(candidate)
        for candidate in (selected_annual, selected_stable)
        if candidate is not None
    ]
    allowed_claims = set(STABLE_RULE_CLAIMS if selected_stable else ())
    if selected_annual:
        allowed_claims.update(ANNUAL_FACT_CLAIMS)
        annual_scope = selected_annual.get("quoted_claims")
        if isinstance(annual_scope, list):
            quoted_claims = {str(item) for item in annual_scope}
            if selected_annual["source_role"] == "subordinate-official-citation":
                allowed_claims.intersection_update(
                    {*STABLE_RULE_CLAIMS, *quoted_claims}
                )
            else:
                allowed_claims.update(quoted_claims)
    prohibited_claims = sorted(requested - allowed_claims)

    if selected_annual:
        status = (
            "official-original"
            if selected_annual["source_role"] == "issuing-authority-original"
            else "official-citation-fallback"
        )
        reason = (
            "已命中发文机关正式原文"
            if status == "official-original"
            else "发文机关原文检索未命中，采用下级政府官网对上级通知的明确引用"
        )
    elif selected_stable:
        status = "management-baseline-only"
        reason = (
            "当年度通知仍未命中，仅采用当前有效管理办法形成稳定门槛和准备方向；"
            "不得生成当年度批次、截止时间、系统入口或年度材料结论"
        )
    else:
        status = "not-found"
        reason = "当前检索层未取得可核验官方原文、官方引用或现行管理依据"

    return {
        "target_year": target_year,
        "as_of": (as_of or date.today()).isoformat(),
        "status": status,
        "reason": reason,
        "selected_documents": selected,
        "allowed_claims": sorted(allowed_claims),
        "prohibited_claims": prohibited_claims,
        "formal_annual_conclusion_allowed": bool(
            selected_annual and not (requested & ANNUAL_FACT_CLAIMS - allowed_claims)
        ),
        "retrieval_trace": [
            {
                "source_url": candidate.get("source_url"),
                "source_role": candidate["source_role"],
                "retrieval_channel": candidate["retrieval_channel"],
                "official": candidate["official"],
                "year": candidate["year"],
                "selected": candidate in (selected_annual, selected_stable),
            }
            for candidate in normalized
        ],
    }
