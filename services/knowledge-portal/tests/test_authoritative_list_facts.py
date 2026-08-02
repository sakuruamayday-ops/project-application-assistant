from __future__ import annotations

import sqlite3

from app.authoritative_list_facts import _provincial_coverage, query_authoritative_list_facts


def memory_database() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    return connection


def test_provincial_coverage_uses_complete_regional_group_for_province_query():
    connection = memory_database()
    connection.executescript(
        """
        CREATE TABLE enterprise_regional_coverage_audits(
            coverage_group_id TEXT PRIMARY KEY,project_name TEXT,event_year INTEGER,
            event_type TEXT,scope TEXT,expected_region_count INTEGER,
            covered_region_count INTEGER,entity_count INTEGER,complete INTEGER,
            strict INTEGER,expected_regions_json TEXT,covered_regions_json TEXT,
            missing_regions_json TEXT,count_mismatch_regions_json TEXT
        );
        INSERT INTO enterprise_regional_coverage_audits VALUES(
            'zhejiang-2026-review','浙江省专精特新中小企业',2026,
            'review_publicity','浙江省11个设区市',11,11,1541,1,1,
            '[]','[]','[]','[]'
        );
        """
    )

    coverage = _provincial_coverage(
        connection,
        year=2026,
        batch="",
        region="浙江省",
        event_type="review_publicity",
    )

    assert coverage["completeness_claim_allowed"] is True
    assert coverage["scope"] == "configured_regional_coverage_group"
    assert coverage["cells"][0]["entity_count"] == 1541


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


def test_national_small_giant_year_defaults_to_new_recognition_plus_review_publication():
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
        CREATE TABLE enterprise_recognition_events(
            id INTEGER PRIMARY KEY,event_uid TEXT,identity_key TEXT,enterprise_name_at_event TEXT,
            normalized_name TEXT,project_name TEXT,subject_type TEXT,subject_key TEXT,
            subject_name TEXT,product_name TEXT,event_year INTEGER,recognition_year INTEGER,
            cohort_year INTEGER,event_type TEXT,event_scope TEXT,evidence_status TEXT,
            lifecycle_rule_id TEXT,cycle_type TEXT,validity_years INTEGER,batch TEXT,status TEXT,
            recognition_province TEXT,recognition_city TEXT,recognition_county TEXT,source_title TEXT,
            source_paths_json TEXT,source_urls_json TEXT,sequence_numbers_json TEXT,source_kinds_json TEXT
        );
        CREATE TABLE enterprise_lifecycle_source_audits(
            source_id TEXT PRIMARY KEY,document_id INTEGER,document_title TEXT,project_name TEXT,
            event_type TEXT,event_year INTEGER,batch TEXT,city TEXT,covered_cities_json TEXT,
            expected_count INTEGER,announced_count INTEGER,actual_count INTEGER,count_aligned INTEGER,
            completeness_claim_allowed INTEGER,known_blank_sequences_json TEXT,source_path TEXT,
            official_url TEXT,source_fingerprint TEXT
        );
        INSERT INTO national_small_giant_master VALUES(
            1,'杭州新认定有限公司','杭州新认定有限公司','','','浙江省','杭州市','余杭区',
            2023,'第五批','认定','','','','dynamic_candidate_pending_official_fragment','',
            '2023年','[]','[]','[]'
        );
        INSERT INTO enterprise_recognition_events VALUES
            (1,'review-1','id-1','杭州复核有限公司','杭州复核有限公司','国家专精特新“小巨人”企业',
             'enterprise','enterprise','杭州复核有限公司','',2023,2023,2020,'review_publicity',
             'qualification','official_publicity_mirror','','',3,'第二批复核','复核通过公示',
             '浙江省','杭州市','','复核公示','[]','[]','["1"]','["lifecycle_manifest"]'),
            (2,'changed-1','id-2','杭州更名有限公司','杭州更名有限公司','国家专精特新“小巨人”企业',
             'enterprise','enterprise','杭州更名有限公司','',2023,2023,2020,'changed',
             'qualification','official_notice','','',3,'第二批','更名',
             '浙江省','杭州市','','更名公告','[]','[]','["1"]','["lifecycle_manifest"]');
        INSERT INTO enterprise_lifecycle_source_audits VALUES(
            'review-source',0,'复核公示','国家专精特新“小巨人”企业','review_publicity',
            2023,'第二批复核','杭州市','[]',1,1,1,1,1,'[]','','','sha'
        );
        """
    )
    result = query_authoritative_list_facts(
        connection,
        list_type="national_small_giant",
        year=2023,
        region="杭州市",
        limit=10,
    )
    assert result["total"] == 2
    assert {item["event_type"] for item in result["results"]} == {
        "recognition",
        "review_publicity",
    }
    assert "杭州更名有限公司" not in {
        item["enterprise_name"] for item in result["results"]
    }
    assert result["filters"]["event_type"] == "annual_published"


def test_national_small_giant_direct_city_publication_overrides_current_geography():
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
        CREATE TABLE enterprise_recognition_events(
            id INTEGER PRIMARY KEY,event_uid TEXT,identity_key TEXT,enterprise_name_at_event TEXT,
            normalized_name TEXT,project_name TEXT,subject_type TEXT,subject_key TEXT,
            subject_name TEXT,product_name TEXT,event_year INTEGER,recognition_year INTEGER,
            cohort_year INTEGER,event_type TEXT,event_scope TEXT,evidence_status TEXT,
            lifecycle_rule_id TEXT,cycle_type TEXT,validity_years INTEGER,batch TEXT,status TEXT,
            recognition_province TEXT,recognition_city TEXT,recognition_county TEXT,source_title TEXT,
            source_paths_json TEXT,source_urls_json TEXT,sequence_numbers_json TEXT,source_kinds_json TEXT
        );
        CREATE TABLE enterprise_lifecycle_source_audits(
            source_id TEXT PRIMARY KEY,document_id INTEGER,document_title TEXT,project_name TEXT,
            event_type TEXT,event_year INTEGER,batch TEXT,city TEXT,covered_cities_json TEXT,
            expected_count INTEGER,announced_count INTEGER,actual_count INTEGER,count_aligned INTEGER,
            completeness_claim_allowed INTEGER,known_blank_sequences_json TEXT,source_path TEXT,
            official_url TEXT,source_fingerprint TEXT
        );
        INSERT INTO national_small_giant_master VALUES
            (1,'当年杭州甲有限公司','当年杭州甲有限公司','','','浙江省','杭州市','余杭区',
             2023,'第五批','认定','','','','dynamic_candidate_pending_official_fragment','',
             '2023年','[]','[]','[]'),
            (2,'后来迁入杭州有限公司','后来迁入杭州有限公司','','','浙江省','杭州市','萧山区',
             2023,'第五批','认定','','','','dynamic_candidate_pending_official_fragment','',
             '2023年','[]','[]','[]');
        INSERT INTO enterprise_recognition_events VALUES
            (1,'rec-1','id-1','当年杭州甲有限公司','当年杭州甲有限公司','国家专精特新“小巨人”企业',
             'enterprise','enterprise','当年杭州甲有限公司','',2023,2023,2023,'recognition_publicity',
             'qualification','official_publicity','','',3,'第五批','公示名单',
             '浙江省','杭州市','','第五批杭州公示','[]','[]','["1"]','["lifecycle_manifest"]');
        INSERT INTO enterprise_lifecycle_source_audits VALUES(
            'recognition-source',0,'第五批杭州公示','国家专精特新“小巨人”企业',
            'recognition_publicity',2023,'第五批','杭州市','[]',1,1,1,1,1,
            '[]','','','sha'
        );
        """
    )
    result = query_authoritative_list_facts(
        connection,
        list_type="national_small_giant",
        year=2023,
        region="杭州市",
        limit=10,
    )
    assert result["total"] == 1
    assert result["results"][0]["enterprise_name"] == "当年杭州甲有限公司"
    assert result["results"][0]["event_type"] == "recognition_publicity"
    assert result["summary"]["verified_count"] == 1
    assert result["coverage"]["completeness_claim_allowed"] is False
    batch_result = query_authoritative_list_facts(
        connection,
        list_type="national_small_giant",
        year=2023,
        batch="第五批",
        region="杭州市",
        limit=10,
    )
    assert batch_result["total"] == 1
    assert batch_result["results"][0]["enterprise_name"] == "当年杭州甲有限公司"
    assert batch_result["coverage"]["completeness_claim_allowed"] is True


def test_provincial_specialized_sme_uses_event_identity_and_explicit_event_type():
    connection = memory_database()
    connection.executescript(
        """
        CREATE TABLE enterprise_recognition_events(
            id INTEGER PRIMARY KEY,event_uid TEXT,identity_key TEXT,enterprise_name_at_event TEXT,
            normalized_name TEXT,project_name TEXT,subject_type TEXT,subject_key TEXT,
            subject_name TEXT,product_name TEXT,event_year INTEGER,recognition_year INTEGER,
            cohort_year INTEGER,event_type TEXT,event_scope TEXT,evidence_status TEXT,
            lifecycle_rule_id TEXT,cycle_type TEXT,validity_years INTEGER,batch TEXT,status TEXT,
            recognition_province TEXT,recognition_city TEXT,recognition_county TEXT,source_title TEXT,
            source_paths_json TEXT,source_urls_json TEXT,sequence_numbers_json TEXT,source_kinds_json TEXT
        );
        CREATE TABLE enterprise_lifecycle_source_audits(
            source_id TEXT PRIMARY KEY,document_id INTEGER,document_title TEXT,project_name TEXT,
            event_type TEXT,event_year INTEGER,batch TEXT,city TEXT,covered_cities_json TEXT,
            expected_count INTEGER,announced_count INTEGER,actual_count INTEGER,count_aligned INTEGER,
            completeness_claim_allowed INTEGER,known_blank_sequences_json TEXT,source_path TEXT,
            official_url TEXT,source_fingerprint TEXT
        );
        INSERT INTO enterprise_recognition_events VALUES
            (1,'evt-1','id-1','杭州甲有限公司','杭州甲有限公司','浙江省专精特新中小企业',
             'enterprise','enterprise','杭州甲有限公司','',2024,2024,2024,'recognition',
             'qualification','official_final_list','','',3,'第一批','认定','浙江省','杭州市','',
             '正式名单','[\"名单.pdf\"]','[]','[\"1\"]','[\"lifecycle_manifest\"]'),
            (2,'evt-2','id-2','杭州乙有限公司','杭州乙有限公司','浙江省专精特新中小企业',
             'enterprise','enterprise','杭州乙有限公司','',2024,2024,2024,'recognition_publicity',
             'qualification','official_publicity','','',3,'第一批','拟认定','浙江省','杭州市','',
             '公示名单','[\"公示.pdf\"]','[]','[\"2\"]','[\"lifecycle_manifest\"]');
        INSERT INTO enterprise_lifecycle_source_audits VALUES
            ('source-1',10,'正式名单','浙江省专精特新中小企业','recognition',2024,'第一批',
             '杭州市','[]',1,1,1,1,1,'[]','名单.pdf','', 'sha'),
            ('source-province',11,'全省正式名单','浙江省专精特新中小企业','recognition',2024,'第一批',
             '','[]',2,2,2,1,1,'[]','全省名单.pdf','', 'sha2');
        """
    )
    result = query_authoritative_list_facts(
        connection,
        list_type="provincial_specialized_sme",
        year=2024,
        batch="第一批",
        region="杭州市",
        event_type="recognition",
        limit=10,
    )
    assert result["total"] == 1
    assert result["summary"]["official_match_count"] == 1
    assert result["summary"]["source_tier_counts"] == {"official_final": 1}
    assert result["results"][0]["event_uid"] == "evt-1"
    assert result["coverage"]["completeness_claim_allowed"] is True


def test_provincial_year_default_excludes_other_validity_events():
    connection = memory_database()
    connection.executescript(
        """
        CREATE TABLE enterprise_recognition_events(
            id INTEGER PRIMARY KEY,event_uid TEXT,identity_key TEXT,enterprise_name_at_event TEXT,
            normalized_name TEXT,project_name TEXT,subject_type TEXT,subject_key TEXT,
            subject_name TEXT,product_name TEXT,event_year INTEGER,recognition_year INTEGER,
            cohort_year INTEGER,event_type TEXT,event_scope TEXT,evidence_status TEXT,
            lifecycle_rule_id TEXT,cycle_type TEXT,validity_years INTEGER,batch TEXT,status TEXT,
            recognition_province TEXT,recognition_city TEXT,recognition_county TEXT,source_title TEXT,
            source_paths_json TEXT,source_urls_json TEXT,sequence_numbers_json TEXT,source_kinds_json TEXT
        );
        CREATE TABLE enterprise_lifecycle_source_audits(
            source_id TEXT PRIMARY KEY,document_id INTEGER,document_title TEXT,project_name TEXT,
            event_type TEXT,event_year INTEGER,batch TEXT,city TEXT,covered_cities_json TEXT,
            expected_count INTEGER,announced_count INTEGER,actual_count INTEGER,count_aligned INTEGER,
            completeness_claim_allowed INTEGER,known_blank_sequences_json TEXT,source_path TEXT,
            official_url TEXT,source_fingerprint TEXT
        );
        INSERT INTO enterprise_recognition_events VALUES
            (1,'rec-1','id-1','杭州新认定有限公司','杭州新认定有限公司','浙江省专精特新中小企业',
             'enterprise','enterprise','杭州新认定有限公司','',2023,2023,2023,'recognition',
             'qualification','official_final_list','','',3,'第一批','认定','浙江省','杭州市','',
             '正式名单','[]','[]','["1"]','["lifecycle_manifest"]'),
            (2,'review-1','id-2','杭州复核有限公司','杭州复核有限公司','浙江省专精特新中小企业',
             'enterprise','enterprise','杭州复核有限公司','',2023,2023,2020,'review_passed',
             'qualification','official_final_list','','',3,'复核批','复核通过','浙江省','杭州市','',
             '复核名单','[]','[]','["1"]','["lifecycle_manifest"]'),
            (3,'active-1','id-3','杭州往年仍有效有限公司','杭州往年仍有效有限公司','浙江省专精特新中小企业',
             'enterprise','enterprise','杭州往年仍有效有限公司','',2023,2023,2021,'continued_support',
             'support','official_final_list','','',3,'支持批','继续支持','浙江省','杭州市','',
             '支持名单','[]','[]','["1"]','["lifecycle_manifest"]'),
            (4,'revoked-1','id-4','杭州撤销有限公司','杭州撤销有限公司','浙江省专精特新中小企业',
             'enterprise','enterprise','杭州撤销有限公司','',2023,2023,2020,'revoked',
             'qualification','official_final_list','','',3,'撤销批','撤销','浙江省','杭州市','',
             '撤销名单','[]','[]','["1"]','["lifecycle_manifest"]'),
            (5,'generic-1','id-5','未经配置的零散附件企业','未经配置的零散附件企业','浙江省专精特新中小企业',
             'enterprise','enterprise','未经配置的零散附件企业','',2023,2023,2023,'recognition_publicity',
             'qualification','official_publicity','','',3,'第一批','公示','浙江省','杭州市','',
             '零散附件','[]','[]','["1"]','["official_or_archived_list"]');
        """
    )
    result = query_authoritative_list_facts(
        connection,
        list_type="provincial_specialized_sme",
        year=2023,
        region="杭州市",
        limit=10,
    )
    assert result["total"] == 2
    assert {item["event_type"] for item in result["results"]} == {
        "recognition",
        "review_passed",
    }
    assert result["filters"]["event_type"] == "annual_published"


def test_provincial_query_accepts_legacy_event_table_without_subject_type():
    connection = memory_database()
    connection.executescript(
        """
        CREATE TABLE enterprise_recognition_events(
            id INTEGER PRIMARY KEY,event_uid TEXT,identity_key TEXT,
            enterprise_name_at_event TEXT,normalized_name TEXT,project_name TEXT,
            subject_key TEXT,subject_name TEXT,product_name TEXT,event_year INTEGER,
            recognition_year INTEGER,cohort_year INTEGER,event_type TEXT,event_scope TEXT,
            evidence_status TEXT,lifecycle_rule_id TEXT,cycle_type TEXT,
            validity_years INTEGER,batch TEXT,status TEXT,recognition_province TEXT,
            recognition_city TEXT,recognition_county TEXT,source_title TEXT,
            source_paths_json TEXT,source_urls_json TEXT,sequence_numbers_json TEXT,
            source_kinds_json TEXT
        );
        INSERT INTO enterprise_recognition_events VALUES(
            1,'legacy-1','id-1','杭州兼容有限公司','杭州兼容有限公司',
            '浙江省专精特新中小企业','enterprise','杭州兼容有限公司','',
            2026,2026,2026,'recognition','qualification','official_final_list',
            '','',3,'第一批','认定','浙江省','杭州市','','正式名单',
            '[\"名单.pdf\"]','[]','[\"1\"]','[\"lifecycle_manifest\"]'
        );
        """
    )

    result = query_authoritative_list_facts(
        connection,
        list_type="provincial_specialized_sme",
        year=2026,
        region="杭州市",
        event_type="recognition",
        limit=10,
    )

    assert result["total"] == 1
    assert result["results"][0]["enterprise_name"] == "杭州兼容有限公司"


def test_three_first_default_list_excludes_discovery_records():
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
    assert first["total"] == 2
    assert first["summary"]["official_match_count"] == 2
    assert first["summary"]["pending_verification_count"] == 0
    assert first["summary"]["excluded_count"] == 1
    assert first["summary"]["source_tier_counts"] == {"official": 2}
    assert first["coverage"]["completeness_claim_allowed"] is True
    assert first["coverage"]["cells"][0]["discovery_rows_excluded"] == 1
    assert first["coverage"]["cells"][0]["official_scope_complete"] is True
    assert first["results"][0]["industry"] == "软件"
    assert first["pagination"]["next_offset"] is None
    assert second["pagination"]["has_more"] is False
    assert len(second["results"]) == 0
