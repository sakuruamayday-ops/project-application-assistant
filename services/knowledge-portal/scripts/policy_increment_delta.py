#!/usr/bin/env python3
"""Build, sign, replay, and measure a policy-only SQLite index delta.

This module deliberately has no OSS, SSH, deployment-lock, or production-pointer
capability.  It consumes one frozen policy handoff and writes only caller-selected
candidate/package directories.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import mmap
import os
import re
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

try:
    from . import build_document_scopes as scope_index
    from . import build_knowledge_content_index as content_index
    from . import update_cloud_policy_manifest as cloud_manifest
except ImportError:
    import build_document_scopes as scope_index
    import build_knowledge_content_index as content_index
    import update_cloud_policy_manifest as cloud_manifest


SCHEMA_VERSION = "1.0"
DELTA_FORMAT = "jiaotang-policy-sqlite-delta-v1"
BASE_FORMAT = "jiaotang-policy-sqlite-base-v1"
DEFAULT_KNOWLEDGE_ROOT = Path("/Users/zsh/JiaotangData/知识库")
DEFAULT_BASE_DB = Path("/Users/zsh/JiaotangData/索引/current/knowledge_content.sqlite3")
DEFAULT_BASE_MANIFEST = Path("/Users/zsh/JiaotangData/索引/current/manifest.jsonl")
INDEXABLE_ACTIONS = {"upload", "reference_duplicate"}
AUTHORITATIVE_LIST_TERMS = (
    "国家专精特新“小巨人”",
    "国家专精特新小巨人",
    "浙江省专精特新中小企业",
    "浙江省首台套",
    "浙江省首台（套）",
    "浙江省首批次新材料",
    "浙江省首版次软件",
)
AUTHORITATIVE_LIST_SEMANTICS = ("名单", "认定", "公示", "复核", "通过", "公布", "公告")
HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class PolicyIncrementError(RuntimeError):
    """A fail-closed policy increment validation error."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_json_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def write_json(path: Path, payload: object) -> None:
    path.write_bytes(canonical_json_bytes(payload))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def ensure_new_directory(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if resolved.exists():
        raise PolicyIncrementError(f"输出目录已存在，拒绝覆盖：{resolved}")
    resolved.mkdir(parents=True)
    return resolved


def ensure_inside(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as error:
        raise PolicyIncrementError(f"交接路径越出知识库根目录：{resolved}") from error
    return resolved


def clone_file(source: Path, target: Path) -> None:
    if target.exists():
        raise PolicyIncrementError(f"克隆目标已存在，拒绝覆盖：{target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    attempts = (
        ["cp", "-c", str(source), str(target)],
        ["cp", "--reflink=always", str(source), str(target)],
    )
    errors: list[str] = []
    for command in attempts:
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            return
        errors.append(result.stderr.strip())
    if os.environ.get("JIAOTANG_POLICY_ALLOW_FULL_COPY") == "1":
        shutil.copy2(source, target)
        return
    raise PolicyIncrementError(
        "写时复制克隆失败；为避免日常增量意外生成整库副本，本工具不回退普通复制。"
        "灾难恢复确需完整复制时才可显式设置JIAOTANG_POLICY_ALLOW_FULL_COPY=1："
        + " | ".join(error for error in errors if error)
    )


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as error:
                raise PolicyIncrementError(f"JSONL 第 {line_number} 行无效：{path}") from error
            if not isinstance(item, dict):
                raise PolicyIncrementError(f"JSONL 第 {line_number} 行不是对象：{path}")
            rows.append(item)
    return rows


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with path.open("wb") as stream:
        for row in rows:
            stream.write(canonical_json_bytes(row))


def load_expected_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        row["size_bytes"] = int(row["size_bytes"])
    return rows


def flattened_handoff_rows(handoff: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in handoff.get("records", []):
        for item in record.get("files", []):
            rows.append(
                {
                    "record_key": str(record["record_key"]),
                    "role": str(item["role"]),
                    "expected_manifest_path": str(item["expected_manifest_path"]),
                    "sha256": str(item["sha256"]),
                    "size_bytes": int(item["size_bytes"]),
                    "match_rule": "exactly_one:path+sha256+size_bytes",
                }
            )
    return sorted(rows, key=lambda row: (row["expected_manifest_path"], row["record_key"]))


def authoritative_list_triggers(handoff: dict[str, Any]) -> list[str]:
    """Return five-category list triggers without treating negating notes as evidence."""
    triggered: set[str] = set()
    for record in handoff.get("records", []):
        metadata = record.get("metadata", {})
        title = " ".join(
            str(metadata.get(field, "")) for field in ("formal_title", "project_name")
        )
        file_type = str(metadata.get("file_type") or "")
        has_list_semantics = any(term in title for term in AUTHORITATIVE_LIST_SEMANTICS)
        if file_type == "申报通知" and not has_list_semantics:
            continue
        if not has_list_semantics:
            continue
        triggered.update(term for term in AUTHORITATIVE_LIST_TERMS if term in title)
    return sorted(triggered)


def verify_frozen_handoff(handoff_dir: Path, knowledge_root: Path) -> dict[str, Any]:
    handoff_path = handoff_dir / "increment_handoff.json"
    expected_path = handoff_dir / "manifest_expected_hits.csv"
    digest_path = handoff_dir / "handoff_digest.json"
    for required in (handoff_path, expected_path, digest_path):
        if not required.is_file():
            raise PolicyIncrementError(f"冻结交接包缺少文件：{required}")
    handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
    digest = json.loads(digest_path.read_text(encoding="utf-8"))
    if handoff.get("schema_version") != SCHEMA_VERSION:
        raise PolicyIncrementError(f"不支持的交接 schema：{handoff.get('schema_version')}")
    if digest.get("handoff_sha256") != sha256_file(handoff_path):
        raise PolicyIncrementError("increment_handoff.json SHA-256 与冻结摘要不一致")
    if digest.get("manifest_expected_hits_sha256") != sha256_file(expected_path):
        raise PolicyIncrementError("manifest_expected_hits.csv SHA-256 与冻结摘要不一致")
    expected = load_expected_csv(expected_path)
    flattened = flattened_handoff_rows(handoff)
    if expected != flattened:
        raise PolicyIncrementError("交接 JSON 与预期 manifest CSV 的逐文件集合不一致")
    declared = int(handoff.get("summary", {}).get("expected_manifest_rows", -1))
    if declared != len(expected):
        raise PolicyIncrementError(f"交接文件数不一致：宣称 {declared}，实际 {len(expected)}")
    record_digests = digest.get("record_content_sha256", {})
    for record in handoff.get("records", []):
        key = str(record["record_key"])
        if record_digests.get(key) != record.get("record_content_sha256"):
            raise PolicyIncrementError(f"政策记录内容摘要不一致：{key}")
    verified_bytes = 0
    for row in expected:
        if not HEX_SHA256.fullmatch(str(row["sha256"])):
            raise PolicyIncrementError(f"非法 SHA-256：{row['expected_manifest_path']}")
        source = ensure_inside(knowledge_root / row["expected_manifest_path"], knowledge_root)
        if not source.is_file():
            raise PolicyIncrementError(f"交接源文件缺失：{source}")
        if source.stat().st_size != row["size_bytes"]:
            raise PolicyIncrementError(f"交接源文件大小变化：{source}")
        if sha256_file(source) != row["sha256"]:
            raise PolicyIncrementError(f"交接源文件哈希变化：{source}")
        verified_bytes += int(row["size_bytes"])
    if verified_bytes != int(handoff.get("summary", {}).get("archive_bytes", -1)):
        raise PolicyIncrementError("交接总字节数与逐文件复核不一致")
    triggered = authoritative_list_triggers(handoff)
    if triggered:
        raise PolicyIncrementError(
            "本交接触发权威名单专用链，普通增量器拒绝处理：" + "、".join(triggered)
        )
    return {
        "handoff": handoff,
        "expected": expected,
        "handoff_sha256": sha256_file(handoff_path),
        "expected_sha256": sha256_file(expected_path),
        "digest_sha256": sha256_file(digest_path),
        "archive_bytes": verified_bytes,
    }


def manifest_verification(
    expected: list[dict[str, Any]], manifest_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    by_path: dict[str, list[dict[str, Any]]] = {}
    for row in manifest_rows:
        by_path.setdefault(str(row.get("relative_path") or ""), []).append(row)
    counts = {key: 0 for key in ("exact", "missing", "duplicate", "hash_mismatch", "size_mismatch")}
    results: list[dict[str, Any]] = []
    for item in expected:
        matches = by_path.get(item["expected_manifest_path"], [])
        if not matches:
            status = "missing"
        elif len(matches) != 1:
            status = "duplicate"
        elif str(matches[0].get("sha256") or "") != item["sha256"]:
            status = "hash_mismatch"
        elif int(matches[0].get("size_bytes") or -1) != int(item["size_bytes"]):
            status = "size_mismatch"
        else:
            status = "exact"
        counts[status] += 1
        results.append({**item, "status": status})
    return {
        "match_key": "relative_path+sha256+size_bytes",
        "required_cardinality": 1,
        "counts": counts,
        "all_exact": counts["exact"] == len(expected),
        "results": results,
    }


def build_manifest_delta(
    handoff: dict[str, Any],
    knowledge_root: Path,
    base_manifest_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    previous: dict[str, dict[str, Any]] = {}
    for row in base_manifest_rows:
        relative = str(row.get("relative_path") or "")
        if relative in previous:
            raise PolicyIncrementError(f"基线 manifest 路径重复：{relative}")
        previous[relative] = row
    delta_rows: list[dict[str, Any]] = []
    for record in handoff["records"]:
        companions = [
            str(item["expected_manifest_path"])
            for item in record["files"]
            if item["role"] == "supporting_file"
        ]
        for item in record["files"]:
            relative = str(item["expected_manifest_path"])
            source = ensure_inside(knowledge_root / relative, knowledge_root)
            row = cloud_manifest.manifest_row(source, previous.get(relative))
            if row["sha256"] != item["sha256"] or int(row["size_bytes"]) != int(item["size_bytes"]):
                raise PolicyIncrementError(f"生成 manifest 行时冻结属性发生变化：{relative}")
            row["handoff_record_key"] = str(record["record_key"])
            row["handoff_file_role"] = str(item["role"])
            if item["role"] == "official_attachment" and companions:
                row["index_mode"] = "archive_only"
                row["text_companion_paths"] = companions
                row["text_companion_status"] = "available"
            delta_rows.append(row)
    return sorted(delta_rows, key=lambda row: str(row["relative_path"]))


def merge_manifest_rows(
    base_rows: list[dict[str, Any]], delta_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for row in base_rows:
        path = str(row.get("relative_path") or "")
        if not path or path in merged:
            raise PolicyIncrementError(f"基线 manifest 存在空路径或重复路径：{path}")
        merged[path] = row
    for row in delta_rows:
        merged[str(row["relative_path"])] = row
    return [merged[path] for path in sorted(merged)]


def metadata_queue_items(metadata: dict[str, Any], document_role: str) -> list[dict[str, str]]:
    if not document_role.startswith(("10_", "20_")):
        return []
    rows: list[dict[str, str]] = []
    if not metadata.get("canonical_project_name") and metadata.get("document_stage") != "其他":
        rows.append({"reason": "项目名称未能可靠映射", "priority": "medium"})
    if (
        metadata.get("document_stage") in content_index.OFFICIAL_VALIDITY_STAGES
        and metadata.get("validity_status") in {"active_candidate", "revised", "trial", "draft"}
    ):
        rows.append({"reason": "有效性需要官方网站复核", "priority": "high"})
    return rows


def build_document_payloads(delta_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    catalog = content_index.load_project_catalog()
    # Full builds currently call infer_document_metadata without an external
    # correction list. Keep the increment path behavior-identical.
    corrections: list[dict[str, Any]] = []
    documents: list[dict[str, Any]] = []
    for item in delta_rows:
        if item.get("upload_action") not in INDEXABLE_ACTIONS or item.get("index_mode") != "extract_text":
            continue
        path = Path(str(item["source_path"]))
        text, status = content_index.extract(path, str(item["extension"]))
        if status != "indexed":
            raise PolicyIncrementError(f"增量文件未能形成可检索文本：{item['relative_path']} ({status})")
        prefix = str(item.get("content_prefix") or "").strip()
        if prefix:
            text = f"{prefix}\n\n{text}".strip()
        metadata = content_index.infer_document_metadata(
            str(item["title"]),
            str(item["relative_path"]),
            text,
            str(item["document_role"]),
            catalog,
            corrections,
        )
        structured_entities: list[tuple[object, ...]] = []
        if str(item["extension"]) == ".json":
            structured_entities = content_index.structured_small_giant_entities(
                path.read_text(encoding="utf-8", errors="ignore")
            )
        mention_rows: list[tuple[str, str, str]] = []
        list_rows: list[tuple[object, ...]] = []
        if structured_entities:
            for entity in structured_entities:
                mention_rows.append((str(entity[0]), str(entity[1]), str(entity[7])))
                list_rows.append(tuple(entity))
        else:
            mention_rows = content_index.enterprise_mentions(text)
            if str(item["document_role"]) == "50_名单与对标":
                for name, sequence, context in mention_rows:
                    confidence = (
                        "high"
                        if metadata.get("canonical_project_name")
                        and metadata.get("document_stage") != "其他"
                        else "medium"
                    )
                    list_rows.append(
                        (
                            name,
                            sequence,
                            str(metadata.get("canonical_project_name") or ""),
                            metadata.get("policy_year"),
                            str(metadata.get("batch") or ""),
                            str(metadata.get("region") or ""),
                            str(metadata.get("document_stage") or ""),
                            context,
                            confidence,
                        )
                    )
        document = {
            "source_key": item["source_key"],
            "title": item["title"],
            "content": text,
            "source": item["relative_path"],
            "cloud_path": item["cloud_path"],
            "document_role": item["document_role"],
            "sensitivity": item["sensitivity"],
            "sha256": item["sha256"],
            "updated_at": item["modified_at"],
            "canonical_project_name": metadata["canonical_project_name"],
            "region": metadata["region"],
            "document_stage": metadata["document_stage"],
            "validity_status": metadata["validity_status"],
            "policy_year": metadata["policy_year"],
            "batch": metadata["batch"],
            "replacement_title": metadata["replacement_title"],
            "replacement_basis": metadata["replacement_basis"],
            "replacement_url": metadata["replacement_url"],
            "chunks": [list(row) for row in content_index.iter_chunks(text)],
            "mentions": [list(row) for row in mention_rows],
            "list_entities": [list(row) for row in list_rows],
            "match_evidence": metadata.get("match_evidence", []),
            "queue_items": metadata_queue_items(metadata, str(item["document_role"])),
        }
        documents.append(document)
    return sorted(documents, key=lambda row: str(row["source_key"]))


DOCUMENT_COLUMNS = (
    "source_key",
    "title",
    "content",
    "source",
    "cloud_path",
    "document_role",
    "sensitivity",
    "sha256",
    "updated_at",
    "canonical_project_name",
    "region",
    "document_stage",
    "validity_status",
    "policy_year",
    "batch",
    "replacement_title",
    "replacement_basis",
    "replacement_url",
)


def delete_external_fts(connection: sqlite3.Connection, table: str, row: sqlite3.Row) -> None:
    connection.execute(
        f"INSERT INTO {table}({table},rowid,title,content,source,document_role) "
        "VALUES('delete',?,?,?,?,?)",
        (
            int(row["id"]),
            str(row["title"]),
            str(row["content"]),
            str(row["source"]),
            str(row["document_role"]),
        ),
    )


def delete_document_dependents(connection: sqlite3.Connection, row: sqlite3.Row) -> set[int]:
    document_id = int(row["id"])
    cluster_ids = {
        int(item[0])
        for item in connection.execute(
            "SELECT cluster_id FROM policy_document_cluster_members WHERE document_id=?",
            (document_id,),
        )
    }
    referenced = connection.execute(
        "SELECT COUNT(*) FROM policy_verification_propagations "
        "WHERE source_document_id=? OR target_document_id=?",
        (document_id, document_id),
    ).fetchone()[0]
    if referenced:
        raise PolicyIncrementError(
            f"修订文档 {document_id} 已进入人工核验传播链，拒绝自动覆盖"
        )
    delete_external_fts(connection, "documents_fts", row)
    delete_external_fts(connection, "documents_fts_trigram", row)
    chunk_fts_ids = [
        int(item[0])
        for item in connection.execute(
            "SELECT rowid FROM document_chunks_fts WHERE document_id=?", (document_id,)
        )
    ]
    connection.executemany(
        "DELETE FROM document_chunks_fts WHERE rowid=?",
        ((rowid,) for rowid in chunk_fts_ids),
    )
    entity_ids = [
        int(item[0])
        for item in connection.execute(
            "SELECT id FROM public_list_entities WHERE document_id=?", (document_id,)
        )
    ]
    connection.executemany(
        "DELETE FROM public_list_entity_years WHERE entity_id=?",
        ((entity_id,) for entity_id in entity_ids),
    )
    for table in (
        "document_chunks",
        "enterprise_mentions",
        "public_list_entities",
        "metadata_match_evidence",
        "policy_verification_queue",
        "document_scopes",
        "virtual_catalog_entries",
        "policy_document_cluster_members",
    ):
        connection.execute(f"DELETE FROM {table} WHERE document_id=?", (document_id,))
    return cluster_ids


def insert_document_dependents(
    connection: sqlite3.Connection,
    document_id: int,
    document: dict[str, Any],
    generated_at: str,
) -> None:
    connection.execute(
        "INSERT INTO documents_fts(rowid,title,content,source,document_role) VALUES (?,?,?,?,?)",
        (
            document_id,
            document["title"],
            document["content"],
            document["source"],
            document["document_role"],
        ),
    )
    connection.execute(
        "INSERT INTO documents_fts_trigram(rowid,title,content,source,document_role) "
        "VALUES (?,?,?,?,?)",
        (
            document_id,
            document["title"],
            document["content"],
            document["source"],
            document["document_role"],
        ),
    )
    chunk_rows = [
        (document_id, int(chunk[0]), str(chunk[1])) for chunk in document["chunks"]
    ]
    connection.executemany(
        "INSERT INTO document_chunks(document_id,chunk_number,content) VALUES (?,?,?)",
        chunk_rows,
    )
    connection.executemany(
        "INSERT INTO document_chunks_fts(document_id,chunk_number,title,content,source) "
        "VALUES (?,?,?,?,?)",
        (
            (document_id, number, document["title"], content, document["source"])
            for _, number, content in chunk_rows
        ),
    )
    connection.executemany(
        "INSERT OR IGNORE INTO enterprise_mentions("
        "document_id,enterprise_name,sequence_no,context) VALUES (?,?,?,?)",
        ((document_id, *row) for row in document["mentions"]),
    )
    for entity in document["list_entities"]:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO public_list_entities(
                document_id,enterprise_name,sequence_no,canonical_project_name,
                policy_year,batch,region,list_status,context,confidence
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (document_id, *entity),
        )
        if cursor.rowcount == 0:
            entity_id = int(
                connection.execute(
                    "SELECT id FROM public_list_entities WHERE document_id=? "
                    "AND enterprise_name=? AND sequence_no=?",
                    (document_id, str(entity[0]), str(entity[1])),
                ).fetchone()[0]
            )
        else:
            entity_id = int(cursor.lastrowid)
        years = {int(year) for year in content_index.YEAR_PATTERN.findall(str(entity[7] or ""))}
        if entity[3]:
            years.add(int(entity[3]))
        year_role = "platform_record" if str(entity[8]) == "medium" else "official_document_year"
        connection.executemany(
            "INSERT OR IGNORE INTO public_list_entity_years(entity_id,year,year_role) VALUES (?,?,?)",
            ((entity_id, year, year_role) for year in sorted(years)),
        )
    for evidence in document["match_evidence"]:
        connection.execute(
            """
            INSERT OR REPLACE INTO metadata_match_evidence(
                document_id,field_name,inferred_value,matched_term,match_method,
                source_scope,source_excerpt,rule_version,confidence,review_status,
                correction_id,created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                document_id,
                evidence["field_name"],
                evidence["inferred_value"],
                evidence["matched_term"],
                evidence["match_method"],
                evidence["source_scope"],
                evidence["source_excerpt"],
                evidence["rule_version"],
                evidence["confidence"],
                evidence["review_status"],
                evidence["correction_id"],
                generated_at,
            ),
        )
    for queue in document["queue_items"]:
        connection.execute(
            """
            INSERT OR IGNORE INTO policy_verification_queue(
                document_id,reason,priority,status,created_at,updated_at
            ) VALUES (?,?,?,'pending',?,?)
            """,
            (document_id, queue["reason"], queue["priority"], generated_at, generated_at),
        )


def rebuild_scope_group(
    connection: sqlite3.Connection, sha256: str, generated_at: str
) -> None:
    existing_canonical = connection.execute(
        "SELECT canonical_document_id FROM canonical_documents WHERE sha256=?", (sha256,)
    ).fetchone()
    members = connection.execute(
        """
        SELECT id,source_key,title,content,source,cloud_path,document_role,sha256,
               canonical_project_name,region,document_stage,policy_year,batch
        FROM documents WHERE sha256=? ORDER BY id
        """,
        (sha256,),
    ).fetchall()
    ids = {int(row["id"]) for row in members}
    if existing_canonical:
        ids.add(int(existing_canonical[0]))
    if ids:
        placeholders = ",".join("?" for _ in ids)
        values = tuple(sorted(ids))
        connection.execute(
            f"DELETE FROM virtual_catalog_entries WHERE document_id IN ({placeholders})", values
        )
        connection.execute(
            f"DELETE FROM document_scopes WHERE document_id IN ({placeholders})", values
        )
        connection.execute(
            f"DELETE FROM document_duplicates WHERE document_id IN ({placeholders}) "
            f"OR canonical_document_id IN ({placeholders})",
            values + values,
        )
    connection.execute("DELETE FROM canonical_documents WHERE sha256=?", (sha256,))
    if not members:
        return
    canonical = min(members, key=scope_index.canonical_sort_key)
    connection.execute(
        """
        INSERT INTO canonical_documents(
            canonical_document_id,sha256,duplicate_count,preferred_basis,rule_version,updated_at
        ) VALUES (?,?,?,?,?,?)
        """,
        (
            int(canonical["id"]),
            sha256,
            len(members),
            "role_official_dynamic_path_priority",
            scope_index.RULE_VERSION,
            generated_at,
        ),
    )
    connection.executemany(
        """
        INSERT INTO document_duplicates(
            document_id,canonical_document_id,duplicate_kind,duplicate_basis,rule_version,updated_at
        ) VALUES (?,?,?,?,?,?)
        """,
        (
            (
                int(member["id"]),
                int(canonical["id"]),
                "canonical" if member["id"] == canonical["id"] else "exact_sha256",
                "sha256",
                scope_index.RULE_VERSION,
                generated_at,
            )
            for member in members
        ),
    )
    scopes = scope_index.scope_rows(canonical, list(members), generated_at)
    connection.executemany(
        """
        INSERT INTO document_scopes(
            document_id,scope_type,scope_value,scope_level,scope_basis,confidence,
            is_primary,rule_version,updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?)
        """,
        scopes,
    )
    connection.executemany(
        """
        INSERT INTO virtual_catalog_entries(
            document_id,virtual_path,catalog_role,sort_key,rule_version,updated_at
        ) VALUES (?,?,?,?,?,?)
        """,
        scope_index.virtual_paths(canonical, scopes, generated_at),
    )


def policy_cluster_identity(connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    manual = connection.execute(
        "SELECT manual_cluster_key,operation_type FROM policy_cluster_manual_assignments "
        "WHERE document_id=?",
        (int(row["id"]),),
    ).fetchone()
    title = str(row["title"] or "")
    source_name = Path(str(row["source"] or "")).name
    document_number = content_index.normalize_policy_document_number(f"{title}\n{source_name}")
    normalized_title = content_index.normalize_policy_cluster_title(title)
    if manual:
        identity = str(manual[0])
        method, confidence = f"manual_{manual[1]}", "high"
    elif document_number:
        identity = f"number:{document_number}"
        method, confidence = "document_number", "high"
    elif len(normalized_title) >= 8 and not content_index.generic_policy_cluster_title(normalized_title):
        scope = "|".join(
            (
                normalized_title,
                str(row["canonical_project_name"] or ""),
                str(row["region"] or ""),
                str(row["policy_year"] or ""),
            )
        )
        identity = f"title:{hashlib.sha256(scope.encode('utf-8')).hexdigest()}"
        method, confidence = "exact_normalized_title_scope", "medium"
    else:
        identity = f"document:{int(row['id'])}"
        method, confidence = "singleton", "low"
    return {
        "cluster_key": identity,
        "normalized_title": normalized_title,
        "document_number": document_number,
        "match_method": method,
        "confidence": confidence,
    }


def refresh_cluster(connection: sqlite3.Connection, cluster_id: int, generated_at: str) -> None:
    members = connection.execute(
        """
        SELECT d.id,d.title,d.source,d.document_role,d.canonical_project_name,d.region,d.policy_year
        FROM policy_document_cluster_members AS m
        JOIN documents AS d ON d.id=m.document_id
        WHERE m.cluster_id=? ORDER BY d.id
        """,
        (cluster_id,),
    ).fetchall()
    if not members:
        propagated = connection.execute(
            "SELECT COUNT(*) FROM policy_verification_propagations WHERE cluster_id=?",
            (cluster_id,),
        ).fetchone()[0]
        if propagated:
            raise PolicyIncrementError(f"空政策簇 {cluster_id} 已被核验传播引用，拒绝自动删除")
        connection.execute("DELETE FROM policy_document_clusters WHERE id=?", (cluster_id,))
        return
    representative = members[0]
    identity = policy_cluster_identity(connection, representative)
    connection.execute(
        """
        UPDATE policy_document_clusters SET
            normalized_title=?,document_number=?,canonical_project_name=?,region=?,policy_year=?,
            representative_document_id=?,match_method=?,confidence=?,rule_version=?,updated_at=?
        WHERE id=?
        """,
        (
            identity["normalized_title"],
            identity["document_number"],
            representative["canonical_project_name"],
            representative["region"],
            representative["policy_year"],
            int(representative["id"]),
            identity["match_method"],
            identity["confidence"],
            content_index.POLICY_CLUSTER_RULE_VERSION,
            generated_at,
            cluster_id,
        ),
    )


def upsert_policy_cluster(
    connection: sqlite3.Connection, document_id: int, generated_at: str
) -> int | None:
    row = connection.execute(
        """
        SELECT id,title,source,document_role,canonical_project_name,region,policy_year
        FROM documents WHERE id=?
        """,
        (document_id,),
    ).fetchone()
    if not str(row["document_role"]).startswith(("10_", "20_")):
        return None
    identity = policy_cluster_identity(connection, row)
    existing = connection.execute(
        "SELECT id FROM policy_document_clusters WHERE cluster_key=?",
        (identity["cluster_key"],),
    ).fetchone()
    if existing:
        cluster_id = int(existing[0])
    else:
        cursor = connection.execute(
            """
            INSERT INTO policy_document_clusters(
                cluster_key,normalized_title,document_number,canonical_project_name,
                region,policy_year,representative_document_id,match_method,confidence,
                rule_version,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                identity["cluster_key"],
                identity["normalized_title"],
                identity["document_number"],
                row["canonical_project_name"],
                row["region"],
                row["policy_year"],
                document_id,
                identity["match_method"],
                identity["confidence"],
                content_index.POLICY_CLUSTER_RULE_VERSION,
                generated_at,
                generated_at,
            ),
        )
        cluster_id = int(cursor.lastrowid)
    connection.execute(
        """
        INSERT OR REPLACE INTO policy_document_cluster_members(
            cluster_id,document_id,membership_basis,confidence,created_at
        ) VALUES (?,?,?,?,?)
        """,
        (
            cluster_id,
            document_id,
            identity["match_method"],
            identity["confidence"],
            generated_at,
        ),
    )
    refresh_cluster(connection, cluster_id, generated_at)
    return cluster_id


def validate_database(path: Path) -> dict[str, Any]:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        counts = {
            "documents": int(connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]),
            "chunks": int(connection.execute("SELECT COUNT(*) FROM document_chunks").fetchone()[0]),
            "documents_fts": int(connection.execute("SELECT COUNT(*) FROM documents_fts").fetchone()[0]),
            "documents_fts_trigram": int(
                connection.execute("SELECT COUNT(*) FROM documents_fts_trigram").fetchone()[0]
            ),
            "document_chunks_fts": int(
                connection.execute("SELECT COUNT(*) FROM document_chunks_fts").fetchone()[0]
            ),
        }
    finally:
        connection.close()
    if quick_check != "ok" or foreign_keys:
        raise PolicyIncrementError(
            f"候选 SQLite 校验失败：quick_check={quick_check}, foreign_keys={len(foreign_keys)}"
        )
    if counts["documents"] != counts["documents_fts"]:
        raise PolicyIncrementError("documents 与 unicode61 FTS 行数不一致")
    if counts["documents"] != counts["documents_fts_trigram"]:
        raise PolicyIncrementError("documents 与 trigram FTS 行数不一致")
    if counts["chunks"] != counts["document_chunks_fts"]:
        raise PolicyIncrementError("document_chunks 与 chunk FTS 行数不一致")
    return {"quick_check": quick_check, "foreign_key_errors": 0, **counts}


def apply_payload(database_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    generated_at = str(payload["generated_at"])
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    inserted = updated = unchanged = 0
    affected_shas: set[str] = set()
    old_cluster_ids: set[int] = set()
    changed_document_ids: list[int] = []
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN IMMEDIATE")
        content_index.ensure_policy_cluster_schema(connection)
        scope_index.create_tables(connection)
        for document in payload["documents"]:
            old = connection.execute(
                "SELECT * FROM documents WHERE source_key=?", (document["source_key"],)
            ).fetchone()
            if old and all(old[column] == document[column] for column in DOCUMENT_COLUMNS):
                unchanged += 1
                continue
            if old:
                affected_shas.add(str(old["sha256"]))
                old_cluster_ids.update(delete_document_dependents(connection, old))
                connection.execute(
                    "UPDATE documents SET "
                    + ",".join(f"{column}=?" for column in DOCUMENT_COLUMNS[1:])
                    + " WHERE id=?",
                    tuple(document[column] for column in DOCUMENT_COLUMNS[1:]) + (int(old["id"]),),
                )
                document_id = int(old["id"])
                updated += 1
            else:
                cursor = connection.execute(
                    "INSERT INTO documents("
                    + ",".join(DOCUMENT_COLUMNS)
                    + ") VALUES ("
                    + ",".join("?" for _ in DOCUMENT_COLUMNS)
                    + ")",
                    tuple(document[column] for column in DOCUMENT_COLUMNS),
                )
                document_id = int(cursor.lastrowid)
                inserted += 1
            affected_shas.add(str(document["sha256"]))
            insert_document_dependents(connection, document_id, document, generated_at)
            changed_document_ids.append(document_id)
        for sha256 in sorted(affected_shas):
            rebuild_scope_group(connection, sha256, generated_at)
        for document_id in changed_document_ids:
            cluster_id = upsert_policy_cluster(connection, document_id, generated_at)
            if cluster_id is not None:
                old_cluster_ids.discard(cluster_id)
        for cluster_id in sorted(old_cluster_ids):
            refresh_cluster(connection, cluster_id, generated_at)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    validation = validate_database(database_path)
    return {
        "inserted_documents": inserted,
        "updated_documents": updated,
        "unchanged_documents": unchanged,
        "affected_sha_groups": len(affected_shas),
        "validation": validation,
    }


def generate_key(private_path: Path, public_path: Path) -> dict[str, str]:
    if private_path.exists() or public_path.exists():
        raise PolicyIncrementError("签名密钥输出已存在，拒绝覆盖")
    private_path.parent.mkdir(parents=True, exist_ok=True)
    public_path.parent.mkdir(parents=True, exist_ok=True)
    private_key = Ed25519PrivateKey.generate()
    private_path.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    os.chmod(private_path, 0o600)
    public_bytes = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    public_path.write_bytes(public_bytes)
    key_id = sha256_bytes(
        private_key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )[:24]
    return {"algorithm": "Ed25519", "key_id": key_id}


def load_private_key(path: Path) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise PolicyIncrementError("增量链签名密钥必须是 Ed25519")
    return key


def load_public_key(path: Path) -> Ed25519PublicKey:
    key = serialization.load_pem_public_key(path.read_bytes())
    if not isinstance(key, Ed25519PublicKey):
        raise PolicyIncrementError("增量链验签公钥必须是 Ed25519")
    return key


def public_key_id(key: Ed25519PublicKey) -> str:
    return sha256_bytes(
        key.public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )[:24]


def sign_delta_manifest(
    package_dir: Path, private_key_path: Path, previous_chain_sha256: str | None
) -> dict[str, Any]:
    manifest_path = package_dir / "delta_manifest.json"
    private_key = load_private_key(private_key_path)
    public_key = private_key.public_key()
    manifest_bytes = manifest_path.read_bytes()
    signature = private_key.sign(manifest_bytes)
    previous = previous_chain_sha256 or "0" * 64
    if not HEX_SHA256.fullmatch(previous):
        raise PolicyIncrementError("previous chain SHA-256 非法")
    manifest_sha = sha256_bytes(manifest_bytes)
    chain_sha = sha256_bytes(previous.encode("ascii") + manifest_sha.encode("ascii") + signature)
    signature_payload = {
        "algorithm": "Ed25519",
        "key_id": public_key_id(public_key),
        "manifest_sha256": manifest_sha,
        "previous_chain_sha256": previous_chain_sha256 or "",
        "chain_sha256": chain_sha,
        "signature_base64": base64.b64encode(signature).decode("ascii"),
    }
    write_json(package_dir / "delta_signature.json", signature_payload)
    (package_dir / "delta_signing_public.pem").write_bytes(
        public_key.public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    return signature_payload


def build_base_anchor(
    base_db: Path,
    base_manifest: Path,
    output_dir: Path,
    private_key_path: Path,
) -> dict[str, Any]:
    target = ensure_new_directory(output_dir)
    private_key = load_private_key(private_key_path)
    public_key = private_key.public_key()
    descriptor = {
        "format": BASE_FORMAT,
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "base_index_sha256": sha256_file(base_db),
        "base_index_bytes": base_db.stat().st_size,
        "base_index_page_size": sqlite_page_size(base_db),
        "base_manifest_sha256": sha256_file(base_manifest),
        "base_manifest_bytes": base_manifest.stat().st_size,
        "key_id": public_key_id(public_key),
    }
    descriptor_path = target / "base_descriptor.json"
    write_json(descriptor_path, descriptor)
    descriptor_bytes = descriptor_path.read_bytes()
    signature = private_key.sign(descriptor_bytes)
    descriptor_sha = sha256_bytes(descriptor_bytes)
    chain_sha = sha256_bytes(
        ("0" * 64).encode("ascii") + descriptor_sha.encode("ascii") + signature
    )
    signature_payload = {
        "algorithm": "Ed25519",
        "key_id": public_key_id(public_key),
        "descriptor_sha256": descriptor_sha,
        "previous_chain_sha256": "",
        "chain_sha256": chain_sha,
        "signature_base64": base64.b64encode(signature).decode("ascii"),
    }
    write_json(target / "base_signature.json", signature_payload)
    (target / "base_signing_public.pem").write_bytes(
        public_key.public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    return {"output_dir": str(target), "descriptor": descriptor, "signature": signature_payload}


def verify_base_anchor(
    anchor_dir: Path,
    base_db: Path,
    base_manifest: Path,
    trusted_public_key: Path,
) -> dict[str, Any]:
    descriptor_path = anchor_dir / "base_descriptor.json"
    signature_path = anchor_dir / "base_signature.json"
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    signature = json.loads(signature_path.read_text(encoding="utf-8"))
    if descriptor.get("format") != BASE_FORMAT or descriptor.get("schema_version") != SCHEMA_VERSION:
        raise PolicyIncrementError("不支持的完整基线锚点格式")
    descriptor_bytes = descriptor_path.read_bytes()
    descriptor_sha = sha256_bytes(descriptor_bytes)
    if descriptor_sha != signature.get("descriptor_sha256"):
        raise PolicyIncrementError("完整基线描述摘要不一致")
    public_key = load_public_key(trusted_public_key)
    if public_key_id(public_key) != signature.get("key_id"):
        raise PolicyIncrementError("完整基线可信公钥 key_id 不一致")
    raw_signature = base64.b64decode(signature["signature_base64"], validate=True)
    public_key.verify(raw_signature, descriptor_bytes)
    chain_sha = sha256_bytes(
        ("0" * 64).encode("ascii") + descriptor_sha.encode("ascii") + raw_signature
    )
    if chain_sha != signature.get("chain_sha256"):
        raise PolicyIncrementError("完整基线链摘要不一致")
    if sha256_file(base_db) != descriptor.get("base_index_sha256"):
        raise PolicyIncrementError("完整基线 SQLite 已变化")
    if sha256_file(base_manifest) != descriptor.get("base_manifest_sha256"):
        raise PolicyIncrementError("完整基线 manifest 已变化")
    return {"descriptor": descriptor, "signature": signature}


def verify_package(
    package_dir: Path,
    trusted_public_key: Path,
    expected_previous_chain_sha256: str | None = None,
) -> dict[str, Any]:
    manifest_path = package_dir / "delta_manifest.json"
    signature_path = package_dir / "delta_signature.json"
    payload_path = package_dir / "delta_payload.json"
    for required in (manifest_path, signature_path, payload_path):
        if not required.is_file():
            raise PolicyIncrementError(f"增量包缺少文件：{required}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    signature = json.loads(signature_path.read_text(encoding="utf-8"))
    if manifest.get("format") != DELTA_FORMAT or manifest.get("schema_version") != SCHEMA_VERSION:
        raise PolicyIncrementError("不支持的增量包格式")
    if sha256_file(payload_path) != manifest.get("payload_sha256"):
        raise PolicyIncrementError("delta_payload.json SHA-256 不一致")
    manifest_bytes = manifest_path.read_bytes()
    if sha256_bytes(manifest_bytes) != signature.get("manifest_sha256"):
        raise PolicyIncrementError("delta_manifest.json SHA-256 不一致")
    public_key = load_public_key(trusted_public_key)
    if public_key_id(public_key) != signature.get("key_id"):
        raise PolicyIncrementError("可信公钥与增量包 key_id 不一致")
    raw_signature = base64.b64decode(signature["signature_base64"], validate=True)
    public_key.verify(raw_signature, manifest_bytes)
    previous = str(signature.get("previous_chain_sha256") or "0" * 64)
    manifest_previous = str(manifest.get("previous_chain_sha256") or "")
    if manifest_previous != str(signature.get("previous_chain_sha256") or ""):
        raise PolicyIncrementError("增量 manifest 与签名记录的前序链摘要不一致")
    if (
        expected_previous_chain_sha256 is not None
        and manifest_previous != expected_previous_chain_sha256
    ):
        raise PolicyIncrementError("增量包未连接到指定的前序链摘要")
    expected_chain = sha256_bytes(
        previous.encode("ascii")
        + str(signature["manifest_sha256"]).encode("ascii")
        + raw_signature
    )
    if expected_chain != signature.get("chain_sha256"):
        raise PolicyIncrementError("增量链摘要不一致")
    for name, digest in manifest.get("handoff_files", {}).items():
        source = package_dir / name
        if not source.is_file() or sha256_file(source) != digest:
            raise PolicyIncrementError(f"增量包内冻结交接文件不一致：{name}")
    return {"manifest": manifest, "signature": signature}


def apply_package(
    package_dir: Path,
    base_db: Path,
    base_manifest: Path,
    output_dir: Path,
    trusted_public_key: Path,
    expected_previous_chain_sha256: str,
) -> dict[str, Any]:
    verified = verify_package(
        package_dir, trusted_public_key, expected_previous_chain_sha256
    )
    manifest = verified["manifest"]
    if sha256_file(base_db) != manifest["base_index_sha256"]:
        raise PolicyIncrementError("恢复基线 SQLite SHA-256 与增量包不一致")
    if sha256_file(base_manifest) != manifest["base_manifest_sha256"]:
        raise PolicyIncrementError("恢复基线 manifest SHA-256 与增量包不一致")
    target = ensure_new_directory(output_dir)
    target_db = target / "knowledge_content.sqlite3"
    target_manifest = target / "manifest.jsonl"
    clone_file(base_db, target_db)
    payload = json.loads((package_dir / "delta_payload.json").read_text(encoding="utf-8"))
    apply_result = apply_payload(target_db, payload)
    merged = merge_manifest_rows(read_jsonl(base_manifest), payload["manifest_rows"])
    write_jsonl(target_manifest, merged)
    if sha256_file(target_db) != manifest["candidate_index_sha256"]:
        raise PolicyIncrementError("灾难恢复重放后的 SQLite SHA-256 不一致")
    if sha256_file(target_manifest) != manifest["candidate_manifest_sha256"]:
        raise PolicyIncrementError("灾难恢复重放后的 manifest SHA-256 不一致")
    return {
        "output_dir": str(target),
        "index_sha256": manifest["candidate_index_sha256"],
        "manifest_sha256": manifest["candidate_manifest_sha256"],
        "chain_sha256": verified["signature"]["chain_sha256"],
        "apply": apply_result,
    }


def build_package(args: argparse.Namespace) -> dict[str, Any]:
    knowledge_root = args.knowledge_root.expanduser().resolve()
    base_db = args.base_db.expanduser().resolve()
    base_manifest = args.base_manifest.expanduser().resolve()
    handoff_dir = args.handoff_dir.expanduser().resolve()
    verified = verify_frozen_handoff(handoff_dir, knowledge_root)
    base_manifest_rows = read_jsonl(base_manifest)
    manifest_delta = build_manifest_delta(verified["handoff"], knowledge_root, base_manifest_rows)
    documents = build_document_payloads(manifest_delta)
    payload = {
        "format": DELTA_FORMAT,
        "schema_version": SCHEMA_VERSION,
        "generated_at": str(verified["handoff"]["generated_at"]),
        "handoff_id": str(verified["handoff"]["handoff_id"]),
        "manifest_rows": manifest_delta,
        "documents": documents,
    }
    candidate_dir = ensure_new_directory(args.candidate_dir)
    package_dir = ensure_new_directory(args.package_dir)
    candidate_db = candidate_dir / "knowledge_content.sqlite3"
    candidate_manifest = candidate_dir / "manifest.jsonl"
    clone_file(base_db, candidate_db)
    write_json(package_dir / "delta_payload.json", payload)
    apply_result = apply_payload(candidate_db, payload)
    merged_manifest = merge_manifest_rows(base_manifest_rows, manifest_delta)
    write_jsonl(candidate_manifest, merged_manifest)
    verification = manifest_verification(verified["expected"], merged_manifest)
    if not verification["all_exact"]:
        raise PolicyIncrementError(f"候选 manifest 未全部 exact：{verification['counts']}")
    write_json(package_dir / "manifest_verification.json", verification)
    handoff_files = {}
    for name in ("increment_handoff.json", "manifest_expected_hits.csv", "handoff_digest.json"):
        source = handoff_dir / name
        target = package_dir / name
        shutil.copy2(source, target)
        handoff_files[name] = sha256_file(target)
    delta_manifest = {
        "format": DELTA_FORMAT,
        "schema_version": SCHEMA_VERSION,
        "handoff_id": str(verified["handoff"]["handoff_id"]),
        "generated_at": str(verified["handoff"]["generated_at"]),
        "base_index_sha256": sha256_file(base_db),
        "candidate_index_sha256": sha256_file(candidate_db),
        "base_manifest_sha256": sha256_file(base_manifest),
        "candidate_manifest_sha256": sha256_file(candidate_manifest),
        "payload_sha256": sha256_file(package_dir / "delta_payload.json"),
        "manifest_verification_sha256": sha256_file(package_dir / "manifest_verification.json"),
        "handoff_files": handoff_files,
        "previous_chain_sha256": args.previous_chain_sha256 or "",
        "counts": {
            "handoff_records": len(verified["handoff"]["records"]),
            "handoff_files": len(verified["expected"]),
            "handoff_bytes": verified["archive_bytes"],
            "manifest_delta_rows": len(manifest_delta),
            "indexed_documents": len(documents),
            **{key: apply_result[key] for key in (
                "inserted_documents", "updated_documents", "unchanged_documents", "affected_sha_groups"
            )},
        },
        "validation": apply_result["validation"],
    }
    write_json(package_dir / "delta_manifest.json", delta_manifest)
    signature = sign_delta_manifest(package_dir, args.signing_private_key, args.previous_chain_sha256)
    return {
        "candidate_dir": str(candidate_dir),
        "package_dir": str(package_dir),
        "candidate_index_sha256": delta_manifest["candidate_index_sha256"],
        "candidate_manifest_sha256": delta_manifest["candidate_manifest_sha256"],
        "chain_sha256": signature["chain_sha256"],
        "counts": delta_manifest["counts"],
        "validation": delta_manifest["validation"],
    }


def sqlite_page_size(path: Path) -> int:
    with path.open("rb") as stream:
        header = stream.read(100)
    if len(header) < 100 or header[:16] != b"SQLite format 3\x00":
        raise PolicyIncrementError(f"不是 SQLite 3 数据库：{path}")
    encoded = int.from_bytes(header[16:18], "big")
    return 65536 if encoded == 1 else encoded


def measure_sqlite_pages(base_db: Path, candidate_db: Path) -> dict[str, Any]:
    page_size = sqlite_page_size(base_db)
    if sqlite_page_size(candidate_db) != page_size:
        raise PolicyIncrementError("基线与候选 SQLite 页大小不一致")
    base_size = base_db.stat().st_size
    candidate_size = candidate_db.stat().st_size
    overlap = min(base_size, candidate_size)
    overlap_pages = (overlap + page_size - 1) // page_size
    changed = 0
    with base_db.open("rb") as base_stream, candidate_db.open("rb") as candidate_stream:
        base_map = mmap.mmap(base_stream.fileno(), 0, access=mmap.ACCESS_READ)
        candidate_map = mmap.mmap(candidate_stream.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            for page in range(overlap_pages):
                start = page * page_size
                end = min(start + page_size, overlap)
                if base_map[start:end] != candidate_map[start:end]:
                    changed += 1
        finally:
            base_map.close()
            candidate_map.close()
    base_pages = (base_size + page_size - 1) // page_size
    candidate_pages = (candidate_size + page_size - 1) // page_size
    appended = max(candidate_pages - base_pages, 0)
    removed = max(base_pages - candidate_pages, 0)
    total_changed = changed + appended + removed
    return {
        "page_size": page_size,
        "base_bytes": base_size,
        "candidate_bytes": candidate_size,
        "base_pages": base_pages,
        "candidate_pages": candidate_pages,
        "changed_existing_pages": changed,
        "appended_pages": appended,
        "removed_pages": removed,
        "total_changed_pages": total_changed,
        "changed_page_bytes": total_changed * page_size,
        "changed_page_ratio": total_changed / max(base_pages, 1),
    }


def parse_rsync_bytes(output: str, label: str) -> int | None:
    match = re.search(
        rf"^{re.escape(label)}:\s*([0-9,]+)\s+(?:bytes|B)$",
        output,
        re.MULTILINE,
    )
    return None if not match else int(match.group(1).replace(",", ""))


def parse_first_rsync_bytes(output: str, labels: tuple[str, ...]) -> int | None:
    for label in labels:
        value = parse_rsync_bytes(output, label)
        if value is not None:
            return value
    return None


def measure_rsync(
    base_db: Path, candidate_db: Path, receiver_dir: Path, block_size: int
) -> dict[str, Any]:
    receiver = ensure_new_directory(receiver_dir)
    receiver_db = receiver / candidate_db.name
    clone_file(base_db, receiver_db)
    command = [
        "rsync",
        "--archive",
        "--no-whole-file",
        "--inplace",
        "--checksum",
        f"--block-size={block_size}",
        "--stats",
        str(candidate_db),
        str(receiver_db),
    ]
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise PolicyIncrementError(f"本地 rsync 差异演练失败：{result.stderr.strip()}")
    receiver_sha = sha256_file(receiver_db)
    candidate_sha = sha256_file(candidate_db)
    if receiver_sha != candidate_sha:
        raise PolicyIncrementError("本地 rsync 差异接收文件 SHA-256 不一致")
    literal = parse_first_rsync_bytes(result.stdout, ("Literal data", "Unmatched data"))
    matched = parse_rsync_bytes(result.stdout, "Matched data")
    sent = parse_first_rsync_bytes(result.stdout, ("Total bytes sent", "Total sent"))
    received = parse_first_rsync_bytes(
        result.stdout, ("Total bytes received", "Total received")
    )
    return {
        "receiver_dir": str(receiver),
        "command": command,
        "literal_bytes": literal,
        "matched_bytes": matched,
        "total_bytes_sent": sent,
        "total_bytes_received": received,
        "wire_bytes_total": None if sent is None or received is None else sent + received,
        "receiver_sha256": receiver_sha,
        "stdout": result.stdout,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    key = subparsers.add_parser("generate-key", help="生成独立 Ed25519 增量链密钥")
    key.add_argument("--private-key", type=Path, required=True)
    key.add_argument("--public-key", type=Path, required=True)

    base = subparsers.add_parser("sign-base", help="为完整 SQLite 与 manifest 基线建立签名锚点")
    base.add_argument("--base-db", type=Path, default=DEFAULT_BASE_DB)
    base.add_argument("--base-manifest", type=Path, default=DEFAULT_BASE_MANIFEST)
    base.add_argument("--output-dir", type=Path, required=True)
    base.add_argument("--signing-private-key", type=Path, required=True)

    base_verify = subparsers.add_parser("verify-base", help="验签并核对完整基线锚点")
    base_verify.add_argument("--anchor-dir", type=Path, required=True)
    base_verify.add_argument("--base-db", type=Path, default=DEFAULT_BASE_DB)
    base_verify.add_argument("--base-manifest", type=Path, default=DEFAULT_BASE_MANIFEST)
    base_verify.add_argument("--trusted-public-key", type=Path, required=True)

    build = subparsers.add_parser("build", help="从冻结交接包构建候选库和签名增量包")
    build.add_argument("--handoff-dir", type=Path, required=True)
    build.add_argument("--knowledge-root", type=Path, default=DEFAULT_KNOWLEDGE_ROOT)
    build.add_argument("--base-db", type=Path, default=DEFAULT_BASE_DB)
    build.add_argument("--base-manifest", type=Path, default=DEFAULT_BASE_MANIFEST)
    build.add_argument("--candidate-dir", type=Path, required=True)
    build.add_argument("--package-dir", type=Path, required=True)
    build.add_argument("--signing-private-key", type=Path, required=True)
    build.add_argument("--previous-chain-sha256")

    apply = subparsers.add_parser("apply", help="验签后从完整基线重放增量包")
    apply.add_argument("--package-dir", type=Path, required=True)
    apply.add_argument("--base-db", type=Path, default=DEFAULT_BASE_DB)
    apply.add_argument("--base-manifest", type=Path, default=DEFAULT_BASE_MANIFEST)
    apply.add_argument("--output-dir", type=Path, required=True)
    apply.add_argument("--trusted-public-key", type=Path, required=True)
    apply.add_argument("--expected-previous-chain-sha256", required=True)

    verify = subparsers.add_parser("verify", help="只校验增量包签名和冻结摘要")
    verify.add_argument("--package-dir", type=Path, required=True)
    verify.add_argument("--trusted-public-key", type=Path, required=True)
    verify.add_argument("--expected-previous-chain-sha256", required=True)

    measure = subparsers.add_parser("measure", help="实测 SQLite 变化页及本地 rsync 字节")
    measure.add_argument("--base-db", type=Path, default=DEFAULT_BASE_DB)
    measure.add_argument("--candidate-db", type=Path, required=True)
    measure.add_argument("--receiver-dir", type=Path, required=True)
    measure.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "generate-key":
        result = generate_key(args.private_key.expanduser().resolve(), args.public_key.expanduser().resolve())
    elif args.command == "sign-base":
        result = build_base_anchor(
            args.base_db.expanduser().resolve(),
            args.base_manifest.expanduser().resolve(),
            args.output_dir,
            args.signing_private_key.expanduser().resolve(),
        )
    elif args.command == "verify-base":
        verified = verify_base_anchor(
            args.anchor_dir.expanduser().resolve(),
            args.base_db.expanduser().resolve(),
            args.base_manifest.expanduser().resolve(),
            args.trusted_public_key.expanduser().resolve(),
        )
        result = {
            "status": "verified",
            "chain_sha256": verified["signature"]["chain_sha256"],
            "base_index_sha256": verified["descriptor"]["base_index_sha256"],
        }
    elif args.command == "build":
        args.signing_private_key = args.signing_private_key.expanduser().resolve()
        result = build_package(args)
    elif args.command == "apply":
        result = apply_package(
            args.package_dir.expanduser().resolve(),
            args.base_db.expanduser().resolve(),
            args.base_manifest.expanduser().resolve(),
            args.output_dir,
            args.trusted_public_key.expanduser().resolve(),
            args.expected_previous_chain_sha256,
        )
    elif args.command == "verify":
        verified = verify_package(
            args.package_dir.expanduser().resolve(),
            args.trusted_public_key.expanduser().resolve(),
            args.expected_previous_chain_sha256,
        )
        result = {
            "status": "verified",
            "chain_sha256": verified["signature"]["chain_sha256"],
            "candidate_index_sha256": verified["manifest"]["candidate_index_sha256"],
        }
    else:
        pages = measure_sqlite_pages(
            args.base_db.expanduser().resolve(), args.candidate_db.expanduser().resolve()
        )
        rsync = measure_rsync(
            args.base_db.expanduser().resolve(),
            args.candidate_db.expanduser().resolve(),
            args.receiver_dir,
            int(pages["page_size"]),
        )
        result = {"measured_at": utc_now(), "pages": pages, "rsync": rsync}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
