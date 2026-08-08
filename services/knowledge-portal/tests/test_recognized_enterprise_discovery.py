from __future__ import annotations

import sqlite3

from app.recognized_enterprise_discovery import (
    build_recognition_query_plan,
    discover_recognized_enterprises,
    recognition_search,
)


def test_three_first_subject_discovery_separates_product_and_recognition_evidence():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE three_first_project_awards(
            id INTEGER PRIMARY KEY,
            project_id TEXT NOT NULL,
            project_name TEXT NOT NULL,
            year INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            recognition_tier TEXT NOT NULL,
            product_category TEXT NOT NULL,
            list_status TEXT NOT NULL,
            source_policy_id TEXT NOT NULL,
            source_index_id TEXT NOT NULL,
            enterprise_name TEXT NOT NULL,
            province TEXT NOT NULL,
            city TEXT NOT NULL,
            county TEXT NOT NULL,
            industry TEXT NOT NULL,
            source_title TEXT NOT NULL,
            source_url TEXT NOT NULL,
            confidence TEXT NOT NULL,
            source_tier TEXT NOT NULL,
            evidence_semantics TEXT NOT NULL,
            product_name_status TEXT NOT NULL,
            user_action TEXT NOT NULL
        );
        INSERT INTO three_first_project_awards VALUES(
            1,'first-software-version','浙江省首版次软件产品',2025,
            '智能配电监控软件V1.0','省级','工业软件','正式认定','p1','i1',
            '甲配电设备有限公司','浙江省','杭州市','余杭区','配电设备',
            '2025年浙江省首版次软件产品名单','https://example.gov.cn/list',
            'verified','official','annual_list_row','verified',''
        );
        """
    )
    result = discover_recognized_enterprises(
        connection,
        projects=["首版次"],
        subject_terms=["智能配电", "配电设备"],
        regions=["浙江省"],
    )
    assert len(result["verified_matches"]) == 1
    match = result["verified_matches"][0]
    assert match["subject_evidence"]["product_name"] == "智能配电监控软件V1.0"
    assert match["recognition_fact"]["enterprise_name"] == "甲配电设备有限公司"
    assert result["pending_candidates"] == []
    assert result["coverage_ledger"]["is_complete"] is False


def test_discovery_rejects_unknown_project_instead_of_guessing():
    connection = sqlite3.connect(":memory:")
    try:
        discover_recognized_enterprises(
            connection,
            projects=["不存在的项目"],
            subject_terms=["湿巾"],
        )
    except ValueError as error:
        assert "暂不支持的认定项目" in str(error)
    else:
        raise AssertionError("未知项目必须显式拒绝")


def test_common_national_small_giant_project_aliases_are_supported():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE national_small_giant_master(
            id INTEGER PRIMARY KEY,
            enterprise_name TEXT,normalized_name TEXT,unified_social_credit_code TEXT,qice_eid TEXT,
            region TEXT,city TEXT,county TEXT,recognition_year INTEGER,batch TEXT,status TEXT,
            official_url TEXT,official_url_role TEXT,official_fragment_key TEXT,verification_status TEXT,
            sequence_no TEXT,platform_year_raw TEXT,former_names_json TEXT,
            source_documents_json TEXT,source_paths_json TEXT
        )
        """
    )
    for alias in (
        "国家专精特新小巨人企业",
        "国家级专精特新小巨人",
        "国家级专精特新“小巨人”企业",
        "国家级小巨人",
    ):
        result = recognition_search(
            connection,
            query="湿巾主题企业反查",
            projects=[alias],
            subject_terms=["湿巾"],
        )
        assert result["route_to"] == "recognition_reverse_lookup"
        assert result["query_plan"]["projects"] == [alias]


def test_recognition_query_plan_parses_gold_queries_and_keeps_all_dimensions():
    plan = build_recognition_query_plan(
        "查询浙江和宁波2024年、2025年做配电柜的首台套和首版次企业"
    )
    assert plan["intent"] == "recognition_reverse_lookup"
    assert plan["projects"] == ["首台套", "首版次"]
    assert plan["subjects"] == ["配电柜"]
    assert plan["regions"] == ["浙江省", "宁波市"]
    assert plan["years"] == [2024, 2025]
    assert plan["clarification"] == ""

    wet_wipes = build_recognition_query_plan("有没有做湿巾的企业报下来小巨人")
    assert wet_wipes["projects"] == ["小巨人"]
    assert wet_wipes["subjects"] == ["湿巾"]
    assert "卫生湿巾" in wet_wipes["exact_terms"]
    assert "无纺布卫生用品" in wet_wipes["related_terms"]
    assert wet_wipes["clarification"] == ""


def test_recognition_search_routes_policy_feasibility_and_writing_away():
    connection = sqlite3.connect(":memory:")
    for query, route in (
        ("小巨人条件是什么", "policy_search"),
        ("某企业能不能报小巨人", "enterprise_lifecycle_decision"),
        ("帮我写申报书", "application-writing"),
    ):
        result = recognition_search(connection, query=query)
        assert result["route_to"] == route
        assert result["exact_results"] == []


def test_three_first_recognition_search_requires_region_then_returns_exact_result():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE three_first_project_awards(
            id INTEGER PRIMARY KEY,
            project_id TEXT NOT NULL,
            project_name TEXT NOT NULL,
            year INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            recognition_tier TEXT NOT NULL,
            product_category TEXT NOT NULL,
            list_status TEXT NOT NULL,
            source_policy_id TEXT NOT NULL,
            source_index_id TEXT NOT NULL,
            enterprise_name TEXT NOT NULL,
            province TEXT NOT NULL,
            city TEXT NOT NULL,
            county TEXT NOT NULL,
            industry TEXT NOT NULL,
            source_title TEXT NOT NULL,
            source_url TEXT NOT NULL,
            confidence TEXT NOT NULL,
            source_tier TEXT NOT NULL,
            evidence_semantics TEXT NOT NULL,
            product_name_status TEXT NOT NULL,
            user_action TEXT NOT NULL
        );
        INSERT INTO three_first_project_awards VALUES(
            1,'first-software-version','浙江省首版次软件产品',2025,
            '智能配电监控软件V1.0','省级','工业软件','正式认定','p1','i1',
            '甲配电设备有限公司','浙江省','杭州市','余杭区','配电设备',
            '2025年浙江省首版次软件产品名单','https://example.gov.cn/list',
            'verified','official','annual_list_row','verified',''
        );
        """
    )
    clarification = recognition_search(
        connection,
        query="查询下做配电柜的首版次企业",
    )
    assert clarification["route_to"] == "clarification"

    result = recognition_search(
        connection,
        query="查询浙江做配电柜的首版次企业",
    )
    assert result["route_to"] == "recognition_reverse_lookup"
    assert len(result["exact_results"]) == 1
    assert result["exact_results"][0]["recognition_fact"]["enterprise_name"] == "甲配电设备有限公司"
    assert result["coverage"]["is_complete"] is False
