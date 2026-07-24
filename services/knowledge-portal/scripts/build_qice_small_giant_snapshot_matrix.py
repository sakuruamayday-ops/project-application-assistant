#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path

try:
    from scripts.build_national_small_giant_master import normalize_name, qice_records
    from scripts.build_small_giant_official_fragments import BATCHES, BATCH_YEARS, PROVINCES
except ModuleNotFoundError:
    from build_national_small_giant_master import normalize_name, qice_records
    from build_small_giant_official_fragments import BATCHES, BATCH_YEARS, PROVINCES


DEFAULT_DB = Path("/Volumes/知识库/_云端迁移索引/cloud_package_index/knowledge_content.sqlite3")
DEFAULT_DATASET = Path.home() / "Downloads" / "企策顾问_国家专精特新小巨人_2019年至今_2026-07-22.json"
DEFAULT_OUTPUT = Path(
    "/Volumes/知识库/_云端知识库/50_名单与对标/优质中小企业梯度培育/"
    "_全国小巨人批次主表/企策企业快照"
)
DEFAULT_ZERO_CELLS = (
    Path(__file__).resolve().parents[1]
    / "references"
    / "confirmed_small_giant_zero_cells.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="建立企策小巨人企业快照层并补充地区批次缺口矩阵")
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--confirmed-zero-cells", type=Path, default=DEFAULT_ZERO_CELLS)
    return parser.parse_args()


def write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def ensure_columns(connection: sqlite3.Connection) -> None:
    existing = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(small_giant_fragment_coverage)")
    }
    columns = {
        "qice_snapshot_count": "INTEGER NOT NULL DEFAULT 0",
        "qice_snapshot_path": "TEXT NOT NULL DEFAULT ''",
        "qice_source_url": "TEXT NOT NULL DEFAULT ''",
        "qice_verification_status": "TEXT NOT NULL DEFAULT ''",
        "resolution_status": "TEXT NOT NULL DEFAULT ''",
    }
    for name, declaration in columns.items():
        if name not in existing:
            connection.execute(
                f"ALTER TABLE small_giant_fragment_coverage ADD COLUMN {name} {declaration}"
            )


def resolution_status(
    official_count: int,
    recovered_url_count: int,
    qice_count: int,
    candidate_count: int,
    confirmed_zero: bool = False,
) -> str:
    if confirmed_zero and not official_count and not qice_count and not candidate_count:
        return "confirmed_zero_enterprises"
    if official_count and recovered_url_count and official_count == candidate_count:
        return "official_count_enterprise_source_closed"
    if official_count and official_count == candidate_count:
        return "official_enterprises_closed_source_url_pending"
    if official_count:
        return "official_fragment_and_qice_snapshot_count_gap"
    if qice_count:
        return "qice_enterprise_snapshot_present_official_fragment_missing"
    return "no_qice_candidate_and_no_official_fragment"


def main() -> None:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    dataset_payload = json.loads(args.dataset.read_text(encoding="utf-8"))
    zero_payload = json.loads(args.confirmed_zero_cells.read_text(encoding="utf-8"))
    confirmed_zero_cells = {
        (str(item["batch"]), str(item["region"]))
        for item in zero_payload.get("cells", [])
    }
    source_url = str(dataset_payload.get("sourceUrl") or "https://aiqice.cn/projectDetail?projectId=98")
    captured_at = str(dataset_payload.get("capturedAt") or "")
    records = [
        record
        for record in qice_records(args.dataset)
        if str(record["batch"]) in BATCHES and str(record["region"]) in PROVINCES
    ]
    grouped: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for record in records:
        grouped[(str(record["batch"]), str(record["region"]))].append(
            {
                "enterprise_name": record["enterprise_name"],
                "normalized_name": normalize_name(str(record["enterprise_name"])),
                "qice_eid": record["qice_eid"],
                "region": record["region"],
                "city": record["city"],
                "county": record["county"],
                "recognition_year": record["recognition_year"],
                "batch": record["batch"],
                "platform_year_raw": record["platform_year_raw"],
                "former_names": record["former_names"],
                "source_layer": "企策快照层",
                "source_url": source_url,
                "captured_at": captured_at,
                "verification_status": "platform_snapshot_pending_official_evidence",
            }
        )
    connection = sqlite3.connect(args.database)
    ensure_columns(connection)
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    connection.executescript(
        """
        DROP TABLE IF EXISTS small_giant_qice_snapshots;
        CREATE TABLE small_giant_qice_snapshots(
            id INTEGER PRIMARY KEY,
            batch TEXT NOT NULL,
            recognition_year INTEGER NOT NULL,
            region TEXT NOT NULL,
            candidate_count INTEGER NOT NULL DEFAULT 0,
            snapshot_path TEXT NOT NULL,
            source_url TEXT NOT NULL,
            captured_at TEXT NOT NULL DEFAULT '',
            verification_status TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            UNIQUE(batch,region)
        );
        CREATE INDEX small_giant_qice_snapshots_lookup_idx
        ON small_giant_qice_snapshots(batch,region,verification_status);
        """
    )
    summaries: list[dict[str, object]] = []
    for batch in BATCHES:
        year = int(BATCH_YEARS[batch])
        batch_dir = args.output / f"{year}_{batch}"
        for region in PROVINCES:
            cell_records = sorted(
                grouped.get((batch, region), []),
                key=lambda item: str(item["enterprise_name"]),
            )
            snapshot_path = batch_dir / f"{region}.jsonl"
            write_jsonl(snapshot_path, cell_records)
            connection.execute(
                """
                INSERT INTO small_giant_qice_snapshots(
                    batch,recognition_year,region,candidate_count,snapshot_path,
                    source_url,captured_at,verification_status,generated_at
                ) VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (
                    batch,
                    year,
                    region,
                    len(cell_records),
                    str(snapshot_path),
                    source_url,
                    captured_at,
                    "platform_snapshot_pending_official_evidence",
                    generated_at,
                ),
            )
            coverage = connection.execute(
                """
                SELECT platform_candidate_count,official_fragment_enterprise_count,
                       recovered_url_count,closure_status
                FROM small_giant_fragment_coverage
                WHERE batch=? AND region=?
                """,
                (batch, region),
            ).fetchone()
            candidate_count, official_count, recovered_url_count, closure_status = (
                coverage if coverage else (len(cell_records), 0, 0, "missing_official_fragment")
            )
            status = resolution_status(
                int(official_count),
                int(recovered_url_count),
                len(cell_records),
                int(candidate_count),
                (batch, region) in confirmed_zero_cells,
            )
            connection.execute(
                """
                UPDATE small_giant_fragment_coverage
                SET qice_snapshot_count=?,qice_snapshot_path=?,qice_source_url=?,
                    qice_verification_status=?,resolution_status=?
                WHERE batch=? AND region=?
                """,
                (
                    len(cell_records),
                    str(snapshot_path),
                    source_url,
                    "platform_snapshot_pending_official_evidence",
                    status,
                    batch,
                    region,
                ),
            )
            summaries.append(
                {
                    "batch": batch,
                    "recognition_year": year,
                    "region": region,
                    "platform_candidate_count": int(candidate_count),
                    "qice_snapshot_count": len(cell_records),
                    "official_fragment_enterprise_count": int(official_count),
                    "count_delta_official_minus_qice": int(official_count) - len(cell_records),
                    "recovered_url_count": int(recovered_url_count),
                    "closure_status": str(closure_status),
                    "resolution_status": status,
                    "qice_snapshot_path": str(snapshot_path),
                    "qice_source_url": source_url,
                }
            )
    connection.commit()
    connection.close()
    fields = list(summaries[0])
    with (args.output / "企策补源后地区批次矩阵.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(summaries)
    missing = [
        item
        for item in summaries
        if item["resolution_status"]
        not in {"official_count_enterprise_source_closed", "confirmed_zero_enterprises"}
    ]
    with (args.output / "企策补源后仍缺官方来源清单.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(missing)
    status_counts: dict[str, int] = defaultdict(int)
    for item in summaries:
        status_counts[str(item["resolution_status"])] += 1
    report = {
        "generated_at": generated_at,
        "schema_version": 1,
        "qice_dataset": str(args.dataset),
        "qice_source_url": source_url,
        "qice_captured_at": captured_at,
        "batch_region_count": len(summaries),
        "qice_enterprise_record_count": len(records),
        "resolution_status_counts": dict(sorted(status_counts.items())),
        "still_missing_official_source_count": len(missing),
        "rules": [
            "企策数据只作为企业候选与历史快照，不替代地方主管部门公示附件。",
            "地区、年度和批次均保留，不允许再次扁平化。",
            "企策候选与官方分片数量不一致时保留差额并进入核验清单。",
            "官方链接、附件和企业名单同时闭环后才标记为官方闭环。",
        ],
    }
    (args.output / "企策补源后闭环报告.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report_lines = [
        "# 企策补源后全国小巨人地区批次闭环报告",
        "",
        f"- 生成时间：{generated_at}",
        f"- 企策企业快照：{len(records)} 条",
        f"- 地区批次单元：{len(summaries)} 个",
        f"- 仍需恢复官方证据：{len(missing)} 个",
        "",
        "## 状态统计",
        "",
    ]
    report_lines.extend(
        f"- {status}：{count} 个"
        for status, count in sorted(status_counts.items())
    )
    status_titles = {
        "official_enterprises_closed_source_url_pending": "企业与数量闭环但官方原始链接待恢复",
        "official_fragment_and_qice_snapshot_count_gap": "官方分片与企策企业快照存在数量差额",
        "qice_enterprise_snapshot_present_official_fragment_missing": "企策有企业快照但缺地方官方附件",
        "confirmed_zero_enterprises": "已人工核验为零企业",
        "no_qice_candidate_and_no_official_fragment": "企策与地方官方分片均无候选记录",
    }
    for status, title in status_titles.items():
        items = [item for item in summaries if item["resolution_status"] == status]
        report_lines.extend(["", f"## {title}", ""])
        if not items:
            report_lines.append("- 无")
            continue
        for item in items:
            report_lines.append(
                f"- {item['recognition_year']}年 {item['batch']} {item['region']}："
                f"企策 {item['qice_snapshot_count']} 家，"
                f"官方分片 {item['official_fragment_enterprise_count']} 家，"
                f"官方链接 {item['recovered_url_count']} 条"
            )
    report_lines.extend(
        [
            "",
            "## 使用边界",
            "",
            "- 企策企业快照可用于候选企业检索、名称变更线索和地区批次数量复核。",
            "- 未恢复主管部门公示页面或附件前，不得把企策快照表述为官方名单原文。",
            "- 数量差额优先检查批次语义、历史认定年份、复核记录、企业更名迁址和地方分片是否完整。",
        ]
    )
    (args.output / "企策补源后闭环报告.md").write_text(
        "\n".join(report_lines) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
