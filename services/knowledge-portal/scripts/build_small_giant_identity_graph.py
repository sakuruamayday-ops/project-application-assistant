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


DEFAULT_DB = Path("/Users/zsh/JiaotangData/索引/current/knowledge_content.sqlite3")
DEFAULT_OUTPUT = Path(
    "/Users/zsh/JiaotangData/知识库/50_名单与对标/优质中小企业梯度培育/"
    "_全国小巨人批次主表/企业身份关联"
)
DEFAULT_REGISTRY = DEFAULT_OUTPUT / "企业信用代码权威补全.csv"
USCC_PATTERN = re.compile(r"^[0-9A-HJ-NPQRTUWXY]{18}$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="建立小巨人企业更名、迁址与统一社会信用代码关联图谱")
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    return parser.parse_args()


def normalize_name(value: str) -> str:
    return re.sub(r"[\s·•（）()\-—_，,。．]+", "", value or "").lower()


def load_registry(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "enterprise_name", "unified_social_credit_code", "province", "city",
                    "former_name", "event_type", "source_url", "source_name", "verified_at",
                ],
            )
            writer.writeheader()
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [{key: str(value or "").strip() for key, value in row.items()} for row in csv.DictReader(handle)]


def main() -> None:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    registry = load_registry(args.registry)
    connection = sqlite3.connect(args.database)
    connection.row_factory = sqlite3.Row
    masters = connection.execute("SELECT * FROM national_small_giant_master").fetchall()
    by_name: dict[str, list[dict[str, str]]] = defaultdict(list)
    invalid_registry: list[dict[str, str]] = []
    for row in registry:
        code = row.get("unified_social_credit_code", "").upper()
        if not USCC_PATTERN.fullmatch(code):
            invalid_registry.append(row)
            continue
        for name in (row.get("enterprise_name", ""), row.get("former_name", "")):
            if name:
                by_name[normalize_name(name)].append({**row, "unified_social_credit_code": code})
    nodes: dict[str, dict[str, object]] = {}
    aliases: list[dict[str, str]] = []
    conflicts: list[dict[str, object]] = []
    for master in masters:
        current_name = str(master["enterprise_name"])
        former_names = json.loads(str(master["former_names_json"] or "[]"))
        candidates: dict[str, dict[str, str]] = {}
        for name in [current_name, *former_names]:
            for candidate in by_name.get(normalize_name(str(name)), []):
                candidates[candidate["unified_social_credit_code"]] = candidate
        if len(candidates) == 1:
            code, evidence = next(iter(candidates.items()))
            identity_key = code
            confidence = "authoritative_uscc"
            connection.execute(
                "UPDATE national_small_giant_master SET unified_social_credit_code=? WHERE id=?",
                (code, int(master["id"])),
            )
        elif len(candidates) > 1:
            identity_key = f"pending:{master['qice_eid'] or normalize_name(current_name)}"
            confidence = "conflict_pending_manual_review"
            conflicts.append(
                {
                    "master_id": int(master["id"]),
                    "enterprise_name": current_name,
                    "candidate_codes": sorted(candidates),
                    "reason": "同一现名或曾用名命中多个统一社会信用代码",
                }
            )
        else:
            identity_key = f"qice:{master['qice_eid']}" if master["qice_eid"] else f"name:{normalize_name(current_name)}"
            confidence = "platform_entity_or_name_pending_uscc"
        node = nodes.setdefault(
            identity_key,
            {
                "identity_key": identity_key,
                "unified_social_credit_code": identity_key if USCC_PATTERN.fullmatch(identity_key) else "",
                "current_name": current_name,
                "current_region": str(master["region"]),
                "current_city": str(master["city"]),
                "qice_eid": str(master["qice_eid"]),
                "confidence": confidence,
                "batches": set(),
                "recognition_regions": set(),
            },
        )
        node["batches"].add(str(master["batch"]))
        node["recognition_regions"].add(str(master["region"]))
        aliases.append(
            {
                "identity_key": identity_key,
                "alias_name": current_name,
                "alias_type": "current_or_list_name",
                "batch": str(master["batch"]),
                "recognition_year": str(master["recognition_year"]),
            }
        )
        for former_name in former_names:
            aliases.append(
                {
                    "identity_key": identity_key,
                    "alias_name": str(former_name),
                    "alias_type": "former_name",
                    "batch": str(master["batch"]),
                    "recognition_year": str(master["recognition_year"]),
                }
            )
    connection.executescript(
        """
        DROP TABLE IF EXISTS small_giant_enterprise_identities;
        DROP TABLE IF EXISTS small_giant_enterprise_aliases;
        DROP TABLE IF EXISTS small_giant_identity_conflicts;
        CREATE TABLE small_giant_enterprise_identities(
            identity_key TEXT PRIMARY KEY,
            unified_social_credit_code TEXT NOT NULL DEFAULT '',
            current_name TEXT NOT NULL,
            current_region TEXT NOT NULL DEFAULT '',
            current_city TEXT NOT NULL DEFAULT '',
            qice_eid TEXT NOT NULL DEFAULT '',
            confidence TEXT NOT NULL,
            batches_json TEXT NOT NULL DEFAULT '[]',
            recognition_regions_json TEXT NOT NULL DEFAULT '[]'
        );
        CREATE TABLE small_giant_enterprise_aliases(
            id INTEGER PRIMARY KEY,
            identity_key TEXT NOT NULL,
            alias_name TEXT NOT NULL,
            normalized_alias TEXT NOT NULL,
            alias_type TEXT NOT NULL,
            batch TEXT NOT NULL DEFAULT '',
            recognition_year INTEGER,
            UNIQUE(identity_key,normalized_alias,alias_type,batch)
        );
        CREATE TABLE small_giant_identity_conflicts(
            id INTEGER PRIMARY KEY,
            master_id INTEGER NOT NULL,
            enterprise_name TEXT NOT NULL,
            candidate_codes_json TEXT NOT NULL,
            reason TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
        );
        CREATE INDEX small_giant_alias_lookup_idx
        ON small_giant_enterprise_aliases(normalized_alias,batch);
        """
    )
    connection.executemany(
        """
        INSERT INTO small_giant_enterprise_identities(
            identity_key,unified_social_credit_code,current_name,current_region,current_city,
            qice_eid,confidence,batches_json,recognition_regions_json
        ) VALUES(?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                item["identity_key"], item["unified_social_credit_code"], item["current_name"],
                item["current_region"], item["current_city"], item["qice_eid"], item["confidence"],
                json.dumps(sorted(item["batches"]), ensure_ascii=False),
                json.dumps(sorted(item["recognition_regions"]), ensure_ascii=False),
            )
            for item in nodes.values()
        ],
    )
    connection.executemany(
        """
        INSERT OR IGNORE INTO small_giant_enterprise_aliases(
            identity_key,alias_name,normalized_alias,alias_type,batch,recognition_year
        ) VALUES(?,?,?,?,?,?)
        """,
        [
            (
                item["identity_key"], item["alias_name"], normalize_name(item["alias_name"]),
                item["alias_type"], item["batch"], int(item["recognition_year"]),
            )
            for item in aliases
            if item["alias_name"]
        ],
    )
    connection.executemany(
        """
        INSERT INTO small_giant_identity_conflicts(
            master_id,enterprise_name,candidate_codes_json,reason
        ) VALUES(?,?,?,?)
        """,
        [
            (
                item["master_id"], item["enterprise_name"],
                json.dumps(item["candidate_codes"], ensure_ascii=False), item["reason"],
            )
            for item in conflicts
        ],
    )
    connection.commit()
    verified_count = connection.execute(
        "SELECT COUNT(*) FROM national_small_giant_master WHERE unified_social_credit_code<>''"
    ).fetchone()[0]
    connection.close()
    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "schema_version": 1,
        "identity_count": len(nodes),
        "alias_count": len(aliases),
        "verified_uscc_records": int(verified_count),
        "conflict_count": len(conflicts),
        "invalid_registry_rows": len(invalid_registry),
        "rules": [
            "统一社会信用代码只接受权威来源导入，不根据名称推算。",
            "统一社会信用代码完全一致时自动关联。",
            "企策eid和曾用名仅用于候选关联，不替代工商核验。",
            "跨省同名、多代码命中和合并重组进入人工待核验。",
        ],
    }
    (args.output / "企业身份关联报告.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (args.output / "企业身份关联待核验.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["master_id", "enterprise_name", "candidate_codes", "reason"])
        writer.writeheader()
        for item in conflicts:
            writer.writerow(
                {
                    "master_id": item["master_id"],
                    "enterprise_name": item["enterprise_name"],
                    "candidate_codes": "、".join(item["candidate_codes"]),
                    "reason": item["reason"],
                }
            )
    with (args.output / "企业信用代码待补全.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "identity_key", "enterprise_name", "former_names", "recognition_regions",
                "batches", "qice_eid", "unified_social_credit_code", "source_url",
                "source_name", "verified_at",
            ],
        )
        writer.writeheader()
        aliases_by_identity: dict[str, set[str]] = defaultdict(set)
        for item in aliases:
            if item["alias_type"] == "former_name":
                aliases_by_identity[item["identity_key"]].add(item["alias_name"])
        for item in sorted(nodes.values(), key=lambda row: str(row["current_name"])):
            if item["unified_social_credit_code"]:
                continue
            writer.writerow(
                {
                    "identity_key": item["identity_key"],
                    "enterprise_name": item["current_name"],
                    "former_names": "、".join(sorted(aliases_by_identity[item["identity_key"]])),
                    "recognition_regions": "、".join(sorted(item["recognition_regions"])),
                    "batches": "、".join(sorted(item["batches"])),
                    "qice_eid": item["qice_eid"],
                    "unified_social_credit_code": "",
                    "source_url": "",
                    "source_name": "",
                    "verified_at": "",
                }
            )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
