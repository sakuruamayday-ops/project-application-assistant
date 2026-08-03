from __future__ import annotations

import sqlite3

from scripts.build_recognition_search_index import build_index
from app.recognized_enterprise_discovery import recognition_search


def test_build_recognition_search_index_backfills_authority_and_subject_evidence():
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE three_first_project_awards(
            id INTEGER PRIMARY KEY,
            enterprise_name TEXT NOT NULL,
            province TEXT NOT NULL,
            city TEXT NOT NULL,
            county TEXT NOT NULL,
            industry TEXT NOT NULL,
            project_id TEXT NOT NULL,
            project_name TEXT NOT NULL,
            year INTEGER,
            product_name TEXT NOT NULL,
            recognition_tier TEXT NOT NULL,
            product_category TEXT NOT NULL,
            list_status TEXT NOT NULL,
            source_title TEXT NOT NULL,
            source_url TEXT NOT NULL,
            source_tier TEXT NOT NULL,
            confidence TEXT NOT NULL
        );
        INSERT INTO three_first_project_awards VALUES(
            1,'甲配电设备有限公司','浙江省','杭州市','余杭区','配电设备',
            'first-software-version','浙江省首版次软件产品',2025,
            '智能配电监控软件V1.0','省级','工业软件','正式认定',
            '2025年浙江省首版次软件产品名单','https://example.gov.cn/list',
            'official','verified'
        );
        CREATE TABLE national_small_giant_master(
            id INTEGER PRIMARY KEY,
            enterprise_name TEXT NOT NULL,
            region TEXT NOT NULL,
            city TEXT NOT NULL,
            county TEXT NOT NULL,
            industry_name TEXT NOT NULL,
            recognition_year INTEGER,
            batch TEXT NOT NULL,
            status TEXT NOT NULL,
            official_url TEXT NOT NULL,
            official_url_role TEXT NOT NULL,
            verification_status TEXT NOT NULL
        );
        INSERT INTO national_small_giant_master VALUES(
            1,'乙湿巾有限公司','浙江省','杭州市','临平区','汽车零部件及配件制造',2024,'第六批',
            '正式认定','https://example.gov.cn/giant','official_attachment',
            'official_local_fragment_match'
        );
        CREATE TABLE documents(
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            source TEXT NOT NULL
        );
        CREATE TABLE enterprise_mentions(
            id INTEGER PRIMARY KEY,
            document_id INTEGER NOT NULL,
            enterprise_name TEXT NOT NULL,
            context TEXT NOT NULL
        );
        INSERT INTO documents VALUES(10,'企业生产卫生湿巾介绍','https://example.gov.cn/company');
        INSERT INTO enterprise_mentions VALUES(20,10,'乙湿巾有限公司','主营卫生湿巾和消毒湿巾');
        """
    )
    counts = build_index(connection)
    assert counts["subject_taxonomy"] >= 4
    assert counts["recognition_records"] == 2
    assert counts["enterprise_subject_evidence"] >= 5
    joined = connection.execute(
        """
        SELECT rr.enterprise_name_at_recognition,ese.canonical_subject,ese.match_level
        FROM recognition_records rr
        JOIN enterprise_subject_evidence ese ON ese.enterprise_id=rr.enterprise_id
        WHERE rr.project_id='national_small_giant'
        """
    ).fetchall()
    assert ("乙湿巾有限公司", "湿巾", "exact") in [tuple(row) for row in joined]
    result = recognition_search(
        connection,
        query="有没有做湿巾的企业报下来小巨人",
    )
    assert result["route_to"] == "recognition_reverse_lookup"
    assert [
        item["recognition_fact"]["enterprise_name"]
        for item in result["exact_results"]
    ] == ["乙湿巾有限公司"]
    assert result["related_results"] == []

    industry_result = recognition_search(
        connection,
        query="有哪些做汽车零部件的小巨人企业",
    )
    assert industry_result["query_plan"]["subjects"] == ["汽车零部件"]
    assert [
        item["recognition_fact"]["enterprise_name"]
        for item in industry_result["exact_results"]
    ] == ["乙湿巾有限公司"]
