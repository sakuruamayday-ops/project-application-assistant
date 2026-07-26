#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
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
DEFAULT_OUTPUT = Path(
    "/Users/zsh/JiaotangData/知识库/50_名单与对标/优质中小企业梯度培育/"
    "_全国小巨人批次主表/官方地方分片"
)
DEFAULT_SOURCES = (
    Path(__file__).resolve().parents[1]
    / "references"
    / "official_small_giant_fragment_sources.json"
)
URL_PATTERN = re.compile(r"https?://[^\s）)\\]\"'<>，。]+", re.I)
PROVINCES = (
    "北京市", "天津市", "上海市", "重庆市", "河北省", "山西省", "辽宁省", "吉林省",
    "黑龙江省", "江苏省", "浙江省", "安徽省", "福建省", "江西省", "山东省", "河南省",
    "湖北省", "湖南省", "广东省", "海南省", "四川省", "贵州省", "云南省", "陕西省",
    "甘肃省", "青海省", "内蒙古自治区", "广西壮族自治区", "西藏自治区",
    "宁夏回族自治区", "新疆维吾尔自治区", "新疆生产建设兵团",
)
BATCHES = ("第四批", "第五批", "第六批", "第七批")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="构建第四至第七批国家小巨人地方官方分片台账")
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    return parser.parse_args()


def normalize_name(value: str) -> str:
    return re.sub(r"[\s·•（）()\-—_，,。．]+", "", value or "").lower()


def infer_province(title: str, content: str, entity_region: str) -> str:
    for province in PROVINCES:
        if province in entity_region:
            return province
    sample = f"{title}\n{content[:2000]}"
    for province in PROVINCES:
        short = province.removesuffix("省").removesuffix("市").replace("自治区", "")
        if province in sample or (len(short) >= 2 and short in title):
            return province
    return "待核验"


def official_urls(source: str, content: str) -> list[str]:
    urls = set(URL_PATTERN.findall(f"{source}\n{content[:12000]}"))
    return sorted(
        url
        for url in urls
        if "aiqice.cn" not in url
        and "r.jina.ai/" not in url
        and not url.startswith("http://baosong.miit.gov.cn")
    )


def main() -> None:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    curated_sources: dict[tuple[str, str], list[str]] = defaultdict(list)
    if args.sources.is_file():
        for item in json.loads(args.sources.read_text(encoding="utf-8")).get("sources", []):
            key = (str(item.get("batch") or ""), str(item.get("region") or ""))
            curated_sources[key].extend(
                str(item.get(field) or "")
                for field in ("official_page_url", "official_attachment_url")
                if str(item.get(field) or "")
            )
    connection = sqlite3.connect(args.database)
    rows = connection.execute(
        """
        SELECT d.id,d.title,d.content,d.source,d.sha256,d.batch,
               e.enterprise_name,e.sequence_no,e.region,e.context
        FROM documents d
        JOIN public_list_entities e ON e.document_id=d.id
        WHERE d.document_role='50_名单与对标'
          AND d.title LIKE '%小巨人%'
          AND d.batch IN ('第四批','第五批','第六批','第七批')
          AND d.source NOT LIKE '%/_全国小巨人批次主表/%'
          AND d.source NOT LIKE '%/_覆盖矩阵/%'
        """
    ).fetchall()
    fragments: dict[tuple[str, str, int], dict[str, object]] = {}
    document_entities: dict[int, set[str]] = defaultdict(set)
    excluded_terms = ("复核", "重点", "建议支持", "不推荐", "主动放弃", "复核不通过", "未通过复核")
    for document_id, title, content, source, sha256, batch, enterprise_name, sequence_no, region, context in rows:
        scope, _ = infer_scope(str(title), str(content), "")
        if scope != "national_small_giant" or any(term in str(title) for term in excluded_terms):
            continue
        if any(term in str(context) for term in excluded_terms[3:]):
            continue
        province = infer_province(str(title), str(content), str(region or ""))
        key = (str(batch), province, int(document_id))
        fragment = fragments.setdefault(
            key,
            {
                "batch": str(batch),
                "recognition_year": int(BATCH_YEARS[str(batch)]),
                "region": province,
                "document_id": int(document_id),
                "title": str(title),
                "source_path": str(source),
                "content_sha256": str(sha256 or ""),
                "official_urls": sorted(
                    set(
                        official_urls(str(source), str(content))
                        + curated_sources.get((str(batch), province), [])
                    )
                ),
                "sequence_min": "",
                "sequence_max": "",
                "enterprise_count": 0,
                "verification_status": "source_present_pending_url_recovery",
            },
        )
        document_entities[int(document_id)].add(normalize_name(str(enterprise_name)))
        sequences = [value for value in re.findall(r"\d+", str(sequence_no or "")) if value]
        if sequences:
            current_min = int(fragment["sequence_min"]) if fragment["sequence_min"] else int(sequences[0])
            current_max = int(fragment["sequence_max"]) if fragment["sequence_max"] else int(sequences[-1])
            fragment["sequence_min"] = str(min(current_min, *(int(value) for value in sequences)))
            fragment["sequence_max"] = str(max(current_max, *(int(value) for value in sequences)))
    for fragment in fragments.values():
        fragment["enterprise_count"] = len(document_entities[int(fragment["document_id"])])
        if fragment["official_urls"]:
            fragment["verification_status"] = "official_url_recovered"
        elif str(fragment["source_path"]).startswith(("http://", "https://")):
            fragment["official_urls"] = [str(fragment["source_path"])]
            fragment["verification_status"] = "official_url_recovered"
        fragment["fragment_key"] = hashlib.sha256(
            f"{fragment['batch']}|{fragment['region']}|{normalize_name(str(fragment['title']))}|"
            f"{fragment['content_sha256']}".encode()
        ).hexdigest()[:24]
    ordered = sorted(
        fragments.values(),
        key=lambda item: (int(item["recognition_year"]), str(item["region"]), str(item["title"])),
    )
    connection.executescript(
        """
        DROP TABLE IF EXISTS small_giant_official_fragments;
        DROP TABLE IF EXISTS small_giant_fragment_coverage;
        CREATE TABLE small_giant_official_fragments(
            fragment_key TEXT PRIMARY KEY,
            batch TEXT NOT NULL,
            recognition_year INTEGER NOT NULL,
            region TEXT NOT NULL,
            document_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            source_path TEXT NOT NULL,
            official_urls_json TEXT NOT NULL DEFAULT '[]',
            content_sha256 TEXT NOT NULL DEFAULT '',
            sequence_min TEXT NOT NULL DEFAULT '',
            sequence_max TEXT NOT NULL DEFAULT '',
            enterprise_count INTEGER NOT NULL DEFAULT 0,
            verification_status TEXT NOT NULL,
            collected_at TEXT NOT NULL
        );
        CREATE INDEX small_giant_official_fragments_lookup_idx
        ON small_giant_official_fragments(batch,region,verification_status);
        CREATE TABLE small_giant_fragment_coverage(
            id INTEGER PRIMARY KEY,
            batch TEXT NOT NULL,
            recognition_year INTEGER NOT NULL,
            region TEXT NOT NULL,
            platform_candidate_count INTEGER NOT NULL DEFAULT 0,
            official_fragment_enterprise_count INTEGER NOT NULL DEFAULT 0,
            count_delta INTEGER NOT NULL DEFAULT 0,
            fragment_count INTEGER NOT NULL DEFAULT 0,
            recovered_url_count INTEGER NOT NULL DEFAULT 0,
            closure_status TEXT NOT NULL,
            UNIQUE(batch,region)
        );
        """
    )
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    connection.executemany(
        """
        INSERT INTO small_giant_official_fragments(
            fragment_key,batch,recognition_year,region,document_id,title,source_path,
            official_urls_json,content_sha256,sequence_min,sequence_max,
            enterprise_count,verification_status,collected_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                item["fragment_key"], item["batch"], item["recognition_year"], item["region"],
                item["document_id"], item["title"], item["source_path"],
                json.dumps(item["official_urls"], ensure_ascii=False), item["content_sha256"],
                item["sequence_min"], item["sequence_max"], item["enterprise_count"],
                item["verification_status"], generated_at,
            )
            for item in ordered
        ],
    )
    batch_region = defaultdict(lambda: {"documents": 0, "enterprise_names": set(), "urls": 0})
    for item in ordered:
        key = (str(item["batch"]), str(item["region"]))
        batch_region[key]["documents"] += 1
        batch_region[key]["enterprise_names"].update(document_entities[int(item["document_id"])])
        batch_region[key]["urls"] += len(item["official_urls"])
    master_counts: dict[tuple[str, str], int] = {}
    master_exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='national_small_giant_master'"
    ).fetchone()
    if master_exists:
        master_counts = {
            (str(batch), str(region)): int(count)
            for batch, region, count in connection.execute(
                """
                SELECT batch,region,COUNT(*)
                FROM national_small_giant_master
                WHERE batch IN ('第四批','第五批','第六批','第七批')
                GROUP BY batch,region
                """
            )
        }
    summary = []
    for batch in BATCHES:
        for region in PROVINCES:
            value = batch_region[(batch, region)]
            official_count = len(value["enterprise_names"])
            candidate_count = master_counts.get((batch, region), 0)
            if official_count and value["urls"] and official_count == candidate_count:
                closure_status = "closed_count_and_source"
            elif official_count and official_count == candidate_count:
                closure_status = "closed_enterprises_url_pending"
            elif official_count:
                closure_status = "partial_fragment_count_gap"
            else:
                closure_status = "missing_official_fragment"
            summary.append(
                {
                    "batch": batch,
                    "recognition_year": BATCH_YEARS[batch],
                    "region": region,
                    "platform_candidate_count": candidate_count,
                    "official_fragment_enterprise_count": official_count,
                    "count_delta": official_count - candidate_count,
                    "fragment_count": value["documents"],
                    "recovered_url_count": value["urls"],
                    "closure_status": closure_status,
                }
            )
    connection.executemany(
        """
        INSERT INTO small_giant_fragment_coverage(
            batch,recognition_year,region,platform_candidate_count,
            official_fragment_enterprise_count,count_delta,fragment_count,
            recovered_url_count,closure_status
        ) VALUES(?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                item["batch"], item["recognition_year"], item["region"],
                item["platform_candidate_count"], item["official_fragment_enterprise_count"],
                item["count_delta"], item["fragment_count"], item["recovered_url_count"],
                item["closure_status"],
            )
            for item in summary
        ],
    )
    connection.commit()
    connection.close()
    payload = {
        "generated_at": generated_at,
        "schema_version": 1,
        "fragment_count": len(ordered),
        "fragments": ordered,
        "batch_region_summary": summary,
    }
    (args.output / "official_fragments.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (args.output / "官方原始链接恢复队列.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "fragment_key", "batch", "recognition_year", "region", "title",
                "source_path", "content_sha256", "suggested_search_query",
                "official_page_url", "official_attachment_url", "verification_status",
            ],
        )
        writer.writeheader()
        for item in ordered:
            if item["official_urls"]:
                continue
            writer.writerow(
                {
                    "fragment_key": item["fragment_key"],
                    "batch": item["batch"],
                    "recognition_year": item["recognition_year"],
                    "region": item["region"],
                    "title": item["title"],
                    "source_path": item["source_path"],
                    "content_sha256": item["content_sha256"],
                    "suggested_search_query": (
                        f"site:gov.cn {item['region']} {item['batch']} "
                        "专精特新 小巨人 企业 公示 名单"
                    ),
                    "official_page_url": "",
                    "official_attachment_url": "",
                    "verification_status": "pending",
                }
            )
    print(json.dumps({"fragment_count": len(ordered), "batch_region_count": len(summary)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
