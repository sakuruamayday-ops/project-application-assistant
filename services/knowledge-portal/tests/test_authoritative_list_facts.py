from __future__ import annotations

import sqlite3

from app.authoritative_list_facts import query_authoritative_list_facts


def memory_database() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    return connection


def test_national_small_giant_reports_total_source_tiers_and_complete_pagination():
    connection = memory_database()
    connection.executescript(
        """
        CREATE TABLE national_small_giant_master(
            id INTEGER PRIMARY KEY,
            enterprise_name TEXT,normalized_name TEXT,unified_social_credit_code TEXT,qice_eid TEXT,
            region TEXT,city TEXT,county TEXT,recognition_year INTEGER,batch TEXT,status TEXT,
            official_url TEXT,official_url_role TEXT,official_fragment_key TEXT,verification_status TEXT,
            sequence_no TEXT,platform_year_raw TEXT,former_names_json TEXT,
            source_documents_json TEXT,source_paths_json TEXT
        );
        """
    )
    rows = [
        (1, "杭州甲有限公司", "official_local_fragment_match", "[101]", '["官方名单.pdf"]'),
        (2, "杭州乙有限公司", "official_local_fragment_match", "[101]", '["官方名单.pdf"]'),
        (3, "杭州丙有限公司", "dynamic_candidate_pending_official_fragment", "[]", "[]"),
    ]
    connection.executemany(
        """
        INSERT INTO national_small_giant_master VALUES(
            ?,?,'','','','浙江省','杭州市','余杭区',2024,'第六批','认定',
            'https://example.gov.cn/list','official_batch_notice','',?,'','2024年','[]',?,?
        )
        """,
        rows,
    )
    first = query_authoritative_list_facts(
        connection,
        list_type="national_small_giant",
        year=2024,
        batch="第六批",
        region="杭州市",
        limit=2,
    )
    second = query_authoritative_list_facts(
        connection,
        list_type="national_small_giant",
        year=2024,
        batch="第六批",
        region="杭州市",
        offset=2,
        limit=2,
    )
    assert first["total"] == 3
    assert first["summary"] == {
        "matched_count": 3,
        "official_match_count": 2,
        "verified_count": 2,
        "pending_verification_count": 1,
        "excluded_count": 0,
        "source_tier_counts": {"licensed_platform_pending": 1, "official": 2},
    }
    assert first["pagination"]["is_truncated"] is True
    assert first["pagination"]["next_offset"] == 2
    assert second["pagination"]["has_more"] is False
    assert len(second["results"]) == 1
    assert {item["fact_id"] for item in first["results"]}.isdisjoint(
        {item["fact_id"] for item in second["results"]}
    )


def test_provincial_specialized_sme_uses_reconciliation_and_city_evidence_only():
    connection = memory_database()
    connection.executescript(
        """
        CREATE TABLE documents(id INTEGER PRIMARY KEY,title TEXT,source TEXT);
        CREATE TABLE public_list_entities(
            id INTEGER PRIMARY KEY,document_id INTEGER,enterprise_name TEXT,region TEXT
        );
        CREATE TABLE list_coverage_evidence(
            id INTEGER PRIMARY KEY,document_id INTEGER,title TEXT,source TEXT,region TEXT,year INTEGER,
            project_scope TEXT,administrative_level TEXT,evidence_type TEXT,confidence TEXT,
            entity_count INTEGER,exclusion_reason TEXT
        );
        CREATE TABLE canonical_list_sources(
            region TEXT,year INTEGER,project_scope TEXT,document_id INTEGER,evidence_type TEXT,
            title TEXT,source TEXT,rule_version TEXT
        );
        CREATE TABLE list_entity_reconciliation(
            id INTEGER PRIMARY KEY,region TEXT,year INTEGER,project_scope TEXT,enterprise_name TEXT,
            normalized_enterprise_name TEXT,result_status TEXT,effective_recognition INTEGER,
            resolution_reason TEXT,final_document_ids TEXT,public_document_ids TEXT,
            final_sources TEXT,public_sources TEXT,rule_version TEXT
        );
        INSERT INTO documents VALUES
            (10,'杭州省专官方名单','杭州省专官方名单.xlsx'),
            (11,'宁波省专官方名单','宁波省专官方名单.xlsx');
        INSERT INTO list_coverage_evidence VALUES
            (1,10,'杭州省专官方名单','杭州省专官方名单.xlsx','浙江省',2024,
             'provincial_specialized_sme','省级','final','high',2,''),
            (2,11,'宁波省专官方名单','宁波省专官方名单.xlsx','浙江省',2024,
             'provincial_specialized_sme','省级','final','high',1,'');
        INSERT INTO public_list_entities VALUES
            (1,10,'杭州甲有限公司','浙江省|杭州市'),
            (2,10,'杭州乙有限公司','浙江省|杭州市'),
            (3,11,'宁波甲有限公司','浙江省|宁波市');
        INSERT INTO canonical_list_sources VALUES
            ('浙江省',2024,'provincial_specialized_sme',10,'final',
             '浙江省专精特新认定名单','浙江省专精特新认定名单.xlsx','final-recognition-first-v1');
        INSERT INTO list_entity_reconciliation VALUES
            (1,'浙江省',2024,'provincial_specialized_sme','杭州甲有限公司','杭州甲有限公司',
             'recognized_final',1,'最终认定','10','','杭州省专官方名单.xlsx','',
             'final-recognition-first-v1'),
            (2,'浙江省',2024,'provincial_specialized_sme','杭州乙有限公司','杭州乙有限公司',
             'public_only_unresolved',0,'仅公示','','10','','杭州省专官方名单.xlsx',
             'final-recognition-first-v1'),
            (3,'浙江省',2024,'provincial_specialized_sme','宁波甲有限公司','宁波甲有限公司',
             'final_only',1,'最终认定','11','','宁波省专官方名单.xlsx','',
             'final-recognition-first-v1'),
            (4,'浙江省',2024,'provincial_specialized_sme','杭州（甲）有限公司','杭州（甲）有限公司',
             'public_only_unresolved',0,'历史归一化重复','','10','','杭州省专官方名单.xlsx',
             'final-recognition-first-v1');
        """
    )
    result = query_authoritative_list_facts(
        connection,
        list_type="provincial_specialized_sme",
        year=2024,
        region="杭州市",
        limit=10,
    )
    assert result["total"] == 2
    assert result["summary"]["official_match_count"] == 1
    assert result["summary"]["pending_verification_count"] == 1
    assert result["summary"]["source_tier_counts"] == {
        "official_final": 1,
        "official_publicity": 1,
    }
    assert {item["enterprise_name"] for item in result["results"]} == {
        "杭州甲有限公司",
        "杭州乙有限公司",
    }
    assert all(item["document_id"] == 10 for item in result["results"])
    assert all(item["source_scope"] == "enterprise_geography_match" for item in result["results"])


def test_three_first_reports_strict_official_matches_and_pending_records():
    connection = memory_database()
    connection.executescript(
        """
        CREATE TABLE three_first_project_awards(
            id INTEGER PRIMARY KEY,enterprise_key TEXT,eid TEXT,enterprise_name TEXT,
            enterprise_aliases TEXT,province TEXT,city TEXT,county TEXT,industry TEXT,
            project_id TEXT,project_name TEXT,year INTEGER,product_name TEXT,recognition_tier TEXT,
            product_category TEXT,list_status TEXT,source_policy_id TEXT,source_index_id TEXT,
            source_title TEXT,source_url TEXT,source_tier TEXT,evidence_semantics TEXT,
            confidence TEXT,product_name_status TEXT,user_action TEXT
        );
        """
    )
    rows = [
        (1, "企业甲", "产品甲", "official", "product_level", "final_recognition"),
        (2, "企业乙", "产品乙", "official", "product_level", "final_recognition"),
        (3, "企业丙", "", "licensed_platform", "discovery_only", "platform_history"),
    ]
    connection.executemany(
        """
        INSERT INTO three_first_project_awards VALUES(
            ?,'key','eid',?,'[]','浙江省','杭州市','余杭区','软件','15',
            '浙江省首版次软件产品',2025,?,'国内首版次软件','工业软件',?,
            '','','官方来源','https://example.gov.cn/three-first',?,'annual_list_row',?,
            'verified',''
        )
        """,
        [(row[0], row[1], row[2], row[5], row[3], row[4]) for row in rows],
    )
    first = query_authoritative_list_facts(
        connection,
        list_type="three_first",
        project_name="浙江省首版次软件产品",
        year=2025,
        region="杭州市",
        limit=2,
    )
    second = query_authoritative_list_facts(
        connection,
        list_type="three_first",
        project_name="浙江省首版次软件产品",
        year=2025,
        region="杭州市",
        offset=2,
        limit=2,
    )
    assert first["total"] == 3
    assert first["summary"]["official_match_count"] == 2
    assert first["summary"]["pending_verification_count"] == 1
    assert first["summary"]["source_tier_counts"] == {
        "licensed_platform": 1,
        "official": 2,
    }
    assert first["pagination"]["next_offset"] == 2
    assert second["pagination"]["has_more"] is False
    assert len(second["results"]) == 1
