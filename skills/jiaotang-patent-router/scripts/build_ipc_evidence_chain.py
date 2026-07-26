#!/usr/bin/env python3
"""从中国专利申请DOCX提取技术主题、生成IPC候选并匹配浙江/杭州预审中心。"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

from claim_structure import analyze_feature

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "references" / "ipc-inference-rules.json"
CENTERS = ROOT / "references" / "ipc-snapshots" / "dual-center-ipc-index.json"
CHECKER_EXTRACTOR = (
    Path.home()
    / ".codex/skills/checking-patdocx-cn-single-agent/scripts/patent_extractor.py"
)
SECTION_WEIGHTS = {
    "title": 6,
    "independent_claim_features": 10,
    "claims": 5,
    "abstract_text": 4,
    "equations_and_notes": 2,
    "description_lead": 2,
    "description": 1,
    "description_figs": 1,
}


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_sections(path):
    if path.suffix.lower() != ".docx":
        raise ValueError("当前自动证据链只接受 .docx")
    if not CHECKER_EXTRACTOR.exists():
        raise FileNotFoundError(f"缺少专利申请文件提取器：{CHECKER_EXTRACTOR}")
    with tempfile.TemporaryDirectory(prefix="ipc-evidence-") as td:
        out = Path(td) / "sections.json"
        run = subprocess.run(
            [sys.executable, str(CHECKER_EXTRACTOR), str(path), "--output-json", str(out)],
            capture_output=True,
            text=True,
        )
        if run.returncode != 0 or not out.exists():
            raise RuntimeError(run.stderr.strip() or run.stdout.strip() or "DOCX提取失败")
        return json.loads(out.read_text(encoding="utf-8"))


def infer_title(path, sections):
    for source in (sections.get("description", ""), sections.get("claims", "")):
        for line in source.splitlines():
            value = line.strip()
            if value and len(value) <= 80 and not value.startswith(("技术领域", "权利要求")):
                return value
    return path.stem


def evidence_fragments(text, keyword, limit=3):
    fragments = []
    for match in re.finditer(re.escape(keyword), text, flags=re.I):
        start = max(0, match.start() - 24)
        end = min(len(text), match.end() + 36)
        fragment = re.sub(r"\s+", " ", text[start:end]).strip()
        if fragment and fragment not in fragments:
            fragments.append(fragment)
        if len(fragments) >= limit:
            break
    return fragments


def _split_claim_items(claims):
    markers = list(re.finditer(r"(?m)^\s*(\d+)\s*[\.\、]\s*", claims))
    items = []
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(claims)
        items.append(
            {
                "number": int(marker.group(1)),
                "text": re.sub(r"\s+", " ", claims[marker.end():end]).strip(),
            }
        )
    return items


def _protection_object(text):
    opening = text[:100]
    if any(word in opening for word in ("用途", "应用")):
        return "use"
    if any(word in opening for word in ("方法", "工艺", "制备")):
        return "method"
    if any(word in opening for word in ("材料", "组合物", "树脂", "合金", "涂料")):
        return "material_or_composition"
    if any(word in opening for word in ("系统", "平台", "网络")):
        return "system"
    if any(word in opening for word in ("装置", "设备", "器", "机构", "组件")):
        return "device"
    return "other"


def _claim_features(text):
    characteristic = re.split(r"其特征在于|特征在于", text, maxsplit=1)
    preamble = characteristic[0].strip(" ，,；;")
    feature_text = characteristic[1] if len(characteristic) > 1 else text
    first_period = feature_text.find("。")
    if first_period >= 0 and feature_text[first_period + 1:].strip():
        feature_text = feature_text[: first_period + 1]
    features = []
    for value in re.split(r"[；;]\s*|(?=[（(]\d+[）)])", feature_text):
        value = re.sub(r"\s+", " ", value).strip(" ，,；;")
        if len(value) >= 4 and value not in features:
            features.append(value)
    return preamble, features


def _expand_claim_references(text, existing_numbers):
    opening = text[:150]
    refs = []
    reference_pattern = re.compile(
        r"权利要求\s*((?:\d+\s*(?:[-至到、,，和或]\s*)?)+)"
    )
    for match in reference_pattern.finditer(opening):
        expression = match.group(1)
        for start, end in re.findall(r"(\d+)\s*[-至到]\s*(\d+)", expression):
            low, high = int(start), int(end)
            if low <= high and high - low <= 100:
                refs.extend(range(low, high + 1))
        expression = re.sub(r"\d+\s*[-至到]\s*\d+", " ", expression)
        refs.extend(int(value) for value in re.findall(r"\d+", expression))
    return sorted({value for value in refs if value in existing_numbers})


def build_claim_reference_graph(claims):
    items = _split_claim_items(claims)
    existing_numbers = {item["number"] for item in items}
    nodes = []
    edges = []
    dependency_pattern = re.compile(r"(根据|如|按照)权利要求\s*\d")
    for item in items:
        text = item["text"]
        preamble, features = _claim_features(text)
        refs = _expand_claim_references(text, existing_numbers)
        is_dependency = bool(dependency_pattern.search(text[:100]))
        relation_type = (
            "dependent_claim"
            if is_dependency
            else "cross_category_reference"
            if refs
            else "independent_claim"
        )
        feature_rows = [
            {
                "feature_id": f"C{item['number']}-F{index}",
                "text": feature,
                "source_claim": item["number"],
                "structure": analyze_feature(
                    f"C{item['number']}-F{index}", feature
                ),
            }
            for index, feature in enumerate(features, 1)
        ]
        nodes.append(
            {
                "claim_number": item["number"],
                "relation_type": relation_type,
                "protection_object": _protection_object(text),
                "referenced_claims": refs,
                "preamble": preamble,
                "direct_features": feature_rows,
            }
        )
        edge_type = "dependency" if is_dependency else "cross_category_reference"
        edges.extend(
            {"from_claim": item["number"], "to_claim": ref, "edge_type": edge_type}
            for ref in refs
        )

    dependency_parents = {
        node["claim_number"]: [
            edge["to_claim"]
            for edge in edges
            if edge["from_claim"] == node["claim_number"] and edge["edge_type"] == "dependency"
        ]
        for node in nodes
    }

    def paths_to_roots(claim_number, trail=()):
        if claim_number in trail:
            return [[claim_number]]
        parents = dependency_parents.get(claim_number, [])
        if not parents:
            return [[claim_number]]
        paths = []
        for parent in parents:
            for path in paths_to_roots(parent, trail + (claim_number,)):
                paths.append(path + [claim_number])
        return paths

    return {
        "nodes": nodes,
        "edges": edges,
        "dependency_paths": {
            str(node["claim_number"]): paths_to_roots(node["claim_number"])
            for node in nodes
        },
        "independent_claims": [
            node["claim_number"]
            for node in nodes
            if node["relation_type"] != "dependent_claim"
        ],
    }


def claim_graph_mermaid(graph):
    lines = ["graph TD"]
    for node in graph["nodes"]:
        label = (
            f"权利要求{node['claim_number']}｜"
            f"{node['protection_object']}｜{node['relation_type']}"
        )
        lines.append(f'  C{node["claim_number"]}["{label}"]')
    for edge in graph["edges"]:
        parent = edge["to_claim"]
        child = edge["from_claim"]
        arrow = "-->" if edge["edge_type"] == "dependency" else "-.->"
        lines.append(f"  C{parent} {arrow} C{child}")
    return "\n".join(lines)


def build_independent_claim_feature_tree(claims):
    tree = []
    dependency_pattern = re.compile(r"(根据|如|按照)权利要求\s*\d")
    for item in _split_claim_items(claims):
        text = item["text"]
        if not text or dependency_pattern.search(text[:90]):
            continue
        preamble, features = _claim_features(text)
        tree.append(
            {
                "claim_number": item["number"],
                "protection_object": _protection_object(text),
                "preamble": preamble,
                "necessary_technical_features": [
                    {
                        "feature_id": f"C{item['number']}-F{index}",
                        "text": feature,
                        "structure": analyze_feature(
                            f"C{item['number']}-F{index}", feature
                        ),
                    }
                    for index, feature in enumerate(features, 1)
                ],
                "feature_count": len(features),
            }
        )
    return tree


def _supplemental_text(sections):
    values = []
    for key in ("footnotes", "endnotes", "equations"):
        for item in sections.get(key, []):
            if item.get("text"):
                values.append(item["text"])
    for item in sections.get("embedded_objects", []):
        values.extend(item.get("recoverable_text", []))
    return "\n".join(values)


def score_candidates(title, sections, feature_tree, rules):
    feature_text = "\n".join(
        feature["text"]
        for claim in feature_tree
        for feature in claim["necessary_technical_features"]
    )
    sources = {
        "title": title,
        "independent_claim_features": feature_text,
        "claims": sections.get("claims", ""),
        "abstract_text": sections.get("abstract_text", ""),
        "equations_and_notes": _supplemental_text(sections),
        "description_lead": sections.get("description", "")[:1800],
        "description": sections.get("description", ""),
        "description_figs": sections.get("description_figs", ""),
    }
    candidates = []
    for rule in rules:
        score = 0
        hits = []
        for keyword in rule["keywords"]:
            keyword_sources = []
            snippets = []
            for section, text in sources.items():
                if keyword.lower() in text.lower():
                    score += SECTION_WEIGHTS[section]
                    keyword_sources.append(section)
                    snippets.extend(evidence_fragments(text, keyword, limit=1))
            if keyword_sources:
                hits.append(
                    {
                        "keyword": keyword,
                        "sections": keyword_sources,
                        "evidence": snippets[:2],
                    }
                )
        if score:
            candidates.append(
                {
                    "code": rule["code"],
                    "label": rule["label"],
                    "theme": rule["theme"],
                    "score": score,
                    "matched_keywords": hits,
                }
            )
    candidates.sort(key=lambda x: (-x["score"], x["code"]))
    if candidates:
        top = candidates[0]["score"]
        for index, item in enumerate(candidates):
            item["rank"] = index + 1
            item["role"] = "primary_candidate" if index == 0 else "alternative_candidate"
            ratio = item["score"] / top
            item["confidence"] = "high" if ratio >= 0.75 else "medium" if ratio >= 0.4 else "low"
    return candidates


def build_search_blueprint(title, feature_tree, candidates):
    ipc_codes = [item["code"] for item in candidates[:3]]
    ipc_terms = []
    for item in candidates[:5]:
        for hit in item.get("matched_keywords", []):
            keyword = hit["keyword"]
            if keyword not in ipc_terms:
                ipc_terms.append(keyword)
    claims = []
    for claim in feature_tree:
        features = claim["necessary_technical_features"]
        claim_terms = []
        for feature in features:
            for keyword in ipc_terms:
                if keyword.lower() in feature["text"].lower() and keyword not in claim_terms:
                    claim_terms.append(keyword)
        if not claim_terms:
            claim_terms = ipc_terms[:4]
        generic_query = " AND ".join(
            [f"IPC={code}" for code in ipc_codes[:2]]
            + [f'"{term}"' for term in claim_terms[:4]]
        )
        claims.append(
            {
                "claim_number": claim["claim_number"],
                "protection_object": claim["protection_object"],
                "ipc_scope": ipc_codes,
                "core_terms": claim_terms[:8],
                "broad_query": f'"{title}" OR ({generic_query})',
                "feature_queries": [
                    {
                        "feature_id": feature["feature_id"],
                        "query": f'({" OR ".join(ipc_codes[:3])}) AND "{feature["text"][:100]}"',
                    }
                    for feature in features
                ],
            }
        )
    return {
        "stage_order": [
            "IPC加技术主题宽检索",
            "独立权利要求逐特征检索",
            "引证与同族追溯",
            "最接近现有技术补检",
            "区别特征技术启示检索",
        ],
        "claims": claims,
        "result_contract": "检索结果必须记录公开日、来源链接、命中段落和证据等级，再进入区别特征对照；标题或摘要相似不能直接记为已公开。",
    }


def detect_route(sections, feature_tree):
    has_claims = bool(sections.get("claims", "").strip())
    has_description = bool(sections.get("description", "").strip())
    if has_claims and has_description and feature_tree:
        return {
            "document_type": "patent_application",
            "route": "PATENT_APPLICATION_DUAL_TRACK",
            "tracks": [
                "P1_P2_P3_COMPREHENSIVE_REVIEW",
                "INDEPENDENT_DOCUMENT_CHECK",
            ],
            "reason": "检测到权利要求书、说明书和独立权利要求；综合审查与申请文件核稿自动分轨执行，结论分别输出。",
        }
    if has_description and not has_claims:
        return {
            "document_type": "technical_material_or_disclosure",
            "route": "P1_P2_P3_COMPREHENSIVE_REVIEW",
            "tracks": ["P1_P2_P3_COMPREHENSIVE_REVIEW"],
            "reason": "检测到技术说明但未形成权利要求书；执行查新、挖掘交底和预审推荐，不启动申请文件核稿。",
        }
    return {
        "document_type": "unclassified",
        "route": "MANUAL_ROUTE_CONFIRMATION",
        "tracks": [],
        "reason": "文件结构不足以自动识别为技术材料或中国专利申请文件。",
    }


def center_matches(candidates, center_data):
    rows = {}
    for center, record in center_data.items():
        allowed = set(record["ipc_subclasses"])
        rows[center] = {
            "release_date": record.get("release_date"),
            "industries": record.get("industries", []),
            "candidate_hits": [x["code"] for x in candidates if x["code"] in allowed],
            "candidate_misses": [x["code"] for x in candidates if x["code"] not in allowed],
            "primary_candidate_hit": bool(candidates and candidates[0]["code"] in allowed),
        }
    return rows


def recommend(location, candidates, matches):
    if not candidates:
        return {
            "result": "NO_IPC_CANDIDATE",
            "recommended_primary_target_center": None,
            "reason": "申请文件未触发内置IPC候选规则，需人工分类。",
        }
    primary = candidates[0]["code"]
    in_hangzhou = "杭州" in location
    in_zhejiang = in_hangzhou or "浙江" in location
    eligible = []
    for center, region_ok in (
        ("浙江省知识产权保护中心", in_zhejiang),
        ("杭州市知识产权保护中心", in_hangzhou),
    ):
        if region_ok and matches[center]["primary_candidate_hit"]:
            eligible.append(center)
    if len(eligible) == 1:
        center = eligible[0]
        return {
            "result": "RECOMMEND_HANGZHOU" if "杭州" in center else "RECOMMEND_ZHEJIANG",
            "recommended_primary_target_center": center,
            "reason": f"申请人属地满足且主IPC候选{primary}仅命中该中心。",
        }
    if not eligible:
        return {
            "result": "NO_ELIGIBLE_CENTER",
            "recommended_primary_target_center": None,
            "reason": f"按当前注册地和主IPC候选{primary}，未形成可推荐中心。",
        }
    theme = " ".join(x["theme"] for x in candidates[:3])
    if any(x in theme for x in ("人工智能", "软件", "通信", "机器人")):
        center = "杭州市知识产权保护中心"
    elif any(x in theme for x in ("高分子", "生物", "医药", "低碳", "电池")):
        center = "浙江省知识产权保护中心"
    else:
        return {
            "result": "CONDITIONAL_TIE",
            "recommended_primary_target_center": None,
            "reason": f"两个中心均命中主IPC候选{primary}，技术主题不足以可靠区分。",
        }
    return {
        "result": "RECOMMEND_HANGZHOU" if "杭州" in center else "RECOMMEND_ZHEJIANG",
        "recommended_primary_target_center": center,
        "reason": f"两个中心均命中主IPC候选{primary}，按申请文件技术主题优先推荐{center}。",
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--file", required=True)
    p.add_argument("--company", default="")
    p.add_argument("--applicant-location", required=True)
    p.add_argument("--cutoff", default=date.today().isoformat())
    p.add_argument("--out")
    a = p.parse_args()
    path = Path(a.file).expanduser().resolve()
    sections = extract_sections(path)
    title = infer_title(path, sections)
    rules = json.loads(RULES.read_text(encoding="utf-8"))["rules"]
    centers = json.loads(CENTERS.read_text(encoding="utf-8"))["centers"]
    feature_tree = build_independent_claim_feature_tree(sections.get("claims", ""))
    claim_graph = build_claim_reference_graph(sections.get("claims", ""))
    candidates = score_candidates(title, sections, feature_tree, rules)
    selected_candidates = candidates[:8]
    matches = center_matches(selected_candidates, centers)
    themes = []
    for candidate in selected_candidates:
        if candidate["theme"] not in themes:
            themes.append(candidate["theme"])
    payload = {
        "schema_version": "1.3",
        "cutoff_date": a.cutoff,
        "applicant": {
            "company": a.company or None,
            "registered_location": a.applicant_location,
            "location_source": "企业登记查询结果（调用方记录具体工具、查询时间和字段）",
            "zhejiang_record_status": "yes",
            "hangzhou_record_status": "yes",
            "record_basis": "用户常设指令：两个中心默认均已备案",
        },
        "source_document": {
            "path": str(path),
            "sha256": sha256(path),
            "title": title,
            "extraction_coverage": {
                "paragraphs": True,
                "tables": True,
                "text_boxes": True,
                "footnotes": True,
                "endnotes": True,
                "omml_equations": True,
                "embedded_ole_objects": "inventory_and_recoverable_text",
            },
            "section_char_counts": {
                key: len(value) for key, value in sections.items() if isinstance(value, str)
            },
        },
        "automatic_route": detect_route(sections, feature_tree),
        "technology_themes": themes[:6],
        "claim_reference_graph": claim_graph,
        "claim_reference_graph_mermaid": claim_graph_mermaid(claim_graph),
        "independent_claim_feature_tree": feature_tree,
        "ipc_candidates": selected_candidates,
        "prior_art_search_blueprint": build_search_blueprint(
            title, feature_tree, selected_candidates
        ),
        "center_match": matches,
        "recommendation": recommend(a.applicant_location, selected_candidates, matches),
        "evidence_chain": [
            "申请文件原件及SHA-256",
            "文件结构自动路由结果",
            "独立权利要求保护客体与必要技术特征树",
            "权利要求引用关系图与继承路径",
            "嵌套并列、择一引用、数值范围与马库什结构解析",
            "标题、摘要、权利要求、说明书、脚注、尾注及可解析公式中的上下文",
            "以独立权利要求技术特征为最高权重的IPC候选规则及分值",
            "IPC与必要技术特征组合形成的查新检索蓝图",
            "浙江/杭州带发布日期的IPC对照库",
            "申请人注册地和默认备案假设",
            "唯一中心推荐或无法推荐原因",
        ],
        "limitations": [
            "IPC结果是申请前候选，不替代正式分类。",
            "正式提交前须以最终独立权利要求和保护中心当日规则复核。",
            "OMML公式可直接提取；传统OLE公式仅提取对象清单和可恢复文本，无法恢复的二进制公式需视觉核验。",
        ],
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if a.out:
        Path(a.out).write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
