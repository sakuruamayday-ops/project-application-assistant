#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


TARGET_PROJECTS = (
    "国家专精特新“小巨人”企业",
    "浙江省专精特新中小企业",
    "浙江省制造业首台（套）装备",
    "浙江省首批次新材料",
    "浙江省首版次软件产品",
)
THREE_FIRST_PROJECTS = TARGET_PROJECTS[2:]
EXPECTED_CORRECTIONS = {
    (
        "91331000563304198L",
        "浙江省首批次新材料",
        2025,
    ): ("复合增亮膜", "国内"),
    (
        "91330401MA28A7N16U",
        "浙江省首批次新材料",
        2025,
    ): ("新能源锂电特种铝制安全防爆材料", "省内"),
    (
        "91331021MA2HET773R",
        "浙江省制造业首台（套）装备",
        2025,
    ): ("重载工业机器人RV减速器", "国内"),
}
REQUIRED_TABLES = {
    "enterprise_project_identity_twins",
    "enterprise_project_identity_twin_steps",
    "enterprise_project_relation_quarantine",
    "enterprise_project_twin_gaps",
    "enterprise_project_twin_rebuild_audit",
    "enterprise_project_product_corrections",
    "enterprise_unified_digital_identities",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="校验三类企业项目数字孪生闭环")
    parser.add_argument("--database", type=Path, required=True)
    return parser.parse_args()


def placeholders(values: tuple[str, ...]) -> str:
    return ",".join("?" for _ in values)


def verify(database: Path) -> dict[str, object]:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        existing = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        missing = sorted(REQUIRED_TABLES - existing)
        if missing:
            raise RuntimeError("项目数字孪生闭环缺少结构表：" + "、".join(missing))
        integrity = str(connection.execute("PRAGMA quick_check").fetchone()[0])
        if integrity != "ok":
            raise RuntimeError(f"SQLite quick_check失败：{integrity}")

        target_sql = placeholders(TARGET_PROJECTS)
        three_first_sql = placeholders(THREE_FIRST_PROJECTS)
        formal_memberships = int(
            connection.execute(
                f"""
                SELECT COUNT(*)
                FROM enterprise_unified_digital_identities i,
                     json_each(i.recognition_projects_json) p
                WHERE p.value IN ({target_sql})
                """,
                TARGET_PROJECTS,
            ).fetchone()[0]
        )
        target_twins = int(
            connection.execute(
                f"SELECT COUNT(*) FROM enterprise_project_identity_twins "
                f"WHERE project_name IN ({target_sql})",
                TARGET_PROJECTS,
            ).fetchone()[0]
        )
        residual_gaps = int(
            connection.execute(
                "SELECT COUNT(*) FROM enterprise_project_twin_gaps"
            ).fetchone()[0]
        )
        enterprises_without_twin = int(
            connection.execute(
                f"""
                SELECT COUNT(*)
                FROM enterprise_unified_digital_identities i
                WHERE EXISTS(
                    SELECT 1 FROM json_each(i.recognition_projects_json)
                    WHERE value IN ({target_sql})
                )
                  AND NOT EXISTS(
                    SELECT 1 FROM enterprise_project_identity_twins t
                    WHERE t.identity_key=i.identity_key
                      AND t.project_name IN ({target_sql})
                )
                """,
                (*TARGET_PROJECTS, *TARGET_PROJECTS),
            ).fetchone()[0]
        )
        three_first_without_product = int(
            connection.execute(
                f"""
                SELECT COUNT(*)
                FROM enterprise_project_identity_twins t
                WHERE t.project_name IN ({three_first_sql})
                  AND NOT EXISTS(
                    SELECT 1 FROM json_each(t.lifecycle_trace_json) s
                    WHERE COALESCE(json_extract(s.value,'$.product_name'),'')<>''
                )
                """,
                THREE_FIRST_PROJECTS,
            ).fetchone()[0]
        )
        if formal_memberships != target_twins:
            raise RuntimeError(
                f"企业项目关系与孪生数不一致：{formal_memberships}!={target_twins}"
            )
        if residual_gaps or enterprises_without_twin or three_first_without_product:
            raise RuntimeError(
                "项目数字孪生仍有缺口："
                + json.dumps(
                    {
                        "residual_gaps": residual_gaps,
                        "enterprises_without_twin": enterprises_without_twin,
                        "three_first_without_product": three_first_without_product,
                    },
                    ensure_ascii=False,
                )
            )

        corrections: dict[tuple[str, str, int], tuple[str, str, str]] = {}
        for row in connection.execute(
            """
            SELECT identity_key,project_name,recognition_year,product_name,
                   evidence_json
            FROM enterprise_project_product_corrections
            """
        ):
            evidence = json.loads(str(row["evidence_json"]))
            corrections[
                (
                    str(row["identity_key"]),
                    str(row["project_name"]),
                    int(row["recognition_year"]),
                )
            ] = (
                str(row["product_name"]),
                str(evidence.get("recognition_level") or ""),
                str(evidence.get("recognition_status") or ""),
            )
        correction_errors = {}
        for key, expected in EXPECTED_CORRECTIONS.items():
            actual = corrections.get(key)
            if actual != (*expected, "final_recognition"):
                correction_errors["|".join(map(str, key))] = {
                    "expected": (*expected, "final_recognition"),
                    "actual": actual,
                }
        if correction_errors:
            raise RuntimeError(
                "三首产品最终认定修正未通过："
                + json.dumps(correction_errors, ensure_ascii=False)
            )
        return {
            "database": str(database),
            "sqlite_quick_check": integrity,
            "formal_memberships": formal_memberships,
            "target_twins": target_twins,
            "residual_gaps": residual_gaps,
            "enterprises_without_twin": enterprises_without_twin,
            "three_first_without_product": three_first_without_product,
            "verified_final_recognition_corrections": len(EXPECTED_CORRECTIONS),
            "status": "pass",
        }
    finally:
        connection.close()


def main() -> None:
    args = parse_args()
    print(json.dumps(verify(args.database), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
