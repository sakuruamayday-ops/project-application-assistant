from __future__ import annotations

import re


PROJECTS = (
    ("首台套", "浙江省制造业首台（套）装备", ("首台", "首台套")),
    ("首版次", "浙江省首版次软件产品", ("首版", "首版次")),
    ("首批次", "浙江省首批次新材料", ("首批", "首批次", "重点新材料")),
)
DIFF_TERMS = ("历年", "版本", "变化", "差异", "新增", "删除", "调整", "条款", "对比")
MATCH_TERMS = ("匹配", "适配", "符合", "是否在目录", "能否申报", "对应目录")


def compact_text(value: str) -> str:
    return re.sub(r"\s+", "", value.strip())


def plan_three_first_analysis(
    query: str,
    *,
    enterprise_name: str = "",
    product_name: str = "",
    award_year: int | None = None,
    from_year: int | None = None,
    to_year: int | None = None,
    include_review_candidates: bool = False,
) -> dict[str, object]:
    normalized_query = compact_text(query)
    project_type = "三首项目"
    project_name = ""
    for candidate_type, candidate_name, terms in PROJECTS:
        if any(term in normalized_query for term in terms):
            project_type = candidate_type
            project_name = candidate_name
            break

    years = [
        int(value)
        for value in re.findall(r"(?<!\d)(20\d{2})(?!\d)", normalized_query)
    ]
    effective_from_year = from_year if from_year is not None else (years[0] if years else None)
    effective_to_year = to_year if to_year is not None else (years[-1] if len(years) >= 2 else None)
    list_year = effective_to_year or effective_from_year or award_year
    diff_requested = project_type == "首批次" and any(
        term in normalized_query for term in DIFF_TERMS
    )
    match_requested = project_type == "首批次" and (
        bool(product_name.strip()) or any(term in normalized_query for term in MATCH_TERMS)
    )
    clarifications: list[str] = []
    if diff_requested and (effective_from_year is None or effective_to_year is None):
        clarifications.append("目录差异分析需要明确两个年度。")
    if match_requested and not product_name.strip():
        clarifications.append("请提供需要匹配的具体产品或材料名称。")

    return {
        "query": normalized_query,
        "project_type": project_type,
        "project_name": project_name,
        "enterprise_name": enterprise_name.strip(),
        "product_name": product_name.strip(),
        "award_year": award_year,
        "from_year": effective_from_year,
        "to_year": effective_to_year,
        "list_year": list_year,
        "include_review_candidates": bool(include_review_candidates),
        "routes": {
            "knowledge_search": True,
            "public_list_search": bool(project_name or enterprise_name.strip() or list_year),
            "directory_diff": diff_requested,
            "product_match": match_requested and bool(product_name.strip()),
        },
        "clarifications": clarifications,
    }
