#!/usr/bin/env python3
"""企业级技术—产品—收入母矩阵与多项目视图生成器。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = (
    SKILL_DIR
    / "assets"
    / "enterprise-technical-product-revenue-matrix.template.json"
)
ADAPTERS_PATH = SKILL_DIR / "references" / "project-view-adapters.json"

ALLOWED_CARRIER_TYPES = {
    "formula",
    "material",
    "component",
    "process",
    "software",
    "embedded_software",
    "algorithm",
    "equipment",
    "other",
}
ALLOWED_PRODUCT_TYPES = {
    "material",
    "component",
    "terminal_product",
    "equipment",
    "system",
    "software",
    "embedded_software",
    "service",
    "medical_device",
    "achievement",
    "prototype",
}
ALLOWED_RELATIONS = {"embedded", "direct", "manufacturing_enabler", "deployed_with"}
ALLOWED_DEVELOPMENT_STATUS = {
    "research",
    "pilot",
    "mass_production",
    "deployed",
    "retired",
}
ALLOWED_SALES_STATUS = {"sold", "trial", "not_sold", "internal_use", "unknown"}
FORBIDDEN_KEYS = {
    "exact_formula",
    "composition_ratio",
    "raw_material_grade",
    "supplier_name",
    "addition_sequence",
    "exact_setpoint",
    "secret_recipe",
    "precise_process_steps",
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def source_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def md(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, list):
        return "；".join(md(item) for item in value)
    if isinstance(value, dict):
        return "；".join(f"{key}：{md(item)}" for key, item in value.items())
    return str(value).replace("|", "｜").replace("\n", "<br>")


def source_label(source: Any) -> str:
    if not isinstance(source, dict):
        return md(source)
    document = source.get("document", "")
    locator = source.get("locator", "")
    evidence_type = source.get("evidence_type", "")
    parts = [part for part in [document, locator, evidence_type] if part]
    return "｜".join(md(part) for part in parts)


def collect_forbidden_keys(value: Any, prefix: str = "") -> list[str]:
    issues: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else key
            if key in FORBIDDEN_KEYS:
                issues.append(path)
            issues.extend(collect_forbidden_keys(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            issues.extend(collect_forbidden_keys(child, f"{prefix}[{index}]"))
    return issues


def validate_master(data: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if data.get("schema_version") != "1.0":
        issues.append("schema_version 必须为 1.0")

    company = data.get("company")
    if not isinstance(company, dict):
        issues.append("缺少 company 对象")
    else:
        if not str(company.get("name", "")).strip():
            issues.append("company.name 不能为空")
        if not str(company.get("as_of_date", "")).strip():
            issues.append("company.as_of_date 不能为空")

    forbidden = collect_forbidden_keys(data)
    for path in forbidden:
        issues.append(f"检测到禁止写入公开母矩阵的敏感字段：{path}")

    technologies = data.get("technologies", [])
    products = data.get("products", [])
    links = data.get("technology_product_links", [])
    commercialization = data.get("commercialization", [])

    for field_name, value in [
        ("technologies", technologies),
        ("products", products),
        ("technology_product_links", links),
        ("commercialization", commercialization),
    ]:
        if not isinstance(value, list):
            issues.append(f"{field_name} 必须为数组")

    if issues and any("必须为数组" in issue for issue in issues):
        return issues

    technology_ids: set[str] = set()
    for index, technology in enumerate(technologies):
        prefix = f"technologies[{index}]"
        tech_id = str(technology.get("id", "")).strip()
        if not tech_id:
            issues.append(f"{prefix}.id 不能为空")
        elif tech_id in technology_ids:
            issues.append(f"技术ID重复：{tech_id}")
        technology_ids.add(tech_id)
        if technology.get("carrier_type") not in ALLOWED_CARRIER_TYPES:
            issues.append(f"{prefix}.carrier_type 不在允许范围")
        if technology.get("development_status") not in ALLOWED_DEVELOPMENT_STATUS:
            issues.append(f"{prefix}.development_status 不在允许范围")
        for required in [
            "internal_version",
            "public_name",
            "technical_goal",
            "public_route",
            "public_window",
        ]:
            if not str(technology.get(required, "")).strip():
                issues.append(f"{prefix}.{required} 不能为空")
        boundary = technology.get("confidential_boundary")
        if not isinstance(boundary, list) or not any(str(item).strip() for item in boundary):
            issues.append(f"{prefix}.confidential_boundary 至少填写一项")
        sources = technology.get("sources")
        if not isinstance(sources, list) or not sources:
            issues.append(f"{prefix}.sources 至少填写一项")

    product_ids: set[str] = set()
    for index, product in enumerate(products):
        prefix = f"products[{index}]"
        product_id = str(product.get("id", "")).strip()
        if not product_id:
            issues.append(f"{prefix}.id 不能为空")
        elif product_id in product_ids:
            issues.append(f"产品ID重复：{product_id}")
        product_ids.add(product_id)
        if not str(product.get("name", "")).strip():
            issues.append(f"{prefix}.name 不能为空")
        if product.get("product_type") not in ALLOWED_PRODUCT_TYPES:
            issues.append(f"{prefix}.product_type 不在允许范围")
        if product.get("sales_status") not in ALLOWED_SALES_STATUS:
            issues.append(f"{prefix}.sales_status 不在允许范围")
        sources = product.get("sources")
        if not isinstance(sources, list) or not sources:
            issues.append(f"{prefix}.sources 至少填写一项")

    linked_technologies: set[str] = set()
    for index, link in enumerate(links):
        prefix = f"technology_product_links[{index}]"
        technology_id = link.get("technology_id")
        product_id = link.get("product_id")
        if technology_id not in technology_ids:
            issues.append(f"{prefix}.technology_id 引用了不存在的技术")
        else:
            linked_technologies.add(technology_id)
        if product_id not in product_ids:
            issues.append(f"{prefix}.product_id 引用了不存在的产品")
        if link.get("relation") not in ALLOWED_RELATIONS:
            issues.append(f"{prefix}.relation 不在允许范围")
        if not isinstance(link.get("stable_use"), bool):
            issues.append(f"{prefix}.stable_use 必须为布尔值")
        contributions = link.get("performance_contributions")
        if not isinstance(contributions, list) or not contributions:
            issues.append(f"{prefix}.performance_contributions 至少填写一项")

    for technology in technologies:
        if technology.get("development_status") in {"mass_production", "deployed"}:
            if technology.get("id") not in linked_technologies:
                issues.append(
                    f"已量产或部署技术 {technology.get('id')} 未映射到任何终端产品"
                )

    for index, item in enumerate(commercialization):
        prefix = f"commercialization[{index}]"
        if item.get("product_id") not in product_ids:
            issues.append(f"{prefix}.product_id 引用了不存在的产品")
        for required in ["year", "amount", "unit", "basis"]:
            if not str(item.get(required, "")).strip():
                issues.append(f"{prefix}.{required} 不能为空")
        if item.get("basis") == "internal_transfer":
            issues.append(f"{prefix}.basis 禁止使用内部转移收入")
        if not isinstance(item.get("source"), dict):
            issues.append(f"{prefix}.source 必须为来源对象")

    return issues


def build_indexes(data: dict[str, Any]) -> dict[str, Any]:
    technologies = {item["id"]: item for item in data.get("technologies", [])}
    products = {item["id"]: item for item in data.get("products", [])}
    links_by_technology: dict[str, list[dict[str, Any]]] = {}
    links_by_product: dict[str, list[dict[str, Any]]] = {}
    for link in data.get("technology_product_links", []):
        links_by_technology.setdefault(link["technology_id"], []).append(link)
        links_by_product.setdefault(link["product_id"], []).append(link)
    commercialization_by_product: dict[str, list[dict[str, Any]]] = {}
    for item in data.get("commercialization", []):
        commercialization_by_product.setdefault(item["product_id"], []).append(item)
    return {
        "technologies": technologies,
        "products": products,
        "links_by_technology": links_by_technology,
        "links_by_product": links_by_product,
        "commercialization_by_product": commercialization_by_product,
    }


def carrier_as_product_type(carrier_type: str) -> str | None:
    mapping = {
        "formula": "material",
        "material": "material",
        "component": "component",
        "software": "software",
        "embedded_software": "embedded_software",
        "equipment": "equipment",
    }
    return mapping.get(carrier_type)


def technology_is_candidate(
    technology: dict[str, Any], adapter: dict[str, Any]
) -> bool:
    if not adapter.get("allow_embedded_technology_as_subject"):
        return False
    mode = adapter.get("subject_mode")
    if mode in {
        "minimum_sufficient_unit",
        "task_or_achievement",
        "achievement",
        "high_tech_product_or_service",
    }:
        return True
    product_type = carrier_as_product_type(technology.get("carrier_type", ""))
    return product_type in adapter.get("accepted_product_types", [])


def product_is_candidate(product: dict[str, Any], adapter: dict[str, Any]) -> bool:
    return product.get("product_type") in adapter.get("accepted_product_types", [])


def linked_product_summary(
    technology_id: str, indexes: dict[str, Any]
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for link in indexes["links_by_technology"].get(technology_id, []):
        product = indexes["products"].get(link["product_id"], {})
        summaries.append(
            {
                "product_id": product.get("id", ""),
                "product_name": product.get("name", ""),
                "product_type": product.get("product_type", ""),
                "relation": link.get("relation", ""),
                "stable_use": link.get("stable_use", False),
                "performance_contributions": link.get(
                    "performance_contributions", []
                ),
                "commercialization": indexes["commercialization_by_product"].get(
                    product.get("id", ""), []
                ),
            }
        )
    return summaries


def product_technology_summary(
    product_id: str, indexes: dict[str, Any]
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for link in indexes["links_by_product"].get(product_id, []):
        technology = indexes["technologies"].get(link["technology_id"], {})
        summaries.append(
            {
                "technology_id": technology.get("id", ""),
                "internal_version": technology.get("internal_version", ""),
                "public_name": technology.get("public_name", ""),
                "carrier_type": technology.get("carrier_type", ""),
                "relation": link.get("relation", ""),
                "stable_use": link.get("stable_use", False),
                "performance_contributions": link.get(
                    "performance_contributions", []
                ),
            }
        )
    return summaries


def project_specific_notes(
    project_id: str,
    technology_candidates: list[dict[str, Any]],
    product_candidates: list[dict[str, Any]],
) -> list[str]:
    notes: list[str] = []
    if project_id == "first_batch_material":
        material_products = [
            item
            for item in product_candidates
            if item.get("product_type") == "material"
        ]
        if technology_candidates and not material_products:
            notes.append(
                "发现材料或配方技术载体，但未发现独立材料产品记录。技术真实性可以保留，材料申报对象、目录品类及商业化口径必须专项核验。"
            )
    if project_id == "first_edition_software":
        if technology_candidates and not product_candidates:
            notes.append(
                "发现软件或嵌入式软件技术载体，但未发现独立软件产品记录。需补软件版本、软著、检测、硬件载体及专项审计映射。"
            )
    if project_id == "first_set_equipment" and not product_candidates:
        notes.append(
            "未发现整机或成套系统产品。核心部件、算法或工艺不能自动取代首台套申报边界。"
        )
    if project_id == "innovative_medical_device" and not product_candidates:
        notes.append(
            "未发现医疗器械产品边界。核心材料、部件或算法不能绕过注册产品和审评要求。"
        )
    if project_id == "high_tech_enterprise":
        notes.append(
            "本视图不自动汇总高新收入。最终口径以高新技术产品或服务专项审计为准。"
        )
    return notes


def build_project_view(
    data: dict[str, Any],
    project_id: str,
    adapter: dict[str, Any],
    master_hash: str,
) -> dict[str, Any]:
    indexes = build_indexes(data)
    technology_candidates: list[dict[str, Any]] = []
    product_candidates: list[dict[str, Any]] = []

    for technology in data.get("technologies", []):
        if not technology_is_candidate(technology, adapter):
            continue
        technology_candidates.append(
            {
                "subject_kind": "technology",
                "subject_id": technology["id"],
                "subject_name": technology.get("public_name", ""),
                "internal_version": technology.get("internal_version", ""),
                "carrier_type": technology.get("carrier_type", ""),
                "technical_goal": technology.get("technical_goal", ""),
                "public_route": technology.get("public_route", ""),
                "public_window": technology.get("public_window", ""),
                "linked_products": linked_product_summary(
                    technology["id"], indexes
                ),
                "sources": technology.get("sources", []),
                "confidential_boundary": technology.get(
                    "confidential_boundary", []
                ),
            }
        )

    for product in data.get("products", []):
        if not product_is_candidate(product, adapter):
            continue
        product_candidates.append(
            {
                "subject_kind": "product",
                "subject_id": product["id"],
                "subject_name": product.get("name", ""),
                "product_type": product.get("product_type", ""),
                "sales_status": product.get("sales_status", ""),
                "policy_attributes": product.get("policy_attributes", []),
                "registered_or_catalog_name": product.get(
                    "registered_or_catalog_name", ""
                ),
                "linked_technologies": product_technology_summary(
                    product["id"], indexes
                ),
                "commercialization": indexes[
                    "commercialization_by_product"
                ].get(product["id"], []),
                "sources": product.get("sources", []),
            }
        )

    has_candidates = bool(technology_candidates or product_candidates)
    status = "结构已生成，待政策核验" if has_candidates else "需换层或不适用"
    notes = project_specific_notes(
        project_id, technology_candidates, product_candidates
    )

    override = data.get("project_overrides", {}).get(project_id, {})
    return {
        "view_schema_version": "1.0",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "master_sha256": master_hash,
        "company": data.get("company", {}),
        "project": {
            "id": project_id,
            "label": adapter.get("label", project_id),
            "subject_mode": adapter.get("subject_mode", ""),
            "commercial_basis": adapter.get("commercial_basis", ""),
            "narrative_focus": adapter.get("narrative_focus", []),
            "policy_gates": adapter.get("policy_gates", []),
        },
        "status": status,
        "technology_subject_candidates": technology_candidates,
        "product_subject_candidates": product_candidates,
        "project_specific_notes": notes,
        "manual_override": override,
        "decision_boundary": "本视图只完成技术、产品和商业化口径转换，不自动形成项目达标或可申报结论。",
    }


def render_master_markdown(data: dict[str, Any], master_hash: str) -> str:
    company = data.get("company", {})
    indexes = build_indexes(data)
    lines = [
        f"# {company.get('name', '')} 企业级技术—产品—收入母矩阵",
        "",
        f"- 数据截至：{company.get('as_of_date', '')}",
        f"- 统一社会信用代码：{company.get('credit_code', '') or '未填写'}",
        f"- 母矩阵SHA-256：`{master_hash}`",
        "- 使用边界：本底稿用于项目口径转换，不自动认定任何项目达标。",
        "",
        "## 一、核心技术版本",
        "",
        "| 技术ID | 内部版本 | 载体类型 | 可公开名称 | 技术目标 | 可公开技术路线 | 可公开窗口 | 状态 | 来源 | 保密边界 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for item in data.get("technologies", []):
        lines.append(
            "| {id} | {version} | {carrier} | {name} | {goal} | {route} | {window} | {status} | {sources} | {boundary} |".format(
                id=md(item.get("id")),
                version=md(item.get("internal_version")),
                carrier=md(item.get("carrier_type")),
                name=md(item.get("public_name")),
                goal=md(item.get("technical_goal")),
                route=md(item.get("public_route")),
                window=md(item.get("public_window")),
                status=md(item.get("development_status")),
                sources=md([source_label(x) for x in item.get("sources", [])]),
                boundary=md(item.get("confidential_boundary", [])),
            )
        )

    lines.extend(
        [
            "",
            "## 二、产品与政策属性",
            "",
            "| 产品ID | 产品名称 | 产品类型 | 销售状态 | 项目属性 | 注册或目录名称 | 来源 |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for item in data.get("products", []):
        lines.append(
            "| {id} | {name} | {kind} | {sales} | {attrs} | {catalog} | {sources} |".format(
                id=md(item.get("id")),
                name=md(item.get("name")),
                kind=md(item.get("product_type")),
                sales=md(item.get("sales_status")),
                attrs=md(item.get("policy_attributes", [])),
                catalog=md(item.get("registered_or_catalog_name")),
                sources=md([source_label(x) for x in item.get("sources", [])]),
            )
        )

    lines.extend(
        [
            "",
            "## 三、技术—产品—性能映射",
            "",
            "| 技术版本 | 终端产品 | 关系 | 稳定使用 | 性能贡献 | 映射来源 |",
            "|---|---|---|---|---|---|",
        ]
    )
    for link in data.get("technology_product_links", []):
        technology = indexes["technologies"].get(link.get("technology_id"), {})
        product = indexes["products"].get(link.get("product_id"), {})
        contributions = [
            f"{item.get('metric', '')}：{item.get('value', '')}｜{item.get('status', '')}"
            for item in link.get("performance_contributions", [])
        ]
        lines.append(
            "| {tech} | {product} | {relation} | {stable} | {performance} | {source} |".format(
                tech=md(
                    f"{technology.get('internal_version', '')}｜{technology.get('public_name', '')}"
                ),
                product=md(product.get("name")),
                relation=md(link.get("relation")),
                stable=md(link.get("stable_use")),
                performance=md(contributions),
                source=source_label(link.get("source", {})),
            )
        )

    lines.extend(
        [
            "",
            "## 四、产品—收入或应用结果",
            "",
            "| 产品 | 年度 | 金额或效益值 | 单位 | 归因基础 | 客户或应用范围 | 来源 |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for item in data.get("commercialization", []):
        product = indexes["products"].get(item.get("product_id"), {})
        lines.append(
            "| {product} | {year} | {amount} | {unit} | {basis} | {scope} | {source} |".format(
                product=md(product.get("name")),
                year=md(item.get("year")),
                amount=md(item.get("amount")),
                unit=md(item.get("unit")),
                basis=md(item.get("basis")),
                scope=md(item.get("customer_or_application_scope")),
                source=source_label(item.get("source", {})),
            )
        )

    lines.extend(
        [
            "",
            "## 五、两链汇合规则",
            "",
            "先由技术资料确认核心技术载体、稳定生产或部署、终端嵌入和性能贡献，再由销售或应用资料核对终端商业化结果。发票没有核心技术名称，不用于否定技术真实性；同时不得虚构内部转移收入。",
            "",
        ]
    )
    return "\n".join(lines)


def performance_summary(candidate: dict[str, Any]) -> str:
    contributions: list[str] = []
    for linked in candidate.get("linked_products", []):
        for item in linked.get("performance_contributions", []):
            contributions.append(
                f"{item.get('metric', '')}：{item.get('value', '')}"
            )
    for linked in candidate.get("linked_technologies", []):
        for item in linked.get("performance_contributions", []):
            contributions.append(
                f"{item.get('metric', '')}：{item.get('value', '')}"
            )
    return md(contributions)


def commercialization_summary(candidate: dict[str, Any]) -> str:
    items: list[dict[str, Any]] = []
    items.extend(candidate.get("commercialization", []))
    for linked in candidate.get("linked_products", []):
        items.extend(linked.get("commercialization", []))
    summaries = [
        f"{item.get('year', '')}年 {item.get('amount', '')}{item.get('unit', '')}｜{item.get('basis', '')}"
        for item in items
    ]
    return md(summaries)


def render_project_markdown(view: dict[str, Any]) -> str:
    company = view.get("company", {})
    project = view.get("project", {})
    lines = [
        f"# {company.get('name', '')}｜{project.get('label', '')}项目口径视图",
        "",
        f"- 生成时间：{view.get('generated_at', '')}",
        f"- 母矩阵SHA-256：`{view.get('master_sha256', '')}`",
        f"- 转换状态：**{view.get('status', '')}**",
        f"- 项目申报对象模式：{project.get('subject_mode', '')}",
        f"- 商业化或应用口径：{project.get('commercial_basis', '')}",
        "",
        "> 本视图只完成技术、产品和商业化口径转换，不自动形成项目达标或可申报结论。",
        "",
        "## 一、技术载体候选",
        "",
        "| 技术版本 | 可公开名称 | 载体类型 | 技术目标 | 可公开路线及窗口 | 终端产品 | 性能贡献 | 商业化承载 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    technologies = view.get("technology_subject_candidates", [])
    if technologies:
        for item in technologies:
            linked_names = [
                linked.get("product_name", "")
                for linked in item.get("linked_products", [])
            ]
            lines.append(
                "| {version} | {name} | {carrier} | {goal} | {route}；{window} | {products} | {performance} | {commercial} |".format(
                    version=md(item.get("internal_version")),
                    name=md(item.get("subject_name")),
                    carrier=md(item.get("carrier_type")),
                    goal=md(item.get("technical_goal")),
                    route=md(item.get("public_route")),
                    window=md(item.get("public_window")),
                    products=md(linked_names),
                    performance=performance_summary(item),
                    commercial=commercialization_summary(item),
                )
            )
    else:
        lines.append("| 不适用 | 未形成技术载体候选 | | | | | | |")

    lines.extend(
        [
            "",
            "## 二、产品申报对象候选",
            "",
            "| 产品名称 | 产品类型 | 销售状态 | 注册或目录名称 | 关联技术 | 商业化或应用结果 | 自动转换结论 |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    products = view.get("product_subject_candidates", [])
    if products:
        for item in products:
            linked_tech = [
                f"{linked.get('internal_version', '')}｜{linked.get('public_name', '')}"
                for linked in item.get("linked_technologies", [])
            ]
            lines.append(
                "| {name} | {kind} | {sales} | {catalog} | {tech} | {commercial} | 结构已生成，待政策核验 |".format(
                    name=md(item.get("subject_name")),
                    kind=md(item.get("product_type")),
                    sales=md(item.get("sales_status")),
                    catalog=md(item.get("registered_or_catalog_name")),
                    tech=md(linked_tech),
                    commercial=commercialization_summary(item),
                )
            )
    else:
        lines.append("| 未发现同类型产品 | | | | | | 需换层或判定不适用 |")

    lines.extend(
        [
            "",
            "## 三、项目叙事转换",
            "",
            f"- 叙事重点：{md(project.get('narrative_focus', []))}",
            "- 固定因果链：核心技术载体→稳定生产或部署→终端应用→性能贡献→商业化或应用结果。",
            "- 收入边界：仅使用项目政策认可的终端收入、软件收入、应用效益或专项审计口径，不确认内部虚拟转移收入。",
            "",
            "## 四、项目专项门槛",
            "",
        ]
    )
    for gate in project.get("policy_gates", []):
        lines.append(f"- [ ] {md(gate)}")
    for note in view.get("project_specific_notes", []):
        lines.append(f"- 提示：{md(note)}")

    lines.extend(
        [
            "",
            "## 五、人工决策边界",
            "",
            "本视图不得替代政策原文核验。最终申报对象、收入归集、目录归属、检测注册及资格结论须按当期项目规则确认。",
            "",
        ]
    )
    return "\n".join(lines)


def init_master(args: argparse.Namespace) -> int:
    output = Path(args.output).expanduser().resolve()
    if output.exists() and not args.force:
        print(f"目标已存在：{output}。如需覆盖请使用 --force。", file=sys.stderr)
        return 2
    template = load_json(TEMPLATE_PATH)
    template["company"]["name"] = args.company
    template["company"]["as_of_date"] = args.as_of or date.today().isoformat()
    if args.credit_code:
        template["company"]["credit_code"] = args.credit_code
    write_json(output, template)
    print(f"已创建母矩阵模板：{output}")
    print("模板包含占位内容，填写完成后请先运行 validate。")
    return 0


def validate_command(args: argparse.Namespace) -> int:
    input_path = Path(args.input).expanduser().resolve()
    data = load_json(input_path)
    issues = validate_master(data)
    if issues:
        print("母矩阵校验未通过：", file=sys.stderr)
        for issue in issues:
            print(f"- {issue}", file=sys.stderr)
        return 1
    print("母矩阵校验通过")
    return 0


def selected_projects(raw: str, adapters: dict[str, Any]) -> list[str]:
    if raw == "all":
        return list(adapters)
    projects = [item.strip() for item in raw.split(",") if item.strip()]
    unknown = [item for item in projects if item not in adapters]
    if unknown:
        raise ValueError(f"未知项目适配器：{', '.join(unknown)}")
    return projects


def build_command(args: argparse.Namespace) -> int:
    input_path = Path(args.input).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    data = load_json(input_path)
    issues = validate_master(data)
    if issues:
        print("母矩阵校验未通过，停止生成：", file=sys.stderr)
        for issue in issues:
            print(f"- {issue}", file=sys.stderr)
        return 1

    adapters_data = load_json(ADAPTERS_PATH)
    adapters = adapters_data["adapters"]
    try:
        projects = selected_projects(args.projects, adapters)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    master_sha256 = source_hash(input_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_text(
        output_dir / "enterprise_master_matrix.md",
        render_master_markdown(data, master_sha256),
    )
    views_dir = output_dir / "project_views"
    manifest_views: dict[str, Any] = {}
    for project_id in projects:
        view = build_project_view(
            data, project_id, adapters[project_id], master_sha256
        )
        json_path = views_dir / f"{project_id}.json"
        md_path = views_dir / f"{project_id}.md"
        write_json(json_path, view)
        write_text(md_path, render_project_markdown(view))
        manifest_views[project_id] = {
            "label": adapters[project_id]["label"],
            "status": view["status"],
            "json": str(json_path),
            "markdown": str(md_path),
        }

    manifest = {
        "manifest_schema_version": "1.0",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "company": data["company"],
        "source_master": str(input_path),
        "source_master_sha256": master_sha256,
        "master_markdown": str(output_dir / "enterprise_master_matrix.md"),
        "project_views": manifest_views,
        "freshness_rule": "读取项目前先比较 source_master_sha256；不一致时重新生成全部项目视图。",
    }
    write_json(output_dir / "manifest.json", manifest)
    print(f"已生成企业母矩阵和 {len(projects)} 个项目视图：{output_dir}")
    return 0


def list_projects_command(_: argparse.Namespace) -> int:
    adapters = load_json(ADAPTERS_PATH)["adapters"]
    for project_id, adapter in adapters.items():
        print(f"{project_id}\t{adapter.get('label', '')}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="企业级技术—产品—收入母矩阵与多项目视图生成器"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="创建母矩阵模板")
    init_parser.add_argument("--company", required=True, help="企业全称")
    init_parser.add_argument("--credit-code", default="", help="统一社会信用代码")
    init_parser.add_argument("--as-of", default="", help="数据截至日期 YYYY-MM-DD")
    init_parser.add_argument("--output", required=True, help="母矩阵JSON输出路径")
    init_parser.add_argument("--force", action="store_true", help="允许覆盖目标文件")
    init_parser.set_defaults(func=init_master)

    validate_parser = subparsers.add_parser("validate", help="校验母矩阵")
    validate_parser.add_argument("--input", required=True, help="母矩阵JSON路径")
    validate_parser.set_defaults(func=validate_command)

    build_parser_command = subparsers.add_parser(
        "build", help="生成企业母矩阵Markdown与多项目视图"
    )
    build_parser_command.add_argument("--input", required=True, help="母矩阵JSON路径")
    build_parser_command.add_argument(
        "--output-dir", required=True, help="项目视图输出目录"
    )
    build_parser_command.add_argument(
        "--projects",
        default="all",
        help="all 或以逗号分隔的项目适配器ID",
    )
    build_parser_command.set_defaults(func=build_command)

    list_parser = subparsers.add_parser("list-projects", help="列出项目适配器")
    list_parser.set_defaults(func=list_projects_command)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
