#!/usr/bin/env python3
"""Build an evidence-layered inventory of enterprise identity data.

The report deliberately separates licensed batch-profile lineage, unified
enterprise subjects, raw list rows, recognition records and replayable
enterprise-project twins.  These counts have different denominators and must
not be presented as interchangeable totals.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


USCC_PATTERN = re.compile(r"^[0-9A-HJ-NPQRTUWXY]{18}$")
PUBLIC_SOURCE = "共创研究院知识库"
DEFAULT_PROVENANCE = Path(
    "/Users/zsh/JiaotangData/知识库/50_名单与对标/企业身份时间轴/企业画像批量回传血缘/"
    "企业画像批量回传主体血缘_current.jsonl"
)
DEFAULT_PROVENANCE_AUDIT = Path(
    "/Users/zsh/JiaotangData/知识库/50_名单与对标/企业身份时间轴/企业画像批量回传血缘/"
    "企业画像批量回传构建报告_current.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="构建企业身份数据库分层统计报告")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, default=DEFAULT_PROVENANCE)
    parser.add_argument(
        "--provenance-audit", type=Path, default=DEFAULT_PROVENANCE_AUDIT
    )
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    return parser.parse_args()


def scalar(connection: sqlite3.Connection, sql: str) -> int:
    value = connection.execute(sql).fetchone()[0]
    return int(value or 0)


def row(connection: sqlite3.Connection, sql: str) -> dict[str, Any]:
    result = connection.execute(sql).fetchone()
    if result is None:
        raise RuntimeError("统计查询未返回结果")
    return dict(result)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def build_report(
    database: Path,
    provenance_path: Path,
    provenance_audit_path: Path,
) -> dict[str, Any]:
    provenance = read_jsonl(provenance_path)
    provenance_audit = json.loads(provenance_audit_path.read_text(encoding="utf-8"))
    provenance_codes = {
        str(item.get("unified_social_credit_code") or "").strip().upper()
        for item in provenance
        if USCC_PATTERN.fullmatch(
            str(item.get("unified_social_credit_code") or "").strip().upper()
        )
    }
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        project_catalog = row(
            connection,
            """
            SELECT COUNT(DISTINCT NULLIF(canonical_project_name,'')) AS project_names,
                   COUNT(DISTINCT NULLIF(project_id,'')) AS project_ids
            FROM documents
            """,
        )
        unified = row(
            connection,
            """
            SELECT COUNT(*) AS master_rows,
                   COUNT(DISTINCT current_name) AS distinct_current_names,
                   COUNT(DISTINCT NULLIF(unified_social_credit_code,'')) AS valid_codes,
                   SUM(CASE WHEN unified_social_credit_code='' THEN 1 ELSE 0 END) AS without_code
            FROM enterprise_unified_digital_identities
            """,
        )
        public_lists = row(
            connection,
            """
            SELECT COUNT(*) AS list_rows,
                   COUNT(DISTINCT enterprise_name) AS distinct_extracted_names
            FROM public_list_entities
            """,
        )
        recognition = row(
            connection,
            """
            SELECT COUNT(*) AS recognition_rows,
                   COUNT(DISTINCT enterprise_id) AS enterprise_ids,
                   COUNT(DISTINCT project_id) AS project_ids,
                   COUNT(DISTINCT project_name) AS project_names
            FROM recognition_records
            """,
        )
        lifecycle = row(
            connection,
            """
            SELECT COUNT(*) AS lifecycle_events,
                   COUNT(DISTINCT identity_key) AS identity_keys,
                   COUNT(DISTINCT project_name) AS project_names
            FROM enterprise_recognition_events
            """,
        )
        twins = row(
            connection,
            """
            SELECT COUNT(*) AS twin_pairs,
                   COUNT(DISTINCT identity_key) AS identity_keys,
                   COUNT(DISTINCT project_name) AS project_names
            FROM enterprise_project_identity_twins
            """,
        )
        twins["lifecycle_steps"] = scalar(
            connection, "SELECT COUNT(*) FROM enterprise_project_identity_twin_steps"
        )
        curated_subset = row(
            connection,
            """
            SELECT COUNT(*) AS profile_subjects,
                   COUNT(DISTINCT unified_social_credit_code) AS unique_codes
            FROM small_giant_enterprise_identity_profiles
            """,
        )
        master_codes = {
            str(item[0]).strip().upper()
            for item in connection.execute(
                "SELECT unified_social_credit_code FROM enterprise_unified_digital_identities "
                "WHERE unified_social_credit_code<>''"
            )
        }
    finally:
        connection.close()

    batch_in_master = provenance_codes & master_codes
    batch_not_in_master = provenance_codes - master_codes
    return {
        "schema_version": "enterprise-identity-inventory-report-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": PUBLIC_SOURCE,
        "project_catalog": {
            **project_catalog,
            "definition": "documents中的去重项目名称和技术项目ID；一个项目族可存在多个名称或版本。",
        },
        "unified_enterprise_master": {
            **unified,
            "definition": "按统一社会信用代码归并后的企业主体主档；不等同名单名称数。",
        },
        "licensed_batch_profile_lineage": {
            "unique_valid_codes": len(provenance_codes),
            "codes_in_unified_master": len(batch_in_master),
            "codes_not_in_unified_master": len(batch_not_in_master),
            "excluded_or_unresolved_codes": sorted(batch_not_in_master),
            "accepted_subjects": int(provenance_audit["accepted_subjects"]),
            "manual_review_name_mismatch": int(
                provenance_audit["manual_review_name_mismatch"]
            ),
            "excluded_unrelated_return": int(
                provenance_audit["excluded_unrelated_return"]
            ),
            "invalid_result_rows": int(provenance_audit["invalid_result_rows"]),
            "definition": "42份许可批量企业画像回传的代码级血缘；包括已入主档、名称差异但已有主档和明确排除项。",
        },
        "curated_small_giant_profile_subset": {
            **curated_subset,
            "definition": "全国小巨人业务图谱使用的精选企业画像子集；不是全部批量回传数量。",
        },
        "public_list_extraction": {
            **public_lists,
            "definition": "公开名单提取层；同一企业可跨文件、年度、批次和项目重复出现。",
        },
        "recognition_records": {
            **recognition,
            "definition": "结构化企业认定记录；不等同企业主体数。",
        },
        "recognition_lifecycle": {
            **lifecycle,
            "definition": "认定、公示、复核、到期等事件记录。",
        },
        "replayable_enterprise_project_twins": {
            **twins,
            "definition": "同时具备企业身份、项目映射、政策版本和可回放生命周期的企业-项目组合；不是企业画像抓取量。",
        },
        "denominator_warning": (
            "批量画像代码数、统一企业主体数、名单行数、认定记录数和可回放企业-项目孪生数"
            "属于不同数据层，禁止互相替代。"
        ),
    }


def write_report(
    report: dict[str, Any], json_output: Path, markdown_output: Path
) -> None:
    json_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    project = report["project_catalog"]
    master = report["unified_enterprise_master"]
    batch = report["licensed_batch_profile_lineage"]
    curated = report["curated_small_giant_profile_subset"]
    lists = report["public_list_extraction"]
    recognition = report["recognition_records"]
    lifecycle = report["recognition_lifecycle"]
    twins = report["replayable_enterprise_project_twins"]
    markdown = f"""# 企业身份数据库分层统计

统计时点：{report['generated_at']}
对外来源：{PUBLIC_SOURCE}

| 数据层 | 当前数量 | 口径 |
|---|---:|---|
| 项目名称 | {project['project_names']:,} | documents中的去重项目名称 |
| 项目技术ID | {project['project_ids']:,} | documents中的去重project_id |
| 企业统一主档 | {master['master_rows']:,} | 按主体归并；有效代码{master['valid_codes']:,}，无代码{master['without_code']:,} |
| 批量企业画像代码级血缘 | {batch['unique_valid_codes']:,} | 42份回传；已入主档{batch['codes_in_unified_master']:,}，明确排除或未入{batch['codes_not_in_unified_master']:,} |
| 全国小巨人精选画像子集 | {curated['unique_codes']:,} | 业务图谱精选子集，不是全部批量回传 |
| 公开名单记录 | {lists['list_rows']:,} | 可跨文件、年度、项目重复 |
| 公开名单不同提取名称 | {lists['distinct_extracted_names']:,} | 名单提取层，不等于统一企业主体 |
| 企业认定记录 | {recognition['recognition_rows']:,} | 涉及{recognition['enterprise_ids']:,}个企业ID |
| 企业认定生命周期事件 | {lifecycle['lifecycle_events']:,} | 涉及{lifecycle['identity_keys']:,}个身份键 |
| 可回放企业-项目身份孪生 | {twins['twin_pairs']:,} | {twins['identity_keys']:,}个身份、{twins['project_names']:,}个具备生命周期规则的项目、{twins['lifecycle_steps']:,}个回放步骤 |

## 口径结论

- {report['denominator_warning']}
- {curated['unique_codes']:,}对应全国小巨人精选画像子集，不是全部批量回传。
- 企业-项目孪生只在身份、项目、政策版本和生命周期证据同时闭环时建立，因此不能用企业画像总量作分母。
"""
    markdown_output.write_text(markdown, encoding="utf-8")


def main() -> None:
    args = parse_args()
    report = build_report(
        args.database,
        args.provenance,
        args.provenance_audit,
    )
    write_report(report, args.json_output, args.markdown_output)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
