#!/usr/bin/env python3
"""
Sidecar lazy-loaded timeline cache (SQLite WAL) for point-in-time peer benchmarking.
Physically decoupled from the read-only enterprise project DB so full DB rebuilds never wipe cached timelines.
Cross-DB anchor key: 18-char uppercase unified social credit code (uscc).
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS patent_timeline (
    uscc TEXT NOT NULL,
    application_no TEXT NOT NULL,
    patent_type TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    application_date TEXT NOT NULL DEFAULT '',
    grant_date TEXT NOT NULL DEFAULT '',
    legal_status TEXT NOT NULL DEFAULT '',
    invalid_date TEXT NOT NULL DEFAULT '',
    is_transferred INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'qcc',
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (uscc, application_no)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_patent_uscc_grant
    ON patent_timeline(uscc, patent_type, grant_date);

CREATE TABLE IF NOT EXISTS honor_timeline (
    uscc TEXT NOT NULL,
    honor_name TEXT NOT NULL,
    honor_level TEXT NOT NULL DEFAULT '',
    cert_year INTEGER NOT NULL DEFAULT 0,
    published_date TEXT NOT NULL DEFAULT '',
    issuer TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'qcc',
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (uscc, honor_name, cert_year, published_date)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_honor_uscc_date
    ON honor_timeline(uscc, published_date);

CREATE TABLE IF NOT EXISTS cache_fetch_log (
    uscc TEXT NOT NULL,
    enterprise_name TEXT NOT NULL DEFAULT '',
    dimension TEXT NOT NULL,
    record_count INTEGER NOT NULL DEFAULT 0,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (uscc, dimension)
) WITHOUT ROWID;
"""

_DATE_RE = re.compile(r"(\d{4})[-/\.](\d{1,2})[-/\.](\d{1,2})")
_YEAR_RE = re.compile(r"((?:19|20)\d{2})")
_TRANSFER_TOKENS = ("受让", "转让", "转入", "并购", "继受")
_INVALID_STATUS_TOKENS = ("失效", "无效", "终止", "放弃", "撤回", "驳回", "届满")


def resolve_cache_db_path(project_db: Path | None = None) -> Path:
    explicit = os.environ.get("LOCAL_KB_TIMELINE_CACHE_PATH", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    if project_db is not None:
        return project_db.parent / "timeline_cache.db"
    try:
        import kb_local

        return kb_local.PROJECT_DB.parent / "timeline_cache.db"
    except Exception:
        return Path.home() / "LocalKB" / "企业数据库" / "data" / "timeline_cache.db"


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _norm_uscc(uscc: str) -> str:
    return re.sub(r"\s+", "", (uscc or "").strip()).upper()


def _norm_app_no(raw: str) -> str:
    return re.sub(r"\s+", "", (raw or "").strip()).upper()


def _norm_date(raw: Any) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    m = _DATE_RE.search(s)
    if not m:
        return ""
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (1900 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31):
        return ""
    return f"{y:04d}-{mo:02d}-{d:02d}"


def _norm_year(raw: Any) -> int:
    m = _YEAR_RE.search(str(raw or ""))
    return int(m.group(1)) if m else 0


def _infer_patent_type(raw_type: str, app_no: str, legal_status: str) -> str:
    t = (raw_type or "").strip()
    if t in {"发明授权", "发明公布", "实用新型", "外观设计"}:
        return t
    if "发明" in t:
        return "发明授权" if any(k in legal_status for k in ("授权", "有效")) else "发明公布"
    if "实用" in t:
        return "实用新型"
    if "外观" in t:
        return "外观设计"
    m = re.search(r"(?:ZL|CN)?(?:19|20)\d{2}(\d)\d{7}", app_no)
    if m:
        digit = m.group(1)
        if digit in {"1", "8"}:
            return "发明授权" if any(k in legal_status for k in ("授权", "有效")) else "发明公布"
        if digit in {"2", "9"}:
            return "实用新型"
        if digit == "3":
            return "外观设计"
    return t or "未知"


def _infer_transferred(item: dict[str, Any]) -> int:
    if item.get("is_transferred") in {True, 1, "1", "true", "True"}:
        return 1
    for key in ("acquisition", "acquisition_method", "权利取得方式", "取得方式"):
        val = str(item.get(key) or "")
        if any(tok in val for tok in _TRANSFER_TOKENS):
            return 1
    return 0


def init_db(cache_path: Path) -> sqlite3.Connection:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(cache_path), timeout=10.0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA_SQL)
    cur_ver = con.execute("PRAGMA user_version").fetchone()[0]
    if cur_ver < SCHEMA_VERSION:
        con.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    con.commit()
    return con


def _ro_cache_conn(cache_path: Path) -> sqlite3.Connection | None:
    if not cache_path.is_file():
        return None
    con = sqlite3.connect(f"file:{cache_path}?mode=ro", uri=True, timeout=10.0)
    con.row_factory = sqlite3.Row
    return con


def ingest_patents(
    uscc: str,
    payload: Any,
    *,
    enterprise_name: str = "",
    dimension: str = "patent_granted_inv",
    source: str = "qcc",
    fetched_at: str | None = None,
    cache_path: Path | None = None,
) -> dict[str, Any]:
    norm_u = _norm_uscc(uscc)
    if not norm_u:
        return {"ok": False, "error": "uscc 不能为空"}
    target_db = cache_path or resolve_cache_db_path()
    ts = fetched_at or _now_iso()

    ent_name = enterprise_name.strip()
    items: list[dict[str, Any]] = []
    if isinstance(payload, list):
        items = [x for x in payload if isinstance(x, dict)]
    elif isinstance(payload, dict):
        if not ent_name:
            ent_name = str(payload.get("企业名称") or payload.get("enterprise_name") or "").strip()
        for key in ("专利信息", "patents", "items", "records"):
            if isinstance(payload.get(key), list):
                items = [x for x in payload[key] if isinstance(x, dict)]
                break

    rows_to_write: list[tuple[Any, ...]] = []
    for item in items:
        app_no = _norm_app_no(
            str(item.get("申请号") or item.get("application_no") or item.get("patent_no") or item.get("no") or "")
        )
        if not app_no:
            continue
        legal_status = str(item.get("法律状态") or item.get("legal_status") or item.get("status") or "").strip()
        raw_type = str(item.get("专利类型") or item.get("patent_type") or item.get("type") or "").strip()
        ptype = _infer_patent_type(raw_type, app_no, legal_status)
        title = str(item.get("发明名称") or item.get("专利名称") or item.get("title") or "").strip()
        app_date = _norm_date(item.get("申请日期") or item.get("application_date"))
        # For granted patents, QCC's 公开（公告）日期 is the grant announcement date; allow explicit grant_date override.
        raw_grant = item.get("grant_date") or item.get("授权公告日")
        if not raw_grant and ptype in {"发明授权", "实用新型", "外观设计"}:
            raw_grant = item.get("公开（公告）日期") or item.get("公开公告日期") or item.get("publication_date")
        grant_date = _norm_date(raw_grant)
        invalid_date = _norm_date(item.get("invalid_date") or item.get("失效日期"))
        is_trans = _infer_transferred(item)
        rows_to_write.append((
            norm_u, app_no, ptype, title, app_date, grant_date,
            legal_status, invalid_date, is_trans, source, ts,
        ))

    with init_db(target_db) as con:
        con.executemany(
            """
            INSERT INTO patent_timeline (
                uscc, application_no, patent_type, title, application_date, grant_date,
                legal_status, invalid_date, is_transferred, source, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(uscc, application_no) DO UPDATE SET
                patent_type = excluded.patent_type,
                title = CASE WHEN excluded.title != '' THEN excluded.title ELSE patent_timeline.title END,
                application_date = CASE WHEN excluded.application_date != '' THEN excluded.application_date ELSE patent_timeline.application_date END,
                grant_date = CASE WHEN excluded.grant_date != '' THEN excluded.grant_date ELSE patent_timeline.grant_date END,
                legal_status = CASE WHEN excluded.legal_status != '' THEN excluded.legal_status ELSE patent_timeline.legal_status END,
                invalid_date = CASE WHEN excluded.invalid_date != '' THEN excluded.invalid_date ELSE patent_timeline.invalid_date END,
                is_transferred = CASE WHEN excluded.is_transferred = 1 THEN 1 ELSE patent_timeline.is_transferred END,
                source = excluded.source,
                fetched_at = excluded.fetched_at
            """,
            rows_to_write,
        )
        con.execute(
            """
            INSERT INTO cache_fetch_log (uscc, enterprise_name, dimension, record_count, fetched_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(uscc, dimension) DO UPDATE SET
                enterprise_name = CASE WHEN excluded.enterprise_name != '' THEN excluded.enterprise_name ELSE cache_fetch_log.enterprise_name END,
                record_count = excluded.record_count,
                fetched_at = excluded.fetched_at
            """,
            (norm_u, ent_name, dimension, len(rows_to_write), ts),
        )
        con.commit()

    return {
        "ok": True,
        "type": "patent",
        "uscc": norm_u,
        "enterprise_name": ent_name,
        "dimension": dimension,
        "upserted": len(rows_to_write),
        "fetched_at": ts,
        "cache_db": str(target_db),
    }


def ingest_honors(
    uscc: str,
    payload: Any,
    *,
    enterprise_name: str = "",
    source: str = "qcc",
    fetched_at: str | None = None,
    cache_path: Path | None = None,
) -> dict[str, Any]:
    norm_u = _norm_uscc(uscc)
    if not norm_u:
        return {"ok": False, "error": "uscc 不能为空"}
    target_db = cache_path or resolve_cache_db_path()
    ts = fetched_at or _now_iso()

    ent_name = enterprise_name.strip()
    items: list[dict[str, Any]] = []
    if isinstance(payload, list):
        items = [x for x in payload if isinstance(x, dict)]
    elif isinstance(payload, dict):
        if not ent_name:
            ent_name = str(payload.get("企业名称") or payload.get("enterprise_name") or "").strip()
        for key in ("荣誉信息", "honors", "items", "records"):
            if isinstance(payload.get(key), list):
                items = [x for x in payload[key] if isinstance(x, dict)]
                break

    rows_to_write: list[tuple[Any, ...]] = []
    for item in items:
        hname = str(item.get("名称") or item.get("honor_name") or item.get("name") or "").strip()
        if not hname:
            continue
        hlevel = str(item.get("级别") or item.get("honor_level") or item.get("level") or "").strip()
        cyear = _norm_year(item.get("认证年份") or item.get("cert_year") or item.get("year"))
        pdate = _norm_date(item.get("发布日期") or item.get("published_date"))
        if cyear == 0 and pdate:
            cyear = int(pdate[:4])
        issuer = str(item.get("发布单位") or item.get("issuer") or "").strip()
        rows_to_write.append((norm_u, hname, hlevel, cyear, pdate, issuer, source, ts))

    with init_db(target_db) as con:
        con.executemany(
            """
            INSERT INTO honor_timeline (
                uscc, honor_name, honor_level, cert_year, published_date, issuer, source, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(uscc, honor_name, cert_year, published_date) DO UPDATE SET
                honor_level = CASE WHEN excluded.honor_level != '' THEN excluded.honor_level ELSE honor_timeline.honor_level END,
                issuer = CASE WHEN excluded.issuer != '' THEN excluded.issuer ELSE honor_timeline.issuer END,
                source = excluded.source,
                fetched_at = excluded.fetched_at
            """,
            rows_to_write,
        )
        con.execute(
            """
            INSERT INTO cache_fetch_log (uscc, enterprise_name, dimension, record_count, fetched_at)
            VALUES (?, ?, 'honor', ?, ?)
            ON CONFLICT(uscc, dimension) DO UPDATE SET
                enterprise_name = CASE WHEN excluded.enterprise_name != '' THEN excluded.enterprise_name ELSE cache_fetch_log.enterprise_name END,
                record_count = excluded.record_count,
                fetched_at = excluded.fetched_at
            """,
            (norm_u, ent_name, len(rows_to_write), ts),
        )
        con.commit()

    return {
        "ok": True,
        "type": "honor",
        "uscc": norm_u,
        "enterprise_name": ent_name,
        "dimension": "honor",
        "upserted": len(rows_to_write),
        "fetched_at": ts,
        "cache_db": str(target_db),
    }


def _eval_one_uscc(con: sqlite3.Connection, uscc: str, as_of_date: str) -> dict[str, Any]:
    norm_u = _norm_uscc(uscc)
    cutoff = _norm_date(as_of_date) or f"{_norm_year(as_of_date) or 2099:04d}-12-31"
    cutoff_year = int(cutoff[:4])

    logs = {
        r["dimension"]: dict(r)
        for r in con.execute(
            "SELECT dimension, record_count, fetched_at FROM cache_fetch_log WHERE uscc = ?",
            (norm_u,),
        ).fetchall()
    }
    pat_log = logs.get("patent_granted_inv") or logs.get("patent_all")
    honor_log = logs.get("honor")

    result: dict[str, Any] = {
        "uscc": norm_u,
        "as_of_date": cutoff,
        "cache_hit": bool(pat_log or honor_log),
        "patent_cache_hit": bool(pat_log),
        "honor_cache_hit": bool(honor_log),
    }

    if pat_log:
        fetched_date = str(pat_log["fetched_at"] or "")[:10]
        result["patent_fetched_at"] = pat_log["fetched_at"]
        result["patent_point_in_time_reliable"] = bool(fetched_date and fetched_date >= cutoff)
        rows = con.execute(
            """
            SELECT application_no, patent_type, grant_date, legal_status, invalid_date, is_transferred
            FROM patent_timeline
            WHERE uscc = ? AND patent_type = '发明授权'
            """,
            (norm_u,),
        ).fetchall()
        valid_at_t = 0
        own_at_t = 0
        current_valid = 0
        for r in rows:
            status = str(r["legal_status"] or "")
            inv_dt = str(r["invalid_date"] or "")
            is_curr_invalid = any(tok in status for tok in _INVALID_STATUS_TOKENS)
            if not is_curr_invalid and not inv_dt:
                current_valid += 1
            elif inv_dt and inv_dt > fetched_date:
                current_valid += 1
            gdt = str(r["grant_date"] or "")
            if gdt and gdt <= cutoff:
                alive_at_t = (not inv_dt and not is_curr_invalid) or (bool(inv_dt) and inv_dt > cutoff)
                if alive_at_t:
                    valid_at_t += 1
                    if int(r["is_transferred"] or 0) == 0:
                        own_at_t += 1
        result["valid_granted_inv_at_t"] = valid_at_t
        result["valid_own_inv_at_t"] = own_at_t
        result["current_granted_inv"] = current_valid
        result["post_hoc_granted_inv_delta"] = current_valid - valid_at_t

    if honor_log:
        result["honor_fetched_at"] = honor_log["fetched_at"]
        hrows = con.execute(
            """
            SELECT honor_name, honor_level, cert_year, published_date, issuer
            FROM honor_timeline WHERE uscc = ?
            ORDER BY published_date DESC, cert_year DESC
            """,
            (norm_u,),
        ).fetchall()
        pre_h: list[str] = []
        post_h: list[str] = []
        for r in hrows:
            pdate = str(r["published_date"] or "")
            cyr = int(r["cert_year"] or 0)
            label = f"{r['honor_level']}{r['honor_name']}" if r["honor_level"] and r["honor_level"] not in r["honor_name"] else r["honor_name"]
            if pdate:
                if pdate <= cutoff:
                    pre_h.append(label)
                else:
                    post_h.append(f"{label}({pdate})")
            elif cyr > 0:
                if cyr <= cutoff_year:
                    pre_h.append(label)
                else:
                    post_h.append(f"{label}({cyr})")
        result["pre_honors_at_t"] = list(dict.fromkeys(pre_h))
        result["post_honors_after_t"] = list(dict.fromkeys(post_h))

    return result


def query_at_date(uscc: str, as_of_date: str, *, cache_path: Path | None = None) -> dict[str, Any]:
    target_db = cache_path or resolve_cache_db_path()
    con = _ro_cache_conn(target_db)
    if con is None:
        return {
            "uscc": _norm_uscc(uscc),
            "as_of_date": _norm_date(as_of_date) or str(as_of_date),
            "cache_hit": False,
            "patent_cache_hit": False,
            "honor_cache_hit": False,
        }
    with con:
        return _eval_one_uscc(con, uscc, as_of_date)


def batch_query_at_date(
    uscc_dates: dict[str, str],
    *,
    cache_path: Path | None = None,
) -> dict[str, dict[str, Any]]:
    target_db = cache_path or resolve_cache_db_path()
    out: dict[str, dict[str, Any]] = {}
    con = _ro_cache_conn(target_db)
    if con is None:
        for u, dt in uscc_dates.items():
            nu = _norm_uscc(u)
            if nu:
                out[nu] = {
                    "uscc": nu,
                    "as_of_date": _norm_date(dt) or str(dt),
                    "cache_hit": False,
                    "patent_cache_hit": False,
                    "honor_cache_hit": False,
                }
        return out
    with con:
        for u, dt in uscc_dates.items():
            nu = _norm_uscc(u)
            if nu:
                out[nu] = _eval_one_uscc(con, nu, dt)
    return out
