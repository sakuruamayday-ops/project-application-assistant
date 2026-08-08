#!/usr/bin/env python3
"""Merge an audited Markdown identity checklist into one knowledge snapshot.

This utility is intentionally narrow: only rows explicitly marked as verified
in the checklist are eligible.  Name corrections are merged as recognition
aliases when their credit code already exists.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


USCC_RE = re.compile(r"^[0-9A-Z]{18}$")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def parse_checklist(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not re.match(r"^\|\s*\d+\s*\|", line):
            continue
        cells = [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]
        if len(cells) != 8:
            continue
        _, recognition_name, current_name, code, status, region, conclusion, source = cells
        code = code.upper()
        if not USCC_RE.fullmatch(code):
            raise RuntimeError(f"核验清单包含无效信用代码：{recognition_name} {code}")
        if "核验通过" not in conclusion and "归并" not in conclusion:
            raise RuntimeError(f"核验清单包含未转正行：{recognition_name} {conclusion}")
        if source != "焦糖知识库":
            raise RuntimeError(f"核验清单来源标签异常：{recognition_name} {source}")
        rows.append(
            {
                "recognition_name": recognition_name,
                "current_name": current_name,
                "unified_social_credit_code": code,
                "registration_status": status,
                "region": region,
                "conclusion": conclusion,
            }
        )
    if len(rows) != 27:
        raise RuntimeError(f"核验清单必须恰好包含 27 家，实际 {len(rows)} 家")
    return rows


def split_region(region: str) -> tuple[str, str]:
    region = region.removeprefix("浙江省")
    match = re.fullmatch(r"(.+?市)(.+?(?:市|区|县))", region)
    if match:
        return match.group(1), match.group(2)
    return region, ""


def merge(
    base_path: Path,
    checklist_path: Path,
    candidate_csv: Path | None,
    dual_source_audit: Path | None,
    output_path: Path,
    audit_path: Path,
) -> dict[str, Any]:
    base_rows = read_jsonl(base_path)
    checklist = parse_checklist(checklist_path)
    by_code: dict[str, dict[str, Any]] = {}
    name_to_code: dict[str, str] = {}
    for row in base_rows:
        code = str(row.get("unified_social_credit_code") or "").upper()
        if not USCC_RE.fullmatch(code):
            raise RuntimeError(f"基础快照包含无效信用代码：{code}")
        if code in by_code:
            raise RuntimeError(f"基础快照信用代码重复：{code}")
        by_code[code] = row
        for name in [row.get("current_name"), *row.get("recognition_names", []), *row.get("former_names", [])]:
            if name:
                name_to_code.setdefault(str(name), code)

    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    inserted = 0
    aliases_merged = 0
    verified_codes = {item["unified_social_credit_code"] for item in checklist}
    for item in checklist:
        code = item["unified_social_credit_code"]
        recognition_name = item["recognition_name"]
        current_name = item["current_name"]
        existing_name_code = name_to_code.get(recognition_name)
        if existing_name_code and existing_name_code != code:
            raise RuntimeError(
                f"名单名称已锚定到其他信用代码：{recognition_name} {existing_name_code} != {code}"
            )
        if code in by_code:
            row = by_code[code]
            if str(row.get("current_name") or "") != current_name:
                raise RuntimeError(
                    f"同一信用代码现名冲突：{code} {row.get('current_name')} != {current_name}"
                )
            recognition_names = list(dict.fromkeys([*row.get("recognition_names", []), recognition_name]))
            projects = list(dict.fromkeys([*row.get("recognition_projects", []), "浙江省隐形冠军企业"]))
            row["recognition_names"] = recognition_names
            row["recognition_projects"] = projects
            row["knowledge_verification_status"] = "verified"
            row["generated_at"] = generated_at
            row.setdefault("source_layers", {})["knowledge_base"] = {
                "source_type": "焦糖知识库",
                "list_membership_status": "verified",
                "enterprise_identity_status": "verified",
                "match_status": "verified_alias_merge",
            }
            aliases_merged += 1
            name_to_code[recognition_name] = code
            continue

        city, county = split_region(item["region"])
        row = {
            "schema_version": "zhejiang-enterprise-base-identity-v1",
            "identity_key": code,
            "master_identity_key": code,
            "merged_master_identity_keys": [code],
            "unified_social_credit_code": code,
            "entity_resolution_status": "resolved_by_verified_knowledge_identity",
            "current_name": current_name,
            "recognition_names": [recognition_name],
            "former_names": [],
            "current_province": "浙江省",
            "current_city": city,
            "current_county": county,
            "current_address": "",
            "registration_authority": "",
            "registration_status": item["registration_status"],
            "founded_date": "",
            "registered_capital": "",
            "company_type": "",
            "industry_level_1": "",
            "industry_level_2": "",
            "industry_level_3": "",
            "website": "",
            "company_introduction": "",
            "business_scope": "",
            "main_product_tags": [],
            "industry_track_tags": [],
            "ip_statistics": {},
            "honors": [],
            "bid_count": "",
            "standard_count": "",
            "listed_status": "",
            "recognition_projects": ["浙江省隐形冠军企业"],
            "category_groups": ["浙江省隐形冠军企业"],
            "project_lifecycles": [],
            "knowledge_verification_status": "verified",
            "source_layers": {
                "knowledge_base": {
                    "source_type": "焦糖知识库",
                    "list_membership_status": "verified",
                    "enterprise_identity_status": "verified",
                    "match_status": "uscc_exact",
                }
            },
            "generated_at": generated_at,
        }
        base_rows.append(row)
        by_code[code] = row
        name_to_code[recognition_name] = code
        name_to_code[current_name] = code
        inserted += 1

    candidate_aliases_merged = 0
    if candidate_csv:
        with candidate_csv.open("r", encoding="utf-8-sig", newline="") as handle:
            for candidate in csv.DictReader(handle):
                code = str(candidate.get("unified_social_credit_code") or "").upper()
                if code not in verified_codes:
                    continue
                row = by_code[code]
                names = [
                    str(candidate.get("current_name") or ""),
                    *str(candidate.get("recognition_names") or "").split("；"),
                ]
                before_names = set(str(item) for item in row.get("recognition_names", []))
                merged_names = list(
                    dict.fromkeys(
                        [
                            *row.get("recognition_names", []),
                            *(name for name in names if name),
                        ]
                    )
                )
                row["recognition_names"] = merged_names
                projects = [
                    project
                    for project in str(candidate.get("recognition_projects") or "").split("；")
                    if project
                ]
                row["recognition_projects"] = list(
                    dict.fromkeys([*row.get("recognition_projects", []), *projects])
                )
                candidate_aliases_merged += len(set(merged_names) - before_names)

    dual_source_inserted = 0
    dual_source_aliases_merged = 0
    if dual_source_audit:
        seen_dual_codes: set[str] = set()
        for item in read_jsonl(dual_source_audit):
            if str(item.get("verification_status") or "") != "dual_commercial_uscc_exact":
                continue
            code = str(item.get("unified_social_credit_code") or "").upper()
            if not USCC_RE.fullmatch(code):
                raise RuntimeError(f"双源复核包含无效信用代码：{code}")
            if code in seen_dual_codes:
                raise RuntimeError(f"双源复核信用代码重复：{code}")
            seen_dual_codes.add(code)
            current_name = str(item.get("verified_current_name") or "").strip()
            recognition_name = str(item.get("recognition_name") or "").strip()
            archived_current_name = str(item.get("archived_current_name") or "").strip()
            names = list(
                dict.fromkeys(
                    name
                    for name in (current_name, recognition_name, archived_current_name)
                    if name
                )
            )
            projects = [
                str(project)
                for project in item.get("recognition_projects", [])
                if str(project)
            ]
            if not current_name or not names:
                raise RuntimeError(f"双源复核缺少企业名称：{code}")
            if code in by_code:
                row = by_code[code]
                if str(row.get("current_name") or "") != current_name:
                    raise RuntimeError(
                        f"双源复核现名与已有快照冲突：{code} "
                        f"{row.get('current_name')} != {current_name}"
                    )
                before_names = set(str(name) for name in row.get("recognition_names", []))
                row["recognition_names"] = list(
                    dict.fromkeys([*row.get("recognition_names", []), *names])
                )
                row["recognition_projects"] = list(
                    dict.fromkeys([*row.get("recognition_projects", []), *projects])
                )
                row["knowledge_verification_status"] = (
                    "dual_commercial_sources_consistent"
                )
                dual_source_aliases_merged += len(
                    set(row["recognition_names"]) - before_names
                )
                continue

            city, county = split_region(str(item.get("current_region") or ""))
            row = {
                "schema_version": "zhejiang-enterprise-base-identity-v1",
                "identity_key": code,
                "master_identity_key": code,
                "merged_master_identity_keys": [code],
                "unified_social_credit_code": code,
                "entity_resolution_status": "resolved_by_dual_commercial_uscc_exact",
                "current_name": current_name,
                "recognition_names": names,
                "former_names": [],
                "current_province": "浙江省",
                "current_city": city,
                "current_county": county,
                "current_address": "",
                "registration_authority": str(item.get("registration_authority") or ""),
                "registration_status": str(item.get("registration_status") or ""),
                "founded_date": str(item.get("founded_date") or ""),
                "registered_capital": "",
                "company_type": "",
                "industry_level_1": "",
                "industry_level_2": "",
                "industry_level_3": "",
                "website": "",
                "company_introduction": "",
                "business_scope": "",
                "main_product_tags": [],
                "industry_track_tags": [],
                "ip_statistics": {},
                "honors": [],
                "bid_count": "",
                "standard_count": "",
                "listed_status": "",
                "recognition_projects": projects,
                "category_groups": projects,
                "project_lifecycles": [],
                "knowledge_verification_status": "dual_commercial_sources_consistent",
                "source_layers": {
                    "knowledge_base": {
                        "source_type": "焦糖知识库",
                        "list_membership_status": "verified",
                        "enterprise_identity_status": "dual_commercial_sources_consistent",
                        "match_status": "dual_commercial_uscc_exact",
                    }
                },
                "generated_at": generated_at,
            }
            base_rows.append(row)
            by_code[code] = row
            for name in names:
                name_to_code[name] = code
            dual_source_inserted += 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for row in sorted(base_rows, key=lambda item: (str(item.get("current_name") or ""), str(item.get("unified_social_credit_code") or ""))):
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    audit = {
        "schema_version": "zhejiang-verified-identity-increment-audit-v1",
        "base_snapshot": str(base_path),
        "verified_checklist": str(checklist_path),
        "output_snapshot": str(output_path),
        "base_identity_count": len(base_rows) - inserted,
        "checklist_identity_count": len(checklist),
        "inserted_identity_count": inserted,
        "verified_alias_merge_count": aliases_merged,
        "verified_candidate_aliases_added": candidate_aliases_merged,
        "dual_source_inserted_identity_count": dual_source_inserted,
        "dual_source_aliases_added": dual_source_aliases_merged,
        "output_identity_count": len(base_rows),
        "generated_at": generated_at,
        "outward_source_label": "焦糖知识库",
    }
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return audit


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True, type=Path)
    parser.add_argument("--checklist", required=True, type=Path)
    parser.add_argument("--candidate-csv", type=Path)
    parser.add_argument("--dual-source-audit", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--audit", required=True, type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            merge(
                args.base,
                args.checklist,
                args.candidate_csv,
                args.dual_source_audit,
                args.output,
                args.audit,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
