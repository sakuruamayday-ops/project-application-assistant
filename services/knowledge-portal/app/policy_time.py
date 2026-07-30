from __future__ import annotations

from datetime import date, datetime
from typing import Mapping, Sequence
from urllib.parse import urlparse


POLICY_TIME_TYPES = frozenset(
    {
        "stable-management",
        "annual-notice",
        "jurisdiction-detail",
        "consultation-draft",
    }
)
EVALUATION_MODES = frozenset(
    {
        "current-assessment",
        "current-year-preparation",
        "historical-fact",
        "forecast",
        "backtest-simulation",
    }
)
OUTPUT_LABELS = {
    "current-assessment": "查询日有效规则判断",
    "current-year-preparation": "当年申报前准备（征求意见稿）",
    "historical-fact": "历史事实回放",
    "forecast": "预测",
    "backtest-simulation": "回测模拟",
}
PROSPECTIVE_POLICY_STATUSES = frozenset({"draft", "active_candidate"})
PREPARATION_MODES = frozenset({"current-year-preparation", "forecast"})


def _is_sha256(value: object) -> bool:
    normalized = str(value or "").strip().lower()
    return len(normalized) == 64 and all(
        character in "0123456789abcdef" for character in normalized
    )


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
        application_phase = str(
            enriched.get("application_phase")
            or enriched.get("application_status")
            or ""
        ).strip()
        pre_application = application_phase in {
            "not-open",
            "not-started",
            "pre-application",
            "preparation",
            "尚未开放",
            "尚未开始",
        } or any(
            term in query
            for term in (
                "尚未开始申报",
                "还没开始申报",
                "尚未开放申报",
                "申报尚未开始",
                "申报还没开始",
                "申报未启动",
            )
        )
        current_year_question = (
            any(term in query for term in ("今年", "本年度", "当年"))
            or _year(enriched.get("year")) == date.today().year
        )
        if pre_application and current_year_question:
            enriched["evaluation_mode"] = "current-year-preparation"
        elif "回测" in query or (
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
        "prospective": "consultation-draft",
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
        "current-year-preparation": "current-year-preparation",
        "current-pre-application": "current-year-preparation",
        "pre-application": "current-year-preparation",
        "当年申报前准备": "current-year-preparation",
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
    if any(_is_sha256(value) for value in archive_hashes):
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
    elif time_type == "consultation-draft":
        verified_draft = bool(
            statuses & PROSPECTIVE_POLICY_STATUSES
        ) and source_level in {"official-online", "audited-official-archive"}
        explicit_replacement = (
            str(layer.get("replacement_signal") or "")
            in {"explicit", "explicit-replacement", "replacement-announced"}
            or bool(layer.get("replaces_rule_ids"))
            or bool(str(layer.get("replaces_policy_title") or "").strip())
        )
        if not verified_draft:
            allowed = False
            reason = (
                "前瞻规则层必须同时具备征求意见稿状态和"
                "政府官网原文或已审计原文归档"
            )
        elif not explicit_replacement:
            allowed = False
            reason = "征求意见稿未明确替代既有政策，不得切换为准备主基线"
        elif mode in PREPARATION_MODES:
            allowed = True
            reason = (
                "已核验且明确替代旧政策的征求意见稿，作为申报准备主基线；"
                "结果必须标明尚未正式生效"
            )
        else:
            allowed = False
            reason = (
                "征求意见稿仅用于预测和准备，不得替代查询日正式政策"
                "或冒充历史事实"
            )
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
        "source_scope_level": str(layer.get("source_scope_level") or ""),
        "source_scope_region": str(layer.get("source_scope_region") or ""),
        "route_status": str(layer.get("route_status") or ""),
        "target_project_id": str(layer.get("target_project_id") or ""),
        "target_project_name": str(layer.get("target_project_name") or ""),
        "formal_level": str(layer.get("formal_level") or ""),
        "route_reason": str(layer.get("route_reason") or ""),
        "policy_legal_status": (
            "draft" if time_type == "consultation-draft" else ""
        ),
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
    has_selected_consultation = any(
        audit.get("policy_time_type") == "consultation-draft"
        for audit in selected
    )
    historical_has_basis = bool(selected) and any(
        audit.get("policy_time_type") in {"annual-notice", "stable-management"}
        for audit in selected
    )
    status = "allowed"
    reason = ""
    if mode in PREPARATION_MODES and not has_selected_annual:
        if has_selected_consultation:
            status = (
                "preapplication-draft-baseline"
                if mode == "current-year-preparation"
                else "forecast-draft-baseline"
            )
            reason = (
                "采用已核验且明确替代旧政策的征求意见稿形成准备基线；"
                "法律状态仍为征求意见稿，不生成正式资格结论或旧通知截止日期"
            )
        else:
            status = (
                "preapplication-baseline-only"
                if mode == "current-year-preparation"
                else "forecast-baseline-only"
            )
            reason = (
                "未取得可切换的已核验替代草案，仅以查询日最新有效管理规则"
                "形成准备方向，不预测旧通知截止日期"
            )
    elif requires_annual and not has_selected_annual:
        status = "blocked"
        reason = "当年度通知尚未核验，不沿用旧年度截止日期"
    elif mode == "historical-fact" and not historical_has_basis:
        status = "blocked"
        reason = "当年有效规则暂缺，只保留名单身份和生命周期，不判断当年是否符合"
    elif mode == "backtest-simulation":
        status = "simulation-only"
        reason = "结果属于回测模拟，不得写成历史事实"
    return {
        "evaluation_mode": mode,
        "output_label": OUTPUT_LABELS[mode],
        "status": status,
        "formal_conclusion_allowed": status == "allowed",
        "baseline_policy_status": (
            "draft" if has_selected_consultation else "current"
        ),
        "reason": reason,
        "selected_layer_ids": [
            str(audit.get("layer_id") or "") for audit in selected
        ],
        "blocked_layers": [dict(audit) for audit in blocked],
    }
