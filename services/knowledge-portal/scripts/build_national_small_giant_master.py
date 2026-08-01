#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path

try:
    from scripts.build_specialized_sme_coverage_matrix import BATCH_YEARS, infer_scope
except ModuleNotFoundError:
    from build_specialized_sme_coverage_matrix import BATCH_YEARS, infer_scope


DEFAULT_DB = Path("/Users/zsh/JiaotangData/索引/current/knowledge_content.sqlite3")
DEFAULT_OUTPUT = Path("/Users/zsh/JiaotangData/知识库/50_名单与对标/优质中小企业梯度培育/_全国小巨人批次主表")
DEFAULT_QICE_DATASET = Path.home() / "Downloads" / "企策顾问_国家专精特新小巨人_2019年至今_2026-07-22.json"
DEFAULT_SOURCES = Path(__file__).resolve().parents[1] / "references" / "official_national_small_giant_batches.json"
YEAR_BATCHES = {year: batch for batch, year in BATCH_YEARS.items() if year <= 2025}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="构建保留地区、年度、批次、状态和官方链接的全国小巨人企业级主表")
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--qice-dataset", type=Path, default=DEFAULT_QICE_DATASET)
    parser.add_argument("--batch-sources", type=Path, default=DEFAULT_SOURCES)
    return parser.parse_args()


def normalize_name(value: str) -> str:
    return re.sub(r"[\s·•（）()\-—_，,。．]+", "", value or "").lower()


def record_years(value: str) -> list[int]:
    """Return every platform year claim; claims are not official cohort evidence."""
    return sorted(
        year
        for year in {int(item) for item in re.findall(r"20\d{2}", value or "")}
        if year in YEAR_BATCHES
    )


def record_year(value: str) -> int | None:
    """Legacy discovery cohort only; the official cohort still requires source reconciliation."""
    years = record_years(value)
    return years[0] if years else None


def official_evidence(connection: sqlite3.Connection) -> dict[tuple[str, str], list[dict[str, object]]]:
    rows = connection.execute(
        """
        SELECT d.id,d.title,d.content,d.source,d.canonical_project_name,d.batch,
               e.enterprise_name,e.sequence_no,e.region,e.list_status,e.context
        FROM documents d
        JOIN public_list_entities e ON e.document_id=d.id
        WHERE d.document_role='50_名单与对标'
          AND d.title LIKE '%小巨人%'
          AND d.batch<>''
        """
    ).fetchall()
    evidence: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    excluded_context_terms = ("不推荐", "主动放弃", "复核不通过", "未通过复核", "复核情况")
    for document_id, title, content, source, canonical, batch, enterprise_name, sequence_no, region, list_status, context in rows:
        scope, _ = infer_scope(str(title), str(content), str(canonical))
        if scope != "national_small_giant" or any(term in str(title) for term in ("复核", "重点", "建议支持")):
            continue
        if str(batch) not in BATCH_YEARS:
            continue
        if any(term in str(context) for term in excluded_context_terms):
            continue
        evidence[(str(batch), normalize_name(str(enterprise_name)))].append(
            {
                "document_id": int(document_id),
                "title": str(title),
                "source": str(source),
                "sequence_no": str(sequence_no or ""),
                "region": str(region or ""),
                "list_status": str(list_status or ""),
            }
        )
    return evidence


def fragment_evidence(connection: sqlite3.Connection) -> dict[int, dict[str, object]]:
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='small_giant_official_fragments'"
    ).fetchone()
    if not exists:
        return {}
    return {
        int(document_id): {
            "fragment_key": str(fragment_key),
            "official_urls": json.loads(str(official_urls_json or "[]")),
            "verification_status": str(verification_status),
        }
        for document_id, fragment_key, official_urls_json, verification_status in connection.execute(
            """
            SELECT document_id,fragment_key,official_urls_json,verification_status
            FROM small_giant_official_fragments
            """
        )
    }


def qice_records(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        raise FileNotFoundError(f"缺少企策全国历史获批数据：{path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    records: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for item in payload.get("records", []):
        if not isinstance(item, dict):
            continue
        enterprise_name = str(item.get("entName") or "").strip()
        year = record_year(str(item.get("subsidyYear") or ""))
        if not enterprise_name or year is None:
            continue
        batch = YEAR_BATCHES[year]
        key = (batch, normalize_name(enterprise_name))
        if key in seen:
            continue
        seen.add(key)
        aliases = [
            str(alias.get("entHisName") or "").strip()
            for alias in (item.get("entHisList") or [])
            if isinstance(alias, dict) and str(alias.get("entHisName") or "").strip()
        ]
        records.append(
            {
                "enterprise_name": enterprise_name,
                "normalized_name": key[1],
                "unified_social_credit_code": "",
                "qice_eid": str(item.get("eid") or ""),
                "region": str(item.get("province") or "待核验"),
                "city": str(item.get("city") or ""),
                "county": str(item.get("county") or ""),
                "recognition_year": year,
                "batch": batch,
                "status": "认定",
                "platform_year_raw": str(item.get("subsidyYear") or ""),
                "former_names": aliases,
            }
        )
    return records


def qice_year_claims(path: Path) -> list[dict[str, object]]:
    """Keep multi-year platform labels as discovery claims instead of false official recognitions."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    claims: list[dict[str, object]] = []
    seen: set[tuple[str, str, int]] = set()
    for item in payload.get("records", []):
        if not isinstance(item, dict):
            continue
        enterprise_name = str(item.get("entName") or "").strip()
        normalized_name = normalize_name(enterprise_name)
        qice_eid = str(item.get("eid") or "")
        raw_years = str(item.get("subsidyYear") or "")
        for year in record_years(raw_years):
            key = (qice_eid, normalized_name, year)
            if not enterprise_name or key in seen:
                continue
            seen.add(key)
            claims.append(
                {
                    "enterprise_name": enterprise_name,
                    "normalized_name": normalized_name,
                    "qice_eid": qice_eid,
                    "claim_year": year,
                    "mapped_batch": YEAR_BATCHES[year],
                    "platform_year_raw": raw_years,
                    "evidence_status": "discovery_only",
                }
            )
    return claims


def write_outputs(
    output: Path,
    records: list[dict[str, object]],
    report: dict[str, object],
) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for batch, year in sorted(BATCH_YEARS.items(), key=lambda item: item[1]):
        if year > 2025:
            continue
        path = output / f"{year}_{batch}_国家专精特新小巨人企业主表.jsonl"
        with path.open("w", encoding="utf-8") as handle:
            for record in (item for item in records if item["batch"] == batch):
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    fieldnames = [
        "enterprise_name", "unified_social_credit_code", "region", "city", "county",
        "recognition_year", "batch", "status", "official_url", "official_url_role",
        "official_fragment_key", "verification_status", "sequence_no", "qice_eid", "platform_year_raw",
        "former_names", "source_documents", "source_paths",
    ]
    with (output / "全国小巨人企业级主表.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            row = {key: record.get(key, "") for key in fieldnames}
            for key in ("former_names", "source_documents", "source_paths"):
                row[key] = json.dumps(row[key], ensure_ascii=False)
            writer.writerow(row)
    pending_fields = ["enterprise_name", "region", "city", "recognition_year", "batch", "status", "verification_status", "official_url"]
    with (output / "全国小巨人待官方分片核验.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=pending_fields)
        writer.writeheader()
        for record in records:
            if record["verification_status"] == "dynamic_candidate_pending_official_fragment":
                writer.writerow({key: record.get(key, "") for key in pending_fields})
    (output / "全国小巨人批次主表核验报告.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def replace_database_table(
    connection: sqlite3.Connection,
    records: list[dict[str, object]],
    platform_claims: list[dict[str, object]] | None = None,
) -> None:
    connection.executescript(
        """
        DROP TABLE IF EXISTS national_small_giant_master;
        CREATE TABLE national_small_giant_master(
            id INTEGER PRIMARY KEY,
            enterprise_name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            unified_social_credit_code TEXT NOT NULL DEFAULT '',
            qice_eid TEXT NOT NULL DEFAULT '',
            region TEXT NOT NULL,
            city TEXT NOT NULL DEFAULT '',
            county TEXT NOT NULL DEFAULT '',
            recognition_year INTEGER NOT NULL,
            batch TEXT NOT NULL,
            status TEXT NOT NULL,
            official_url TEXT NOT NULL DEFAULT '',
            official_url_role TEXT NOT NULL DEFAULT '',
            official_fragment_key TEXT NOT NULL DEFAULT '',
            verification_status TEXT NOT NULL,
            sequence_no TEXT NOT NULL DEFAULT '',
            platform_year_raw TEXT NOT NULL DEFAULT '',
            former_names_json TEXT NOT NULL DEFAULT '[]',
            source_documents_json TEXT NOT NULL DEFAULT '[]',
            source_paths_json TEXT NOT NULL DEFAULT '[]',
            UNIQUE(normalized_name,batch,status)
        );
        CREATE INDEX national_small_giant_master_lookup_idx
        ON national_small_giant_master(enterprise_name,recognition_year,batch,region,status);
        DROP TABLE IF EXISTS national_small_giant_platform_year_claims;
        CREATE TABLE national_small_giant_platform_year_claims(
            id INTEGER PRIMARY KEY,
            enterprise_name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            qice_eid TEXT NOT NULL DEFAULT '',
            claim_year INTEGER NOT NULL,
            mapped_batch TEXT NOT NULL,
            platform_year_raw TEXT NOT NULL DEFAULT '',
            evidence_status TEXT NOT NULL DEFAULT 'discovery_only',
            UNIQUE(qice_eid,normalized_name,claim_year)
        );
        CREATE INDEX national_small_giant_platform_year_claims_lookup_idx
        ON national_small_giant_platform_year_claims(enterprise_name,claim_year,mapped_batch);
        """
    )
    connection.executemany(
        """
        INSERT INTO national_small_giant_master(
            enterprise_name,normalized_name,unified_social_credit_code,qice_eid,
            region,city,county,recognition_year,batch,status,official_url,
            official_url_role,official_fragment_key,verification_status,sequence_no,platform_year_raw,
            former_names_json,source_documents_json,source_paths_json
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            (
                item["enterprise_name"], item["normalized_name"], item["unified_social_credit_code"],
                item["qice_eid"], item["region"], item["city"], item["county"],
                item["recognition_year"], item["batch"], item["status"], item["official_url"],
                item["official_url_role"], item["official_fragment_key"], item["verification_status"], item["sequence_no"],
                item["platform_year_raw"], json.dumps(item["former_names"], ensure_ascii=False),
                json.dumps(item["source_documents"], ensure_ascii=False),
                json.dumps(item["source_paths"], ensure_ascii=False),
            )
            for item in records
        ),
    )
    connection.executemany(
        """
        INSERT INTO national_small_giant_platform_year_claims(
            enterprise_name,normalized_name,qice_eid,claim_year,mapped_batch,
            platform_year_raw,evidence_status
        ) VALUES(?,?,?,?,?,?,?)
        """,
        (
            (
                item["enterprise_name"], item["normalized_name"], item["qice_eid"],
                item["claim_year"], item["mapped_batch"], item["platform_year_raw"],
                item["evidence_status"],
            )
            for item in (platform_claims or [])
        ),
    )
    connection.commit()


def replace_batch_coverage_table(
    connection: sqlite3.Connection,
    summaries: list[dict[str, object]],
) -> None:
    connection.executescript(
        """
        DROP TABLE IF EXISTS national_small_giant_batch_coverage;
        CREATE TABLE national_small_giant_batch_coverage(
            batch TEXT PRIMARY KEY,
            recognition_year INTEGER NOT NULL,
            expected_official_count INTEGER NOT NULL,
            extracted_count INTEGER NOT NULL,
            count_delta INTEGER NOT NULL,
            official_local_match_count INTEGER NOT NULL,
            completeness_state TEXT NOT NULL,
            completeness_claim_allowed INTEGER NOT NULL,
            official_url TEXT NOT NULL DEFAULT ''
        );
        """
    )
    connection.executemany(
        """
        INSERT INTO national_small_giant_batch_coverage VALUES(?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                item["batch"], item["year"], item["expected_official_count"],
                item["candidate_count"], item["count_delta"],
                item["official_local_match_count"], item["completeness_state"],
                int(
                    item["count_delta"] == 0
                    and item["official_local_match_count"] == item["expected_official_count"]
                ),
                item["official_url"],
            )
            for item in summaries
        ],
    )
    connection.commit()


def main() -> None:
    args = parse_args()
    sources = json.loads(args.batch_sources.read_text(encoding="utf-8"))
    source_by_batch = {item["batch"]: item for item in sources["batches"]}
    connection = sqlite3.connect(args.database)
    evidence = official_evidence(connection)
    fragments = fragment_evidence(connection)
    records = qice_records(args.qice_dataset)
    platform_claims = qice_year_claims(args.qice_dataset)
    batch_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"candidate": 0, "official_match": 0})
    for record in records:
        batch = str(record["batch"])
        names = [str(record["normalized_name"])] + [normalize_name(str(name)) for name in record["former_names"]]
        matches = []
        for name in names:
            matches.extend(evidence.get((batch, name), []))
        source = source_by_batch[batch]
        batch_stats[batch]["candidate"] += 1
        if matches:
            batch_stats[batch]["official_match"] += 1
        record["source_documents"] = sorted({int(item["document_id"]) for item in matches})
        record["source_paths"] = sorted({str(item["source"]) for item in matches})
        record["sequence_no"] = "、".join(sorted({str(item["sequence_no"]) for item in matches if item["sequence_no"]}))
        matched_fragments = [
            fragments[int(item["document_id"])]
            for item in matches
            if int(item["document_id"]) in fragments
        ]
        fragment_urls = [
            str(url)
            for fragment in matched_fragments
            for url in fragment["official_urls"]
            if str(url)
        ]
        record["official_fragment_key"] = "、".join(
            sorted({str(fragment["fragment_key"]) for fragment in matched_fragments})
        )
        if matches:
            record["verification_status"] = "official_local_fragment_match"
        elif source.get("central_complete_attachment"):
            record["verification_status"] = "central_attachment_name_match_pending"
        else:
            record["verification_status"] = "dynamic_candidate_pending_official_fragment"
        record["official_url"] = fragment_urls[0] if fragment_urls else str(source.get("official_url") or "")
        record["official_url_role"] = (
            "official_local_fragment"
            if fragment_urls
            else str(source.get("official_url_role") or "")
        )
    records.sort(key=lambda item: (int(item["recognition_year"]), str(item["region"]), str(item["enterprise_name"])))
    summaries: list[dict[str, object]] = []
    for batch, year in sorted(BATCH_YEARS.items(), key=lambda item: item[1]):
        if year > 2025:
            continue
        source = source_by_batch[batch]
        candidate = batch_stats[batch]["candidate"]
        expected = int(source["expected_count"])
        summaries.append(
            {
                "batch": batch,
                "year": year,
                "expected_official_count": expected,
                "candidate_count": candidate,
                "count_delta": candidate - expected,
                "official_local_match_count": batch_stats[batch]["official_match"],
                "central_complete_attachment": bool(source.get("central_complete_attachment")),
                "completeness_state": "count_aligned" if candidate == expected else "gap_or_surplus_requires_reconciliation",
                "official_url": source.get("official_url", ""),
            }
        )
    replace_database_table(connection, records, platform_claims)
    replace_batch_coverage_table(connection, summaries)
    connection.close()
    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "schema_version": 2,
        "record_count": len(records),
        "platform_year_claim_count": len(platform_claims),
        "batches": summaries,
        "mandatory_fields": ["region", "recognition_year", "batch", "status", "official_url"],
        "rules": [
            "认定、复核、重点支持和地方小巨人分别建记录，禁止扁平合并。",
            "企策数据仅作发现与补全，不替代官方名单。",
            "官方链接缺失时保留空值并进入核验，不允许伪造或用平台链接冒充。",
            "后续导入必须保留地区、年度、批次、状态和官方链接。",
            "平台多年度标签逐年保留在 discovery_only 声明表，不得直接升级为官方认定批次。",
        ],
    }
    write_outputs(args.output, records, report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
