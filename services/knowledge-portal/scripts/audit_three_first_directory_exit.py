#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


DEFAULT_DB = Path(
    "/Users/zsh/JiaotangData/索引/current/knowledge_content.sqlite3"
)
DEFAULT_OUTPUT = Path(
    "/Users/zsh/JiaotangData/知识库/50_名单与对标/三首项目/_结构化数据/"
    "三首目录退出原文覆盖审计.md"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="审计三首目录退出原文与状态时间轴覆盖率")
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    connection = sqlite3.connect(f"file:{args.database}?mode=ro", uri=True)
    try:
        total_product_records = connection.execute(
            "SELECT COUNT(*) FROM three_first_project_awards WHERE product_name<>''"
        ).fetchone()[0]
        timeline_counts = dict(
            connection.execute(
                """
                SELECT event_status,COUNT(*)
                FROM three_first_status_timeline
                WHERE event_type='directory_exit'
                GROUP BY event_status
                """
            ).fetchall()
        )
        scheduled = int(timeline_counts.get("scheduled", 0))
        confirmed = int(timeline_counts.get("confirmed", 0))
        project_rows = connection.execute(
            """
            SELECT project_name,
                   COUNT(*) AS total,
                   SUM(CASE WHEN event_status='scheduled' THEN 1 ELSE 0 END) AS scheduled,
                   SUM(CASE WHEN event_status='confirmed' THEN 1 ELSE 0 END) AS confirmed
            FROM three_first_status_timeline
            WHERE event_type='directory_exit'
            GROUP BY project_name
            ORDER BY project_name
            """
        ).fetchall()
        mechanism_docs = connection.execute(
            """
            SELECT id,title,cloud_path
            FROM documents
            WHERE content LIKE '%退出目录%'
              AND (
                title LIKE '%首台%' OR cloud_path LIKE '%首台套%'
                OR title LIKE '%首版次%' OR cloud_path LIKE '%首版次%'
                OR title LIKE '%首批次%' OR cloud_path LIKE '%首批次%'
              )
            ORDER BY id
            """
        ).fetchall()
    finally:
        connection.close()

    explicit_events = scheduled + confirmed
    cross_year_coverage = (
        explicit_events / total_product_records if total_product_records else 0.0
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# 三首目录退出原文覆盖审计",
        "",
        "## 结论",
        "",
        f"- 三首产品级主记录：{total_product_records} 条。",
        f"- 已结构化计划退出事件：{scheduled} 条。",
        f"- 已结构化实际退出事件：{confirmed} 条。",
        f"- 跨年产品记录的明确退出时间覆盖率：{explicit_events}/{total_product_records}，即 {cross_year_coverage:.2%}。",
        f"- 当前目录内计划退出时间字段完整率：{scheduled}/{scheduled}，即 {100 if scheduled else 0:.2f}%。",
        "- 计划退出不等于已经退出；实际退出必须以当期目录、退出名单或撤销原文再次核验。",
        "",
        "## 项目分布",
        "",
        "| 项目 | 退出事件 | 计划退出 | 已实际退出 |",
        "|---|---:|---:|---:|",
    ]
    lines.extend(
        f"| {project} | {total} | {scheduled_count or 0} | {confirmed_count or 0} |"
        for project, total, scheduled_count, confirmed_count in project_rows
    )
    lines.extend(
        [
            "",
            "## 退出机制原文",
            "",
            f"当前命中 {len(mechanism_docs)} 份含“退出目录”表述的三首相关原文：",
            "",
        ]
    )
    lines.extend(f"- #{doc_id} {title}｜{path}" for doc_id, title, path in mechanism_docs)
    lines.extend(
        [
            "",
            "## 使用限制",
            "",
            "- 2026年推广应用指导目录提供的是计划退出时间，不能提前写成已退出。",
            "- 历史年度没有明确退出时间或退出名单时，只能标记“当前检索层未取得退出原文”。",
            "- 首版次、首批次若后续取得独立退出、撤销或目录调整原文，应追加事件，不覆盖原认定记录。",
            "",
        ]
    )
    args.output.write_text("\n".join(lines), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "total_product_records": total_product_records,
                "scheduled_exit_events": scheduled,
                "confirmed_exit_events": confirmed,
                "cross_year_coverage": cross_year_coverage,
                "mechanism_documents": len(mechanism_docs),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
