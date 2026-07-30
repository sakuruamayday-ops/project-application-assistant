from __future__ import annotations

from datetime import date, datetime
from typing import Mapping, Sequence
from urllib.parse import urlparse


POLICY_TIME_TYPES = frozenset(
    {
        "stable-management",
        "annual-notice",
        "jurisdiction-detail",
    }
)
EVALUATION_MODES = frozenset(
    {
        "current-assessment",
        "historical-fact",
        "forecast",
        "backtest-simulation",
    }
)
OUTPUT_LABELS = {
    "current-assessment": "查询日有效规则判断",
    "historical-fact": "历史事实回放",
    "forecast": "预测",
    "backtest-simulation": "回测模拟",
}


def enrich_policy_time_context(
    query: str,
    project_context: Mapping[str, object],
) -> dict[str, object]:
    """Infer time semantics from the user query while preserving explicit input."""
    enriched = dict(project_context)
    if not (
        enriched.get("evaluation_mode")
        or enriched.get("policy_evaluation_mode")
    ):
        if "回测" in query or (
            "最新规则" in query
            and any(term in query for term in ("历史", "过去", "当年"))
        ):
            enriched["evaluation_mode"] = "backtest-simulation"
        elif any(
            term in query
            for term in ("预测", "下一年度", "下一年", "明年", "准备方向")
        ):
            enriched["evaluation_mode"] = "forecast"
        elif any(
            term in query
            for term in (
                "历史回放",
                "当年为什么符合",
                "某年为什么符合",
                "当年有效规则",
                "历史事实",
            )
        ):
            enriched["evaluation_mode"] = "historical-fact"
    if "annual_notice_required" not in enriched:
        enriched["annual_notice_required"] = any(
            term in query
            for term in (
                "年度通知",
                "申报通知",
                "截止",
                "申报时间",
                "申报期",
                "开放时间",
                "何时报",
            )
        )
    return enriched


def policy_time_type_for_layer(layer_type: str) -> str:
    return {
        "stable": "stable-management",
        "annual": "annual-notice",
        "jurisdiction": "jurisdiction-detail",
    }.get(layer_type, "")


def normalize_evaluation_mode(project_context: Mapping[str, object]) -> str:
    explicit = str(
        project_context.get("evaluation_mode")
        or project_context.get("policy_evaluation_mode")
        or ""
    ).strip()
    aliases = {
        "current": "current-assessment",
        "current-assessment": "current-assessment",
        "historical": "historical-fact",
        "historical-fact": "historical-fact",
        "replay": "historical-fact",
        "forecast": "forecast",
        "prediction": "forecast",
        "backtest": "backtest-simulation",
        "backtest-simulation": "backtest-simulation",
        "回测模拟": "backtest-simulation",
        "预测": "forecast",
        "历史事实": "historical-fact",
    }
    return aliases.get(explicit, "current-assessment")


def _year(value: object) -> int | None:
    text = str(value or "").strip()
    if len(text) >= 4 and text[:4].isdigit():
        return int(text[:4])
    return int(value) if isinstance(value, int) else None


def _date(value: object) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        year = _year(text)
        return date(year, 1, 1) if year else None


def _official_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == "gov.cn" or host.endswith(".gov.cn")


def source_evidence_level(
    layer: Mapping[str, object],
    rules: Sequence[Mapping[str, object]],
) -> str:
    urls = [
        str(layer.get("source_url") or ""),
        *[str(rule.get("source_url") or "") for rule in rules],
    ]
    if any(_official_host(url) for url in urls if url):
        return "official-online"
    archive_hashes = [
        str(layer.get("source_archive_sha256") or ""),
        *[str(rule.get("source_archive_sha256") or "") for rule in rules],
    ]
    if any(len(value) == 64 for value in archive_hashes):
        return "audited-official-archive"
    return "unverified-source"


def _effective_window(layer: Mapping[str, object]) -> tuple[date | None, date | None]:
    applicability = layer.get("applicability", {})
    if not isinstance(applicability, Mapping):
        applicability = {}
    return (
        _date(layer.get("effective_from") or applicability.get("effective_from")),
        _date(layer.get("effective_to") or applicability.get("effective_to")),
    )


def _covers_year(layer: Mapping[str, object], target_year: int | None) -> bool:
    if target_year is None:
        return False
    applicability = layer.get("applicability", {})
    if not isinstance(applicability, Mapping):
        applicability = {}
    years = {
        _year(value)
        for value in applicability.get("years", [])
        if _year(value) is not None
    }
    if years:
        return target_year in years
    effective_from, effective_to = _effective_window(layer)
    start = effective_from.year if effective_from else None
    end = effective_to.year if effective_to else None
    return bool(
        start is not None
        and start <= target_year
        and (end is None or target_year <= end)
    )


def assess_policy_layer_time(
    layer: Mapping[str, object],
    project_context: Mapping[str, object],
    *,
    today: date | None = None,
) -> dict[str, object]:
    current_date = today or date.today()
    mode = normalize_evaluation_mode(project_context)
    layer_type = str(layer.get("layer_type") or "")
    time_type = str(
        layer.get("policy_time_type") or policy_time_type_for_layer(layer_type)
    )
    target_year = _year(
        project_context.get("year")
        or project_context.get("policy_year")
        or project_context.get("application_year")
    )
    rules = [
        rule
        for rule in layer.get("rules", [])
        if isinstance(rule, Mapping)
    ]
    statuses = {
        str(rule.get("policy_status") or "")
        for rule in rules
        if str(rule.get("policy_status") or "")
    }
    source_level = source_evidence_level(layer, rules)
    allowed = True
    reason = ""

    if time_type not in POLICY_TIME_TYPES:
        allowed = False
        reason = "规则层缺少可识别的政策时间类型"
    elif (
        time_type == "annual-notice"
        and source_level == "unverified-source"
        and any(str(rule.get("review_status") or "") == "confirmed" for rule in rules)
    ):
        allowed = False
        reason = "年度通知缺少政府官网原文或已审计官方附件"
    elif mode == "historical-fact":
        allowed = _covers_year(layer, target_year)
        reason = (
            "规则层覆盖目标历史年度"
            if allowed
            else "规则层没有覆盖目标历史年度，禁止以当前规则替代历史事实"
        )
    elif mode == "backtest-simulation":
        allowed = "current" in statuses or _covers_year(layer, target_year)
        reason = (
            "允许按当前规则回测历史数据，输出必须标为回测模拟"
            if allowed
            else "规则层既非当前有效，也不覆盖目标年度"
        )
    elif mode == "forecast":
        if time_type == "annual-notice":
            allowed = bool(
                target_year
                and _covers_year(layer, target_year)
                and ("current" in statuses or not statuses)
            )
            reason = (
                "已取得目标年度正式通知"
                if allowed
                else "目标年度正式通知尚未取得，不能沿用旧截止日期"
            )
        else:
            allowed = "current" in statuses or not statuses
            reason = (
                "以查询日最新有效稳定规则形成预测准备方向"
                if allowed
                else "非当前有效规则不得用于预测"
            )
    else:
        if time_type == "annual-notice":
            requested_year = target_year or current_date.year
            allowed = _covers_year(layer, requested_year) and (
                bool(statuses & {"current", "historical_reference"})
                or not statuses
            )
            reason = (
                "已精确匹配请求年度通知"
                if allowed
                else "年度通知与查询年度不一致或不是当前有效状态"
            )
        else:
            allowed = "current" in statuses or not statuses
            reason = (
                "查询日有效规则"
                if allowed
                else "历史或失效规则不得形成当前结论"
            )

    return {
        "layer_id": str(layer.get("layer_id") or ""),
        "layer_type": layer_type,
        "policy_time_type": time_type,
        "evaluation_mode": mode,
        "output_label": OUTPUT_LABELS[mode],
        "target_year": target_year,
        "source_evidence_level": source_level,
        "allowed": allowed,
        "reason": reason,
    }


def summarize_policy_time_selection(
    audits: Sequence[Mapping[str, object]],
    project_context: Mapping[str, object],
) -> dict[str, object]:
    mode = normalize_evaluation_mode(project_context)
    selected = [audit for audit in audits if audit.get("allowed")]
    blocked = [audit for audit in audits if not audit.get("allowed")]
    requires_annual = bool(project_context.get("annual_notice_required"))
    has_selected_annual = any(
        audit.get("policy_time_type") == "annual-notice"
        for audit in selected
    )
    historical_has_basis = bool(selected) and any(
        audit.get("policy_time_type") in {"annual-notice", "stable-management"}
        for audit in selected
    )
    status = "allowed"
    reason = ""
    if requires_annual and not has_selected_annual:
        status = "blocked"
        reason = "当年度通知尚未核验，不沿用旧年度截止日期"
    elif mode == "historical-fact" and not historical_has_basis:
        status = "blocked"
        reason = "当年有效规则暂缺，只保留名单身份和生命周期，不判断当年是否符合"
    elif mode == "forecast" and not has_selected_annual:
        status = "forecast-baseline-only"
        reason = "仅以查询日最新有效管理规则形成准备方向，不预测旧通知截止日期"
    elif mode == "backtest-simulation":
        status = "simulation-only"
        reason = "结果属于回测模拟，不得写成历史事实"
    return {
        "evaluation_mode": mode,
        "output_label": OUTPUT_LABELS[mode],
        "status": status,
        "formal_conclusion_allowed": status == "allowed",
        "reason": reason,
        "selected_layer_ids": [
            str(audit.get("layer_id") or "") for audit in selected
        ],
        "blocked_layers": [dict(audit) for audit in blocked],
    }
