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
from typing import Any, Iterable


DEFAULT_DB = Path("/Users/zsh/JiaotangData/索引/current/knowledge_content.sqlite3")
DEFAULT_OUTPUT = Path(
    "/Users/zsh/JiaotangData/知识库/50_名单与对标/优质中小企业梯度培育/"
    "_全国小巨人批次主表/企业身份关联"
)
DEFAULT_REGISTRY = DEFAULT_OUTPUT / "企业信用代码权威补全.csv"
DEFAULT_CANDIDATE_DIR = DEFAULT_OUTPUT / "企知道批量归档"
PUBLIC_SOURCE = "共创研究院知识库"
USCC_PATTERN = re.compile(r"^[0-9A-HJ-NPQRTUWXY]{18}$")
YEAR_PATTERN = re.compile(r"(?:19|20)\d{2}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="建立小巨人企业更名、迁址与统一社会信用代码关联图谱")
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--candidate-dir", type=Path, default=DEFAULT_CANDIDATE_DIR)
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


def read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            item = json.loads(line)
            if not isinstance(item, dict):
                raise RuntimeError(f"{path}:{line_number} 不是JSON对象")
            rows.append(item)
    return rows


def _list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if not value:
        return []
    return [item.strip() for item in re.split(r"[;；、]", str(value)) if item.strip()]


def load_candidate_profiles(
    directory: Path,
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, dict[str, set[str]]],
    dict[str, Any],
]:
    """Load audited batch identities without promoting them to official evidence."""
    profiles: dict[str, dict[str, Any]] = {}
    name_matches: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    invalid_rows = 0
    raw_rows = 0
    files = sorted(directory.glob("企业数字身份证_*.jsonl")) if directory.is_dir() else []
    for path in files:
        for row in read_jsonl(path):
            raw_rows += 1
            code = str(row.get("unified_social_credit_code") or "").strip().upper()
            recognition_name = str(row.get("recognition_name") or "").strip()
            current_name = str(row.get("current_name") or recognition_name).strip()
            if not USCC_PATTERN.fullmatch(code) or not recognition_name or not current_name:
                invalid_rows += 1
                continue
            profile = profiles.setdefault(
                code,
                {
                    "identity_key": code,
                    "unified_social_credit_code": code,
                    "current_name": current_name,
                    "recognition_names": [],
                    "former_names": [],
                    "registration_status": str(row.get("registration_status") or ""),
                    "founded_date": str(row.get("founded_date") or ""),
                    "registered_capital": str(row.get("registered_capital") or ""),
                    "province": str(row.get("province") or ""),
                    "city": str(row.get("city") or ""),
                    "county": str(row.get("county") or ""),
                    "address": str(row.get("address") or ""),
                    "company_type": str(row.get("company_type") or ""),
                    "industry_level_1": str(row.get("industry_level_1") or ""),
                    "industry_level_2": str(row.get("industry_level_2") or ""),
                    "industry_level_3": str(row.get("industry_level_3") or ""),
                    "company_introduction": str(row.get("company_introduction") or ""),
                    "business_scope": str(row.get("business_scope") or ""),
                    "main_product_tags": _list(row.get("main_product_tags")),
                    "industry_track_tags": _list(row.get("industry_track_tags")),
                    "ip_statistics": row.get("ip_statistics") if isinstance(row.get("ip_statistics"), dict) else {},
                    "honors": _list(row.get("honors")),
                    "recognition_years": [],
                    "recognition_batches": [],
                    "verification_status": "audited_single_source_candidate",
                    "source": PUBLIC_SOURCE,
                    "captured_at": str(row.get("qizhi_captured_at") or ""),
                    "source_validation_status": "已完成批次代码锚定，保留单源候选等级",
                },
            )
            row_former_names = _list(row.get("former_names"))
            profile["recognition_names"].append(recognition_name)
            profile["former_names"].extend(row_former_names)
            year = row.get("recognition_year")
            if year not in (None, ""):
                profile["recognition_years"].append(int(year))
            batch = str(row.get("recognition_batch") or "").strip()
            if batch:
                profile["recognition_batches"].append(batch)
            for relation, names in (
                ("recognition", [recognition_name]),
                ("current", [current_name]),
                ("former", row_former_names),
            ):
                for name in names:
                    normalized = normalize_name(name)
                    if normalized:
                        name_matches[normalized][relation].add(code)
    for profile in profiles.values():
        for key in ("recognition_names", "former_names", "recognition_years", "recognition_batches"):
            profile[key] = list(dict.fromkeys(profile[key]))
    stats = {
        "candidate_files": len(files),
        "candidate_rows": raw_rows,
        "candidate_valid_rows": raw_rows - invalid_rows,
        "candidate_invalid_rows": invalid_rows,
        "candidate_unique_codes": len(profiles),
        "candidate_conflicting_names": sum(
            len(set().union(*relations.values())) > 1
            for relations in name_matches.values()
        ),
    }
    return profiles, name_matches, stats


def _founded_year(profile: dict[str, Any]) -> int | None:
    match = YEAR_PATTERN.search(str(profile.get("founded_date") or ""))
    return int(match.group(0)) if match else None


def _eligible_candidate_codes(
    codes: Iterable[str],
    profiles: dict[str, dict[str, Any]],
    recognition_year: int | None,
) -> set[str]:
    result: set[str] = set()
    for code in codes:
        founded_year = _founded_year(profiles.get(code, {}))
        if recognition_year and founded_year and founded_year > recognition_year:
            continue
        result.add(code)
    return result


def resolve_candidate_codes(
    current_name: str,
    former_names: list[str],
    recognition_year: int | None,
    profiles: dict[str, dict[str, Any]],
    name_matches: dict[str, dict[str, set[str]]],
) -> tuple[set[str], str]:
    """Resolve current names before aliases and reject post-recognition entities."""
    normalized_current = normalize_name(current_name)
    exact_current = _eligible_candidate_codes(
        name_matches.get(normalized_current, {}).get("current", set()),
        profiles,
        recognition_year,
    )
    if exact_current:
        return exact_current, "exact_current_name"

    fallback: set[str] = set()
    for name in [current_name, *former_names]:
        relations = name_matches.get(normalize_name(str(name)), {})
        for relation in ("recognition", "former", "current"):
            fallback.update(relations.get(relation, set()))
    return (
        _eligible_candidate_codes(fallback, profiles, recognition_year),
        "historical_name",
    )


def candidate_profile_contains_name(profile: dict[str, Any], name: str) -> bool:
    normalized = normalize_name(name)
    return any(
        normalize_name(str(candidate)) == normalized
        for candidate in [
            profile.get("current_name", ""),
            *profile.get("recognition_names", []),
            *profile.get("former_names", []),
        ]
    )


def write_public_profiles(path: Path, profiles: dict[str, dict[str, Any]]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        for profile in sorted(profiles.values(), key=lambda item: (str(item["current_name"]), str(item["identity_key"]))):
            stream.write(json.dumps(profile, ensure_ascii=False, sort_keys=True) + "\n")
    temporary.replace(path)


def main() -> None:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    registry = load_registry(args.registry)
    candidate_profiles, candidate_name_matches, candidate_stats = load_candidate_profiles(
        args.candidate_dir
    )
    connection = sqlite3.connect(args.database)
    connection.row_factory = sqlite3.Row
    masters = connection.execute("SELECT * FROM national_small_giant_master").fetchall()
    registry_current_by_name: dict[str, list[dict[str, str]]] = defaultdict(list)
    registry_alias_by_name: dict[str, list[dict[str, str]]] = defaultdict(list)
    invalid_registry: list[dict[str, str]] = []
    for row in registry:
        code = row.get("unified_social_credit_code", "").upper()
        if not USCC_PATTERN.fullmatch(code):
            invalid_registry.append(row)
            continue
        candidate = {**row, "unified_social_credit_code": code}
        if row.get("enterprise_name"):
            registry_current_by_name[normalize_name(row["enterprise_name"])].append(candidate)
        if row.get("former_name"):
            registry_alias_by_name[normalize_name(row["former_name"])].append(candidate)
    nodes: dict[str, dict[str, object]] = {}
    aliases: list[dict[str, str]] = []
    conflicts: list[dict[str, object]] = []
    for master in masters:
        current_name = str(master["enterprise_name"])
        former_names = json.loads(str(master["former_names_json"] or "[]"))
        recognition_year = int(master["recognition_year"]) if master["recognition_year"] else None
        authoritative_candidates: dict[str, dict[str, str]] = {}
        exact_authoritative = registry_current_by_name.get(normalize_name(current_name), [])
        registry_matches = exact_authoritative or [
            candidate
            for name in [current_name, *former_names]
            for candidate in [
                *registry_current_by_name.get(normalize_name(str(name)), []),
                *registry_alias_by_name.get(normalize_name(str(name)), []),
            ]
        ]
        for candidate in registry_matches:
            authoritative_candidates[candidate["unified_social_credit_code"]] = candidate
        audited_candidate_codes, audited_match_tier = resolve_candidate_codes(
            current_name,
            [str(item) for item in former_names],
            recognition_year,
            candidate_profiles,
            candidate_name_matches,
        )
        if len(authoritative_candidates) == 1:
            code, _ = next(iter(authoritative_candidates.items()))
            identity_key = code
            confidence = "authoritative_uscc"
            if audited_candidate_codes and audited_candidate_codes != {code}:
                conflicts.append(
                    {
                        "master_id": int(master["id"]),
                        "enterprise_name": current_name,
                        "candidate_codes": sorted({code, *audited_candidate_codes}),
                        "reason": (
                            "权威代码与批次候选代码不一致，保留权威代码并公开冲突路径；"
                            f"批次匹配层级={audited_match_tier}"
                        ),
                    }
                )
            connection.execute(
                "UPDATE national_small_giant_master SET unified_social_credit_code=? WHERE id=?",
                (code, int(master["id"])),
            )
        elif len(authoritative_candidates) > 1:
            identity_key = f"pending:{master['qice_eid'] or normalize_name(current_name)}"
            confidence = "conflict_pending_manual_review"
            conflicts.append(
                {
                    "master_id": int(master["id"]),
                    "enterprise_name": current_name,
                    "candidate_codes": sorted(authoritative_candidates),
                    "reason": "同一现名或曾用名命中多个权威统一社会信用代码",
                }
            )
        elif len(audited_candidate_codes) == 1:
            code = next(iter(audited_candidate_codes))
            identity_key = code
            confidence = "audited_single_source_candidate"
            connection.execute(
                "UPDATE national_small_giant_master SET unified_social_credit_code=? WHERE id=?",
                (code, int(master["id"])),
            )
        elif len(audited_candidate_codes) > 1:
            identity_key = f"pending:{master['qice_eid'] or normalize_name(current_name)}"
            confidence = "conflict_pending_manual_review"
            conflicts.append(
                {
                    "master_id": int(master["id"]),
                    "enterprise_name": current_name,
                    "candidate_codes": sorted(audited_candidate_codes),
                    "reason": f"同一名称层级命中多个批次候选代码：{audited_match_tier}",
                }
            )
        else:
            identity_key = f"qice:{master['qice_eid']}" if master["qice_eid"] else f"name:{normalize_name(current_name)}"
            confidence = "platform_entity_or_name_pending_uscc"
        candidate_profile = candidate_profiles.get(identity_key, {})
        node = nodes.setdefault(
            identity_key,
            {
                "identity_key": identity_key,
                "unified_social_credit_code": identity_key if USCC_PATTERN.fullmatch(identity_key) else "",
                "current_name": str(candidate_profile.get("current_name") or current_name),
                "current_region": str(candidate_profile.get("province") or master["region"]),
                "current_city": str(candidate_profile.get("city") or master["city"]),
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
            selected_profile = candidate_profiles.get(identity_key, {})
            competing_current_codes = candidate_name_matches.get(
                normalize_name(str(former_name)), {}
            ).get("current", set()) - {identity_key}
            if competing_current_codes and not candidate_profile_contains_name(
                selected_profile, str(former_name)
            ):
                continue
            aliases.append(
                {
                    "identity_key": identity_key,
                    "alias_name": str(former_name),
                    "alias_type": "former_name",
                    "batch": str(master["batch"]),
                    "recognition_year": str(master["recognition_year"]),
                }
            )
        for recognition_name in candidate_profile.get("recognition_names", []):
            aliases.append(
                {
                    "identity_key": identity_key,
                    "alias_name": str(recognition_name),
                    "alias_type": "recognition_name",
                    "batch": str(master["batch"]),
                    "recognition_year": str(master["recognition_year"]),
                }
            )
        for former_name in candidate_profile.get("former_names", []):
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
        DROP TABLE IF EXISTS small_giant_enterprise_identity_profiles;
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
        CREATE TABLE small_giant_enterprise_identity_profiles(
            identity_key TEXT PRIMARY KEY,
            unified_social_credit_code TEXT NOT NULL,
            current_name TEXT NOT NULL,
            current_province TEXT NOT NULL DEFAULT '',
            current_city TEXT NOT NULL DEFAULT '',
            current_county TEXT NOT NULL DEFAULT '',
            verification_status TEXT NOT NULL,
            profile_json TEXT NOT NULL,
            source TEXT NOT NULL,
            captured_at TEXT NOT NULL DEFAULT ''
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
        INSERT INTO small_giant_enterprise_identity_profiles(
            identity_key,unified_social_credit_code,current_name,current_province,
            current_city,current_county,verification_status,profile_json,source,captured_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                item["identity_key"], item["unified_social_credit_code"], item["current_name"],
                item["province"], item["city"], item["county"],
                item["verification_status"], json.dumps(item, ensure_ascii=False),
                PUBLIC_SOURCE, item["captured_at"],
            )
            for item in candidate_profiles.values()
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
    linked_code_count = connection.execute(
        "SELECT COUNT(*) FROM national_small_giant_master WHERE unified_social_credit_code<>''"
    ).fetchone()[0]
    authoritative_count = sum(
        item["confidence"] == "authoritative_uscc" for item in nodes.values()
    )
    candidate_linked_count = sum(
        item["confidence"] == "audited_single_source_candidate" for item in nodes.values()
    )
    connection.close()
    write_public_profiles(args.output / "全国小巨人企业数字身份证.jsonl", candidate_profiles)
    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "schema_version": 2,
        "source": PUBLIC_SOURCE,
        "identity_count": len(nodes),
        "alias_count": len(aliases),
        "linked_uscc_master_rows": int(linked_code_count),
        "authoritative_identity_subjects": authoritative_count,
        "audited_single_source_candidate_subjects": candidate_linked_count,
        "conflict_count": len(conflicts),
        "invalid_registry_rows": len(invalid_registry),
        **candidate_stats,
        "rules": [
            "权威来源代码保持最高优先级，不根据名称推算信用代码。",
            "现名精确匹配优先于曾用名和名单名；候选企业成立时间晚于认定年份时不参与该次认定关联。",
            "已完成批次代码锚定的记录按单源候选等级增量关联，不冒充权威工商核验。",
            "平台内部实体标识和曾用名仅用于候选关联，不替代工商核验。",
            "跨省同名、多代码命中和合并重组进入人工待核验。",
            "所有公开来源字段统一投影为共创研究院知识库。",
        ],
    }
    (args.output / "全国小巨人企业数字身份证增量报告.json").write_text(
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
