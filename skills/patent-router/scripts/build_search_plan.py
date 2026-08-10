#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def unique(values):
    rows = []
    seen = set()
    for value in values:
        item = clean(value)
        key = item.casefold()
        if item and key not in seen:
            rows.append(item)
            seen.add(key)
    return rows


def normalized_features(payload):
    if payload.get("schema_version") == "technical-feature-map/v1":
        values = payload.get("search_units") or payload.get("features") or []
    else:
        values = payload.get("features") or []
    rows = []
    for index, value in enumerate(values, 1):
        if isinstance(value, str):
            rows.append(
                {
                    "feature_id": f"F{index}",
                    "feature": clean(value),
                    "role": "core" if index == 1 else "supporting",
                    "keywords": [],
                    "synonyms": [],
                    "translations": [],
                    "ipc_candidates": [],
                    "cpc_candidates": [],
                    "evidence": [],
                }
            )
            continue
        if not isinstance(value, dict):
            continue
        terms = unique(
            list(value.get("terms") or [])
            + list(value.get("search_terms") or [])
        )
        feature = clean(value.get("feature") or value.get("text") or (terms[0] if terms else ""))
        if feature and feature not in terms:
            terms.insert(0, feature)
        rows.append(
            {
                "feature_id": clean(value.get("feature_id")) or f"F{index}",
                "feature": feature,
                "role": clean(value.get("role")) or "supporting",
                "keywords": terms,
                "synonyms": unique(list(value.get("aliases") or [])),
                "translations": unique(list(value.get("translations") or [])),
                "ipc_candidates": unique(list(value.get("ipc_candidates") or [])),
                "cpc_candidates": unique(list(value.get("cpc_candidates") or [])),
                "evidence": list(value.get("evidence") or []),
            }
        )
    return [row for row in rows if row["feature"]]


def quoted(value):
    return f'"{value.replace(chr(34), "")}"'


def build_search_units(features):
    units = []
    for feature in features:
        atoms = unique(
            [feature["feature"]]
            + feature["keywords"]
            + feature["synonyms"]
            + feature["translations"]
        )
        units.append(
            {
                "unit_id": f"single:{feature['feature_id']}",
                "kind": "single_feature",
                "feature_ids": [feature["feature_id"]],
                "query_atoms": atoms,
                "generic_expression": " OR ".join(quoted(item) for item in atoms),
                "purpose": "定位单项特征的上位概念、下位实施和等同表达候选。",
                "evidence": feature["evidence"],
            }
        )
        for classification in feature["ipc_candidates"] + feature["cpc_candidates"]:
            units.append(
                {
                    "unit_id": f"classification:{feature['feature_id']}:{classification}",
                    "kind": "classification_cross",
                    "feature_ids": [feature["feature_id"]],
                    "query_atoms": atoms,
                    "classification": classification,
                    "generic_expression": f"CLASS={classification} AND ({' OR '.join(quoted(item) for item in atoms)})",
                    "purpose": "用案件级候选分类号与技术特征交叉检索；分类号仍需根据完整权利要求复核。",
                    "evidence": feature["evidence"],
                }
            )

    core = [item for item in features if item["role"] == "core"]
    supporting = [item for item in features if item["role"] == "supporting"]
    combinations = []
    if len(core) >= 2:
        combinations.append((core[0], core[1]))
    elif core and supporting:
        combinations.append((core[0], supporting[0]))
    for left, right in combinations:
        left_atom = (left["keywords"] or [left["feature"]])[0]
        right_atom = (right["keywords"] or [right["feature"]])[0]
        units.append(
            {
                "unit_id": f"combination:{left['feature_id']}+{right['feature_id']}",
                "kind": "core_combination",
                "feature_ids": [left["feature_id"], right["feature_id"]],
                "query_atoms": [left_atom, right_atom],
                "generic_expression": f"{quoted(left_atom)} AND {quoted(right_atom)}",
                "purpose": "检索核心特征组合，避免只按整段技术交底做单次语义检索。",
                "evidence": left["evidence"] + right["evidence"],
            }
        )
    return units


def build_plan(payload):
    features = normalized_features(payload)
    units = build_search_units(features)
    source_readiness = payload.get("readiness") if isinstance(payload.get("readiness"), dict) else {}
    source_search_status = clean(source_readiness.get("search"))
    source_blockers = list(source_readiness.get("blockers") or [])
    blocked_by_source = (
        payload.get("schema_version") == "technical-feature-map/v1"
        and source_search_status != "READY"
    )
    return {
        "schema_version": "patent-search-plan/v2",
        "case_id": payload.get("case_id"),
        "case_revision": payload.get("case_revision"),
        "purpose": payload.get("purpose", "未指定"),
        "jurisdictions": payload.get("jurisdictions") or [],
        "cutoff_date": payload.get("cutoff_date"),
        "source_feature_map": (
            "technical-feature-map/v1"
            if payload.get("schema_version") == "technical-feature-map/v1"
            else None
        ),
        "features": features,
        "search_units": units,
        "query_rounds": ["宽检索", "区别特征收窄", "分类号交叉", "引证与同族扩展"],
        "rounds": [
            {
                "round": 1,
                "name": "单项特征宽检索",
                "unit_kinds": ["single_feature"],
                "stop_condition": "已获得主要上位词、下位词和分类号候选，并保存检索式与结果数。",
            },
            {
                "round": 2,
                "name": "核心特征组合检索",
                "unit_kinds": ["core_combination"],
                "stop_condition": "已查明最接近组合的文献候选，不以摘要相似代替全文复核。",
            },
            {
                "round": 3,
                "name": "分类号交叉与申请人线索",
                "unit_kinds": ["classification_cross"],
                "stop_condition": "已复核分类号合理性，并对关键申请人、发明人或系列申请做扩展。",
            },
            {
                "round": 4,
                "name": "引证、被引证与同族扩展",
                "unit_kinds": [],
                "stop_condition": "已记录同族、优先权、公开日和关键引证链，明确未覆盖范围。",
            },
        ],
        "evidence_requirements": {
            "document_fields": [
                "publication_number",
                "publication_date",
                "priority_date",
                "source_url",
                "source_verified",
                "prior_art_eligible",
            ],
            "mapping_fields": [
                "feature_id",
                "status",
                "source_locators",
                "evidence_text",
                "figure_markers",
            ],
            "legal_boundary": "标题、摘要或语义相似度只能形成候选；认定已公开必须回到在先文件原文及具体定位。",
        },
        "evidence_log": [],
        "coverage": {
            "feature_count": len(features),
            "search_unit_count": len(units),
            "unmapped_features": [
                item["feature_id"] for item in features if not item["evidence"]
            ],
        },
        "readiness": {
            "status": "BLOCKED" if blocked_by_source else "READY",
            "source_search_status": source_search_status or None,
            "source_blockers": source_blockers,
            "decision_boundary": (
                "READY只表示已形成分层检索任务，不表示检索覆盖完整，"
                "也不表示任何技术特征具备新颖性或创造性。"
            ),
        },
    }


def main():
    parser = argparse.ArgumentParser(description="生成专利检索计划JSON")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--strict", action="store_true", help="来源特征图不可检索时返回失败")
    arguments = parser.parse_args()
    payload = json.loads(arguments.input.read_text(encoding="utf-8"))
    result = build_plan(payload)
    arguments.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if arguments.strict and result["readiness"]["status"] != "READY":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
