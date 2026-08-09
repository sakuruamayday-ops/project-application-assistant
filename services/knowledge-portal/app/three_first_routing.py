from __future__ import annotations

import re


PROJECTS = (
    ("首台套", "浙江省制造业首台（套）装备", ("首台", "首台套")),
    ("首版次", "浙江省首版次软件产品", ("首版", "首版次")),
    ("首批次", "浙江省首批次新材料", ("首批", "首批次", "重点新材料")),
)
DIFF_TERMS = ("历年", "版本", "变化", "差异", "新增", "删除", "调整", "条款", "对比")
MATCH_TERMS = ("匹配", "适配", "符合", "是否在目录", "能否申报", "对应目录")
NON_TOPIC_TERMS = (
    "政策",
    "条件",
    "要求",
    "门槛",
    "怎么申报",
    "如何申报",
    *(term for term in DIFF_TERMS if term != "历年"),
    *MATCH_TERMS,
)
TOPIC_COMMAND_TERMS = (
    "主题词",
    "主题",
    "反查",
    "查询",
    "检索",
    "查找",
    "核验",
    "有哪些",
    "历年不限",
    "历年",
)


def compact_text(value: str) -> str:
    return re.sub(r"\s+", "", value.strip())


def infer_topic_product_name(
    query: str,
    *,
    explicit_product_name: str = "",
    regions: list[str] | None = None,
) -> str:
    """Infer a product topic for the dedicated Three-First reverse lookup.

    ``three_first_analysis`` is itself the project boundary, so a short query
    such as ``智能水表`` is a product topic rather than an unspecified policy
    question.  The inference deliberately stops for policy, rule, difference
    and feasibility intents so those questions remain knowledge-only routes.
    """

    if explicit_product_name.strip():
        return explicit_product_name.strip()
    normalized = compact_text(query)
    if not normalized or any(term in normalized for term in NON_TOPIC_TERMS):
        return ""
    candidate = normalized
    project_terms = {
        term
        for _, _, terms in PROJECTS
        for term in terms
    }
    for term in sorted(project_terms, key=len, reverse=True):
        candidate = candidate.replace(term, "")
    candidate = candidate.replace("三首项目", "").replace("三首", "")
    for region in regions or []:
        normalized_region = compact_text(str(region))
        if normalized_region:
            candidate = candidate.replace(normalized_region, "")
            candidate = candidate.replace(normalized_region.removesuffix("省"), "")
            candidate = candidate.replace(normalized_region.removesuffix("市"), "")
    candidate = re.sub(r"(?<!\d)20\d{2}(?!\d)", "", candidate)
    for term in TOPIC_COMMAND_TERMS:
        candidate = candidate.replace(term, "")
    candidate = re.sub(r"[：:，,、；;。.?？/／×]+", "", candidate).strip()
    return candidate if 2 <= len(candidate) <= 100 else ""


def plan_three_first_analysis(
    query: str,
    *,
    enterprise_name: str = "",
    product_name: str = "",
    regions: list[str] | None = None,
    award_year: int | None = None,
    from_year: int | None = None,
    to_year: int | None = None,
    include_review_candidates: bool = False,
) -> dict[str, object]:
    normalized_query = compact_text(query)
    inferred_product_name = infer_topic_product_name(
        normalized_query,
        explicit_product_name=product_name,
        regions=regions,
    )
    project_types: list[str] = []
    project_names: list[str] = []
    for candidate_type, candidate_name, terms in PROJECTS:
        if any(term in normalized_query for term in terms):
            project_types.append(candidate_type)
            project_names.append(candidate_name)
    if not project_names and ("三首" in normalized_query or inferred_product_name):
        project_types = [item[0] for item in PROJECTS]
        project_names = [item[1] for item in PROJECTS]
    project_type = project_types[0] if len(project_types) == 1 else "三首项目"
    project_name = project_names[0] if len(project_names) == 1 else ""

    years = [
        int(value)
        for value in re.findall(r"(?<!\d)(20\d{2})(?!\d)", normalized_query)
    ]
    effective_from_year = from_year if from_year is not None else (years[0] if years else None)
    effective_to_year = to_year if to_year is not None else (years[-1] if len(years) >= 2 else None)
    list_year = effective_to_year or effective_from_year or award_year
    diff_requested = "首批次" in project_types and any(
        term in normalized_query for term in DIFF_TERMS
    )
    match_requested = "首批次" in project_types and (
        bool(product_name.strip()) or any(term in normalized_query for term in MATCH_TERMS)
    )
    clarifications: list[str] = []
    if diff_requested and (effective_from_year is None or effective_to_year is None):
        clarifications.append("目录差异分析需要明确两个年度。")
    if match_requested and not product_name.strip():
        clarifications.append("请提供需要匹配的具体产品或材料名称。")
    list_requested = bool(
        project_names
        and (
            enterprise_name.strip()
            or inferred_product_name
            or list_year
            or any(
                term in normalized_query
                for term in ("名单", "列出", "产品", "企业", "获批", "入选", "公示")
            )
        )
    )

    return {
        "query": normalized_query,
        "project_type": project_type,
        "project_name": project_name,
        "project_types": project_types,
        "project_names": project_names,
        "regions": list(dict.fromkeys(str(item).strip() for item in (regions or []) if str(item).strip())),
        "enterprise_name": enterprise_name.strip(),
        "product_name": inferred_product_name,
        "product_name_origin": (
            "explicit"
            if product_name.strip()
            else "query_topic"
            if inferred_product_name
            else "unavailable"
        ),
        "award_year": award_year,
        "from_year": effective_from_year,
        "to_year": effective_to_year,
        "list_year": list_year,
        "include_review_candidates": bool(include_review_candidates),
        "routes": {
            "knowledge_search": True,
            "public_list_search": list_requested,
            "recognition_search": bool(project_names and inferred_product_name),
            "directory_diff": diff_requested,
            "product_match": match_requested and bool(product_name.strip()),
        },
        "clarifications": clarifications,
    }
