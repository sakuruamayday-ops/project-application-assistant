#!/usr/bin/env python3
"""把权利要求引用图、IPC检索蓝图和现有技术证据串成可审计对照表。"""

import argparse
import difflib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EQUIVALENCE_RULES = ROOT / "references" / "technical-equivalence-rules.json"


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def evidence_snippets(text, terms, limit=3):
    rows = []
    for term in terms:
        match = re.search(re.escape(term), text, flags=re.I)
        if not match:
            continue
        start = max(0, match.start() - 35)
        end = min(len(text), match.end() + 65)
        snippet = re.sub(r"\s+", " ", text[start:end]).strip()
        if snippet and snippet not in rows:
            rows.append(snippet)
        if len(rows) >= limit:
            break
    return rows


def figure_markers(text):
    rows = []
    for value in re.findall(r"(?:附图|图)\s*\d+[A-Za-z]?|附图标记\s*\d+", text):
        value = re.sub(r"\s+", "", value)
        if value not in rows:
            rows.append(value)
    return rows


def auto_passages(text):
    if not text:
        return []
    marker = re.compile(r"(?m)^\s*(\[\d{4}\]|【\d{4}】|权利要求\s*\d+|图\s*\d+[A-Za-z]?)")
    matches = list(marker.finditer(text))
    if not matches:
        return [
            {
                "kind": "full_text",
                "locator": "全文",
                "text": text,
                "figure_markers": figure_markers(text),
            }
        ]
    rows = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        passage = re.sub(r"\s+", " ", text[match.start():end]).strip()
        rows.append(
            {
                "kind": (
                    "claim"
                    if match.group(1).startswith("权利要求")
                    else "figure"
                    if match.group(1).startswith("图")
                    else "paragraph"
                ),
                "locator": match.group(1),
                "text": passage,
                "figure_markers": figure_markers(passage),
            }
        )
    return rows


def normalize_passages(item):
    rows = item.get("passages") or auto_passages(item.get("text", ""))
    normalized = []
    for index, row in enumerate(rows, 1):
        text = row.get("text", "")
        normalized.append(
            {
                "kind": row.get("kind", "paragraph"),
                "locator": row.get("locator") or f"片段{index}",
                "text": text,
                "figure_markers": row.get("figure_markers") or figure_markers(text),
            }
        )
    return normalized


def semantic_normalize(text, equivalence_rules):
    value = re.sub(r"\s+|[，。；、,;:：()（）\[\]【】]", "", text.lower())
    for group in equivalence_rules.get("canonical_groups", []):
        canonical = f"<{group['canonical']}>"
        for term in sorted(group["terms"], key=len, reverse=True):
            value = value.replace(term.lower(), canonical)
    return value


def ngrams(text, size=3):
    if len(text) <= size:
        return {text} if text else set()
    return {text[index:index + size] for index in range(len(text) - size + 1)}


def semantic_score(left, right, equivalence_rules):
    a = semantic_normalize(left, equivalence_rules)
    b = semantic_normalize(right, equivalence_rules)
    if not a or not b:
        return 0.0
    sequence = difflib.SequenceMatcher(None, a, b).ratio()
    ga, gb = ngrams(a), ngrams(b)
    jaccard = len(ga & gb) / len(ga | gb) if ga | gb else 0.0
    return round(sequence * 0.45 + jaccard * 0.55, 4)


def feature_terms(feature_text, ipc_candidates):
    terms = []
    for candidate in ipc_candidates:
        for hit in candidate.get("matched_keywords", []):
            term = hit["keyword"]
            if term.lower() in feature_text.lower() and term not in terms:
                terms.append(term)
    if terms:
        return terms
    for value in re.findall(r"[A-Za-z][A-Za-z0-9+-]{1,20}|[\u4e00-\u9fff]{2,12}", feature_text):
        if value not in terms:
            terms.append(value)
    return terms[:8]


def normalized_documents(prior_art):
    rows = []
    for item in prior_art.get("documents", []):
        document_id = item.get("document_id") or item.get("publication_number")
        if not document_id:
            raise ValueError("每份现有技术必须提供 document_id 或 publication_number")
        passages = normalize_passages(item)
        full_text = item.get("text", "") or "\n".join(
            row["text"] for row in passages
        )
        rows.append(
            {
                "document_id": document_id,
                "title": item.get("title"),
                "publication_date": item.get("publication_date"),
                "source_url": item.get("source_url"),
                "source_verified": bool(item.get("source_verified")),
                "prior_art_eligible": bool(item.get("prior_art_eligible")),
                "evidence_level": item.get("evidence_level"),
                "procedural_role": item.get("procedural_role"),
                "text": full_text,
                "passages": passages,
                "feature_mappings": item.get("feature_mappings", []),
            }
        )
    return rows


def explicit_mapping(document, feature_id):
    for mapping in document["feature_mappings"]:
        if mapping.get("feature_id") == feature_id:
            return mapping
    return None


def mapping_locators(mapping):
    rows = list(mapping.get("source_locators", []))
    for item in mapping.get("evidence", []):
        if isinstance(item, dict) and item.get("locator") and item["locator"] not in rows:
            rows.append(item["locator"])
    return rows


def build_matrix(chain, documents, equivalence_rules):
    matrix = []
    ipc_candidates = chain.get("ipc_candidates", [])
    for claim in chain.get("independent_claim_feature_tree", []):
        for feature in claim["necessary_technical_features"]:
            terms = feature_terms(feature["text"], ipc_candidates)
            comparisons = []
            for document in documents:
                mapping = explicit_mapping(document, feature["feature_id"])
                passage_candidates = []
                for passage in document["passages"]:
                    matched_terms = [
                        term for term in terms if term.lower() in passage["text"].lower()
                    ]
                    score = semantic_score(
                        feature["text"], passage["text"], equivalence_rules
                    )
                    if matched_terms or score >= 0.42:
                        passage_candidates.append(
                            {
                                "kind": passage["kind"],
                                "locator": passage["locator"],
                                "text": passage["text"],
                                "figure_markers": passage["figure_markers"],
                                "matched_terms": matched_terms,
                                "semantic_score": score,
                            }
                        )
                passage_candidates.sort(
                    key=lambda item: (
                        -len(item["matched_terms"]),
                        -item["semantic_score"],
                        item["locator"],
                    )
                )
                passage_candidates = passage_candidates[:5]
                if mapping:
                    status = mapping.get("status", "uncertain")
                    evidence = mapping.get("evidence", [])
                    basis = "verified_feature_mapping"
                    source_locators = mapping_locators(mapping)
                    if status == "disclosed" and (not evidence or not source_locators):
                        status = "MAPPING_INCOMPLETE"
                        basis = "mapping_missing_evidence_or_locator"
                elif any(item["matched_terms"] for item in passage_candidates):
                    status = "LEXICAL_REVIEW_REQUIRED"
                    evidence = passage_candidates
                    basis = "machine_candidate_only"
                    source_locators = [
                        item["locator"] for item in passage_candidates
                    ]
                elif passage_candidates:
                    status = "SEMANTIC_REVIEW_REQUIRED"
                    evidence = passage_candidates
                    basis = "hybrid_semantic_candidate_only"
                    source_locators = [
                        item["locator"] for item in passage_candidates
                    ]
                else:
                    status = "NOT_LOCATED_IN_PROVIDED_TEXT"
                    evidence = []
                    basis = "machine_candidate_only"
                    source_locators = []
                comparisons.append(
                    {
                        "document_id": document["document_id"],
                        "status": status,
                        "basis": basis,
                        "matched_terms": [
                            term for term in terms if term.lower() in document["text"].lower()
                        ],
                        "evidence": evidence,
                        "source_locators": source_locators,
                        "candidate_passages": passage_candidates,
                        "source_url": document["source_url"],
                    }
                )
            matrix.append(
                {
                    "claim_number": claim["claim_number"],
                    "protection_object": claim["protection_object"],
                    "feature_id": feature["feature_id"],
                    "feature_text": feature["text"],
                    "feature_structure": feature.get("structure", {}),
                    "application_locator": {
                        "claim_number": claim["claim_number"],
                        "figure_markers": feature.get("structure", {}).get(
                            "figure_markers", []
                        ),
                    },
                    "ipc_candidates": [item["code"] for item in ipc_candidates[:5]],
                    "search_terms": terms,
                    "comparisons": comparisons,
                }
            )
    return matrix


def patentability_screening(chain, documents, matrix):
    by_claim = {}
    for row in matrix:
        by_claim.setdefault(row["claim_number"], []).append(row)
    results = []
    for claim_number, rows in by_claim.items():
        full_mapping_docs = []
        closest = None
        closest_score = (-1, -1)
        for document in documents:
            statuses = []
            explicit_count = 0
            candidate_count = 0
            for row in rows:
                cell = next(
                    item
                    for item in row["comparisons"]
                    if item["document_id"] == document["document_id"]
                )
                statuses.append(cell["status"])
                explicit_count += cell["status"] == "disclosed"
                candidate_count += cell["status"] in (
                    "LEXICAL_REVIEW_REQUIRED",
                    "SEMANTIC_REVIEW_REQUIRED",
                )
            if (
                document["source_verified"]
                and document["prior_art_eligible"]
                and statuses
                and all(status == "disclosed" for status in statuses)
                and all(
                    next(
                        item
                        for item in row["comparisons"]
                        if item["document_id"] == document["document_id"]
                    )["source_locators"]
                    for row in rows
                )
            ):
                full_mapping_docs.append(document["document_id"])
            score = (explicit_count, candidate_count)
            if score > closest_score:
                closest_score = score
                closest = document["document_id"]
        distinguishing = []
        if closest:
            for row in rows:
                cell = next(
                    item
                    for item in row["comparisons"]
                    if item["document_id"] == closest
                )
                if cell["status"] != "disclosed":
                    distinguishing.append(row["feature_id"])
        results.append(
            {
                "claim_number": claim_number,
                "novelty_screening": {
                    "result": (
                        "POTENTIAL_SINGLE_DOCUMENT_NOVELTY_RISK"
                        if full_mapping_docs
                        else "NO_VERIFIED_SINGLE_DOCUMENT_FULL_MAPPING_IN_CURRENT_EVIDENCE"
                    ),
                    "full_mapping_documents": full_mapping_docs,
                    "legal_boundary": "仅在同一份、公开日在先且来源已核验的文件逐项公开全部必要技术特征时形成新颖性风险；本字段是初筛，不代替法律意见。",
                },
                "inventiveness_screening": {
                    "closest_prior_art_candidate": closest,
                    "distinguishing_feature_ids": distinguishing,
                    "objective_technical_problem": None,
                    "technical_teaching_or_motivation": "REQUIRES_SEPARATE_EVIDENCE",
                    "result": (
                        "REQUIRES_DIFFERENCE_EFFECT_AND_TEACHING_ANALYSIS"
                        if closest
                        else "AWAITING_PRIOR_ART"
                    ),
                },
            }
        )
    return results


def office_action_scaffold(documents, matrix):
    cited = [
        document["document_id"]
        for document in documents
        if document.get("procedural_role") == "examiner_cited"
    ]
    by_claim = {}
    for row in matrix:
        by_claim.setdefault(row["claim_number"], []).append(row)
    claims = []
    for claim_number, rows in by_claim.items():
        disputed = []
        locator_gaps = []
        for row in rows:
            for cell in row["comparisons"]:
                if cell["document_id"] not in cited:
                    continue
                if cell["status"] != "disclosed":
                    disputed.append(
                        {
                            "feature_id": row["feature_id"],
                            "document_id": cell["document_id"],
                            "status": cell["status"],
                        }
                    )
                if cell["status"] in ("disclosed", "MAPPING_INCOMPLETE") and not cell[
                    "source_locators"
                ]:
                    locator_gaps.append(
                        {
                            "feature_id": row["feature_id"],
                            "document_id": cell["document_id"],
                        }
                    )
        claims.append(
            {
                "claim_number": claim_number,
                "examiner_cited_documents": cited,
                "disputed_or_unverified_features": disputed,
                "locator_gaps": locator_gaps,
                "analysis_sequence": [
                    "核对审查意见对该特征的原文定位和解释",
                    "核对对比文件上下文权利要求及相关附图",
                    "判断是否为明确公开、隐含公开、语义候选或未公开",
                    "确定区别特征的技术效果和实际解决的技术问题",
                    "核验是否存在技术启示、组合动机及相反教导",
                    "比较意见陈述、限缩修改、重组权利要求或分案方案",
                ],
            }
        )
    return {
        "ready": bool(cited),
        "examiner_cited_documents": cited,
        "claims": claims,
    }


def markdown(payload):
    lines = [
        "# 权利要求引用关系与现有技术对照",
        "",
        f"- 证据链基准日：{payload.get('cutoff_date')}",
        f"- 主IPC候选：{', '.join(payload.get('primary_ipc_candidates', [])) or '未形成'}",
        "",
        "## 权利要求关系图",
        "",
        "```mermaid",
        payload.get("claim_reference_graph_mermaid", "graph TD"),
        "```",
        "",
        "| 权利要求 | 类型 | 保护客体 | 引用 |",
        "|---:|---|---|---|",
    ]
    for node in payload["claim_reference_graph"].get("nodes", []):
        refs = "、".join(map(str, node["referenced_claims"])) or "-"
        lines.append(
            f"| {node['claim_number']} | {node['relation_type']} | {node['protection_object']} | {refs} |"
        )
    lines.extend(
        [
            "",
            "## Claim Chart：区别技术特征—现有技术对照表",
            "",
        ]
    )
    document_ids = [
        item["document_id"] for item in payload.get("prior_art_documents", [])
    ]
    headers = ["申请定位", "特征ID", "必要技术特征"] + (
        document_ids or ["现有技术"]
    )
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join(["---"] * len(headers)) + "|")
    for row in payload["feature_prior_art_matrix"]:
        feature = row["feature_text"].replace("|", "｜")
        app_figures = "、".join(
            row["application_locator"].get("figure_markers", [])
        )
        application_locator = f"权利要求{row['claim_number']}"
        if app_figures:
            application_locator += f"<br>{app_figures}"
        cells = [application_locator, row["feature_id"], feature]
        by_document = {
            item["document_id"]: item for item in row["comparisons"]
        }
        for document_id in document_ids:
            comparison = by_document[document_id]
            locators = "、".join(comparison.get("source_locators", []))
            figures = []
            for passage in comparison.get("candidate_passages", []):
                for marker in passage.get("figure_markers", []):
                    if marker not in figures:
                        figures.append(marker)
            value = comparison["status"]
            if locators:
                value += f"<br>定位：{locators}"
            if figures:
                value += f"<br>附图：{'、'.join(figures)}"
            cells.append(value)
        if not document_ids:
            cells.append("待执行查新并回填证据")
        lines.append("| " + " | ".join(cells) + " |")
    lines.extend(
        [
            "",
            "## 新颖性与创造性初筛",
            "",
            "未命中只能理解为当前证据范围未定位，不得表述为不存在现有技术。",
            "",
        ]
    )
    for result in payload["patentability_screening"]:
        lines.append(
            f"- 权利要求{result['claim_number']}："
            f"{result['novelty_screening']['result']}；"
            f"{result['inventiveness_screening']['result']}。"
        )
    lines.extend(
        [
            "",
            "## 审查意见分析工作区",
            "",
        ]
    )
    office = payload["office_action_analysis"]
    if not office["ready"]:
        lines.append("尚未标记审查员引用文件；取得审查意见后将相应文件设为 `examiner_cited`。")
    else:
        for claim in office["claims"]:
            disputed = "、".join(
                item["feature_id"]
                for item in claim["disputed_or_unverified_features"]
            ) or "无"
            lines.append(
                f"- 权利要求{claim['claim_number']}：待争议或待核验特征 {disputed}。"
            )
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-chain", required=True)
    parser.add_argument("--prior-art")
    parser.add_argument("--out-json")
    parser.add_argument("--out-md")
    args = parser.parse_args()
    chain = load_json(args.evidence_chain)
    prior_art = load_json(args.prior_art) if args.prior_art else {"documents": []}
    documents = normalized_documents(prior_art)
    equivalence_rules = load_json(EQUIVALENCE_RULES)
    matrix = build_matrix(chain, documents, equivalence_rules)
    payload = {
        "schema_version": "1.1",
        "cutoff_date": chain.get("cutoff_date"),
        "source_document_sha256": chain.get("source_document", {}).get("sha256"),
        "claim_reference_graph": chain.get("claim_reference_graph", {}),
        "claim_reference_graph_mermaid": chain.get(
            "claim_reference_graph_mermaid", "graph TD"
        ),
        "primary_ipc_candidates": [
            item["code"] for item in chain.get("ipc_candidates", [])[:5]
        ],
        "prior_art_search_blueprint": chain.get("prior_art_search_blueprint", {}),
        "prior_art_documents": [
            {
                key: value
                for key, value in item.items()
                if key not in ("text", "passages", "feature_mappings")
            }
            for item in documents
        ],
        "semantic_equivalence_policy": equivalence_rules,
        "feature_prior_art_matrix": matrix,
        "patentability_screening": patentability_screening(
            chain, documents, matrix
        ),
        "office_action_analysis": office_action_scaffold(documents, matrix),
        "legal_boundary": [
            "机器词项命中只能作为待复核候选，不能自动记为技术特征已公开。",
            "新颖性逐项判断单一在先文件；创造性另行判断最接近现有技术、区别特征、技术效果、实际技术问题和技术启示。",
            "查无结果只能写当前检索范围未命中。",
        ],
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out_json:
        Path(args.out_json).write_text(text + "\n", encoding="utf-8")
    if args.out_md:
        Path(args.out_md).write_text(markdown(payload), encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
