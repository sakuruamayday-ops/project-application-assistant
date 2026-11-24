#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import unicodedata
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse, urlunparse


FIELD_ALIASES = {
    "source_record_id": ["source_record_id", "recordId", "id", "源记录ID"],
    "year": ["year", "application_year", "年度"],
    "source_version": ["source_version", "version", "源版本"],
    "title": ["title", "name", "policyTitle", "projectName", "标题", "项目名称", "政策名称"],
    "region": ["region", "area", "district", "地区", "区域"],
    "record_type": ["record_type", "recordType", "type", "类型", "政策类型"],
    "topics": ["topics", "tags", "labels", "标签", "主题"],
    "publish_date": ["publish_date", "publishDate", "releaseDate", "发布日期"],
    "issuer": ["issuer", "department", "publishOrg", "发文机构", "发布部门"],
    "article_source": ["article_source", "articleSource", "sourceName", "文章来源", "source"],
    "application_status": ["application_status", "applicationStatus", "declareStatus", "申报状态", "status"],
    "application_period": ["application_period", "applicationPeriod", "declareTime", "申报时间"],
    "detail_url": ["detail_url", "detailUrl", "url", "详情链接"],
    "official_url": ["official_url", "officialUrl", "sourceUrl", "官方链接", "原文链接"],
    "verification_status": ["verification_status", "verificationStatus", "核验状态"],
    "eligibility_conditions": ["eligibility_conditions", "eligibilityConditions", "requirements", "申报条件", "申报要求"],
    "beneficiary_companies": ["beneficiary_companies", "beneficiaryCompanies", "approvedCompanies", "公示企业", "通过企业", "获批企业"],
    "beneficiary_count": ["beneficiary_count", "beneficiaryCount", "approvedCount", "累计奖补数", "企业数量"],
    "query": ["query", "searchQuery", "检索条件"],
    "page_number": ["page_number", "pageNumber", "页码"],
    "content": ["content", "body", "text", "正文", "内容"],
}

INGEST_COUNTS = ("inserted", "updated", "unchanged", "failed", "missing_official")
REPORT_NAMES = {"batch_history": "批次履历", "delivery_checklist": "交付检查表"}
CHECKLIST_ITEMS = ("字段完整性", "分页覆盖", "去重", "来源链接", "授权范围")
CHECKLIST_STATES = ("已取得", "部分取得", "未取得", "不适用")


class DeliveryReportError(ValueError):
    pass


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def default_root():
    configured = os.environ.get("PROJECT_APPLICATION_ASSISTANT_INDEX_ROOT")
    return Path(configured).expanduser() if configured else Path.home() / ".project-application-assistant" / "index"


def default_db():
    return default_root() / "policy-index.sqlite3"


def connect(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def initialize(connection):
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY,
            dedupe_key TEXT NOT NULL UNIQUE,
            source TEXT NOT NULL,
            source_record_id TEXT NOT NULL DEFAULT '',
            year TEXT NOT NULL DEFAULT '',
            source_version TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL,
            normalized_title TEXT NOT NULL,
            region TEXT NOT NULL DEFAULT '',
            record_type TEXT NOT NULL DEFAULT '',
            topics_json TEXT NOT NULL DEFAULT '[]',
            publish_date TEXT NOT NULL DEFAULT '',
            issuer TEXT NOT NULL DEFAULT '',
            article_source TEXT NOT NULL DEFAULT '',
            application_status TEXT NOT NULL DEFAULT '',
            application_period TEXT NOT NULL DEFAULT '',
            detail_url TEXT NOT NULL DEFAULT '',
            official_url TEXT NOT NULL DEFAULT '',
            verification_status TEXT NOT NULL DEFAULT '未核验',
            eligibility_conditions TEXT NOT NULL DEFAULT '',
            beneficiary_companies_json TEXT NOT NULL DEFAULT '[]',
            beneficiary_count INTEGER NOT NULL DEFAULT 0,
            query_text TEXT NOT NULL DEFAULT '',
            page_number INTEGER NOT NULL DEFAULT 0,
            authorization_scope TEXT NOT NULL DEFAULT '用户自有账号本地使用',
            content TEXT NOT NULL DEFAULT '',
            content_hash TEXT NOT NULL,
            current_version INTEGER NOT NULL DEFAULT 1,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        );
        CREATE INDEX IF NOT EXISTS idx_records_publish_date ON records(publish_date);
        CREATE INDEX IF NOT EXISTS idx_records_region ON records(region);
        CREATE INDEX IF NOT EXISTS idx_records_type ON records(record_type);
        CREATE INDEX IF NOT EXISTS idx_records_official_url ON records(official_url);

        CREATE TABLE IF NOT EXISTS record_versions (
            id INTEGER PRIMARY KEY,
            record_id INTEGER NOT NULL REFERENCES records(id) ON DELETE CASCADE,
            version INTEGER NOT NULL,
            content_hash TEXT NOT NULL,
            canonical_json TEXT NOT NULL,
            collected_at TEXT NOT NULL,
            UNIQUE(record_id, version)
        );

        CREATE TABLE IF NOT EXISTS collection_runs (
            run_id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            collection_date TEXT NOT NULL,
            scope_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            input_path TEXT,
            inserted_count INTEGER NOT NULL DEFAULT 0,
            updated_count INTEGER NOT NULL DEFAULT 0,
            unchanged_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            missing_official_count INTEGER NOT NULL DEFAULT 0,
            error_summary TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS collection_days (
            source TEXT NOT NULL,
            collection_date TEXT NOT NULL,
            status TEXT NOT NULL,
            last_run_id TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(source, collection_date)
        );

        CREATE TABLE IF NOT EXISTS collection_checkpoints (
            source TEXT NOT NULL,
            scope_key TEXT NOT NULL,
            last_success_date TEXT,
            last_page INTEGER NOT NULL DEFAULT 0,
            cursor TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            PRIMARY KEY(source, scope_key)
        );

        CREATE TABLE IF NOT EXISTS ingestion_errors (
            id INTEGER PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES collection_runs(run_id) ON DELETE CASCADE,
            item_number INTEGER NOT NULL,
            error TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS collection_metrics (
            id INTEGER PRIMARY KEY,
            source TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            pages_attempted INTEGER NOT NULL DEFAULT 0,
            pages_succeeded INTEGER NOT NULL DEFAULT 0,
            list_records INTEGER NOT NULL DEFAULT 0,
            detail_requests INTEGER NOT NULL DEFAULT 0,
            throttled_count INTEGER NOT NULL DEFAULT 0,
            captcha_count INTEGER NOT NULL DEFAULT 0,
            login_required_count INTEGER NOT NULL DEFAULT 0,
            min_interval_seconds REAL NOT NULL DEFAULT 0,
            max_interval_seconds REAL NOT NULL DEFAULT 0,
            notes TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS official_link_checks (
            id INTEGER PRIMARY KEY,
            record_id INTEGER NOT NULL REFERENCES records(id) ON DELETE CASCADE,
            checked_at TEXT NOT NULL,
            http_status INTEGER,
            final_url TEXT NOT NULL DEFAULT '',
            valid INTEGER NOT NULL DEFAULT 0,
            error TEXT NOT NULL DEFAULT ''
        );
        """
    )
    existing_columns = {row[1] for row in connection.execute("PRAGMA table_info(records)")}
    migrations = {
        "source_record_id": "TEXT NOT NULL DEFAULT ''",
        "year": "TEXT NOT NULL DEFAULT ''",
        "source_version": "TEXT NOT NULL DEFAULT ''",
        "eligibility_conditions": "TEXT NOT NULL DEFAULT ''",
        "beneficiary_companies_json": "TEXT NOT NULL DEFAULT '[]'",
        "beneficiary_count": "INTEGER NOT NULL DEFAULT 0",
        "query_text": "TEXT NOT NULL DEFAULT ''",
        "page_number": "INTEGER NOT NULL DEFAULT 0",
    }
    for column, definition in migrations.items():
        if column not in existing_columns:
            connection.execute(f"ALTER TABLE records ADD COLUMN {column} {definition}")
    connection.commit()


def normalize_text(value):
    value = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    return re.sub(r"[\s、，,.。：:;；\-_—“”\"'（）()【】\[\]]+", "", value)


def normalize_url(value):
    value = str(value or "").strip()
    if not value:
        return ""
    parsed = urlparse(value)
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), "", parsed.query, ""))


def first_value(record, aliases):
    for alias in aliases:
        if alias in record and record[alias] not in (None, ""):
            return record[alias]
    return ""


def canonicalize(raw, source, authorization_scope):
    record = {field: first_value(raw, aliases) for field, aliases in FIELD_ALIASES.items()}
    record["title"] = str(record["title"]).strip()
    if not record["title"]:
        raise ValueError("缺少标题")
    topics = record["topics"]
    if isinstance(topics, str):
        topics = [item.strip() for item in re.split(r"[,，;；|/]", topics) if item.strip()]
    elif not isinstance(topics, list):
        topics = []
    record["topics"] = topics
    companies = record["beneficiary_companies"]
    if isinstance(companies, str):
        companies = [item.strip() for item in re.split(r"[\n;；|]", companies) if item.strip()]
    elif not isinstance(companies, list):
        companies = []
    record["beneficiary_companies"] = list(dict.fromkeys(str(item).strip() for item in companies if str(item).strip()))
    for field in FIELD_ALIASES:
        if field not in {"topics", "beneficiary_companies"}:
            record[field] = str(record[field]).strip()
    try:
        record["beneficiary_count"] = int(float(record["beneficiary_count"] or len(record["beneficiary_companies"])))
    except ValueError:
        record["beneficiary_count"] = len(record["beneficiary_companies"])
    try:
        record["page_number"] = int(float(record["page_number"] or 0))
    except ValueError:
        record["page_number"] = 0
    record["source"] = source
    record["authorization_scope"] = authorization_scope
    record["normalized_title"] = normalize_text(record["title"])
    record["detail_url"] = normalize_url(record["detail_url"])
    record["official_url"] = normalize_url(record["official_url"])
    record["verification_status"] = record["verification_status"] or "未核验"
    # 明确失效与申报截止不同；截止通知仍可作为有效历史政策检索。
    active = raw.get("active", record["application_status"])
    record["active"] = 0 if str(active).strip().lower() in {"inactive", "false", "0", "失效", "已失效", "废止", "已废止"} else 1
    return record


def dedupe_key(record):
    # 源记录 ID 不能冒充 SQLite 主键，也不能靠可变标题或年度识别同一记录。
    if record["source_record_id"]:
        return f'{record["source"]}:id:{record["source_record_id"]}'
    detail = urlparse(record["detail_url"])
    query = parse_qs(detail.query)
    identifiers = [query.get("id", [""])[0], query.get("indexId", [""])[0]]
    if any(identifiers):
        return f'{record["source"]}:detail:' + ":".join(identifiers)
    if record["official_url"]:
        return f'{record["source"]}:official:{record["official_url"]}'
    identity = "|".join((record["normalized_title"], normalize_text(record["issuer"]), record["publish_date"]))
    return f'{record["source"]}:fallback:' + hashlib.sha256(identity.encode("utf-8")).hexdigest()


def record_hash(record):
    payload = {key: value for key, value in record.items() if key not in {"authorization_scope"}}
    # 老索引重新导入未变化的数据时，不因新增的空字段产生伪版本。
    for field in ("source_record_id", "year", "source_version"):
        if not payload.get(field):
            payload.pop(field, None)
    if payload.get("active") == 1:
        payload.pop("active", None)
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def load_input(path):
    text = path.read_text(encoding="utf-8-sig").strip()
    if not text:
        return []
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    value = json.loads(text)
    if isinstance(value, list):
        return value
    for key in ("records", "items", "list", "data", "rows"):
        candidate = value.get(key) if isinstance(value, dict) else None
        if isinstance(candidate, list):
            return candidate
        if isinstance(candidate, dict):
            for nested in ("records", "items", "list", "rows"):
                if isinstance(candidate.get(nested), list):
                    return candidate[nested]
    if isinstance(value, dict) and first_value(value, FIELD_ALIASES["title"]):
        return [value]
    raise ValueError("未找到记录数组")


def upsert_record(connection, record, collected_at):
    key = dedupe_key(record)
    digest = record_hash(record)
    existing = connection.execute("SELECT * FROM records WHERE dedupe_key = ?", (key,)).fetchone()
    if existing is None:
        existing = connection.execute(
            """SELECT * FROM records WHERE source=? AND normalized_title=? AND issuer=? AND publish_date=?
            AND source_record_id='' ORDER BY current_version DESC LIMIT 1""",
            (record["source"], record["normalized_title"], record["issuer"], record["publish_date"]),
        ).fetchone()
        if existing is not None and existing["dedupe_key"] != key:
            connection.execute("UPDATE records SET dedupe_key=? WHERE id=?", (key, existing["id"]))
    canonical_json = json.dumps(record, ensure_ascii=False, sort_keys=True)
    if existing is None:
        cursor = connection.execute(
            """INSERT INTO records (
                dedupe_key, source, source_record_id, year, source_version, title, normalized_title, region, record_type, topics_json,
                publish_date, issuer, article_source, application_status, application_period,
                detail_url, official_url, verification_status, authorization_scope, content,
                eligibility_conditions, beneficiary_companies_json, beneficiary_count, query_text,
                page_number, content_hash, current_version, first_seen_at, last_seen_at, active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)""",
            (
                key, record["source"], record["source_record_id"], record["year"], record["source_version"],
                record["title"], record["normalized_title"], record["region"],
                record["record_type"], json.dumps(record["topics"], ensure_ascii=False), record["publish_date"],
                record["issuer"], record["article_source"], record["application_status"], record["application_period"],
                record["detail_url"], record["official_url"], record["verification_status"],
                record["authorization_scope"], record["content"], record["eligibility_conditions"],
                json.dumps(record["beneficiary_companies"], ensure_ascii=False), record["beneficiary_count"],
                record["query"], record["page_number"], digest, collected_at, collected_at, record["active"],
            ),
        )
        record_id = cursor.lastrowid
        connection.execute(
            "INSERT INTO record_versions(record_id, version, content_hash, canonical_json, collected_at) VALUES (?, 1, ?, ?, ?)",
            (record_id, digest, canonical_json, collected_at),
        )
        return "inserted", not bool(record["official_url"])
    if existing["content_hash"] == digest:
        connection.execute("UPDATE records SET last_seen_at = ?, active = ? WHERE id = ?", (collected_at, record["active"], existing["id"]))
        return "unchanged", not bool(existing["official_url"])
    version = existing["current_version"] + 1
    connection.execute(
        """UPDATE records SET
            title=?, normalized_title=?, region=?, record_type=?, topics_json=?, publish_date=?, issuer=?,
            article_source=?, application_status=?, application_period=?, detail_url=?, official_url=?,
            verification_status=?, authorization_scope=?, content=?, content_hash=?, current_version=?,
            eligibility_conditions=?, beneficiary_companies_json=?, beneficiary_count=?, query_text=?,
            page_number=?, last_seen_at=?, source_record_id=?, year=?, source_version=?, active=? WHERE id=?""",
        (
            record["title"], record["normalized_title"], record["region"], record["record_type"],
            json.dumps(record["topics"], ensure_ascii=False), record["publish_date"], record["issuer"],
            record["article_source"], record["application_status"], record["application_period"],
            record["detail_url"], record["official_url"], record["verification_status"],
            record["authorization_scope"], record["content"], digest, version,
            record["eligibility_conditions"], json.dumps(record["beneficiary_companies"], ensure_ascii=False),
            record["beneficiary_count"], record["query"], record["page_number"], collected_at,
            record["source_record_id"], record["year"], record["source_version"], record["active"], existing["id"],
        ),
    )
    connection.execute(
        "INSERT INTO record_versions(record_id, version, content_hash, canonical_json, collected_at) VALUES (?, ?, ?, ?, ?)",
        (existing["id"], version, digest, canonical_json, collected_at),
    )
    return "updated", not bool(record["official_url"])


def coverage_state(obtained, total):
    if total == 0:
        return "不适用"
    if obtained == total:
        return "已取得"
    return "部分取得" if obtained else "未取得"


def delivery_checklist(batch, index_path, history_path, records_with_page):
    indexed = batch["inserted"] + batch["updated"] + batch["unchanged"]
    checked = indexed + batch["failed"]
    valid_fields_state = coverage_state(indexed, checked)
    known_links = indexed - batch["missing_official"]
    scope_recorded = bool(batch["authorization_scope"].strip())
    index_evidence = str(index_path if index_path.is_file() else history_path)
    return {
        "run_id": batch["run_id"],
        "items": {
            "字段完整性": {
                "status": valid_fields_state,
                "evidence": batch["input_path"],
                "detail": f"{indexed}/{checked} 条通过入箱字段检查，{batch['failed']} 条失败。" if checked else "无入箱记录。",
            },
            "分页覆盖": {
                "status": "部分取得" if records_with_page else "未取得",
                "evidence": batch["input_path"],
                "detail": f"{records_with_page} 条索引记录带页码。缺整批分页覆盖证据。",
            },
            "去重": {
                "status": valid_fields_state,
                "evidence": index_evidence,
                "detail": (
                    f"新增 {batch['inserted']} 条，变更 {batch['updated']} 条，重复 {batch['unchanged']} 条。"
                    if checked else "无入箱记录。"
                ),
            },
            "来源链接": {
                "status": coverage_state(known_links, indexed),
                "evidence": index_evidence,
                "detail": f"{known_links}/{indexed} 条索引记录含官方链接。" if indexed else "无可检查的索引记录。",
            },
            "授权范围": {
                "status": "部分取得" if scope_recorded else "未取得",
                "evidence": str(history_path),
                "detail": "已记录授权范围。缺授权凭证。" if scope_recorded else "缺授权范围与授权凭证。",
            },
        },
    }


def write_delivery_reports(paths, batch, checklist):
    directory = paths["batch_history"].parent
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise DeliveryReportError(f"无法创建批次履历和交付检查表目录 {directory}。{error}") from error
    for key, report in (("batch_history", batch), ("delivery_checklist", checklist)):
        try:
            paths[key].write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError as error:
            raise DeliveryReportError(f"无法写入{REPORT_NAMES[key]} {paths[key]}。{error}") from error


def validate_delivery_reports(paths, batch):
    reports = {}
    errors = []
    for key, path in paths.items():
        label = REPORT_NAMES[key]
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            errors.append(f"缺少{label} {path}")
            continue
        except (OSError, ValueError) as error:
            errors.append(f"无法读取{label} {path}。{error}")
            continue
        if isinstance(report, dict):
            reports[key] = report
        else:
            errors.append(f"{label} {path} 必须是 JSON 对象")

    if "batch_history" in reports:
        history = reports["batch_history"]
        for field in ("run_id", "collection_date", "source", *INGEST_COUNTS, "input_path", "authorization_scope"):
            actual = history.get(field)
            expected = batch[field]
            if field not in history or (
                field != "authorization_scope" and isinstance(actual, str) and not actual.strip()
            ):
                errors.append(f"批次履历缺少字段 {field}")
            elif type(actual) is not type(expected) or actual != expected:
                errors.append(f"批次履历字段 {field} 与本批写入结果不符")

    if "delivery_checklist" in reports:
        checklist = reports["delivery_checklist"]
        if checklist.get("run_id") != batch["run_id"]:
            errors.append("交付检查表缺少本批批次号 run_id")
        items = checklist.get("items")
        if not isinstance(items, dict):
            errors.append("交付检查表缺少逐项检查 items")
        else:
            for name in CHECKLIST_ITEMS:
                item = items.get(name)
                if not isinstance(item, dict):
                    errors.append(f"交付检查表缺少检查项 {name}")
                    continue
                if item.get("status") not in CHECKLIST_STATES:
                    errors.append(f"交付检查表 {name} 缺少有效四态 status")
                for field in ("evidence", "detail"):
                    value = item.get(field)
                    if not isinstance(value, str) or not value.strip():
                        errors.append(f"交付检查表 {name} 缺少字段 {field}")
                    elif field == "evidence" and not Path(value).is_file():
                        errors.append(f"交付检查表 {name} 的证据路径缺少文件 {value}")
    if errors:
        raise DeliveryReportError("；".join(errors))


def ingest(connection, input_path, source, collection_date, authorization_scope, scope, index_path):
    run_id = str(uuid.uuid4())
    started = now_iso()
    connection.execute(
        "INSERT INTO collection_runs(run_id, source, collection_date, scope_json, status, started_at, input_path) VALUES (?, ?, ?, ?, 'running', ?, ?)",
        (run_id, source, collection_date, json.dumps(scope, ensure_ascii=False), started, str(input_path)),
    )
    counts = dict.fromkeys(INGEST_COUNTS, 0)
    records_with_page = 0
    delivery_error = None
    try:
        items = load_input(input_path)
        if not items:
            raise DeliveryReportError("未提供可入库的记录")
        for item_number, raw in enumerate(items, 1):
            try:
                record = canonicalize(raw, source, authorization_scope)
                status, missing_official = upsert_record(connection, record, started)
                counts[status] += 1
                counts["missing_official"] += int(missing_official)
                records_with_page += int(record["page_number"] > 0)
            except Exception as error:
                counts["failed"] += 1
                connection.execute(
                    "INSERT INTO ingestion_errors(run_id, item_number, error, created_at) VALUES (?, ?, ?, ?)",
                    (run_id, item_number, str(error), now_iso()),
                )
        status = "success" if counts["failed"] == 0 else "partial"
        batch = {
            "run_id": run_id,
            "collection_date": collection_date,
            "source": source,
            **counts,
            "input_path": str(input_path.absolute()),
            "authorization_scope": authorization_scope,
        }
        index_path = index_path.absolute()
        paths = {key: index_path.parent / "reports" / f"{run_id}_{key}.json" for key in REPORT_NAMES}
        try:
            checklist = delivery_checklist(batch, index_path, paths["batch_history"], records_with_page)
            write_delivery_reports(paths, batch, checklist)
            validate_delivery_reports(paths, batch)
        except DeliveryReportError as error:
            status = "failed"
            delivery_error = error
        finished = now_iso()
        connection.execute(
            """UPDATE collection_runs SET status=?, finished_at=?, inserted_count=?, updated_count=?,
            unchanged_count=?, failed_count=?, missing_official_count=?, error_summary=? WHERE run_id=?""",
            (status, finished, counts["inserted"], counts["updated"], counts["unchanged"],
             counts["failed"], counts["missing_official"], str(delivery_error or ""), run_id),
        )
        connection.execute(
            """INSERT INTO collection_days(source, collection_date, status, last_run_id, updated_at)
            VALUES (?, ?, ?, ?, ?) ON CONFLICT(source, collection_date) DO UPDATE SET
            status=excluded.status, last_run_id=excluded.last_run_id, updated_at=excluded.updated_at""",
            (source, collection_date, status, run_id, finished),
        )
        if status == "success":
            connection.execute(
                """INSERT INTO collection_checkpoints(source, scope_key, last_success_date, updated_at)
                VALUES (?, ?, ?, ?) ON CONFLICT(source, scope_key) DO UPDATE SET
                last_success_date=excluded.last_success_date, updated_at=excluded.updated_at""",
                (source, json.dumps(scope, ensure_ascii=False, sort_keys=True), collection_date, finished),
            )
        connection.commit()
    except Exception as error:
        finished = now_iso()
        connection.execute(
            "UPDATE collection_runs SET status='failed', finished_at=?, error_summary=? WHERE run_id=?",
            (finished, str(error), run_id),
        )
        connection.execute(
            """INSERT INTO collection_days(source, collection_date, status, last_run_id, updated_at)
            VALUES (?, ?, 'failed', ?, ?) ON CONFLICT(source, collection_date) DO UPDATE SET
            status='failed', last_run_id=excluded.last_run_id, updated_at=excluded.updated_at""",
            (source, collection_date, run_id, finished),
        )
        connection.commit()
        raise
    if delivery_error is not None:
        raise delivery_error
    return {
        "run_id": run_id, "status": status, **counts, "collection_date": collection_date,
        "reports": {key: str(path) for key, path in paths.items()},
    }


def query_records(connection, regions, keywords, limit, include_inactive, years=()):
    clauses = []
    parameters = []
    if not include_inactive:
        clauses.append("active = 1")
    if regions:
        clauses.append("(" + " OR ".join("region LIKE ?" for _ in regions) + ")")
        parameters.extend(f"%{region}%" for region in regions)
    if years:
        clauses.append("COALESCE(NULLIF(year, ''), SUBSTR(publish_date, 1, 4)) IN (" + ",".join("?" for _ in years) + ")")
        parameters.extend(str(year) for year in years)
    for keyword in keywords:
        clauses.append("(title LIKE ? OR issuer LIKE ? OR topics_json LIKE ? OR content LIKE ? OR eligibility_conditions LIKE ? OR beneficiary_companies_json LIKE ?)")
        parameters.extend([f"%{keyword}%"] * 6)
    sql = "SELECT * FROM records"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY publish_date DESC, last_seen_at DESC LIMIT ?"
    parameters.append(limit)
    return connection.execute(sql, parameters).fetchall()


def export_records(connection, output, output_format):
    records = connection.execute("SELECT * FROM records WHERE active=1 ORDER BY publish_date DESC, title").fetchall()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output_format == "jsonl":
        with output.open("w", encoding="utf-8") as handle:
            for record in records:
                value = dict(record)
                value["topics"] = json.loads(value.pop("topics_json"))
                value["beneficiary_companies"] = json.loads(value.pop("beneficiary_companies_json"))
                handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
        return len(records)
    output.mkdir(parents=True, exist_ok=True)
    projects = output / "项目"
    projects.mkdir(exist_ok=True)
    for record in records:
        safe_name = re.sub(r"[\\/:*?\"<>|]", "_", record["title"])[:120]
        text = [
            "---",
            f'source: {record["source"]}',
            f'publish_date: {record["publish_date"]}',
            f'region: {record["region"]}',
            f'verification_status: {record["verification_status"]}',
            f'last_seen_at: {record["last_seen_at"]}',
            "---",
            "",
            f'# {record["title"]}',
            "",
            f'- 发文机构：{record["issuer"]}',
            f'- 记录类型：{record["record_type"]}',
            f'- 申报状态：{record["application_status"]}',
            f'- 申报时间：{record["application_period"]}',
            f'- 第三方线索：{record["detail_url"]}',
            f'- 官方原文：{record["official_url"] or "待核验"}',
            "",
            "## 申报条件",
            "",
            record["eligibility_conditions"] or "待采集或待官方核验",
            "",
            "## 通过或公示企业",
            "",
            "\n".join(f"- {name}" for name in json.loads(record["beneficiary_companies_json"])) or "未提取到企业名单",
            "",
            f'- 页面标示企业数量：{record["beneficiary_count"] or "未标明"}',
            "",
            "## 正文",
            "",
            record["content"],
        ]
        (projects / f"{safe_name}.md").write_text("\n".join(text).rstrip() + "\n", encoding="utf-8")
    return len(records)


def print_rows(rows):
    for row in rows:
        value = dict(row)
        if "topics_json" in value:
            value["topics"] = json.loads(value.pop("topics_json"))
        if "beneficiary_companies_json" in value:
            value["beneficiary_companies"] = json.loads(value.pop("beneficiary_companies_json"))
        print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=default_db())
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init")
    ingest_parser = subparsers.add_parser("ingest")
    ingest_parser.add_argument("--input", type=Path, required=True)
    ingest_parser.add_argument("--source", default="aiqice")
    ingest_parser.add_argument("--collection-date", default=date.today().isoformat())
    ingest_parser.add_argument("--authorization-scope", default="用户自有账号本地使用")
    ingest_parser.add_argument("--region", action="append", default=[])
    query_parser = subparsers.add_parser("query")
    query_parser.add_argument("--region", action="append", default=[])
    query_parser.add_argument("--keyword", action="append", default=[])
    query_parser.add_argument("--year", action="append", type=int, default=[])
    query_parser.add_argument("--limit", type=int, default=50)
    query_parser.add_argument("--include-inactive", action="store_true")
    subparsers.add_parser("status")
    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("--format", choices=("jsonl", "markdown"), default="markdown")
    export_parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    connection = connect(args.db)
    try:
        initialize(connection)
        if args.command == "init":
            result = {"status": "initialized", "db": str(args.db)}
        elif args.command == "ingest":
            result = ingest(
                connection, args.input, args.source, args.collection_date, args.authorization_scope,
                {"regions": args.region}, args.db,
            )
        elif args.command == "query":
            print_rows(query_records(connection, args.region, args.keyword, args.limit, args.include_inactive, args.year))
            return
        elif args.command == "status":
            result = {
                "db": str(args.db),
                "records": connection.execute("SELECT COUNT(*) FROM records").fetchone()[0],
                "versions": connection.execute("SELECT COUNT(*) FROM record_versions").fetchone()[0],
                "last_run": dict(connection.execute("SELECT * FROM collection_runs ORDER BY started_at DESC LIMIT 1").fetchone() or {}),
                "last_success_date": connection.execute("SELECT MAX(collection_date) FROM collection_days WHERE status='success'").fetchone()[0],
            }
        else:
            output = args.output or (default_root() / ("records.jsonl" if args.format == "jsonl" else "markdown"))
            result = {"status": "exported", "format": args.format, "output": str(output), "records": export_records(connection, output, args.format)}
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    except DeliveryReportError as error:
        print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    finally:
        connection.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise
