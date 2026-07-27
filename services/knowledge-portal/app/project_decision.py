from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Mapping, Sequence


POLICY_INTENT_TERMS = (
    "条件",
    "要求",
    "标准",
    "门槛",
    "办法",
    "政策",
    "申报",
    "认定",
    "复核",
    "通知",
    "公示",
    "名单",
    "截止",
    "材料",
    "流程",
)

SMALL_GIANT_RECOGNITION_BATCH_BY_YEAR = {
    2019: "第一批",
    2020: "第二批",
    2021: "第三批",
    2022: "第四批",
    2023: "第五批",
    2024: "第六批",
    2025: "第七批",
    2026: "第八批",
}

BLOCKED_POLICY_VALIDITY = frozenset(
    {"historical_reference", "superseded", "invalid"}
)
REVIEW_POLICY_VALIDITY = frozenset({"draft", "trial", "active_candidate"})
SUPPORTING_EVIDENCE_STATES = frozenset({"verified", "computed"})
EVIDENCE_STATES = frozenset(
    {
        "verified",
        "computed",
        "claimed",
        "missing",
        "conflicting",
        "not-applicable",
    }
)
RULE_TYPES = frozenset(
    {"exclusion", "hard-threshold", "competitive", "submission"}
)
GATE_STATES = frozenset(
    {"passed", "failed", "pending", "unknown", "not-applicable"}
)
RULE_LAYER_TYPES = frozenset({"stable", "annual", "jurisdiction"})

DEADLINE_DATE_PATTERN = re.compile(
    r"(?:(?P<year>20\d{2})年)?"
    r"(?P<month>\d{1,2})月(?P<day>\d{1,2})日"
    r"(?:\s*(?P<meridiem>上午|下午|中午)?\s*"
    r"(?P<hour>\d{1,2})(?:[:：时](?P<minute>\d{1,2}))?(?:分)?)?"
)
DEADLINE_CONTEXT_PATTERN = re.compile(
    r"(?:申报|申请|提交|填报|受理|报名|材料|系统|网上|企业)?"
    r"(?:截止|截至|截止时间|申报期限|受理期限|报名期限)"
)


def unique_strings(values: Sequence[object]) -> list[str]:
    return list(
        dict.fromkeys(str(value).strip() for value in values if str(value).strip())
    )


def normalize_search_text(value: object) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", str(value or ""))


def normalize_project_query(query: str) -> str:
    normalized = query.strip().replace("高企", "高新技术企业")
    if "高新技术企业" not in normalized and "高新" in normalized:
        normalized = normalized.replace("高新", "高新技术企业")
    return normalized


def explicit_project_regions(query: str) -> list[str]:
    normalized_query = re.sub(r"(?<!\d)20\d{2}(?:年|年度)?", " ", query)
    return list(
        dict.fromkeys(
            region
            for region in re.findall(
                r"[\u4e00-\u9fff]{2,8}(?:省|自治区|市|区|县)",
                normalized_query,
            )
            if not region.startswith(("重点", "省级", "市级", "区级", "国家"))
        )
    )


def matched_project_retrieval_rule(
    query: str,
    rules: Sequence[Mapping[str, object]],
) -> Mapping[str, object] | None:
    matches: list[tuple[int, Mapping[str, object]]] = []
    normalized_query = normalize_search_text(query)
    for rule in rules:
        excluded_terms = [
            normalize_search_text(term)
            for term in rule.get("excluded_title_terms", [])
            if str(term).strip()
        ]
        if any(term and term in normalized_query for term in excluded_terms):
            continue
        for alias in rule.get("aliases", []):
            normalized_alias = str(alias).strip()
            if normalized_alias and normalized_alias in query:
                matches.append((len(normalized_alias), rule))
    return max(matches, key=lambda item: item[0])[1] if matches else None


def selected_project_targets(
    query: str,
    rule: Mapping[str, object],
) -> list[str]:
    targets = unique_strings(rule.get("targets", []))
    selectors = rule.get("selectors", {})
    if isinstance(selectors, Mapping):
        for selector, target in sorted(
            selectors.items(),
            key=lambda item: len(str(item[0])),
            reverse=True,
        ):
            if str(selector) in query and str(target) in targets:
                return [str(target)]
    if str(rule.get("id") or "") == "green-factory":
        if "国家" in query:
            return ["国家绿色工厂"]
        if "浙江省" in query or "省级" in query:
            return ["浙江省绿色低碳工厂"]
        if re.search(r"[\u4e00-\u9fff]{2,8}(?:区|县)", query) or "区级" in query:
            return ["区级绿色工厂"]
        if re.search(r"[\u4e00-\u9fff]{2,8}市", query) or "市级" in query:
            return ["市级绿色工厂"]
    return targets


def project_region_prompt(
    query: str,
    rule: Mapping[str, object],
    targets: Sequence[str],
) -> str | None:
    regions = explicit_project_regions(query)
    required_level = str(rule.get("required_region_level") or "")
    if required_level == "city" and not any(region.endswith("市") for region in regions):
        return str(rule.get("region_prompt") or "请先说明企业所在城市。")
    if required_level == "district" and not any(
        region.endswith(("区", "县")) for region in regions
    ):
        return str(rule.get("region_prompt") or "请先说明企业所在区县。")
    region_required_targets = set(unique_strings(rule.get("region_required_targets", [])))
    if region_required_targets.intersection(targets):
        needs_district = any(target.startswith("区级") for target in targets)
        suffixes = ("区", "县") if needs_district else ("市",)
        if not any(region.endswith(suffixes) for region in regions):
            return str(rule.get("region_prompt") or "请先说明企业所在地区。")
    return None


def project_selection_prompt(
    query: str,
    rules: Sequence[Mapping[str, object]],
) -> str | None:
    rule = matched_project_retrieval_rule(query, rules)
    if not rule:
        return None
    targets = selected_project_targets(query, rule)
    region_prompt = project_region_prompt(query, rule, targets)
    if region_prompt:
        return region_prompt
    if not bool(rule.get("selection_required")) or len(targets) == 1:
        return None
    all_targets = unique_strings(rule.get("targets", []))
    return str(
        rule.get("selection_prompt") or f"请选择具体项目：{'、'.join(all_targets)}。"
    )


def requires_current_policy_sources(query: str) -> bool:
    project_terms = (
        "专精特新",
        "小巨人",
        "梯度培育",
        "研发中心",
        "企业研究院",
        "高新技术企业",
        "高企",
        "高新",
    )
    return any(term in query for term in project_terms) and any(
        term in query for term in POLICY_INTENT_TERMS
    )


def requires_current_sme_policy_sources(query: str) -> bool:
    project_terms = (
        "优质中小企业梯度培育",
        "专精特新",
        "重点专精特新",
        "小巨人",
        "重点小巨人",
    )
    return requires_current_policy_sources(query) and any(
        term in query for term in project_terms
    )


def small_giant_recognition_batch(query: str) -> str:
    if "小巨人" not in query or any(
        term in query for term in ("复核", "重点小巨人", "重点专精特新")
    ):
        return ""
    explicit = re.search(r"第[一二三四五六七八九十0-9]+批", query)
    if explicit:
        return explicit.group(0)
    match = re.search(r"(?<!\d)(20\d{2})(?:年|年度)?", query)
    if not match:
        return ""
    return SMALL_GIANT_RECOGNITION_BATCH_BY_YEAR.get(int(match.group(1)), "")


def base_knowledge_search_query(query: str) -> str:
    normalized = normalize_project_query(query)
    if "公司法" in normalized:
        legal_terms = [
            term
            for term in (
                "公司法",
                "注册资本",
                "股东出资",
                "股权转让",
                "董事",
                "清算",
                "注销",
            )
            if term in normalized
        ]
        return " ".join(legal_terms[:3]) or "公司法"
    if not requires_current_policy_sources(normalized):
        return normalized
    terms: list[str] = []
    for term in (
        "优质中小企业梯度培育",
        "重点专精特新",
        "重点小巨人",
        "专精特新",
        "小巨人",
        "杭州市",
        "宁波市",
        "金华市",
        "绍兴市",
        "浙江省",
        "研发中心",
        "企业研究院",
        "高新技术企业",
    ):
        if term in normalized and term not in terms:
            terms.append(term)
    return " ".join(terms) or normalized


def project_query_variants(
    query: str,
    *,
    rules: Sequence[Mapping[str, object]],
    project_records: Sequence[Mapping[str, object]],
    configured_aliases: Mapping[str, Sequence[str]],
) -> list[str]:
    normalized = normalize_project_query(query)
    region_terms = explicit_project_regions(normalized)

    def with_regions(project_name: str) -> str:
        prefixes = [region for region in region_terms if region not in project_name]
        return " ".join((*prefixes, project_name))

    retrieval_rule = matched_project_retrieval_rule(query, rules)
    if retrieval_rule:
        targets = selected_project_targets(query, retrieval_rule)
        if targets:
            return list(dict.fromkeys(with_regions(name) for name in targets))

    formal_matches: list[str] = []
    indexed_alias_matches: list[str] = []
    for record in project_records:
        canonical_name = str(record.get("canonical_project_name") or "").strip()
        if canonical_name and canonical_name in normalized:
            formal_matches.append(canonical_name)
            continue
        for alias in record.get("aliases", []):
            normalized_alias = str(alias).strip()
            if normalized_alias and normalized_alias in normalized:
                indexed_alias_matches.append(canonical_name)
                break
    if formal_matches:
        return list(dict.fromkeys(with_regions(name) for name in formal_matches))
    if indexed_alias_matches:
        return list(dict.fromkeys(with_regions(name) for name in indexed_alias_matches))

    matched_aliases = [alias for alias in configured_aliases if alias in normalized]
    if matched_aliases:
        longest = max(len(alias) for alias in matched_aliases)
        variants: list[str] = []
        for alias in matched_aliases:
            if len(alias) == longest:
                variants.extend(str(value) for value in configured_aliases[alias])
        return list(dict.fromkeys(with_regions(name) for name in variants))

    base_query = base_knowledge_search_query(normalized)
    if base_query != normalized:
        return [base_query]
    reduced = normalized
    for term in sorted(POLICY_INTENT_TERMS, key=len, reverse=True):
        reduced = reduced.replace(term, " ")
    reduced = re.sub(
        r"(?:帮我|请问|查询|检索|一下|有哪些|是什么|怎么报|如何报|怎么申请|如何申请)",
        " ",
        reduced,
    )
    reduced = re.sub(r"[的，。！？、：:；;（）()]+", " ", reduced)
    reduced = re.sub(r"\s+", " ", reduced).strip()
    return [reduced or normalized]


def project_query_is_resolved(
    query: str,
    *,
    rules: Sequence[Mapping[str, object]],
    project_records: Sequence[Mapping[str, object]],
    configured_aliases: Mapping[str, Sequence[str]],
) -> bool:
    if matched_project_retrieval_rule(query, rules):
        return True
    normalized = normalize_project_query(query)
    if "高新技术企业" in normalized and not any(
        term in normalized for term in ("研究开发中心", "研究院", "产业园", "产品")
    ):
        return True
    for record in project_records:
        canonical_name = str(record.get("canonical_project_name") or "").strip()
        if canonical_name and canonical_name in normalized:
            return True
        if any(
            str(alias).strip() and str(alias).strip() in normalized
            for alias in record.get("aliases", [])
        ):
            return True
    return any(alias in normalized for alias in configured_aliases)


def resolved_canonical_projects(
    query: str,
    *,
    variants: Sequence[str],
    project_records: Sequence[Mapping[str, object]],
) -> list[str]:
    normalized_variants = {
        normalize_search_text(term)
        for value in variants
        for term in (value, *re.split(r"\s+", value.strip()))
        if len(normalize_search_text(term)) >= 4
    }
    matches: list[str] = []
    for record in project_records:
        canonical = str(record.get("canonical_project_name") or "").strip()
        names = [canonical, *(str(alias).strip() for alias in record.get("aliases", []))]
        normalized_names = {normalize_search_text(name) for name in names if name}
        if any(
            variant == name or variant in name or name in variant
            for variant in normalized_variants
            for name in normalized_names
        ):
            matches.append(canonical)
    return list(dict.fromkeys(matches))


def build_project_decision(
    query: str,
    *,
    rules: Sequence[Mapping[str, object]],
    project_records: Sequence[Mapping[str, object]],
    configured_aliases: Mapping[str, Sequence[str]],
) -> dict[str, object]:
    normalized_query = query.strip()
    base_variants = project_query_variants(
        normalized_query,
        rules=rules,
        project_records=project_records,
        configured_aliases=configured_aliases,
    )
    clarification = project_selection_prompt(normalized_query, rules)
    year_match = re.search(r"(?<!\d)(20\d{2})(?:年|年度)?", normalized_query)
    requested_year = int(year_match.group(1)) if year_match else None
    requested_batch = small_giant_recognition_batch(normalized_query)
    retrieval_rule = matched_project_retrieval_rule(normalized_query, rules)
    if retrieval_rule:
        targets = selected_project_targets(normalized_query, retrieval_rule)
    else:
        targets = resolved_canonical_projects(
            normalized_query,
            variants=base_variants,
            project_records=project_records,
        )
    resolved = project_query_is_resolved(
        normalized_query,
        rules=rules,
        project_records=project_records,
        configured_aliases=configured_aliases,
    )
    if not targets and resolved:
        targets = list(base_variants)

    regions = explicit_project_regions(normalized_query)
    list_intent = any(
        term in normalized_query
        for term in ("名单", "公示", "认定企业", "入选企业", "通过企业", "同行")
    )
    condition_intent = any(
        term in normalized_query
        for term in (
            "条件",
            "要求",
            "标准",
            "门槛",
            "办法",
            "材料",
            "流程",
            "怎么报",
            "如何报",
        )
    )
    current_intent = any(
        term in normalized_query
        for term in ("最新", "当前", "通知", "截止", "开放", "申报期", "正在申报")
    )
    planning_intent = any(
        term in normalized_query
        for term in (
            "成长路径",
            "项目规划",
            "申报规划",
            "未来规划",
            "五年规划",
            "可报项目",
            "能报什么",
        )
    )
    stages: list[str] = []
    if condition_intent:
        stages.extend(("申报通知", "管理办法"))
    if list_intent:
        stages.extend(("认定名单", "公示名单"))
    if current_intent or planning_intent:
        stages.append("申报通知")

    variants: list[str] = []
    for base_variant in base_variants:
        variants.append(base_variant)
        if requested_year is not None:
            variants.append(f"{base_variant} {requested_year}")
        if requested_batch:
            variants.append(f"{base_variant} {requested_batch}")
        for stage in stages:
            variants.append(f"{base_variant} {stage}")
            if requested_year is not None:
                variants.append(f"{base_variant} {requested_year} {stage}")
            if requested_batch:
                variants.append(f"{base_variant} {requested_batch} {stage}")
    if requested_batch and "小巨人" in normalized_query:
        variants.extend(
            (
                f"{requested_batch} 专精特新 小巨人",
                f"{requested_batch} 专精特新 小巨人 申报通知",
                f"{requested_batch} 专精特新 小巨人 公示名单",
                f"{requested_batch} 专精特新 小巨人 认定名单",
            )
        )

    current_policy_only = requested_year is None and not requested_batch and (
        requires_current_policy_sources(normalized_query)
        or (
            resolved
            and any(term in normalized_query for term in POLICY_INTENT_TERMS)
        )
    )
    current_sme_policy_only = (
        requested_year is None
        and not requested_batch
        and requires_current_sme_policy_sources(normalized_query)
    )
    rule_id = str(retrieval_rule.get("id") or "") if retrieval_rule else ""
    matched_aliases = (
        [
            str(alias)
            for alias in retrieval_rule.get("aliases", [])
            if str(alias) in normalized_query
        ]
        if retrieval_rule
        else []
    )
    matched_alias = max(matched_aliases, key=len) if matched_aliases else ""
    return {
        "schema_version": 1,
        "query": normalized_query,
        "normalized_query": normalize_project_query(normalized_query),
        "rule_id": rule_id,
        "matched_alias": matched_alias,
        "resolved": resolved,
        "clarification": clarification,
        "targets": unique_strings(targets),
        "regions": regions,
        "year": requested_year,
        "batch": requested_batch,
        "list_intent": list_intent,
        "condition_intent": condition_intent,
        "current_intent": current_intent,
        "planning_intent": planning_intent,
        "stages": list(dict.fromkeys(stages)),
        "variants": list(
            dict.fromkeys(variant.strip() for variant in variants if variant.strip())
        )[:30],
        "retrieval_policy": {
            "current_policy_only": current_policy_only,
            "current_sme_policy_only": current_sme_policy_only,
            "excluded_validity_statuses": (
                sorted(BLOCKED_POLICY_VALIDITY) if current_policy_only else []
            ),
            "minimum_sme_policy_year": 2026 if current_sme_policy_only else None,
            "canonical_documents_only": True,
        },
        "evidence_policy": {
            "block_historical_or_invalid": True,
            "draft_requires_review": True,
            "unconfirmed_current_policy_requires_review": True,
        },
        "deadline_policy": {
            "enabled": resolved or planning_intent,
            "prefer_enterprise_deadline": True,
            "administrative_deadline_is_secondary": True,
        },
    }


def evaluate_policy_evidence(
    metadata: Mapping[str, object],
) -> dict[str, object]:
    def value(key: str, default: object = "") -> object:
        getter = getattr(metadata, "get", None)
        if callable(getter):
            return getter(key, default)
        try:
            return metadata[key]
        except (IndexError, KeyError):
            return default

    validity = str(value("validity_status", "active_candidate") or "active_candidate")
    source = str(value("source") or "")
    replacement_url = str(value("replacement_url") or "")
    content = str(value("content") or "")
    official_source = bool(value("official_source_detected", False)) or "gov.cn" in (
        f"{source} {replacement_url} {content}".lower()
    )
    confidence = str(value("confidence") or "").lower()
    review_status = str(value("review_status") or "").lower()
    reasons: list[str] = []
    if validity in BLOCKED_POLICY_VALIDITY:
        reasons.append("文件已识别为历史、被替代或失效状态")
        return {
            "status": "blocked",
            "usable_for_current_conclusion": False,
            "official_source": official_source,
            "reasons": reasons,
        }
    if validity == "draft":
        reasons.append("文件为草案或征求意见稿，不得冒充现行正式政策")
    elif validity in REVIEW_POLICY_VALIDITY and not official_source:
        reasons.append("现行状态尚未由官方原文或人工确认闭环")
    if confidence == "low":
        reasons.append("元数据识别置信度较低")
    if review_status == "needs_review":
        reasons.append("关键字段仍待人工核验")
    if reasons:
        return {
            "status": "needs_review",
            "usable_for_current_conclusion": False,
            "official_source": official_source,
            "reasons": list(dict.fromkeys(reasons)),
        }
    return {
        "status": "allowed",
        "usable_for_current_conclusion": True,
        "official_source": official_source,
        "reasons": [],
    }


def compile_policy_rule_candidates(
    policy_text: str,
    *,
    source: str,
    policy_status: str,
    fact_contract: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    clauses = [
        clause.strip()
        for clause in re.split(r"[\n。；;]+", policy_text)
        if clause.strip()
    ]
    operator_phrases = (
        ("不低于", "gte"),
        ("不少于", "gte"),
        ("不小于", "gte"),
        ("至少", "gte"),
        ("达到", "gte"),
        ("不超过", "lte"),
        ("不高于", "lte"),
        ("不得高于", "lte"),
        ("低于", "lt"),
        ("少于", "lt"),
        ("高于", "gt"),
        ("超过", "gt"),
    )
    for clause in clauses:
        for field_spec in fact_contract:
            field = str(field_spec.get("field") or "").strip()
            aliases = unique_strings(
                [
                    field_spec.get("label", ""),
                    *field_spec.get("aliases", []),
                ]
            )
            matched_aliases = [alias for alias in aliases if alias and alias in clause]
            if not field or not matched_aliases:
                continue
            alias = max(matched_aliases, key=len)
            operator = ""
            expected: object = None
            unit = str(field_spec.get("unit") or "")
            confidence = "medium"
            after_alias = clause.split(alias, 1)[1]
            for phrase, candidate_operator in operator_phrases:
                match = re.search(
                    rf"{re.escape(phrase)}\s*([-+]?\d+(?:\.\d+)?)\s*(亿元|万元|元|%|％|人|件|项|年)?",
                    after_alias,
                )
                if not match:
                    continue
                operator = candidate_operator
                expected = _normalize_numeric_unit(
                    match.group(1),
                    match.group(2) or unit,
                    target_unit=unit,
                )
                confidence = "high" if expected is not None else "low"
                break
            if not operator and any(
                phrase in after_alias[:20]
                for phrase in ("应具备", "须具备", "必须具备", "应当具备")
            ):
                operator = "truthy"
                expected = True
            if not operator and re.search(r"(?:应|须|必须|需)提供", clause):
                operator = "exists"
                expected = True
                confidence = "medium"
            if not operator:
                continue
            rule_type = (
                "submission"
                if operator == "exists" and re.search(r"(?:材料|证明|报告|附件)", clause)
                else "hard-threshold"
            )
            digest = hashlib.sha256(
                f"{source}\n{field}\n{operator}\n{expected}\n{clause}".encode("utf-8")
            ).hexdigest()[:16]
            candidates.append(
                {
                    "rule_id": f"rule-{digest}",
                    "type": rule_type,
                    "field": field,
                    "operator": operator,
                    "expected": expected,
                    "unit": unit,
                    "source": source,
                    "source_quote": clause,
                    "policy_status": policy_status,
                    "review_status": "candidate",
                    "parser_confidence": confidence,
                    "matched_alias": alias,
                }
            )
    return list(
        {
            (
                candidate["field"],
                candidate["operator"],
                str(candidate["expected"]),
                candidate["source_quote"],
            ): candidate
            for candidate in candidates
        }.values()
    )


def activate_confirmed_policy_rules(
    candidates: Sequence[Mapping[str, object]],
    confirmations: Mapping[str, object],
) -> dict[str, object]:
    reviewed: list[dict[str, object]] = []
    active: list[dict[str, object]] = []
    for raw_candidate in candidates:
        candidate = dict(raw_candidate)
        rule_id = str(candidate.get("rule_id") or "")
        decision = confirmations.get(rule_id)
        if isinstance(decision, Mapping):
            review_status = str(
                decision.get("review_status")
                or candidate.get("review_status")
                or "candidate"
            )
            for key in ("type", "field", "operator", "expected", "unit"):
                if key in decision:
                    candidate[key] = decision[key]
            candidate["review_note"] = str(decision.get("review_note") or "")
        else:
            review_status = str(
                decision or candidate.get("review_status") or "candidate"
            )
        if review_status not in {"candidate", "confirmed", "rejected"}:
            review_status = "candidate"
        candidate["review_status"] = review_status
        reviewed.append(candidate)
        if (
            review_status == "confirmed"
            and str(candidate.get("policy_status") or "") == "current"
        ):
            active.append(candidate)
    return {
        "reviewed_candidates": reviewed,
        "active_rules": active,
        "blocked_candidates": [
            candidate
            for candidate in reviewed
            if candidate["review_status"] != "confirmed"
            or str(candidate.get("policy_status") or "") != "current"
        ],
    }


def convert_host_extractions_to_materials(
    extractions: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    materials: list[dict[str, object]] = []
    warnings: list[dict[str, object]] = []
    for index, extraction in enumerate(extractions, start=1):
        source = str(
            extraction.get("source")
            or extraction.get("file_name")
            or f"host-extraction-{index}"
        )
        format_name = str(
            extraction.get("format")
            or extraction.get("kind")
            or extraction.get("file_type")
            or ""
        ).lower()
        document_type = str(extraction.get("document_type") or "unknown")
        fields: dict[str, object] = {}
        field_locations: dict[str, str] = {}
        direct_fields = extraction.get("fields", {})
        if isinstance(direct_fields, Mapping):
            for name, value in direct_fields.items():
                fields[str(name)] = value
                field_locations[str(name)] = "宿主结构化字段"

        table_count = 0
        for table_index, table in enumerate(_host_tables(extraction), start=1):
            table_count += 1
            rows = _host_table_rows(table)
            for row_index, row in enumerate(rows, start=1):
                pairs = _host_row_field_pairs(row)
                for name, value in pairs:
                    if name in fields and _comparable_value(fields[name]) != _comparable_value(value):
                        warnings.append(
                            {
                                "source": source,
                                "field": name,
                                "reason": "同一宿主提取结果出现多个不同值，后续进入事实冲突判断",
                            }
                        )
                    fields[name] = value
                    field_locations[name] = f"表格{table_index}第{row_index}行"

        text_parts = _host_text_parts(extraction)
        text = "\n".join(part for part in text_parts if part.strip())
        if not fields and not text:
            warnings.append(
                {
                    "source": source,
                    "reason": "宿主提取结果未包含可用文本、字段或表格",
                }
            )
        materials.append(
            {
                "document_type": document_type,
                "source": source,
                "period": str(extraction.get("period") or ""),
                "scope": str(extraction.get("scope") or ""),
                "verified": bool(extraction.get("verified")),
                "evidence_state": str(extraction.get("evidence_state") or ""),
                "fields": fields,
                "field_locations": field_locations,
                "text": text,
                "host_extraction": {
                    "format": format_name,
                    "extractor": str(extraction.get("extractor") or ""),
                    "table_count": table_count,
                    "page_count": int(extraction.get("page_count") or 0),
                    "worksheet_count": len(extraction.get("worksheets", []))
                    if isinstance(extraction.get("worksheets"), list)
                    else 0,
                },
            }
        )
    return {
        "materials": materials,
        "warnings": warnings,
    }


def _host_text_parts(extraction: Mapping[str, object]) -> list[str]:
    parts: list[str] = []
    for key in ("text", "markdown", "content"):
        value = extraction.get(key)
        if isinstance(value, str):
            parts.append(value)
    pages = extraction.get("pages", [])
    if isinstance(pages, list):
        for page in pages:
            if isinstance(page, str):
                parts.append(page)
            elif isinstance(page, Mapping):
                for key in ("text", "markdown", "content"):
                    value = page.get(key)
                    if isinstance(value, str):
                        parts.append(value)
                        break
    paragraphs = extraction.get("paragraphs", [])
    if isinstance(paragraphs, list):
        parts.extend(str(paragraph) for paragraph in paragraphs if str(paragraph).strip())
    return parts


def _host_tables(extraction: Mapping[str, object]) -> list[object]:
    tables: list[object] = []
    direct_tables = extraction.get("tables", [])
    if isinstance(direct_tables, list):
        tables.extend(direct_tables)
    worksheets = extraction.get("worksheets", [])
    if isinstance(worksheets, list):
        for worksheet in worksheets:
            if isinstance(worksheet, Mapping):
                if isinstance(worksheet.get("tables"), list):
                    tables.extend(worksheet["tables"])
                elif isinstance(worksheet.get("rows"), list):
                    tables.append({"rows": worksheet["rows"]})
    return tables


def _host_table_rows(table: object) -> list[object]:
    if isinstance(table, Mapping):
        rows = table.get("rows", [])
        return rows if isinstance(rows, list) else []
    return table if isinstance(table, list) else []


def _host_row_field_pairs(row: object) -> list[tuple[str, object]]:
    if isinstance(row, Mapping):
        field_key = next(
            (
                key
                for key in ("字段", "指标", "项目", "名称", "field", "name")
                if key in row
            ),
            None,
        )
        value_key = next(
            (
                key
                for key in ("数值", "值", "内容", "value", "result")
                if key in row
            ),
            None,
        )
        if field_key and value_key:
            return [(str(row[field_key]).strip(), row[value_key])]
        if len(row) == 2:
            values = list(row.values())
            return [(str(values[0]).strip(), values[1])]
        return []
    if isinstance(row, (list, tuple)) and len(row) == 2:
        return [(str(row[0]).strip(), row[1])]
    return []


def extract_enterprise_fact_candidates(
    materials: Sequence[Mapping[str, object]],
    *,
    fact_contract: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    alias_map: list[tuple[str, Mapping[str, object]]] = []
    for field_spec in fact_contract:
        aliases = unique_strings(
            [
                field_spec.get("field", ""),
                field_spec.get("label", ""),
                *field_spec.get("aliases", []),
            ]
        )
        alias_map.extend((alias, field_spec) for alias in aliases if alias)
    alias_map.sort(key=lambda item: len(item[0]), reverse=True)

    facts: list[dict[str, object]] = []
    unresolved: list[dict[str, object]] = []
    for material_index, material in enumerate(materials, start=1):
        document_type = str(material.get("document_type") or "unknown")
        source = str(material.get("source") or f"material-{material_index}")
        period = str(material.get("period") or "")
        scope = str(material.get("scope") or "")
        verified_material = bool(material.get("verified"))
        explicit_state = str(material.get("evidence_state") or "")
        structured_fields = material.get("fields", {})
        field_locations = material.get("field_locations", {})
        if isinstance(structured_fields, Mapping):
            for raw_name, raw_value in structured_fields.items():
                match = _match_fact_field(str(raw_name), alias_map)
                if not match:
                    unresolved.append(
                        {
                            "source": source,
                            "raw_field": str(raw_name),
                            "reason": "字段未进入统一事实契约",
                        }
                    )
                    continue
                alias, field_spec = match
                value, provided_unit, provided_state = _material_field_value(raw_value)
                normalized_value = normalize_fact_value(
                    value,
                    value_type=str(field_spec.get("value_type") or "string"),
                    source_unit=provided_unit,
                    target_unit=str(field_spec.get("unit") or ""),
                )
                facts.append(
                    _fact_candidate(
                        material_index=material_index,
                        field_spec=field_spec,
                        value=normalized_value,
                        document_type=document_type,
                        source=source,
                        period=period,
                        scope=scope,
                        location=str(
                            field_locations.get(raw_name, raw_name)
                            if isinstance(field_locations, Mapping)
                            else raw_name
                        ),
                        matched_alias=alias,
                        verified_material=verified_material,
                        explicit_state=provided_state or explicit_state,
                        extraction_method="structured-field",
                    )
                )
        text = str(material.get("text") or "")
        if text:
            for alias, field_spec in alias_map:
                match = re.search(
                    rf"{re.escape(alias)}\s*[:：为]?\s*"
                    r"(?P<value>[-+]?\d+(?:\.\d+)?\s*(?:亿元|万元|元|%|％|人|件|项|年)?|"
                    r"是|否|有|无|正常|异常|[A-Za-z0-9\u4e00-\u9fff（）()·\-]{2,40})",
                    text,
                )
                if not match:
                    continue
                raw_value = match.group("value").strip()
                normalized_value = normalize_fact_value(
                    raw_value,
                    value_type=str(field_spec.get("value_type") or "string"),
                    source_unit="",
                    target_unit=str(field_spec.get("unit") or ""),
                )
                facts.append(
                    _fact_candidate(
                        material_index=material_index,
                        field_spec=field_spec,
                        value=normalized_value,
                        document_type=document_type,
                        source=source,
                        period=period,
                        scope=scope,
                        location=f"文本字段：{alias}",
                        matched_alias=alias,
                        verified_material=False,
                        explicit_state="claimed",
                        extraction_method="text-pattern",
                    )
                )
    deduplicated = list(
        {
            (
                fact["field"],
                _comparable_value(fact["value"]),
                fact["source"],
                fact["period"],
            ): fact
            for fact in facts
        }.values()
    )
    return {
        "facts": deduplicated,
        "unresolved_fields": unresolved,
    }


def _match_fact_field(
    raw_name: str,
    alias_map: Sequence[tuple[str, Mapping[str, object]]],
) -> tuple[str, Mapping[str, object]] | None:
    normalized = normalize_search_text(raw_name)
    for alias, field_spec in alias_map:
        normalized_alias = normalize_search_text(alias)
        if normalized == normalized_alias or normalized_alias in normalized:
            return alias, field_spec
    return None


def _material_field_value(raw_value: object) -> tuple[object, str, str]:
    if isinstance(raw_value, Mapping):
        return (
            raw_value.get("value"),
            str(raw_value.get("unit") or ""),
            str(raw_value.get("evidence_state") or ""),
        )
    return raw_value, "", ""


def normalize_fact_value(
    value: object,
    *,
    value_type: str,
    source_unit: str,
    target_unit: str,
) -> object:
    if value_type == "number":
        text = str(value or "").strip()
        unit_match = re.search(r"(亿元|万元|元|%|％|人|件|项|年)", text)
        unit = source_unit or (unit_match.group(1) if unit_match else target_unit)
        number_match = re.search(r"[-+]?\d+(?:\.\d+)?", text.replace(",", ""))
        if not number_match:
            return value
        normalized = _normalize_numeric_unit(
            number_match.group(0),
            unit,
            target_unit=target_unit,
        )
        return normalized if normalized is not None else value
    if value_type == "boolean":
        normalized = normalize_search_text(value)
        if normalized in {"是", "有", "具备", "符合", "正常", "true", "1"}:
            return True
        if normalized in {"否", "无", "不具备", "不符合", "异常", "false", "0"}:
            return False
    return str(value).strip() if isinstance(value, str) else value


def _normalize_numeric_unit(
    number: object,
    source_unit: str,
    *,
    target_unit: str,
) -> float | int | None:
    numeric = _numeric_value(number)
    if numeric is None:
        return None
    normalized_source = source_unit.replace("％", "%")
    normalized_target = target_unit.replace("％", "%")
    if normalized_target == "万元":
        if normalized_source == "亿元":
            numeric *= 10000
        elif normalized_source == "元":
            numeric /= 10000
    elif normalized_target == "元":
        if normalized_source == "万元":
            numeric *= 10000
        elif normalized_source == "亿元":
            numeric *= 100000000
    return int(numeric) if numeric.is_integer() else numeric


def _fact_candidate(
    *,
    material_index: int,
    field_spec: Mapping[str, object],
    value: object,
    document_type: str,
    source: str,
    period: str,
    scope: str,
    location: str,
    matched_alias: str,
    verified_material: bool,
    explicit_state: str,
    extraction_method: str,
) -> dict[str, object]:
    trusted_types = set(unique_strings(field_spec.get("trusted_document_types", [])))
    state = explicit_state if explicit_state in EVIDENCE_STATES else "claimed"
    if (
        not explicit_state
        and verified_material
        and document_type in trusted_types
        and extraction_method == "structured-field"
    ):
        state = "computed" if document_type == "verified_calculation" else "verified"
    digest = hashlib.sha256(
        f"{source}\n{field_spec.get('field')}\n{period}\n{value}".encode("utf-8")
    ).hexdigest()[:16]
    return {
        "id": f"material-fact-{material_index:03d}-{digest}",
        "subject": "企业",
        "field": str(field_spec.get("field") or ""),
        "value": value,
        "evidence_state": state,
        "source": source,
        "location": location,
        "period": period,
        "scope": scope,
        "document_type": document_type,
        "matched_alias": matched_alias,
        "extraction_method": extraction_method,
        "review_status": "confirmed" if state in SUPPORTING_EVIDENCE_STATES else "candidate",
    }


def validate_project_algorithm_pack(
    pack: Mapping[str, object],
) -> list[str]:
    errors: list[str] = []
    project_id = str(pack.get("project_id") or "").strip()
    if not project_id:
        errors.append("缺少project_id")
    if not str(pack.get("project_name") or "").strip():
        errors.append("缺少project_name")
    if not str(pack.get("version") or "").strip():
        errors.append("缺少version")
    if not isinstance(pack.get("aliases"), list):
        errors.append("aliases必须为列表")
    coverage_status = str(
        pack.get("coverage_status") or "rules-candidate"
    )
    if coverage_status not in {
        "routing-only",
        "rules-candidate",
        "rules-confirmed",
    }:
        errors.append("coverage_status无效")
    for field_name in ("fact_fields", "rule_cards", "gold_cases"):
        if not isinstance(pack.get(field_name), list):
            errors.append(f"{field_name}必须为列表")
    if "rule_layers" in pack and not isinstance(pack.get("rule_layers"), list):
        errors.append("rule_layers必须为列表")
    forbidden_keys = {
        "api",
        "api_url",
        "endpoint",
        "mcp",
        "mcp_url",
        "route",
        "router",
    }

    def scan(value: object, path: str) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                normalized_key = str(key).lower()
                if normalized_key in forbidden_keys:
                    errors.append(f"{path}包含禁止的入口字段：{key}")
                scan(item, f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                scan(item, f"{path}[{index}]")

    scan(pack, "pack")
    seen_fields: set[str] = set()
    for index, field_spec in enumerate(pack.get("fact_fields", [])):
        if not isinstance(field_spec, Mapping):
            errors.append(f"fact_fields[{index}]必须为对象")
            continue
        field = str(field_spec.get("field") or "").strip()
        if not field:
            errors.append(f"fact_fields[{index}]缺少field")
        elif field in seen_fields:
            errors.append(f"fact_fields重复：{field}")
        seen_fields.add(field)
    seen_rules: set[str] = set()
    for index, rule in enumerate(pack.get("rule_cards", [])):
        if not isinstance(rule, Mapping):
            errors.append(f"rule_cards[{index}]必须为对象")
            continue
        rule_id = str(rule.get("rule_id") or "").strip()
        if not rule_id:
            errors.append(f"rule_cards[{index}]缺少rule_id")
        elif rule_id in seen_rules:
            errors.append(f"rule_cards重复：{rule_id}")
        seen_rules.add(rule_id)
        review_status = str(rule.get("review_status") or "candidate")
        if review_status not in {"candidate", "confirmed"}:
            errors.append(f"rule_cards[{index}].review_status无效")
        for required_field in (
            "field",
            "operator",
            "source",
        ):
            if not str(rule.get(required_field) or "").strip():
                errors.append(
                    f"rule_cards[{index}]缺少{required_field}"
                )
        if review_status == "confirmed":
            for audit_field in (
                "approved_by",
                "approved_at",
                "source_url",
            ):
                if not str(rule.get(audit_field) or "").strip():
                    errors.append(
                        f"rule_cards[{index}]已确认规则缺少{audit_field}"
                    )
            if str(rule.get("policy_status") or "") != "current":
                errors.append(
                    f"rule_cards[{index}]已确认规则的policy_status必须为current"
                )
        if str(rule.get("type") or "") not in RULE_TYPES:
            errors.append(f"rule_cards[{index}].type无效")
        if not str(rule.get("source_quote") or "").strip():
            errors.append(f"rule_cards[{index}]缺少source_quote")
    if coverage_status == "routing-only" and pack.get("rule_cards"):
        errors.append("routing-only算法包不得包含规则卡")
    if coverage_status == "rules-confirmed" and any(
        str(rule.get("review_status") or "candidate") != "confirmed"
        for rule in pack.get("rule_cards", [])
        if isinstance(rule, Mapping)
    ):
        errors.append("rules-confirmed算法包只能包含已确认规则")
    seen_layers: set[str] = set()
    for layer_index, layer in enumerate(pack.get("rule_layers", [])):
        if not isinstance(layer, Mapping):
            errors.append(f"rule_layers[{layer_index}]必须为对象")
            continue
        layer_id = str(layer.get("layer_id") or "").strip()
        layer_type = str(layer.get("layer_type") or "").strip()
        if not layer_id:
            errors.append(f"rule_layers[{layer_index}]缺少layer_id")
        elif layer_id in seen_layers:
            errors.append(f"rule_layers重复：{layer_id}")
        seen_layers.add(layer_id)
        if layer_type not in RULE_LAYER_TYPES:
            errors.append(f"rule_layers[{layer_index}].layer_type无效")
        applicability = layer.get("applicability", {})
        if not isinstance(applicability, Mapping):
            errors.append(f"rule_layers[{layer_index}].applicability必须为对象")
            applicability = {}
        if layer_type == "annual" and not applicability.get("years"):
            errors.append(f"rule_layers[{layer_index}]年度层缺少years")
        if layer_type == "jurisdiction" and not applicability.get("regions"):
            errors.append(f"rule_layers[{layer_index}]属地层缺少regions")
        if not isinstance(layer.get("rules"), list):
            errors.append(f"rule_layers[{layer_index}].rules必须为列表")
            continue
        for rule_index, rule in enumerate(layer.get("rules", [])):
            if not isinstance(rule, Mapping):
                errors.append(
                    f"rule_layers[{layer_index}].rules[{rule_index}]必须为对象"
                )
                continue
            if str(rule.get("review_status") or "") != "confirmed":
                errors.append(
                    f"rule_layers[{layer_index}].rules[{rule_index}]必须已确认"
                )
            if str(rule.get("policy_status") or "") != "current":
                errors.append(
                    f"rule_layers[{layer_index}].rules[{rule_index}]必须为current"
                )
    if not pack.get("gold_cases"):
        errors.append("gold_cases不能为空")
    for index, case in enumerate(pack.get("gold_cases", [])):
        if not isinstance(case, Mapping):
            errors.append(f"gold_cases[{index}]必须为对象")
            continue
        if str(case.get("expected_conclusion") or "") not in {
            "eligible",
            "conditional",
            "ineligible",
            "undetermined",
        }:
            errors.append(f"gold_cases[{index}].expected_conclusion无效")
    return list(dict.fromkeys(errors))


def select_project_algorithm_rules(
    pack: Mapping[str, object],
    project_context: Mapping[str, object],
) -> dict[str, object]:
    layers = pack.get("rule_layers")
    if not isinstance(layers, list) or not layers:
        return {
            "rules": [
                dict(rule)
                for rule in pack.get("rule_cards", [])
                if isinstance(rule, Mapping)
            ],
            "selected_layers": ["legacy-rule-cards"],
        }
    context_year = str(
        project_context.get("year")
        or project_context.get("policy_year")
        or project_context.get("application_year")
        or ""
    ).strip()
    context_application_type = str(
        project_context.get("application_type") or ""
    ).strip()
    context_regions = unique_strings(
        [
            *(
                project_context.get("regions", [])
                if isinstance(project_context.get("regions"), list)
                else []
            ),
            project_context.get("region"),
            project_context.get("province"),
            project_context.get("city"),
            project_context.get("jurisdiction"),
        ]
    )

    def values_match(expected: Sequence[object], actual: str) -> bool:
        normalized_expected = {str(value).strip() for value in expected if str(value).strip()}
        return not normalized_expected or actual in normalized_expected

    def regions_match(expected: Sequence[object]) -> bool:
        expected_regions = unique_strings(expected)
        if not expected_regions:
            return True
        return any(
            expected_region == actual_region
            or expected_region in actual_region
            or actual_region in expected_region
            for expected_region in expected_regions
            for actual_region in context_regions
        )

    selected_layers: list[str] = []
    selected_rules: dict[str, dict[str, object]] = {}
    for layer_type in ("stable", "annual", "jurisdiction"):
        for layer in layers:
            if not isinstance(layer, Mapping):
                continue
            if str(layer.get("layer_type") or "") != layer_type:
                continue
            applicability = layer.get("applicability", {})
            if not isinstance(applicability, Mapping):
                continue
            if not values_match(applicability.get("years", []), context_year):
                continue
            if not values_match(
                applicability.get("application_types", []),
                context_application_type,
            ):
                continue
            if not regions_match(applicability.get("regions", [])):
                continue
            selected_layers.append(str(layer.get("layer_id") or layer_type))
            for rule in layer.get("rules", []):
                if not isinstance(rule, Mapping):
                    continue
                rule_id = str(rule.get("rule_id") or "").strip()
                if rule_id:
                    selected_rules[rule_id] = dict(rule)
    return {
        "rules": list(selected_rules.values()),
        "selected_layers": selected_layers,
    }


def merge_fact_contract(
    base_contract: Sequence[Mapping[str, object]],
    extension_fields: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    merged: dict[str, dict[str, object]] = {}
    for raw_field in [*base_contract, *extension_fields]:
        field = str(raw_field.get("field") or "").strip()
        if not field:
            continue
        existing = merged.get(field, {})
        combined = {**existing, **dict(raw_field)}
        combined["aliases"] = unique_strings(
            [
                *existing.get("aliases", []),
                *raw_field.get("aliases", []),
            ]
        )
        combined["trusted_document_types"] = unique_strings(
            [
                *existing.get("trusted_document_types", []),
                *raw_field.get("trusted_document_types", []),
            ]
        )
        merged[field] = combined
    return list(merged.values())


def project_algorithm_pack_matches(
    pack: Mapping[str, object],
    project_context: Mapping[str, object],
) -> bool:
    identifiers = {
        normalize_search_text(project_context.get("project_id")),
        normalize_search_text(project_context.get("project_name")),
    }
    pack_identifiers = {
        normalize_search_text(pack.get("project_id")),
        normalize_search_text(pack.get("project_name")),
        *(
            normalize_search_text(alias)
            for alias in pack.get("aliases", [])
            if str(alias).strip()
        ),
    }
    return bool((identifiers - {""}).intersection(pack_identifiers - {""}))


def build_enterprise_fact_ledger(
    facts: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    normalized_facts: list[dict[str, object]] = []
    by_field: dict[str, list[dict[str, object]]] = {}
    for index, raw_fact in enumerate(facts, start=1):
        field = str(raw_fact.get("field") or raw_fact.get("claim") or "").strip()
        if not field:
            continue
        evidence_state = str(
            raw_fact.get("evidence_state")
            or raw_fact.get("status")
            or "claimed"
        ).strip()
        if evidence_state == "unverified":
            evidence_state = "claimed"
        elif evidence_state == "conflicted":
            evidence_state = "conflicting"
        elif evidence_state == "expired":
            evidence_state = "claimed"
        if evidence_state not in EVIDENCE_STATES:
            evidence_state = "claimed"
        fact = {
            "id": str(raw_fact.get("id") or f"fact-{index:04d}"),
            "subject": str(raw_fact.get("subject") or "企业"),
            "field": field,
            "value": raw_fact.get("value"),
            "evidence_state": evidence_state,
            "source": str(raw_fact.get("source") or ""),
            "location": str(raw_fact.get("location") or ""),
            "period": str(raw_fact.get("period") or ""),
            "scope": str(raw_fact.get("scope") or ""),
            "retrieved_at": str(raw_fact.get("retrieved_at") or ""),
        }
        normalized_facts.append(fact)
        by_field.setdefault(field, []).append(fact)

    resolved: dict[str, dict[str, object]] = {}
    conflicts: list[dict[str, object]] = []
    for field, field_facts in by_field.items():
        supporting = [
            fact
            for fact in field_facts
            if fact["evidence_state"] in SUPPORTING_EVIDENCE_STATES
        ]
        supporting_values = {
            _comparable_value(fact.get("value")) for fact in supporting
        }
        explicit_conflict = any(
            fact["evidence_state"] == "conflicting" for fact in field_facts
        )
        if explicit_conflict or len(supporting_values) > 1:
            conflict = {
                "field": field,
                "fact_ids": [fact["id"] for fact in field_facts],
                "values": [fact.get("value") for fact in field_facts],
                "reason": "同一事实存在冲突来源或核验值不一致",
            }
            conflicts.append(conflict)
            resolved[field] = {
                "field": field,
                "value": None,
                "evidence_state": "conflicting",
                "fact_ids": conflict["fact_ids"],
            }
            continue
        candidates = supporting or [
            fact for fact in field_facts if fact["evidence_state"] != "missing"
        ]
        selected = candidates[-1] if candidates else field_facts[-1]
        resolved[field] = {
            "field": field,
            "value": selected.get("value"),
            "evidence_state": selected["evidence_state"],
            "fact_ids": [fact["id"] for fact in field_facts],
            "source": selected.get("source", ""),
            "period": selected.get("period", ""),
            "scope": selected.get("scope", ""),
        }
    return {
        "schema_version": 1,
        "facts": normalized_facts,
        "resolved": resolved,
        "conflicts": conflicts,
    }


def _comparable_value(value: object) -> object:
    if isinstance(value, str):
        return re.sub(r"\s+", "", value).lower()
    if isinstance(value, list):
        return tuple(_comparable_value(item) for item in value)
    if isinstance(value, dict):
        return tuple(
            sorted((str(key), _comparable_value(item)) for key, item in value.items())
        )
    return value


def _numeric_value(value: object) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    normalized = str(value or "").replace(",", "").replace("，", "").strip()
    match = re.fullmatch(r"[-+]?\d+(?:\.\d+)?", normalized)
    return float(normalized) if match else None


def evaluate_requirement(
    requirement: Mapping[str, object],
    fact_ledger: Mapping[str, object],
) -> dict[str, object]:
    rule_id = str(requirement.get("rule_id") or "").strip()
    rule_type = str(requirement.get("type") or "hard-threshold").strip()
    field = str(requirement.get("field") or "").strip()
    operator = str(requirement.get("operator") or "exists").strip()
    expected = requirement.get("expected")
    source = str(requirement.get("source") or "")
    resolved = fact_ledger.get("resolved", {})
    fact = resolved.get(field) if isinstance(resolved, Mapping) else None
    if rule_type not in RULE_TYPES:
        return {
            "rule_id": rule_id,
            "type": rule_type,
            "field": field,
            "status": "unknown",
            "evidence_state": "missing",
            "source": source,
            "reason": "规则类型不受支持",
        }
    if not field or not isinstance(fact, Mapping):
        return {
            "rule_id": rule_id,
            "type": rule_type,
            "field": field,
            "status": "unknown",
            "evidence_state": "missing",
            "source": source,
            "reason": "企业事实底稿缺少对应字段",
        }
    evidence_state = str(fact.get("evidence_state") or "claimed")
    if evidence_state == "not-applicable":
        return {
            "rule_id": rule_id,
            "type": rule_type,
            "field": field,
            "status": "not-applicable",
            "evidence_state": evidence_state,
            "source": source,
            "reason": "规则经确认不适用于当前主体",
        }
    if evidence_state == "conflicting":
        return {
            "rule_id": rule_id,
            "type": rule_type,
            "field": field,
            "status": "pending",
            "evidence_state": evidence_state,
            "source": source,
            "reason": "同一企业事实存在冲突，需先完成口径裁决",
        }
    if evidence_state not in SUPPORTING_EVIDENCE_STATES:
        return {
            "rule_id": rule_id,
            "type": rule_type,
            "field": field,
            "status": "pending",
            "evidence_state": evidence_state,
            "source": source,
            "reason": "现有证据不足以支撑硬门槛结论",
        }

    actual = fact.get("value")
    matched = _compare_requirement(actual, operator, expected)
    if matched is None:
        status = "unknown"
        reason = "事实值与规则运算符不兼容"
    else:
        if rule_type == "exclusion":
            status = "failed" if matched else "passed"
            reason = "命中一票否决项" if matched else "未命中一票否决项"
        else:
            status = "passed" if matched else "failed"
            reason = "已核验事实满足硬门槛" if matched else "已核验事实不满足硬门槛"
    return {
        "rule_id": rule_id,
        "type": rule_type,
        "field": field,
        "operator": operator,
        "expected": expected,
        "actual": actual,
        "status": status,
        "evidence_state": evidence_state,
        "source": source,
        "reason": reason,
        "fact_ids": list(fact.get("fact_ids") or []),
    }


def _compare_requirement(
    actual: object,
    operator: str,
    expected: object,
) -> bool | None:
    if operator == "exists":
        return actual not in (None, "", [], {})
    if operator == "truthy":
        return bool(actual)
    if operator == "falsy":
        return not bool(actual)
    if operator == "equals":
        return _comparable_value(actual) == _comparable_value(expected)
    if operator == "not-equals":
        return _comparable_value(actual) != _comparable_value(expected)
    if operator in {"in", "not-in"}:
        if not isinstance(expected, (list, tuple, set, frozenset)):
            return None
        matched = _comparable_value(actual) in {
            _comparable_value(item) for item in expected
        }
        return matched if operator == "in" else not matched
    if operator == "contains":
        if isinstance(actual, (list, tuple, set, frozenset)):
            return _comparable_value(expected) in {
                _comparable_value(item) for item in actual
            }
        return normalize_search_text(expected) in normalize_search_text(actual)
    if operator in {"gte", "gt", "lte", "lt"}:
        actual_number = _numeric_value(actual)
        expected_number = _numeric_value(expected)
        if actual_number is None or expected_number is None:
            return None
        if operator == "gte":
            return actual_number >= expected_number
        if operator == "gt":
            return actual_number > expected_number
        if operator == "lte":
            return actual_number <= expected_number
        return actual_number < expected_number
    return None


def evaluate_project_feasibility(
    *,
    project_context: Mapping[str, object],
    requirements: Sequence[Mapping[str, object]],
    fact_ledger: Mapping[str, object],
) -> dict[str, object]:
    gates = [
        evaluate_requirement(requirement, fact_ledger)
        for requirement in requirements
        if str(requirement.get("type") or "hard-threshold")
        in {"exclusion", "hard-threshold", "submission"}
    ]
    decisive_gates = [
        gate for gate in gates if gate["type"] in {"exclusion", "hard-threshold"}
    ]
    statuses = {str(gate["status"]) for gate in decisive_gates}
    policy_status = str(project_context.get("policy_status") or "unknown")
    if "failed" in statuses:
        conclusion = "ineligible"
    elif policy_status != "current":
        conclusion = "undetermined"
    elif not decisive_gates or "unknown" in statuses:
        conclusion = "undetermined"
    elif "pending" in statuses:
        conclusion = "conditional"
    else:
        conclusion = "eligible"

    evidence_gaps: list[dict[str, object]] = []
    for gate in gates:
        if gate["status"] not in {"pending", "unknown"}:
            continue
        evidence_gaps.append(
            {
                "rule_id": gate["rule_id"],
                "field": gate["field"],
                "current_state": gate["evidence_state"],
                "reason": gate["reason"],
                "required_evidence": _requirement_evidence_description(gate),
                "action": f"补齐并核验企业字段：{gate['field']}",
            }
        )
    return {
        "project_context": dict(project_context),
        "overall_conclusion": conclusion,
        "hard_gates": gates,
        "evidence_gaps": evidence_gaps,
        "uncertainties": [
            {
                "field": conflict["field"],
                "reason": conflict["reason"],
                "fact_ids": conflict["fact_ids"],
            }
            for conflict in fact_ledger.get("conflicts", [])
        ],
        "actions": [
            {
                "priority": index,
                "action": gap["action"],
                "rule_id": gap["rule_id"],
            }
            for index, gap in enumerate(evidence_gaps, start=1)
        ],
        "scoring": {
            "enabled": False,
            "reason": "本阶段仅执行非量化硬门槛与证据判断",
        },
    }


def _requirement_evidence_description(gate: Mapping[str, object]) -> str:
    operator = str(gate.get("operator") or "exists")
    expected = gate.get("expected")
    if operator == "exists":
        return "提供可定位原件或高等级来源证明该事实存在"
    return f"提供可定位证据并按规则核验：{operator} {expected}"


def build_growth_path(
    project_assessments: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    assessments_by_id = {
        str(item.get("project_id") or item.get("project_name") or ""): item
        for item in project_assessments
        if str(item.get("project_id") or item.get("project_name") or "")
    }
    path: list[dict[str, object]] = []
    for position, assessment in enumerate(
        sorted(
            project_assessments,
            key=lambda item: (
                int(item.get("sequence") or 9999),
                str(item.get("project_name") or ""),
            ),
        ),
        start=1,
    ):
        project_id = str(
            assessment.get("project_id") or assessment.get("project_name") or ""
        )
        prerequisites = unique_strings(assessment.get("prerequisite_projects", []))
        unmet_prerequisites = [
            prerequisite
            for prerequisite in prerequisites
            if str(
                assessments_by_id.get(prerequisite, {}).get("overall_conclusion")
                or ""
            )
            != "eligible"
        ]
        conclusion = str(assessment.get("overall_conclusion") or "undetermined")
        if unmet_prerequisites:
            stage = "later"
            reason = "前置项目尚未完成"
        elif conclusion == "eligible":
            stage = "ready"
            reason = "硬门槛已满足，可进入申报准备"
        elif conclusion == "conditional":
            stage = "prepare"
            reason = "先补齐关键证据，再确认申报"
        elif conclusion == "ineligible":
            stage = "blocked"
            reason = "存在明确硬门槛失败"
        else:
            stage = "verify"
            reason = "政策版本或关键事实不足，需先核验"
        path.append(
            {
                "position": position,
                "project_id": project_id,
                "project_name": str(assessment.get("project_name") or project_id),
                "stage": stage,
                "reason": reason,
                "unmet_prerequisites": unmet_prerequisites,
                "evidence_gaps": list(assessment.get("evidence_gaps") or []),
                "deadline": assessment.get("deadline"),
            }
        )
    return path


def audit_delivery_quality(
    deliverable: Mapping[str, object] | None,
    *,
    feasibility: Mapping[str, object],
) -> dict[str, object]:
    if not deliverable:
        return {
            "status": "not-run",
            "blocking_issues": [],
            "warnings": [],
        }
    sections = deliverable.get("sections", {})
    required_sections = unique_strings(deliverable.get("required_sections", []))
    if isinstance(sections, Mapping):
        present_sections = {
            str(name)
            for name, content in sections.items()
            if str(content or "").strip()
        }
    else:
        present_sections = set(unique_strings(sections if isinstance(sections, list) else []))
    blocking_issues = [
        f"缺少必填章节：{section}"
        for section in required_sections
        if section not in present_sections
    ]
    warnings: list[str] = []
    consistency_groups = deliverable.get("consistency_groups", [])
    if isinstance(consistency_groups, list):
        for group in consistency_groups:
            if not isinstance(group, Mapping):
                continue
            values = [
                _comparable_value(value)
                for value in group.get("values", [])
                if value not in (None, "")
            ]
            if len(set(values)) > 1:
                blocking_issues.append(
                    f"跨章节口径冲突：{group.get('name') or '未命名一致性组'}"
                )
    unresolved_claims = int(deliverable.get("unresolved_claims") or 0)
    if unresolved_claims:
        blocking_issues.append(f"仍有{unresolved_claims}项事实断言未绑定证据")
    if feasibility.get("overall_conclusion") in {"conditional", "undetermined"}:
        warnings.append("项目结论仍有待补证或待核验事项，正式交付不得写成确定达标")
    if feasibility.get("overall_conclusion") == "ineligible":
        blocking_issues.append("存在明确硬门槛失败，交付结论不得写成可申报")
    return {
        "status": "blocked" if blocking_issues else ("warning" if warnings else "passed"),
        "blocking_issues": blocking_issues,
        "warnings": warnings,
    }


def build_lifecycle_decision(
    query: str,
    *,
    rules: Sequence[Mapping[str, object]],
    project_records: Sequence[Mapping[str, object]],
    configured_aliases: Mapping[str, Sequence[str]],
    enterprise_facts: Sequence[Mapping[str, object]],
    project_context: Mapping[str, object],
    requirements: Sequence[Mapping[str, object]],
    growth_projects: Sequence[Mapping[str, object]] = (),
    deliverable: Mapping[str, object] | None = None,
    enterprise_materials: Sequence[Mapping[str, object]] = (),
    fact_contract: Sequence[Mapping[str, object]] = (),
    policy_text: str = "",
    policy_source: str = "",
    policy_status: str = "",
    rule_confirmations: Mapping[str, object] | None = None,
    rule_candidates: Sequence[Mapping[str, object]] = (),
) -> dict[str, object]:
    project_decision = build_project_decision(
        query,
        rules=rules,
        project_records=project_records,
        configured_aliases=configured_aliases,
    )
    material_extraction = extract_enterprise_fact_candidates(
        enterprise_materials,
        fact_contract=fact_contract,
    ) if enterprise_materials and fact_contract else {
        "facts": [],
        "unresolved_fields": [],
    }
    combined_facts = [*enterprise_facts, *material_extraction["facts"]]
    fact_ledger = build_enterprise_fact_ledger(combined_facts)
    compiled_rule_candidates = compile_policy_rule_candidates(
        policy_text,
        source=policy_source,
        policy_status=policy_status or str(project_context.get("policy_status") or ""),
        fact_contract=fact_contract,
    ) if policy_text and fact_contract else []
    combined_rule_candidates = [
        *rule_candidates,
        *compiled_rule_candidates,
    ]
    rule_activation = activate_confirmed_policy_rules(
        combined_rule_candidates,
        rule_confirmations or {},
    )
    active_requirements = [*requirements, *rule_activation["active_rules"]]
    feasibility = evaluate_project_feasibility(
        project_context=project_context,
        requirements=active_requirements,
        fact_ledger=fact_ledger,
    )
    assessments = [dict(item) for item in growth_projects]
    current_project_id = str(
        project_context.get("project_id")
        or project_context.get("project_name")
        or ""
    )
    if current_project_id:
        assessments.append(
            {
                "project_id": current_project_id,
                "project_name": str(
                    project_context.get("project_name") or current_project_id
                ),
                "sequence": project_context.get("sequence", 9999),
                "prerequisite_projects": project_context.get(
                    "prerequisite_projects", []
                ),
                **feasibility,
            }
        )
    return {
        **project_decision,
        "decision_type": "enterprise-project-lifecycle",
        "material_extraction": material_extraction,
        "policy_rule_compilation": rule_activation,
        "enterprise_fact_ledger": fact_ledger,
        "feasibility": feasibility,
        "evidence_gaps": feasibility["evidence_gaps"],
        "growth_path": build_growth_path(assessments),
        "delivery_quality": audit_delivery_quality(
            deliverable,
            feasibility=feasibility,
        ),
        "scoring": {
            "enabled": False,
            "reason": "主人要求本阶段暂不实施量化评分",
        },
    }


def parse_deadline_candidates(
    text: str,
    *,
    policy_year: int | None,
    now: datetime,
) -> list[tuple[datetime, str, int]]:
    normalized = re.sub(r"\s+", " ", text)
    candidates: list[tuple[datetime, str, int]] = []
    for match in DEADLINE_DATE_PATTERN.finditer(normalized):
        context_start = max(0, match.start() - 90)
        context_end = min(len(normalized), match.end() + 100)
        context = normalized[context_start:context_end]
        if not DEADLINE_CONTEXT_PATTERN.search(context):
            continue
        year = int(match.group("year") or policy_year or now.year)
        month = int(match.group("month"))
        day = int(match.group("day"))
        hour_value = match.group("hour")
        minute_value = match.group("minute")
        meridiem = match.group("meridiem") or ""
        hour = int(hour_value) if hour_value else 23
        minute = int(minute_value) if minute_value else (0 if hour_value else 59)
        if meridiem == "下午" and hour < 12:
            hour += 12
        elif meridiem == "中午" and hour < 11:
            hour += 12
        try:
            deadline = datetime(
                year,
                month,
                day,
                hour,
                minute,
                59,
                tzinfo=now.tzinfo,
            )
        except ValueError:
            continue
        remaining_seconds = (deadline - now).total_seconds()
        if remaining_seconds < 0 or remaining_seconds > 370 * 24 * 60 * 60:
            continue
        role_prefix = normalized[max(0, match.start() - 90) : match.start()]
        role_suffix = normalized[match.end() : min(len(normalized), match.end() + 30)]
        role_context = re.split(r"[。；;，,\n]", role_prefix)[-1] + role_suffix
        administrative_context = any(
            term in role_context
            for term in (
                "推荐单位",
                "主管部门",
                "区县",
                "审核截止",
                "报送截止",
                "经信部门",
                "科技部门",
            )
        )
        enterprise_context = any(
            term in role_context
            for term in (
                "企业申报",
                "申报人",
                "网上申报",
                "申请人",
                "报名",
                "材料提交",
            )
        )
        priority = 0 if enterprise_context else (2 if administrative_context else 1)
        candidates.append((deadline, context.strip(), priority))
    return candidates
