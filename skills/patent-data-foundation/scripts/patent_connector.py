#!/usr/bin/env python3
import argparse
import csv
import hashlib
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path


FIELDS = (
    "publication_number", "application_number", "jurisdiction", "document_kind", "title",
    "abstract", "claims", "description", "filing_date", "grant_date", "priority_dates",
    "applicants_original", "owners_current", "inventors", "ipc", "cpc", "legal_status",
    "status_sources", "simple_family_id", "extended_family_id", "source_url", "retrieved_at",
)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def normalize_number(value):
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def as_list(value):
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return [item.strip() for item in re.split(r"[\n,，;；|]", str(value)) if item.strip()]


def normalize_record(raw, provider):
    record = {field: raw.get(field, "") for field in FIELDS}
    record["publication_number"] = normalize_number(record["publication_number"])
    record["application_number"] = normalize_number(record["application_number"])
    if not record["publication_number"] and not record["application_number"]:
        raise ValueError("缺少公开号和申请号")
    if not record["title"]:
        raise ValueError("缺少专利名称")
    for field in ("priority_dates", "applicants_original", "owners_current", "inventors", "ipc", "cpc", "status_sources"):
        record[field] = as_list(record[field])
    record["jurisdiction"] = str(record["jurisdiction"] or record["publication_number"][:2]).upper()
    kind_match = re.search(r"([A-Z]\d?)$", record["publication_number"])
    record["document_kind"] = str(record["document_kind"] or (kind_match.group(1) if kind_match else "")).upper()
    record["legal_status"] = str(record["legal_status"] or "无法确认")
    record["retrieved_at"] = str(record["retrieved_at"] or now_iso())
    record["provider"] = provider
    return record


def connect(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS patents (
            id INTEGER PRIMARY KEY,
            identity_key TEXT NOT NULL UNIQUE,
            publication_number TEXT NOT NULL DEFAULT '',
            application_number TEXT NOT NULL DEFAULT '',
            jurisdiction TEXT NOT NULL DEFAULT '',
            document_kind TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL,
            abstract TEXT NOT NULL DEFAULT '',
            claims TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            filing_date TEXT NOT NULL DEFAULT '',
            grant_date TEXT NOT NULL DEFAULT '',
            priority_dates_json TEXT NOT NULL DEFAULT '[]',
            applicants_original_json TEXT NOT NULL DEFAULT '[]',
            owners_current_json TEXT NOT NULL DEFAULT '[]',
            inventors_json TEXT NOT NULL DEFAULT '[]',
            ipc_json TEXT NOT NULL DEFAULT '[]',
            cpc_json TEXT NOT NULL DEFAULT '[]',
            legal_status TEXT NOT NULL DEFAULT '无法确认',
            status_sources_json TEXT NOT NULL DEFAULT '[]',
            simple_family_id TEXT NOT NULL DEFAULT '',
            extended_family_id TEXT NOT NULL DEFAULT '',
            source_url TEXT NOT NULL DEFAULT '',
            provider TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            current_version INTEGER NOT NULL DEFAULT 1,
            retrieved_at TEXT NOT NULL,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_patents_application ON patents(application_number);
        CREATE INDEX IF NOT EXISTS idx_patents_title ON patents(title);
        CREATE INDEX IF NOT EXISTS idx_patents_status ON patents(legal_status);
        CREATE TABLE IF NOT EXISTS patent_versions (
            id INTEGER PRIMARY KEY,
            patent_id INTEGER NOT NULL REFERENCES patents(id) ON DELETE CASCADE,
            version INTEGER NOT NULL,
            content_hash TEXT NOT NULL,
            canonical_json TEXT NOT NULL,
            collected_at TEXT NOT NULL,
            UNIQUE(patent_id, version)
        );
        CREATE TABLE IF NOT EXISTS patent_import_runs (
            run_id TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            input_path TEXT NOT NULL,
            status TEXT NOT NULL,
            inserted_count INTEGER NOT NULL DEFAULT 0,
            updated_count INTEGER NOT NULL DEFAULT 0,
            unchanged_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            started_at TEXT NOT NULL,
            finished_at TEXT NOT NULL DEFAULT ''
        );
        """
    )
    connection.commit()
    return connection


def load_records(path):
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    if suffix == ".json":
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(value, list):
            return value
        for key in ("records", "items", "data", "results"):
            if isinstance(value.get(key), list):
                return value[key]
        return [value]
    if suffix == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    raise ValueError("仅支持JSON、JSONL和CSV；国家知识产权局批量包请先按开放目录解压并映射为标准字段")


def identity_key(record):
    value = record["publication_number"] or record["application_number"]
    return f'{record["jurisdiction"]}:{value}:{record["document_kind"]}'


def upsert(connection, record):
    key = identity_key(record)
    canonical = json.dumps(record, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    existing = connection.execute("SELECT * FROM patents WHERE identity_key=?", (key,)).fetchone()
    list_fields = ("priority_dates", "applicants_original", "owners_current", "inventors", "ipc", "cpc", "status_sources")
    values = [json.dumps(record[field], ensure_ascii=False) for field in list_fields]
    if existing is None:
        cursor = connection.execute(
            """INSERT INTO patents(identity_key, publication_number, application_number, jurisdiction,
            document_kind, title, abstract, claims, description, filing_date, grant_date,
            priority_dates_json, applicants_original_json, owners_current_json, inventors_json,
            ipc_json, cpc_json, legal_status, status_sources_json, simple_family_id,
            extended_family_id, source_url, provider, content_hash, retrieved_at, first_seen_at, last_seen_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (key, record["publication_number"], record["application_number"], record["jurisdiction"],
             record["document_kind"], record["title"], record["abstract"], record["claims"], record["description"],
             record["filing_date"], record["grant_date"], *values[:6], record["legal_status"], values[6],
             record["simple_family_id"], record["extended_family_id"], record["source_url"], record["provider"],
             digest, record["retrieved_at"], now_iso(), now_iso()),
        )
        connection.execute(
            "INSERT INTO patent_versions(patent_id, version, content_hash, canonical_json, collected_at) VALUES (?,1,?,?,?)",
            (cursor.lastrowid, digest, canonical, now_iso()),
        )
        return "inserted"
    if existing["content_hash"] == digest:
        connection.execute("UPDATE patents SET last_seen_at=? WHERE id=?", (now_iso(), existing["id"]))
        return "unchanged"
    version = existing["current_version"] + 1
    connection.execute(
        """UPDATE patents SET title=?, abstract=?, claims=?, description=?, filing_date=?, grant_date=?,
        priority_dates_json=?, applicants_original_json=?, owners_current_json=?, inventors_json=?, ipc_json=?, cpc_json=?,
        legal_status=?, status_sources_json=?, simple_family_id=?, extended_family_id=?, source_url=?, provider=?,
        content_hash=?, current_version=?, retrieved_at=?, last_seen_at=? WHERE id=?""",
        (record["title"], record["abstract"], record["claims"], record["description"], record["filing_date"],
         record["grant_date"], *values[:6], record["legal_status"], values[6], record["simple_family_id"],
         record["extended_family_id"], record["source_url"], record["provider"], digest, version,
         record["retrieved_at"], now_iso(), existing["id"]),
    )
    connection.execute(
        "INSERT INTO patent_versions(patent_id, version, content_hash, canonical_json, collected_at) VALUES (?,?,?,?,?)",
        (existing["id"], version, digest, canonical, now_iso()),
    )
    return "updated"


def ingest(connection, path, provider):
    run_id = str(uuid.uuid4())
    started = now_iso()
    counts = {"inserted": 0, "updated": 0, "unchanged": 0, "failed": 0}
    connection.execute(
        "INSERT INTO patent_import_runs(run_id, provider, input_path, status, started_at) VALUES (?,?,?,'running',?)",
        (run_id, provider, str(path), started),
    )
    for raw in load_records(path):
        try:
            counts[upsert(connection, normalize_record(raw, provider))] += 1
        except (TypeError, ValueError, sqlite3.Error):
            counts["failed"] += 1
    status = "success" if counts["failed"] == 0 else "partial"
    connection.execute(
        """UPDATE patent_import_runs SET status=?, inserted_count=?, updated_count=?, unchanged_count=?,
        failed_count=?, finished_at=? WHERE run_id=?""",
        (status, counts["inserted"], counts["updated"], counts["unchanged"], counts["failed"], now_iso(), run_id),
    )
    connection.commit()
    return {"run_id": run_id, "status": status, **counts}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path.home() / ".project-application-assistant" / "patents" / "patent-index.sqlite3")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init")
    import_parser = subparsers.add_parser("import")
    import_parser.add_argument("--input", type=Path, required=True)
    import_parser.add_argument("--provider", choices=("cnipa-bulk", "user-export", "third-party"), default="user-export")
    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("--keyword", required=True)
    search_parser.add_argument("--limit", type=int, default=20)
    subparsers.add_parser("status")
    arguments = parser.parse_args()
    connection = connect(arguments.db)
    if arguments.command == "init":
        result = {"status": "initialized", "db": str(arguments.db)}
    elif arguments.command == "import":
        result = ingest(connection, arguments.input, arguments.provider)
    elif arguments.command == "search":
        rows = connection.execute(
            "SELECT * FROM patents WHERE title LIKE ? OR abstract LIKE ? OR claims LIKE ? ORDER BY filing_date DESC LIMIT ?",
            (f"%{arguments.keyword}%", f"%{arguments.keyword}%", f"%{arguments.keyword}%", arguments.limit),
        ).fetchall()
        result = {"status": "success", "records": [dict(row) for row in rows]}
    else:
        result = {
            "db": str(arguments.db),
            "records": connection.execute("SELECT COUNT(*) FROM patents").fetchone()[0],
            "versions": connection.execute("SELECT COUNT(*) FROM patent_versions").fetchone()[0],
            "last_run": dict(connection.execute("SELECT * FROM patent_import_runs ORDER BY started_at DESC LIMIT 1").fetchone() or {}),
            "providers": {
                "cnipa_bulk": "registered user export required",
            },
        }
    connection.close()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
