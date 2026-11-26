#!/usr/bin/env python3
"""
Local read-only Enterprise Knowledge Base connector (zero MCP dependency).
Directly queries:
  - Local read-only SQLite enterprise database (override via LOCAL_KB_DB_PATH or LOCAL_KB_DATA_ROOT; auto-discovers ~/.../企业数据库/data/*.db)
  - Local rag-query.sh (override via LOCAL_KB_RAG_QUERY, with source-permission & privacy filtering)
  - Full provincial/city/district region resolver (including Zhejiang county-level cities)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
from pathlib import Path
from typing import Any


def _has_enterprise_table(db_path: Path) -> bool:
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            row = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='enterprise' LIMIT 1").fetchone()
            return row is not None
        finally:
            con.close()
    except sqlite3.Error:
        return False


def _pick_preferred_db(candidates: list[Path]) -> Path | None:
    valid = [p for p in candidates if p.is_file() and p.stat().st_size > 0]
    if not valid:
        return candidates[0] if candidates else None
    ent_dbs = [p for p in valid if _has_enterprise_table(p)]
    pool = ent_dbs or valid
    pool.sort(key=lambda p: (p.stat().st_size, p.stat().st_mtime), reverse=True)
    return pool[0]


def _discover_default_db() -> Path:
    explicit_db = os.environ.get("LOCAL_KB_DB_PATH", "").strip()
    if explicit_db:
        return Path(explicit_db).expanduser()
    explicit_root = os.environ.get("LOCAL_KB_DATA_ROOT", "").strip()
    if explicit_root:
        root = Path(explicit_root).expanduser()
        found = sorted((root / "企业数据库" / "data").glob("*.db"))
        picked = _pick_preferred_db(found)
        if picked:
            return picked
        return root / "企业数据库" / "data" / "enterprise.db"
    discovered = sorted(Path.home().glob("*/企业数据库/data/*.db"))
    picked = _pick_preferred_db(discovered)
    if picked:
        return picked
    return Path.home() / "LocalKB" / "企业数据库" / "data" / "enterprise.db"


PROJECT_DB = _discover_default_db()
DATA_ROOT = PROJECT_DB.parents[2] if len(PROJECT_DB.parents) >= 3 else Path.home() / "LocalKB"
KB_ROOT = DATA_ROOT / "知识库"
RAG_QUERY_SH = Path(os.environ.get("LOCAL_KB_RAG_QUERY") or str(Path.home() / "rag" / "rag-query.sh"))

# Complete Zhejiang 11 prefecture-level cities + major counties/districts for reliable policy scoping
ZHEJIANG_DISTRICTS: dict[str, str] = {
    # 杭州市
    "上城区": "杭州市", "拱墅区": "杭州市", "西湖区": "杭州市", "滨江区": "杭州市",
    "萧山区": "杭州市", "余杭区": "杭州市", "临平区": "杭州市", "钱塘区": "杭州市",
    "富阳区": "杭州市", "临安区": "杭州市", "桐庐县": "杭州市", "淳安县": "杭州市", "建德市": "杭州市",
    # 宁波市
    "海曙区": "宁波市", "江北区": "宁波市", "北仑区": "宁波市", "镇海区": "宁波市",
    "鄞州区": "宁波市", "奉化区": "宁波市", "余姚市": "宁波市", "慈溪市": "宁波市",
    "象山县": "宁波市", "宁海县": "宁波市",
    # 温州市
    "鹿城区": "温州市", "龙湾区": "温州市", "瓯海区": "温州市", "洞头区": "温州市",
    "瑞安市": "温州市", "乐清市": "温州市", "龙港市": "温州市", "永嘉县": "温州市",
    "平阳县": "温州市", "苍南县": "温州市", "文成县": "温州市", "泰顺县": "温州市",
    # 嘉兴市
    "南湖区": "嘉兴市", "秀洲区": "嘉兴市", "海宁市": "嘉兴市", "平湖市": "嘉兴市",
    "桐乡市": "嘉兴市", "嘉善县": "嘉兴市", "海盐县": "嘉兴市",
    # 湖州市
    "吴兴区": "湖州市", "南浔区": "湖州市", "德清县": "湖州市", "长兴县": "湖州市", "安吉县": "湖州市",
    # 绍兴市
    "越城区": "绍兴市", "柯桥区": "绍兴市", "上虞区": "绍兴市", "诸暨市": "绍兴市",
    "嵊州市": "绍兴市", "新昌县": "绍兴市",
    # 金华市
    "婺城区": "金华市", "金东区": "金华市", "兰溪市": "金华市", "义乌市": "金华市",
    "东阳市": "金华市", "永康市": "金华市", "武义县": "金华市", "浦江县": "金华市", "磐安县": "金华市",
    # 衢州市
    "柯城区": "衢州市", "衢江区": "衢州市", "江山市": "衢州市", "常山县": "衢州市",
    "开化县": "衢州市", "龙游县": "衢州市",
    # 舟山市
    "定海区": "舟山市", "普陀区": "舟山市", "岱山县": "舟山市", "嵊泗县": "舟山市",
    # 台州市
    "椒江区": "台州市", "黄岩区": "台州市", "路桥区": "台州市", "临海市": "台州市",
    "温岭市": "台州市", "玉环市": "台州市", "三门县": "台州市", "天台县": "台州市", "仙居县": "台州市",
    # 丽水市
    "莲都区": "丽水市", "龙泉市": "丽水市", "青田县": "丽水市", "缙云县": "丽水市",
    "遂昌县": "丽水市", "松阳县": "丽水市", "云和县": "丽水市", "庆元县": "丽水市", "景宁畲族自治县": "丽水市",
}
ZHEJIANG_CITIES = set(ZHEJIANG_DISTRICTS.values())

PRIVACY_TITLE_TERMS = ("养老保险", "社保明细", "身份证", "工资表", "个人所得税", "花名册", "联系方式")
DUP_SUFFIX_RE = re.compile(r"(?:\s*\(\d+\)|\s+\d+|__[0-9a-f]{6,12})$", re.IGNORECASE)

# Higher rank wins when deduplicating same-enterprise + same-project + same-year recognition events
STATUS_RANK = {
    "计划退出目录": 90,
    "已退出目录": 95,
    "撤销": 100,
    "取消": 100,
    "正式认定": 80,
    "认定": 75,
    "复核通过": 75,
    "拟复核通过": 50,
    "拟认定": 40,
    "拟支持": 40,
    "公示": 35,
    "平台线索": 10,
}


def resolve_region_scope(text: str) -> dict[str, Any]:
    """Resolve province / city / district (including county-level cities like 金华市义乌市) cleanly without cross-province collision."""
    raw = (text or "").strip()
    province = ""
    city = ""
    district = ""

    # 1. Explicit province / municipality match FIRST
    m_prov = re.search(r"([\u4e00-\u9fa5]{2,5}(?:省|自治区)|北京|上海|天津|重庆)(?:市)?", raw)
    if m_prov:
        p = m_prov.group(1)
        province = p if p.endswith(("省", "自治区")) else p + "市"

    # 2. Match first city token AFTER province prefix without crossing another 市/区/县 delimiter
    after_prov = raw[m_prov.end():] if m_prov else raw
    m_city = re.search(r"([^\s省市区县]{2,5}市)", after_prov)
    explicit_city = m_city.group(1) if m_city else ""
    if (
        explicit_city
        and explicit_city not in ZHEJIANG_CITIES
        and explicit_city not in ZHEJIANG_DISTRICTS
        and explicit_city not in {"北京市", "上海市", "天津市", "重庆市"}
    ):
        city = explicit_city

    is_non_zj = (bool(province) and province != "浙江省") or (bool(city) and city not in ZHEJIANG_CITIES)

    # 3. Match Zhejiang cities/districts ONLY when NOT explicitly outside Zhejiang
    if not is_non_zj:
        # If explicit prefecture city matched (e.g. 金华市 in 浙江省金华市义乌市), search district after it first
        dist_search_text = after_prov[m_city.end():] if (m_city and explicit_city in ZHEJIANG_CITIES) else after_prov
        for dist_name, parent_city in ZHEJIANG_DISTRICTS.items():
            if explicit_city and explicit_city in ZHEJIANG_CITIES and explicit_city != parent_city:
                continue
            short = dist_name[:-1] if len(dist_name) >= 3 and dist_name[-1] in "区县市" else dist_name
            if dist_name in dist_search_text or (len(short) >= 2 and short in dist_search_text):
                district = dist_name
                city = parent_city
                province = "浙江省"
                break
        if not city:
            if explicit_city in ZHEJIANG_CITIES:
                city = explicit_city
                province = "浙江省"
            else:
                for c in ZHEJIANG_CITIES:
                    short = c[:-1]
                    if c in after_prov or short in after_prov:
                        city = c
                        province = "浙江省"
                        break
    else:
        after_city = after_prov[m_city.end():] if m_city else after_prov
        m_dist = re.search(r"([^\s省市区县]{2,6}(?:区|县|市))", after_city)
        if m_dist:
            district = m_dist.group(1)

    scopes = ["国家"]
    if province:
        scopes.append(province)
    if city and city != province:
        scopes.append(city)
    if district:
        scopes.append(district)
    return {
        "input": raw,
        "province": province,
        "city": city,
        "district": district,
        "scopes": scopes,
    }


def _ro_conn(db_path: Path = PROJECT_DB) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10.0)
    con.row_factory = sqlite3.Row
    return con


def normalize_batch(batch: str) -> str:
    s = re.sub(r"\s+", "", (batch or "").strip())
    s = s.replace("年度", "年")
    return s


def deduplicate_recognitions(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse duplicate (enterprise, project, year, product) rows keeping highest-authority verbatim status."""
    grouped: dict[tuple[str, str, Any, str], dict[str, Any]] = {}
    for r in records:
        key = (
            str(r.get("enterprise_name") or "").strip(),
            str(r.get("project_name") or "").strip(),
            r.get("recognition_year"),
            re.sub(r"\s+", "", str(r.get("product_name") or "").strip()),
        )
        rank = STATUS_RANK.get(str(r.get("result") or "").strip(), 20)
        existing = grouped.get(key)
        if existing is None or rank > existing["_rank"]:
            entry = dict(r)
            entry["_rank"] = rank
            entry["merged_statuses"] = sorted(
                set((existing.get("merged_statuses", []) if existing else []) + [str(r.get("result") or "")])
            )
            grouped[key] = entry
        else:
            existing["merged_statuses"] = sorted(
                set(existing.get("merged_statuses", []) + [str(r.get("result") or "")])
            )
    out = []
    for v in grouped.values():
        v.pop("_rank", None)
        out.append(v)
    out.sort(key=lambda x: (x.get("recognition_year") or 0, x.get("project_name") or ""), reverse=True)
    return out


def _norm_company(name: str) -> str:
    return re.sub(r"[\s\u3000（）()·\-_]+", "", (name or "").strip())


def query_enterprise(enterprise_name: str, db_path: Path = PROJECT_DB, *, credit_code: str = "") -> dict[str, Any]:
    """Query enterprise profile, financials, deduplicated recognitions, and application records directly from local DB.
    Enforces strict identity verification:
      - If credit_code is supplied and not found, NEVER silently falls back to enterprise_name.
      - If BOTH enterprise_name and credit_code are supplied, verifies they resolve to the SAME enterprise.
      - Refuses ambiguous multi-company short-name collisions unless an exact full name or credit_code uniquely resolves one subject.
    """
    if not db_path.is_file():
        return {"found": False, "error": f"local database not found: {db_path}"}
    norm_code = credit_code.strip().upper()
    norm_query_name = enterprise_name.strip()
    with _ro_conn(db_path) as con:
        rows = []
        if norm_code:
            rows = con.execute(
                """
                SELECT id, name, unified_social_credit_code, province, city, county,
                       founded_date, registered_capital, industry_l1, industry_l2, industry_l3, company_intro
                FROM enterprise WHERE upper(unified_social_credit_code) = ? LIMIT 5
                """,
                (norm_code,),
            ).fetchall()
            if not rows:
                return {
                    "found": False,
                    "credit_code_not_found": True,
                    "query": norm_query_name,
                    "credit_code": norm_code,
                    "error": f"未在本地库检索到统一社会信用代码「{norm_code}」对应企业，已停止按企业名称回退以防串户",
                }
            row = rows[0]
            if norm_query_name:
                q_norm = _norm_company(norm_query_name)
                db_norm = _norm_company(str(row["name"] or ""))
                is_full_query = norm_query_name.endswith(("有限公司", "有限责任公司", "股份有限公司"))
                same_subject = (q_norm == db_norm) if is_full_query else (q_norm in db_norm or db_norm in q_norm)
                if not same_subject:
                    return {
                        "found": False,
                        "subject_conflict": True,
                        "query": norm_query_name,
                        "credit_code": norm_code,
                        "matched_name_by_code": row["name"],
                        "error": f"企业标识冲突：输入名称「{norm_query_name}」与信用代码「{norm_code}」对应主体「{row['name']}」不一致，已拦截且不返回财务数据",
                    }
        else:
            rows = con.execute(
                """
                SELECT id, name, unified_social_credit_code, province, city, county,
                       founded_date, registered_capital, industry_l1, industry_l2, industry_l3, company_intro
                FROM enterprise WHERE name LIKE ? ORDER BY length(name) ASC LIMIT 10
                """,
                (f"%{norm_query_name}%",),
            ).fetchall()
            if not rows:
                return {"found": False, "query": norm_query_name}
            exact = [r for r in rows if _norm_company(r["name"]) == _norm_company(norm_query_name)]
            if exact:
                row = exact[0]
            elif len(rows) > 1:
                return {
                    "found": False,
                    "ambiguous": True,
                    "query": norm_query_name,
                    "error": f"简称「{norm_query_name}」命中 {len(rows)} 家不同企业，请提供完整企业名称或18位统一社会信用代码防止串户",
                    "candidates": [
                        {"name": r["name"], "credit_code": r["unified_social_credit_code"], "city": r["city"]}
                        for r in rows[:10]
                    ],
                }
            else:
                row = rows[0]
        ent = dict(row)
        eid = ent["id"]
        fins = [
            dict(r)
            for r in con.execute(
                """
                SELECT DISTINCT fiscal_year, metric, value_text, unit, amount_yuan
                FROM enterprise_financial WHERE enterprise_id = ?
                ORDER BY fiscal_year DESC, metric
                """,
                (eid,),
            ).fetchall()
        ]
        raw_recs = [
            dict(r)
            for r in con.execute(
                """
                SELECT ? AS enterprise_name, project_name, recognition_year, batch, result,
                       product_name, primary_source_title, published_date, evidence_status
                FROM recognition WHERE enterprise_id = ?
                ORDER BY recognition_year DESC
                """,
                (ent["name"], eid),
            ).fetchall()
        ]
        apps = [
            dict(r)
            for r in con.execute(
                """
                SELECT a.enterprise_name, p.name AS project_name, a.application_year, a.file_path
                FROM application a LEFT JOIN project p ON a.project_id = p.id
                WHERE a.enterprise_id = ?
                ORDER BY a.application_year DESC
                """,
                (eid,),
            ).fetchall()
        ]
    # Detect cross-year financial conflicts (e.g., two different revenues for same year)
    fin_by_ym: dict[tuple[int, str], list[str]] = {}
    for f in fins:
        fin_by_ym.setdefault((f["fiscal_year"], f["metric"]), []).append(f["value_text"])
    fin_conflicts = [
        {"year": y, "metric": m, "values": sorted(set(vs))}
        for (y, m), vs in sorted(fin_by_ym.items(), reverse=True)
        if len(set(vs)) > 1
    ]
    return {
        "found": True,
        "source": "local_enterprise_db",
        "enterprise": ent,
        "financials": fins,
        "financial_conflicts": fin_conflicts,
        "recognitions_raw_count": len(raw_recs),
        "recognitions": deduplicate_recognitions(raw_recs),
        "applications": apps,
    }


def _extract_query_terms(query: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z0-9]{3,}|[\u4e00-\u9fff]{2,}", query)
    stop = {"关于", "通知", "办法", "条件", "申报", "认定", "企业", "项目", "政策", "如何", "什么"}
    return [t for t in tokens if t not in stop] or tokens


def _canonical_doc_stem(title: str) -> str:
    stem = Path(title).stem
    stem = DUP_SUFFIX_RE.sub("", stem).strip()
    return re.sub(r"\s+", "", stem)


RESTRICTED_ACCESS_VALUES = {
    "restricted", "private", "confidential", "internal", "secret", "client_private", "client-private",
    "受限", "机密", "绝密", "内部受限", "仅内部", "客户机密", "禁止外发",
}


def _is_restricted_rag_item(item: dict[str, Any]) -> bool:
    for bool_key in ("restricted", "is_restricted", "confidential", "is_private", "private"):
        if item.get(bool_key) is True:
            return True
    for key in ("sensitivity", "access_level", "visibility", "permission", "security_level", "access", "scope", "data_classification", "权限", "访问级别", "密级"):
        val = str(item.get(key) or "").strip().lower()
        if val and (val in RESTRICTED_ACCESS_VALUES or any(tok in val for tok in ("restricted", "private", "confidential", "受限", "机密", "仅内部"))):
            return True
    role_and_src = f"{item.get('document_role') or ''} {item.get('source') or ''}".lower()
    if any(tok in role_and_src for tok in ("restricted", "confidential", "client_private", "受限资料", "客户机密", "内部受限")):
        return True
    return False


def search_local_rag(
    query: str,
    limit: int = 8,
    category: str = "",
    *,
    exclude_privacy: bool = True,
    dedup_copies: bool = True,
) -> dict[str, Any]:
    """Run local rag-query.sh with source-permission filtering FIRST, then PII redaction, false-positive rejection & copy dedup."""
    if not RAG_QUERY_SH.is_file():
        return {"query": query, "count": 0, "error": f"rag-query.sh missing: {RAG_QUERY_SH}", "results": []}
    fetch_k = min(30, max(limit * 3, 12))
    cmd = [str(RAG_QUERY_SH), query, str(fetch_k)]
    if category:
        cmd.append(category)
    env = os.environ.copy()
    env["PYTHONWARNINGS"] = "ignore::UserWarning"
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        return {"query": query, "count": 0, "error": proc.stderr[:400], "results": []}
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return {"query": query, "count": 0, "error": f"invalid rag JSON: {exc}", "results": []}

    terms = _extract_query_terms(query)
    alnum_tokens = [t.lower() for t in re.findall(r"[A-Za-z0-9_\-]{4,}", query)]
    code_tokens = [t for t in alnum_tokens if any(ch.isdigit() for ch in t) and any(ch.isalpha() for ch in t)]
    seen_stems: set[str] = set()
    filtered = []
    dropped_privacy = 0
    dropped_restricted = 0
    dropped_duplicates = 0
    dropped_irrelevant = 0

    for item in data.get("results", []):
        if not isinstance(item, dict):
            continue
        # 1. Source permission filter FIRST (even if excerpt contains no privacy keywords)
        if exclude_privacy and _is_restricted_rag_item(item):
            dropped_restricted += 1
            continue

        title = str(item.get("title") or "")
        source = str(item.get("source") or "")
        excerpt = str(item.get("excerpt") or "")
        haystack = f"{title} {source} {excerpt}".lower()

        if exclude_privacy and any(p in title or p in source or p in excerpt for p in PRIVACY_TITLE_TERMS):
            dropped_privacy += 1
            continue
        # 2. Redact mobile phone numbers & ID numbers from allowed excerpts before returning downstream
        excerpt_clean = re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", "[已脱敏手机]", excerpt)
        excerpt_clean = re.sub(r"(?<!\d)[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)", "[已脱敏证件]", excerpt_clean)

        # False-positive guard:
        if code_tokens and not all(tok in haystack for tok in code_tokens):
            dropped_irrelevant += 1
            continue
        if alnum_tokens and not any(tok in haystack for tok in alnum_tokens):
            dropped_irrelevant += 1
            continue
        if terms and not any(t.lower() in haystack for t in terms):
            dropped_irrelevant += 1
            continue

        if dedup_copies:
            cstem = _canonical_doc_stem(title)
            if cstem in seen_stems:
                dropped_duplicates += 1
                continue
            seen_stems.add(cstem)

        filtered.append({
            "title": title,
            "source": source,
            "document_role": item.get("document_role"),
            "region": item.get("适用地区") or item.get("region"),
            "validity_status": item.get("validity_status"),
            "score": item.get("score"),
            "excerpt": excerpt_clean[:500],
        })
        if len(filtered) >= limit:
            break

    return {
        "query": query,
        "effective_query": data.get("effective_query"),
        "count": len(filtered),
        "dropped": {
            "restricted": dropped_restricted,
            "privacy": dropped_privacy,
            "duplicates": dropped_duplicates,
            "irrelevant": dropped_irrelevant,
        },
        "results": filtered,
    }


def _table_columns(con: sqlite3.Connection, table_name: str) -> set[str]:
    try:
        return {str(r[1]) for r in con.execute(f"PRAGMA table_info({table_name})").fetchall()}
    except sqlite3.Error:
        return set()


def _quantiles_summary(vals: list[float]) -> dict[str, Any]:
    cleaned = sorted(float(v) for v in vals if v is not None)
    n = len(cleaned)
    if n == 0:
        return {"n": 0}

    def _pct(p: float) -> float:
        idx = (n - 1) * p
        lo = int(idx)
        hi = min(lo + 1, n - 1)
        frac = idx - lo
        return round(cleaned[lo] * (1.0 - frac) + cleaned[hi] * frac, 1)

    return {
        "n": n,
        "min": round(cleaned[0], 1),
        "p25": _pct(0.25),
        "median": _pct(0.50),
        "p75": _pct(0.75),
        "mean": round(sum(cleaned) / n, 1),
        "max": round(cleaned[-1], 1),
    }


def _infer_apply_date(recognition_year: int | None, published_date: str | None, override_apply_date: str = "") -> tuple[str, int | None]:
    if override_apply_date:
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", override_apply_date)
        if m:
            return m.group(0), int(m.group(1))
        m_y = re.search(r"((?:19|20)\d{2})", override_apply_date)
        if m_y:
            yr = int(m_y.group(1))
            return f"{yr:04d}-12-31", yr
    if recognition_year:
        pub = str(published_date or "").strip()
        m_pub = re.search(r"(\d{4})-(\d{2})-(\d{2})", pub)
        if m_pub and int(m_pub.group(1)) == recognition_year and int(m_pub.group(2)) <= 3:
            yr = recognition_year - 1
            return f"{yr:04d}-12-31", yr
        return f"{recognition_year:04d}-12-31", recognition_year
    return "", None


def _calc_age_at_date(founded_date: str | None, as_of_date: str) -> float | None:
    if not founded_date or not as_of_date:
        return None
    m_f = re.match(r"(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?", str(founded_date).strip())
    m_t = re.match(r"(\d{4})-(\d{2})-(\d{2})", as_of_date.strip())
    if not m_f or not m_t:
        return None
    fy = int(m_f.group(1))
    fm = int(m_f.group(2) or 6)
    ty = int(m_t.group(1))
    tm = int(m_t.group(2))
    age = (ty - fy) + (tm - fm) / 12.0
    if age < 0 or age > 120:
        return None
    return round(age, 1)


def query_peers(
    project_keyword: str,
    region: str = "",
    industry_keyword: str = "",
    limit: int = 20,
    db_path: Path = PROJECT_DB,
    *,
    year: int | None = None,
    exclude_review: bool = False,
    apply_date: str = "",
    benchmark: bool = False,
    cache_path: Path | None = None,
) -> dict[str, Any]:
    """Query deduplicated comparable peers directly from local enterprise database recognition table.
    Supports point-in-time cohort benchmarking (age_at_apply, pre-existing vs post-hoc companion projects,
    and sidecar timeline_cache.db patent/honor lookup) while remaining 100% backward compatible.
    """
    if not db_path.is_file():
        return {"count": 0, "error": f"local database not found: {db_path}", "peers": []}

    with _ro_conn(db_path) as con:
        rec_cols = _table_columns(con, "recognition")
        ent_cols = _table_columns(con, "enterprise")
        has_rec_status = "recognition_status" in rec_cols
        has_pub_date = "published_date" in rec_cols
        has_founded = "founded_date" in ent_cols
        has_cap = "registered_capital" in ent_cols

        clauses = ["r.project_name LIKE ?"]
        params: list[Any] = [f"%{project_keyword}%"]
        if has_rec_status:
            clauses.append("r.recognition_status = 'recognized'")
        if year is not None:
            clauses.append("r.recognition_year = ?")
            params.append(int(year))
        if exclude_review:
            clauses.append("r.result NOT LIKE '%复核%'")
        if region:
            clauses.append("(e.province LIKE ? OR e.city LIKE ? OR e.county LIKE ?)")
            params.extend([f"%{region}%"] * 3)
        if industry_keyword:
            clauses.append("(e.industry_l2 LIKE ? OR e.industry_l3 LIKE ? OR e.company_intro LIKE ? OR r.product_name LIKE ?)")
            params.extend([f"%{industry_keyword}%"] * 4)

        select_parts = [
            "e.id AS enterprise_id",
            "e.name AS enterprise_name",
            "e.unified_social_credit_code AS credit_code",
            "e.province",
            "e.city",
            "e.county",
            "e.industry_l2",
            "e.industry_l3",
            "e.founded_date" if has_founded else "'' AS founded_date",
            "e.registered_capital" if has_cap else "'' AS registered_capital",
            "r.project_name",
            "r.recognition_year",
            "r.batch",
            "r.result",
            "r.product_name",
            "r.primary_source_title",
            "r.published_date" if has_pub_date else "'' AS published_date",
        ]
        sql = f"""
            SELECT {', '.join(select_parts)}
            FROM recognition r JOIN enterprise e ON r.enterprise_id = e.id
            WHERE {' AND '.join(clauses)}
            ORDER BY r.recognition_year DESC, e.name ASC
            LIMIT ?
        """
        fetch_limit = max(limit * 3, 200) if benchmark else limit * 3
        params.append(fetch_limit)
        raw = [dict(r) for r in con.execute(sql, params).fetchall()]
        deduped = deduplicate_recognitions(raw)[:limit]

        # Point-in-time companion recognition lookup (L1 exact backtest)
        eids = sorted({int(p["enterprise_id"]) for p in deduped if p.get("enterprise_id") is not None})
        companion_first: dict[int, dict[str, int]] = {}
        if eids:
            placeholders = ",".join("?" for _ in eids)
            status_filter = "AND recognition_status = 'recognized'" if has_rec_status else ""
            c_rows = con.execute(
                f"""
                SELECT enterprise_id, project_name, MIN(recognition_year) AS first_year
                FROM recognition
                WHERE enterprise_id IN ({placeholders}) {status_filter}
                GROUP BY enterprise_id, project_name
                """,
                tuple(eids),
            ).fetchall()
            for cr in c_rows:
                companion_first.setdefault(int(cr["enterprise_id"]), {})[str(cr["project_name"])] = int(cr["first_year"])

    # Sidecar timeline cache batch lookup (L3 exact backtest where cached)
    uscc_dates: dict[str, str] = {}
    for p in deduped:
        eff_date, eff_year = _infer_apply_date(p.get("recognition_year"), p.get("published_date"), apply_date)
        p["apply_date"] = eff_date
        p["apply_year"] = eff_year
        p["is_review"] = "复核" in str(p.get("result") or "")
        p["age_at_apply"] = _calc_age_at_date(p.get("founded_date"), eff_date)
        eid = p.get("enterprise_id")
        pre_proj: list[str] = []
        post_proj: list[str] = []
        if eid is not None and eff_year is not None:
            for pname, fyr in sorted(companion_first.get(int(eid), {}).items()):
                if pname == p.get("project_name"):
                    continue
                if fyr <= eff_year:
                    pre_proj.append(f"{pname}({fyr})")
                else:
                    post_proj.append(f"{pname}({fyr})")
        p["pre_existing_projects"] = pre_proj
        p["post_hoc_projects"] = post_proj
        uscc = str(p.get("credit_code") or "").strip().upper()
        if uscc and eff_date:
            uscc_dates[uscc] = eff_date

    cache_hits: dict[str, dict[str, Any]] = {}
    try:
        import timeline_cache

        resolved_cache = cache_path or timeline_cache.resolve_cache_db_path(db_path)
        cache_hits = timeline_cache.batch_query_at_date(uscc_dates, cache_path=resolved_cache)
    except Exception:
        cache_hits = {}

    for p in deduped:
        uscc = str(p.get("credit_code") or "").strip().upper()
        hit = cache_hits.get(uscc)
        if hit and hit.get("cache_hit"):
            p["timeline_cache"] = hit

    res: dict[str, Any] = {
        "raw_count": len(raw),
        "deduped_count": len(deduped),
        "peers": deduped,
    }

    if benchmark:
        warnings: list[str] = []
        cohorts_map: dict[tuple[Any, bool], list[dict[str, Any]]] = {}
        for p in deduped:
            key = (p.get("recognition_year"), bool(p.get("is_review")))
            cohorts_map.setdefault(key, []).append(p)
        if len(cohorts_map) > 1:
            warnings.append(
                f"检索结果跨越 {len(cohorts_map)} 个不同年度/类别批次，已自动按 (recognition_year, is_review) 拆组统计；严禁跨届或混同复核直接求中位数"
            )
        cohorts_out: list[dict[str, Any]] = []
        for (ryear, is_rev), items in sorted(cohorts_map.items(), key=lambda kv: (kv[0][0] or 0, kv[0][1]), reverse=True):
            n = len(items)
            ages = [x["age_at_apply"] for x in items if x.get("age_at_apply") is not None]
            pre_counts: dict[str, int] = {}
            post_counts: dict[str, int] = {}
            inv_at_t: list[float] = []
            inv_curr: list[float] = []
            cached_pat_n = 0
            pending_usccs: list[dict[str, str]] = []
            for x in items:
                for tag in x.get("pre_existing_projects", []):
                    base = tag.split("(")[0]
                    pre_counts[base] = pre_counts.get(base, 0) + 1
                for tag in x.get("post_hoc_projects", []):
                    base = tag.split("(")[0]
                    post_counts[base] = post_counts.get(base, 0) + 1
                tc = x.get("timeline_cache") or {}
                if tc.get("patent_cache_hit") and tc.get("valid_granted_inv_at_t") is not None:
                    cached_pat_n += 1
                    inv_at_t.append(float(tc["valid_granted_inv_at_t"]))
                    if tc.get("current_granted_inv") is not None:
                        inv_curr.append(float(tc["current_granted_inv"]))
                else:
                    u = str(x.get("credit_code") or "").strip().upper()
                    if u and len(pending_usccs) < 15:
                        pending_usccs.append({"uscc": u, "name": str(x.get("enterprise_name") or ""), "apply_date": str(x.get("apply_date") or "")})

            inflation_pct = None
            if inv_at_t and inv_curr and sum(inv_at_t) > 0:
                inflation_pct = round(100.0 * (sum(inv_curr) - sum(inv_at_t)) / sum(inv_at_t), 1)

            cohorts_out.append({
                "recognition_year": ryear,
                "category": "review" if is_rev else "new_recognition",
                "count": n,
                "age_at_apply": _quantiles_summary(ages),
                "pre_existing_project_rates_pct": {k: round(100.0 * v / n, 1) for k, v in sorted(pre_counts.items(), key=lambda kv: -kv[1])},
                "post_hoc_project_rates_pct": {k: round(100.0 * v / n, 1) for k, v in sorted(post_counts.items(), key=lambda kv: -kv[1])},
                "timeline_cache_patents": {
                    "cached_count": cached_pat_n,
                    "coverage_pct": round(100.0 * cached_pat_n / n, 1) if n else 0.0,
                    "valid_granted_inv_at_apply": _quantiles_summary(inv_at_t),
                    "current_granted_inv": _quantiles_summary(inv_curr),
                    "post_hoc_inflation_pct": inflation_pct,
                },
                "pending_cache_sample": pending_usccs,
            })

        res["benchmark_summary"] = {
            "cohort_count": len(cohorts_out),
            "cohorts": cohorts_out,
            "warnings": warnings,
        }
    return res


def main() -> int:
    parser = argparse.ArgumentParser(description="本地只读知识库洁净检索与企业查询 CLI（无 MCP 依赖）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ent = sub.add_parser("enterprise", help="查询企业档案、财务、冲突与去重认定")
    p_ent.add_argument("name")

    p_rag = sub.add_parser("rag", help="洁净检索本地 rag-query.sh（防假阳性/去副本/隐私过滤）")
    p_rag.add_argument("query")
    p_rag.add_argument("--limit", type=int, default=6)
    p_rag.add_argument("--category", default="")

    p_peer = sub.add_parser("peers", help="查询去重可比同行名单")
    p_peer.add_argument("--project", required=True)
    p_peer.add_argument("--region", default="")
    p_peer.add_argument("--industry", default="")
    p_peer.add_argument("--limit", type=int, default=15)

    p_reg = sub.add_parser("region", help="解析省市区县政策层级")
    p_reg.add_argument("text")

    args = parser.parse_args()
    if args.cmd == "enterprise":
        print(json.dumps(query_enterprise(args.name), ensure_ascii=False, indent=2))
    elif args.cmd == "rag":
        print(json.dumps(search_local_rag(args.query, args.limit, args.category), ensure_ascii=False, indent=2))
    elif args.cmd == "peers":
        print(json.dumps(query_peers(args.project, args.region, args.industry, args.limit), ensure_ascii=False, indent=2))
    elif args.cmd == "region":
        print(json.dumps(resolve_region_scope(args.text), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
