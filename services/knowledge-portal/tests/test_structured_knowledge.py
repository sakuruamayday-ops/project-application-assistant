import json
import hashlib
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from scripts.build_knowledge_content_index import create_database
from scripts.build_knowledge_content_index import enterprise_mentions
from scripts.build_knowledge_content_index import infer_document_metadata
from scripts.build_document_scopes import rebuild_document_scopes
from scripts.upgrade_structured_knowledge_index import upgrade_database
from scripts.evaluate_structured_knowledge import DEFAULT_GOLD_SET, evaluate, load_cases
from scripts.import_qice_small_giant_dataset import import_dataset
from scripts.build_small_giant_identity_graph import USCC_PATTERN
from scripts.build_small_giant_identity_graph import normalize_name as normalize_identity_name
from scripts.collect_small_giant_official_fragments import allowed as official_fragment_url_allowed
from scripts.build_three_first_benchmark_graph import canonicalize_details
from scripts.build_three_first_benchmark_graph import build_graph as build_three_first_graph
from scripts.build_three_first_benchmark_graph import build_status_timeline
from scripts.build_three_first_benchmark_graph import merge_records as merge_three_first_records
from scripts.build_specialized_sme_coverage_matrix import Evidence
from scripts.build_specialized_sme_coverage_matrix import build_reconciliation
from scripts.build_specialized_sme_coverage_matrix import canonical_evidence
from scripts.build_specialized_sme_coverage_matrix import infer_evidence_type
from scripts.build_specialized_sme_coverage_matrix import infer_mixed_year_roles
from scripts.build_specialized_sme_coverage_matrix import infer_region
from scripts.build_specialized_sme_coverage_matrix import infer_scope
from scripts.build_specialized_sme_coverage_matrix import matrix_status
from scripts.collect_official_specialized_sme_lists import attachment_evidence_type
from scripts.collect_official_specialized_sme_lists import attachment_links
from scripts.collect_official_specialized_sme_lists import evidence_filename
from scripts.verify_structured_knowledge_tables import verify as verify_structured_tables
from scripts.refresh_index_from_oss import (
    REQUIRED_STRUCTURED_TABLES,
    valid_index as valid_cached_index,
)
from scripts.publish_index_to_oss import full_index_due


def test_full_index_policy_skips_recent_weekly_snapshot():
    now = datetime(2026, 7, 26, tzinfo=timezone.utc)
    recent = SimpleNamespace(last_modified=(now - timedelta(days=2)).timestamp())
    stale = SimpleNamespace(last_modified=(now - timedelta(days=8)).timestamp())

    assert not full_index_due("skip", stale, max_age_days=7, now=now)
    assert not full_index_due("weekly", recent, max_age_days=7, now=now)
    assert full_index_due("weekly", stale, max_age_days=7, now=now)
    assert full_index_due("weekly", None, max_age_days=7, now=now)
    assert full_index_due("always", recent, max_age_days=7, now=now)


def test_full_index_build_creates_policy_metadata_and_public_list_entities(tmp_path):
    database_path = tmp_path / "knowledge_content.sqlite3"
    create_database(
        database_path,
        [
            {
                "source_key": "list-one",
                "title": "2025年浙江省第六批专精特新小巨人认定名单",
                "content": "1 | 杭州测试装备有限公司",
                "source": "50_名单与对标/2025年浙江省第六批小巨人名单.md",
                "cloud_path": "50_名单与对标/2025年浙江省第六批小巨人名单.md",
                "document_role": "50_名单与对标",
                "sensitivity": "public",
                "sha256": "list-sha",
                "updated_at": "2025-10-01T00:00:00+00:00",
            },
            {
                "source_key": "policy-one",
                "title": "2025年浙江省专精特新小巨人申报通知",
                "content": "申报企业应当符合专精特新发展方向。",
                "source": "10_政策与通知/2025年浙江省小巨人申报通知.md",
                "cloud_path": "10_政策与通知/2025年浙江省小巨人申报通知.md",
                "document_role": "10_政策与通知",
                "sensitivity": "public",
                "sha256": "policy-sha",
                "updated_at": "2025-06-01T00:00:00+00:00",
            },
            {
                "source_key": "policy-one-pdf",
                "title": "2025年浙江省专精特新小巨人申报通知",
                "content": "申报企业应当符合专精特新发展方向。",
                "source": "10_政策与通知/2025年浙江省小巨人申报通知.pdf",
                "cloud_path": "10_政策与通知/2025年浙江省小巨人申报通知.pdf",
                "document_role": "10_政策与通知",
                "sensitivity": "public",
                "sha256": "policy-pdf-sha",
                "updated_at": "2025-06-01T00:00:00+00:00",
            },
        ],
    )

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        list_document = connection.execute(
            "SELECT * FROM documents WHERE source_key = 'list-one'"
        ).fetchone()
        entity = connection.execute("SELECT * FROM public_list_entities").fetchone()
        policy = connection.execute(
            "SELECT * FROM documents WHERE source_key = 'policy-one'"
        ).fetchone()
    finally:
        connection.close()

    assert list_document["canonical_project_name"] == "国家专精特新“小巨人”企业"
    assert list_document["policy_year"] == 2025
    assert list_document["batch"] == "第六批"
    assert list_document["document_stage"] == "认定名单"
    assert entity["enterprise_name"] == "杭州测试装备有限公司"
    assert entity["canonical_project_name"] == "国家专精特新“小巨人”企业"
    assert entity["confidence"] == "high"
    assert policy["document_stage"] == "申报通知"
    assert policy["validity_status"] == "active_candidate"
    with closing(sqlite3.connect(database_path)) as audit:
        assert audit.execute(
            "SELECT COUNT(*) FROM metadata_match_evidence"
        ).fetchone()[0] >= 16
        assert audit.execute(
            "SELECT COUNT(*) FROM policy_verification_queue"
        ).fetchone()[0] >= 1
        duplicate_cluster = audit.execute(
            """
            SELECT c.id,COUNT(m.id)
            FROM policy_document_clusters c
            JOIN policy_document_cluster_members m ON m.cluster_id=c.id
            GROUP BY c.id HAVING COUNT(m.id)=2
            """
        ).fetchone()
        assert duplicate_cluster is not None
        canonical_rows = audit.execute(
            "SELECT canonical_document_id,duplicate_count FROM canonical_documents ORDER BY canonical_document_id"
        ).fetchall()
        scope_count = audit.execute("SELECT COUNT(*) FROM document_scopes").fetchone()[0]
        virtual_count = audit.execute(
            "SELECT COUNT(*) FROM virtual_catalog_entries"
        ).fetchone()[0]
        assert canonical_rows
        assert scope_count >= 3
        assert virtual_count >= 3


def test_structured_table_gate_rejects_fulltext_only_database(tmp_path):
    database_path = tmp_path / "fulltext-only.sqlite3"
    create_database(
        database_path,
        [
            {
                "source_key": "policy-only",
                "title": "测试政策",
                "content": "测试内容",
                "source": "10_政策与目录/测试政策.md",
                "cloud_path": "10_政策与目录/测试政策.md",
                "document_role": "10_政策与目录",
                "sensitivity": "public",
                "sha256": "policy-only-sha",
                "updated_at": "2026-07-24T00:00:00+00:00",
            }
        ],
    )

    try:
        verify_structured_tables(database_path)
    except RuntimeError as error:
        assert "缺少结构化专表" in str(error)
    else:
        raise AssertionError("全文索引缺少派生专表时应阻止发布")


def test_oss_cache_rejects_index_without_structured_tables(tmp_path):
    database_path = tmp_path / "oss-cache.sqlite3"
    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute("CREATE TABLE documents(id INTEGER PRIMARY KEY)")
        connection.commit()
    assert valid_cached_index(database_path) is False

    with closing(sqlite3.connect(database_path)) as connection:
        for table, minimum in REQUIRED_STRUCTURED_TABLES.items():
            connection.execute(f'CREATE TABLE "{table}"(id INTEGER PRIMARY KEY)')
            connection.executemany(
                f'INSERT INTO "{table}"(id) VALUES(?)',
                [(index,) for index in range(1, minimum + 1)],
            )
        connection.commit()
    assert valid_cached_index(database_path) is True
    assert valid_cached_index(database_path, quick_check=False) is True


def test_list_entity_extraction_keeps_factory_research_institute_and_qualifier():
    mentions = enterprise_mentions(
        "368.0 | 杭州华润传感器厂\n"
        "403.0 | 杭州西湖电子研究所\n"
        "605.0 | 中汽商用汽车有限公司（杭州）"
    )
    assert [(item[0], item[1]) for item in mentions] == [
        ("杭州华润传感器厂", "368"),
        ("杭州西湖电子研究所", "403"),
        ("中汽商用汽车有限公司（杭州）", "605"),
    ]


def test_document_scopes_deduplicate_and_propagate_province_to_cities(tmp_path):
    database_path = tmp_path / "document-scopes.sqlite3"
    create_database(
        database_path,
        [
            {
                "source_key": "zhejiang-policy-hangzhou-copy",
                "title": "2025年浙江省首版次软件产品申报通知",
                "content": "浙江省首版次软件产品申报要求。",
                "source": "10_政策与目录/政策数据库/企策顾问/杭州市/2025年浙江省首版次软件产品申报通知.pdf",
                "cloud_path": "10_政策与目录/政策数据库/企策顾问/杭州市/2025年浙江省首版次软件产品申报通知.pdf",
                "document_role": "10_政策与目录",
                "sensitivity": "public",
                "sha256": "same-policy-sha",
                "updated_at": "2025-06-01T00:00:00+00:00",
            },
            {
                "source_key": "zhejiang-policy-ningbo-copy",
                "title": "2025年浙江省首版次软件产品申报通知",
                "content": "浙江省首版次软件产品申报要求。",
                "source": "10_政策与目录/政策数据库/企策顾问/宁波市/2025年浙江省首版次软件产品申报通知.pdf",
                "cloud_path": "10_政策与目录/政策数据库/企策顾问/宁波市/2025年浙江省首版次软件产品申报通知.pdf",
                "document_role": "10_政策与目录",
                "sensitivity": "public",
                "sha256": "same-policy-sha",
                "updated_at": "2025-06-01T00:00:00+00:00",
            },
        ],
    )
    with closing(sqlite3.connect(database_path)) as connection:
        connection.row_factory = sqlite3.Row
        result = rebuild_document_scopes(connection)
        canonical_id = connection.execute(
            "SELECT canonical_document_id FROM canonical_documents WHERE sha256='same-policy-sha'"
        ).fetchone()[0]
        duplicate_rows = connection.execute(
            "SELECT document_id,canonical_document_id FROM document_duplicates ORDER BY document_id"
        ).fetchall()
        city_scopes = {
            row[0]
            for row in connection.execute(
                """
                SELECT scope_value FROM document_scopes
                WHERE document_id=? AND scope_type='applicable_city'
                """,
                (canonical_id,),
            ).fetchall()
        }
        virtual_paths = [
            row[0]
            for row in connection.execute(
                "SELECT virtual_path FROM virtual_catalog_entries WHERE document_id=?",
                (canonical_id,),
            ).fetchall()
        ]
    assert result["canonical_documents"] == 1
    assert result["duplicate_documents"] == 1
    assert all(row[1] == canonical_id for row in duplicate_rows)
    assert {"杭州市", "宁波市", "金华市", "绍兴市"} <= city_scopes
    assert any("杭州市" in path for path in virtual_paths)
    assert any("宁波市" in path for path in virtual_paths)


def test_document_scopes_prefers_final_recognition_over_public_copy(tmp_path):
    database_path = tmp_path / "final-recognition-priority.sqlite3"
    create_database(
        database_path,
        [
            {
                "source_key": "public-copy",
                "title": "公示过程_2024年浙江省专精特新中小企业名单",
                "content": "1 | 测试企业有限公司",
                "source": "50_名单与对标/公示过程_名单.pdf",
                "cloud_path": "50_名单与对标/公示过程_名单.pdf",
                "document_role": "50_名单与对标",
                "sensitivity": "public",
                "sha256": "same-final-public-sha",
                "updated_at": "2024-06-01T00:00:00+00:00",
            },
            {
                "source_key": "final-copy",
                "title": "正式认定_2024年浙江省专精特新中小企业名单",
                "content": "1 | 测试企业有限公司",
                "source": "50_名单与对标/正式认定_名单.pdf",
                "cloud_path": "50_名单与对标/正式认定_名单.pdf",
                "document_role": "50_名单与对标",
                "sensitivity": "public",
                "sha256": "same-final-public-sha",
                "updated_at": "2024-07-01T00:00:00+00:00",
            },
        ],
    )
    with closing(sqlite3.connect(database_path)) as connection:
        connection.row_factory = sqlite3.Row
        rebuild_document_scopes(connection)
        canonical = connection.execute(
            """
            SELECT d.source_key
            FROM canonical_documents c
            JOIN documents d ON d.id=c.canonical_document_id
            WHERE c.sha256='same-final-public-sha'
            """
        ).fetchone()[0]
    assert canonical == "final-copy"


def test_final_source_requires_extracted_enterprise_rows():
    evidence = Evidence(
        document_id=1,
        title="正式认定_2024年测试省专精特新中小企业名单",
        source="正式认定_名单.pdf",
        region="测试省",
        year=2024,
        project_scope="provincial_specialized_sme",
        administrative_level="省级",
        evidence_type="final",
        confidence="high",
        entity_count=0,
        exclusion_reason="",
    )
    assert matrix_status([evidence], 0) == "final_source_needs_extraction"
    assert matrix_status([evidence], 1) == "verified_final"


def test_three_first_final_list_replaces_public_and_history_duplicates():
    base = {
        "enterprise_key": "enterprise-1",
        "eid": "enterprise-1",
        "enterprise_name": "浙江测试装备有限公司",
        "enterprise_aliases": [],
        "province": "浙江省",
        "city": "杭州市",
        "county": "",
        "industry": "",
        "project_id": "12",
        "project_name": "浙江省制造业首台（套）装备",
        "year": 2024,
        "product_name": "",
        "recognition_tier": "",
        "product_category": "",
        "list_status": "platform_history",
        "source_policy_id": "",
        "source_index_id": "",
        "source_title": "",
        "source_url": "",
        "confidence": "discovery_only",
    }
    public = {
        **base,
        "product_name": "测试装备A",
        "recognition_tier": "拟认定",
        "source_title": "2024年度浙江省首台（套）装备认定结果公示",
        "source_url": "https://example.test/public",
        "confidence": "product_level",
    }
    final = {
        **public,
        "recognition_tier": "国际首台套",
        "source_title": "关于公布2024年度浙江省首台（套）装备名单的通知",
        "source_url": "https://example.test/final",
    }
    canonical = canonicalize_details([public, final])
    merged = merge_three_first_records([base], canonical)
    assert len(canonical) == 1
    assert canonical[0]["source_url"] == "https://example.test/final"
    assert len(merged) == 1
    assert merged[0]["product_name"] == "测试装备A"


def test_three_first_timeline_keeps_publicity_recognition_reward_and_exit_separate():
    base = {
        "enterprise_key": "enterprise-1",
        "enterprise_name": "浙江测试装备有限公司",
        "project_id": "12",
        "project_name": "浙江省制造业首台（套）装备",
        "year": 2024,
        "product_name": "测试装备A",
        "source_tier": "official",
        "evidence_semantics": "annual_list_row",
        "confidence": "product_level",
        "source_url": "https://example.test/source",
    }
    evidence = [
        {**base, "list_status": "publicity", "source_title": "2024年度认定结果公示"},
        {**base, "list_status": "final_recognition_reward", "source_title": "关于公布认定及奖励名单的通知"},
        {**base, "list_status": "directory_exit", "source_title": "关于部分产品退出目录的通知"},
    ]
    timeline = build_status_timeline(evidence)
    assert [row["event_type"] for row in timeline] == [
        "publicity",
        "recognition",
        "reward",
        "directory_exit",
    ]
    assert [row["event_status"] for row in timeline] == [
        "confirmed",
        "confirmed",
        "confirmed",
        "confirmed",
    ]


def test_three_first_missing_product_does_not_create_placeholder_product_node():
    record = {
        "enterprise_key": "enterprise-1",
        "eid": "",
        "enterprise_name": "浙江测试材料有限公司",
        "enterprise_aliases": [],
        "province": "浙江省",
        "city": "",
        "county": "",
        "industry": "",
        "project_id": "11",
        "project_name": "浙江省首批次新材料",
        "year": 2021,
        "product_name": "",
        "recognition_tier": "",
        "product_category": "",
        "list_status": "platform_history",
        "source_policy_id": "",
        "source_index_id": "",
        "source_title": "",
        "source_url": "",
        "source_tier": "licensed_platform",
        "evidence_semantics": "platform_history_claim",
        "confidence": "discovery_only",
    }
    merged = merge_three_first_records([record], [])
    nodes, edges = build_three_first_graph(merged)
    assert merged[0]["product_name_status"] == "missing_user_lookup_required"
    assert not [node for node in nodes if node["type"] == "product"]
    assert not [edge for edge in edges if edge["relation"] == "recognized_product"]


def test_specialized_sme_final_recognition_overrides_public_candidates():
    public = Evidence(
        document_id=1,
        title="2024年浙江省专精特新中小企业公示名单",
        source="public.pdf",
        region="浙江省",
        year=2024,
        project_scope="provincial_specialized_sme",
        administrative_level="省级",
        evidence_type="public_or_recommended",
        confidence="high",
        entity_count=2,
        exclusion_reason="",
    )
    final = Evidence(
        document_id=2,
        title="关于公布2024年浙江省专精特新中小企业认定名单的通知",
        source="final.pdf",
        region="浙江省",
        year=2024,
        project_scope="provincial_specialized_sme",
        administrative_level="省级",
        evidence_type="final",
        confidence="high",
        entity_count=1,
        exclusion_reason="",
    )
    grouped = {("浙江省", 2024, "provincial_specialized_sme"): [public, final]}
    entities = {
        1: {"甲公司": "甲公司", "乙公司": "乙公司"},
        2: {"甲公司": "甲公司"},
    }
    canonical = canonical_evidence([public, final])
    rows = build_reconciliation(grouped, entities)
    assert canonical is not None
    assert canonical.document_id == 2
    assert {row["enterprise_name"]: row["result_status"] for row in rows} == {
        "甲公司": "recognized_final",
        "乙公司": "not_in_final_recognition",
    }
    rejected = next(row for row in rows if row["enterprise_name"] == "乙公司")
    assert rejected["effective_recognition"] == 0
    assert "最终认定名单未见" in rejected["resolution_reason"]


def test_mixed_recognition_and_review_document_splits_year_roles():
    roles = infer_mixed_year_roles(
        "关于公布2025年兵团专精特新中小企业认定和2022年兵团专精特新中小企业复核名单的通知",
        "现确定新认定的2025年度企业和复核通过的2022年度企业名单。",
    )
    assert roles == {2025: "final", 2022: "final_review"}
    proposed_roles = infer_mixed_year_roles(
        "2025年拟认定名单和2022年拟复核通过名单",
        "",
    )
    assert proposed_roles == {
        2025: "public_or_recommended",
        2022: "public_or_recommended",
    }


def test_provincial_specialized_sme_title_is_not_reclassified_by_small_giant_goal_text():
    scope, exclusion = infer_scope(
        "关于公布2025年兵团专精特新中小企业认定名单的通知",
        "支持企业积极成长为国家专精特新“小巨人”企业。",
        "省级专精特新中小企业",
    )
    assert scope == "provincial_specialized_sme"
    assert exclusion == ""


def test_region_inference_prefers_source_path_over_enterprise_names():
    region, confidence = infer_region(
        "2022年度自治区专精特新中小企业名单",
        "50_名单与对标/_省级专精特新/新疆维吾尔自治区/2022/名单.md",
        "1 北京测试科技有限公司",
        "",
    )
    assert region == "新疆维吾尔自治区"
    assert confidence == "high"


def test_specialized_sme_final_notice_is_not_downgraded_by_publication_procedure_text():
    assert infer_evidence_type(
        "关于公布2024年浙江省专精特新中小企业认定名单的通知",
        "经企业申报、专家评审和网上公示等程序，现将认定名单予以公布。",
        "认定名单",
    ) == "final"
    assert infer_evidence_type(
        "2024年浙江省专精特新中小企业拟认定名单公示",
        "现予以公示。",
        "公示名单",
    ) == "public_or_recommended"
    assert infer_evidence_type(
        "2024年度名单",
        "- 证据类型：final\n- 官方来源：https://example.test/final",
        "",
    ) == "final"
    assert infer_evidence_type(
        "自治区专精特新中小企业复核结果",
        "322家企业通过复核，60家企业未通过复核并取消称号，现将名单予以公布。",
        "",
    ) == "final_review"


def test_official_list_attachment_inherits_source_status_without_mixing_renames():
    source = {
        "expected_title": "2025年某省专精特新中小企业及复核通过名单",
        "evidence_type": "final_review",
    }
    assert attachment_evidence_type(source, "附件1 新认定企业名单") == "final"
    assert attachment_evidence_type(source, "附件2 复核通过名单") == "final_review"
    assert attachment_evidence_type(source, "附件3 简单更名名单") == "identity_change"
    assert attachment_evidence_type(source, "附件4 复核未通过名单") == "revocation"
    assert evidence_filename(source, "附件1.xls", "新认定企业名单").startswith("正式认定_")


def test_official_attachment_links_reads_javascript_file_arrays():
    html = """
    <script>
    var fLinks = 'https://example.gov.cn/files/final.xls,./notice.pdf'.split(',');
    var fNames = '附件：正式认定名单.xls,正式通知.pdf'.split(',');
    </script>
    """
    links = attachment_links(html, "https://example.gov.cn/policy/page.html")
    assert (
        "https://example.gov.cn/files/final.xls",
        "附件：正式认定名单.xls",
    ) in links
    assert (
        "https://example.gov.cn/policy/notice.pdf",
        "正式通知.pdf",
    ) in links


def test_qice_small_giant_dataset_builds_structured_region_and_platform_years(tmp_path):
    database_path = tmp_path / "qice-small-giant.sqlite3"
    content = json.dumps(
        {
            "dataset": "国家专精特新小巨人企业历史获批",
            "projectId": 98,
            "sourceLayer": "动态层",
            "records": [
                {
                    "entName": "浙江红相科技有限公司",
                    "province": "浙江省",
                    "city": "杭州市",
                    "county": "滨江区",
                    "industryName": "仪器仪表制造",
                    "subsidyYear": "2022年,2019年",
                },
                {
                    "entName": "杭州测试装备有限公司",
                    "province": "浙江省",
                    "city": "杭州市",
                    "county": "萧山区",
                    "industryName": "专用设备制造",
                    "subsidyYear": "2024年",
                },
            ],
        },
        ensure_ascii=False,
    )
    create_database(
        database_path,
        [
            {
                "source_key": "qice-small-giant",
                "title": "企策顾问国家专精特新小巨人历史获批名单",
                "content": content,
                "source": "50_名单与对标/企策顾问国家专精特新小巨人历史获批名单.json",
                "cloud_path": "50_名单与对标/企策顾问国家专精特新小巨人历史获批名单.json",
                "document_role": "50_名单与对标",
                "sensitivity": "internal",
                "sha256": "qice-small-giant-sha",
                "updated_at": "2026-07-22T00:00:00+00:00",
            }
        ],
    )
    with closing(sqlite3.connect(database_path)) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT * FROM public_list_entities ORDER BY sequence_no"
        ).fetchall()
    assert len(rows) == 2
    assert rows[0]["enterprise_name"] == "浙江红相科技有限公司"
    assert rows[0]["region"] == "浙江省杭州市滨江区"
    assert rows[0]["policy_year"] is None
    assert rows[0]["batch"] == ""
    assert rows[0]["confidence"] == "medium"
    with closing(sqlite3.connect(database_path)) as connection:
        years = connection.execute(
            """
            SELECT y.year,y.year_role
            FROM public_list_entity_years y
            JOIN public_list_entities e ON e.id=y.entity_id
            WHERE e.enterprise_name='浙江红相科技有限公司'
            ORDER BY y.year
            """
        ).fetchall()
    assert years == [(2019, "platform_record"), (2022, "platform_record")]


def test_qice_small_giant_incremental_import_keeps_original_database(tmp_path):
    source_database = tmp_path / "source.sqlite3"
    output_database = tmp_path / "output.sqlite3"
    dataset = tmp_path / "small-giant.json"
    create_database(source_database, [])
    dataset.write_text(
        json.dumps(
            {
                "dataset": "国家专精特新小巨人企业历史获批",
                "projectId": 98,
                "capturedAt": "2026-07-22T00:00:00+00:00",
                "records": [
                    {
                        "entName": "浙江齐治科技有限公司",
                        "province": "浙江省",
                        "city": "杭州市",
                        "county": "余杭区",
                        "industryName": "软件开发",
                        "subsidyYear": "2022年",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    original_digest = hashlib.sha256(source_database.read_bytes()).hexdigest()
    result = import_dataset(
        source_database,
        dataset,
        output_database,
        "50_名单与对标/企策顾问小巨人历史获批.json",
    )
    assert result["records"] == 1
    assert hashlib.sha256(source_database.read_bytes()).hexdigest() == original_digest
    with closing(sqlite3.connect(output_database)) as connection:
        row = connection.execute(
            "SELECT enterprise_name,policy_year,region FROM public_list_entities"
        ).fetchone()
        assert row == ("浙江齐治科技有限公司", None, "浙江省杭州市余杭区")
        years = connection.execute(
            "SELECT year,year_role FROM public_list_entity_years"
        ).fetchall()
        assert years == [(2022, "platform_record")]
        assert connection.execute(
            "SELECT year,year_role FROM public_list_entity_years"
        ).fetchone() == (2022, "platform_record")


def test_existing_index_can_be_upgraded_without_overwriting_source(tmp_path):
    source = tmp_path / "legacy.sqlite3"
    output = tmp_path / "structured.sqlite3"
    connection = sqlite3.connect(source)
    try:
        connection.executescript(
            """
            CREATE TABLE documents (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                source TEXT NOT NULL,
                document_role TEXT NOT NULL
            );
            CREATE TABLE enterprise_mentions (
                id INTEGER PRIMARY KEY,
                document_id INTEGER NOT NULL,
                enterprise_name TEXT NOT NULL,
                sequence_no TEXT NOT NULL,
                context TEXT NOT NULL
            );
            INSERT INTO documents VALUES(
                1,
                '2025年浙江省第六批专精特新小巨人认定名单',
                '1 | 杭州测试装备有限公司',
                '50_名单与对标/浙江省小巨人名单.md',
                '50_名单与对标'
            );
            INSERT INTO enterprise_mentions VALUES(
                1,1,'杭州测试装备有限公司','1','1 | 杭州测试装备有限公司'
            );
            """
        )
        connection.commit()
    finally:
        connection.close()

    result = upgrade_database(source, output)

    assert result["integrity"] == "ok"
    assert result["public_list_entities"] == 1
    assert source.stat().st_size > 0
    with closing(sqlite3.connect(output)) as upgraded:
        assert upgraded.execute(
            "SELECT canonical_project_name FROM documents WHERE id=1"
        ).fetchone()[0] == "国家专精特新“小巨人”企业"


def test_policy_clusters_prefer_document_number_and_do_not_use_fuzzy_titles(tmp_path):
    database_path = tmp_path / "cluster.sqlite3"
    base = {
        "content": "政策正文",
        "document_role": "10_政策与通知",
        "sensitivity": "public",
        "updated_at": "2026-07-19T00:00:00+00:00",
    }
    records = []
    for source_key, title in (
        ("number-pdf", "优质中小企业梯度培育管理办法（工信部企业〔2026〕2号）.pdf"),
        ("number-docx", "附件：梯度培育办法 工信部企业〔2026〕2号.docx"),
        ("work-one", "浙江省某协会关于开展机电制造高级工程师评审工作的通知"),
        ("work-two", "浙江省某协会关于开展信息技术高级工程师评审工作的通知"),
        ("generic-one", "申报人员网上申报办法.pdf"),
        ("generic-two", "申报人员网上申报办法.docx"),
    ):
        records.append(
            {
                **base,
                "source_key": source_key,
                "title": title,
                "source": f"10_政策与通知/{title}",
                "cloud_path": f"10_政策与通知/{title}",
                "sha256": f"sha-{source_key}",
            }
        )
    records.extend(
        [
            {
                **base,
                "source_key": "citation-one",
                "title": "常规项目申报条件",
                "content": "本材料仅引用国科发火〔2016〕32号",
                "source": "20_项目规则与指南/常规项目申报条件.xlsx",
                "cloud_path": "20_项目规则与指南/常规项目申报条件.xlsx",
                "sha256": "sha-citation-one",
            },
            {
                **base,
                "source_key": "citation-two",
                "title": "高新技术企业培训讲义",
                "content": "讲义引用国科发火〔2016〕32号",
                "source": "20_项目规则与指南/高新技术企业培训讲义.pdf",
                "cloud_path": "20_项目规则与指南/高新技术企业培训讲义.pdf",
                "sha256": "sha-citation-two",
            },
        ]
    )
    create_database(database_path, records)

    with closing(sqlite3.connect(database_path)) as connection:
        duplicate_clusters = connection.execute(
            """
            SELECT c.document_number,c.match_method,c.confidence,COUNT(m.id)
            FROM policy_document_clusters c
            JOIN policy_document_cluster_members m ON m.cluster_id=c.id
            GROUP BY c.id HAVING COUNT(m.id)>1
            """
        ).fetchall()
    assert duplicate_clusters == [
        ("工信部企业〔2026〕2号", "document_number", "high", 2)
    ]


def test_superseded_policy_and_rd_platform_metadata_are_hard_gated():
    from scripts.build_knowledge_content_index import infer_document_metadata

    old_sme = infer_document_metadata(
        "优质中小企业梯度培育管理暂行办法（工信部企业〔2022〕63号）.pdf",
        "10_政策与通知/旧办法.pdf",
        "优质中小企业梯度培育管理暂行办法",
        "10_政策与通知",
    )
    current_sme = infer_document_metadata(
        "优质中小企业梯度培育管理办法.pdf",
        "10_政策与通知/新办法.pdf",
        "工信部企业〔2026〕2号 科技和创新型中小企业 质量评价得分",
        "10_政策与通知",
    )
    old_provincial_rd = infer_document_metadata(
        "浙江省高新技术企业研究开发中心建设与管理办法.pdf",
        "10_政策与通知/省研发中心旧办法.pdf",
        "浙江省高新技术企业研究开发中心",
        "10_政策与通知",
    )
    current_hangzhou = infer_document_metadata(
        "杭州市企业高新技术研究开发中心管理办法.pdf",
        "10_政策与通知/杭州市正式办法.pdf",
        "杭科高〔2022〕39号",
        "10_政策与通知",
    )
    hangzhou_draft = infer_document_metadata(
        "2026-05-29_杭州市重点企业研究院、企业研究院建设管理办法（征求意见稿）.docx",
        "10_政策与通知/杭州市企业研究院/征求意见稿.docx",
        "本办法拟将原杭州市企业高新技术研究开发中心资格平移为杭州市企业研究院。",
        "10_政策与通知",
    )
    first_batch_publicity_draft = infer_document_metadata(
        "关于2025年浙江省重点新材料首批次应用示范指导目录的公示—浙江省重点新材料首批次应用示范指导目录（2025年版）.pdf",
        "10_政策与目录/政策数据库/企策顾问/公示公告/浙江省首批次/附件.pdf",
        "浙江省重点新材料首批次应用示范指导目录（2025年版）（公示稿）",
        "10_政策与通知",
    )

    assert old_sme["validity_status"] == "superseded"
    assert "2026" in old_sme["replacement_title"]
    assert current_sme["validity_status"] == "active_candidate"
    assert old_provincial_rd["validity_status"] == "superseded"
    assert old_provincial_rd["replacement_title"] == "浙江省企业研究院"
    assert current_hangzhou["validity_status"] == "active_candidate"
    assert hangzhou_draft["validity_status"] == "draft"
    assert first_batch_publicity_draft["validity_status"] == "draft"
    assert first_batch_publicity_draft["document_stage"] == "公示"


def test_parent_directory_terms_do_not_contaminate_document_metadata():
    metadata = infer_document_metadata(
        "2025年湖南省专精特新中小企业认定名单.docx",
        "/知识库/专精特新和小巨人公示名单与认定名单/湖南名单.docx",
        "湖南测试制造有限公司",
        "50_名单与对标",
    )

    assert metadata["canonical_project_name"] == "专精特新中小企业"
    assert metadata["document_stage"] == "认定名单"
    assert metadata["region"] == "湖南省"


def test_small_giant_public_list_infers_year_from_batch_and_region_from_content():
    metadata = infer_document_metadata(
        "附件1.第六批专精特新“小巨人”企业公示名单.pdf",
        "50_名单与对标/优质中小企业梯度培育/附件1.第六批专精特新“小巨人”企业公示名单.pdf",
        "省(区、市） 企业名称\n浙江省 杭州测试装备有限公司\n浙江省 宁波测试材料有限公司",
        "50_名单与对标",
    )

    assert metadata["canonical_project_name"] == "国家专精特新“小巨人”企业"
    assert metadata["policy_year"] == 2024
    assert metadata["batch"] == "第六批"
    assert metadata["region"] == "浙江省"


def test_local_small_giant_titles_are_not_mislabeled_as_national():
    provincial = infer_document_metadata(
        "关于2021年省级第三批专精特新“小巨人”企业名单的公示.docx",
        "50_名单与对标/省级第三批名单.docx",
        "省级专精特新企业名单",
        "50_名单与对标",
    )
    municipal = infer_document_metadata(
        "拟认定台州市第六批市级专精特新“小巨人”企业名单.docx",
        "50_名单与对标/台州市名单.docx",
        "台州测试制造有限公司",
        "50_名单与对标",
    )
    technology = infer_document_metadata(
        "2025年青海省科技小巨人企业认定名单.docx",
        "50_名单与对标/青海科技小巨人.docx",
        "青海测试科技有限公司",
        "50_名单与对标",
    )

    assert provincial["canonical_project_name"] == "地方专精特新小巨人企业"
    assert municipal["canonical_project_name"] == "地方专精特新小巨人企业"
    assert technology["canonical_project_name"] == "地方科技小巨人企业"


def test_three_first_subject_fields_extract_tier_category_and_material_name():
    from scripts.build_three_first_benchmark_graph import subject_fields

    equipment = subject_fields("装备类别：成套装备::拟认定档次：国际首台（套）")
    material = subject_fields("国内首批次::材料名称：高性能靶材-超高纯Ta靶材")

    assert equipment["product_category"] == "成套装备"
    assert equipment["recognition_tier"] == "国际首台（套）"
    assert material["recognition_tier"] == "国内首批次"
    assert material["product_name"] == "高性能靶材-超高纯Ta靶材"


def test_three_first_subject_fields_support_positional_2024_formats():
    from scripts.build_three_first_benchmark_graph import subject_fields

    first_version = subject_fields("国内首版次软件::工业软件::中智达智能动态优化控制软件")
    first_set = subject_fields("新型立式贴片机::省内首台（套）::整机装备")
    product_with_internal_colon = subject_fields(
        "省内首版次软件::点线推演者系统（简称：点线推演者）"
    )

    assert first_version == {
        "product_name": "中智达智能动态优化控制软件",
        "recognition_tier": "国内首版次软件",
        "product_category": "工业软件",
    }
    assert first_set == {
        "product_name": "新型立式贴片机",
        "recognition_tier": "省内首台（套）",
        "product_category": "整机装备",
    }
    assert product_with_internal_colon["product_name"] == "点线推演者系统（简称：点线推演者）"


def test_three_first_details_never_use_project_name_as_product_name():
    from scripts.build_three_first_benchmark_graph import normalize_details

    payload = {
        "projects": [
            {
                "projectId": "10",
                "projectName": "浙江省首版次软件产品",
                "policies": [
                    {
                        "policy": {
                            "title": "关于公布《2024年浙江省首版次软件产品应用推广指导目录》的通知",
                            "publishTime": "2024-12-30 00:00:00",
                        },
                        "records": [
                            {
                                "entName": "测试企业",
                                "projectName": "浙江省首版次软件产品",
                                "subject": "省内首版次软件::测试产品V1.0",
                                "assessYear": "2024",
                            }
                        ],
                    }
                ],
            }
        ]
    }

    records = normalize_details(payload, {})

    assert records[0]["product_name"] == "测试产品V1.0"
    assert records[0]["recognition_tier"] == "省内首版次软件"
    assert records[0]["list_status"] == "final_recognition"


def test_three_first_collector_includes_historical_first_set_title():
    from scripts.collect_qice_three_first_details import include_policy

    policy = {
        "title": "关于公布2016年浙江省装备制造业重点领域首台（套）产品名单的通知",
        "areaName": "浙江省",
        "policyType": 3,
    }

    assert include_policy("12", policy)


def test_three_first_collector_paginates_related_policies(monkeypatch):
    from scripts import collect_qice_three_first_details as collector

    calls = []

    def fake_post(_session, _token, _endpoint, payload):
        calls.append(dict(payload))
        current = payload["current"]
        return {
            "data": {
                "pages": 2,
                "records": [{"id": current}],
            }
        }

    monkeypatch.setattr(collector, "post", fake_post)
    monkeypatch.setattr(collector.time, "sleep", lambda _seconds: None)

    records = collector.related_policies(object(), "token", "11")

    assert [record["id"] for record in records] == [1, 2]
    assert [call["current"] for call in calls] == [1, 2]


def test_three_first_public_supplement_parses_2024_first_batch(tmp_path):
    from scripts.collect_three_first_public_supplements import parse_2024_first_batch

    rows = "".join(
        f"<tr><td>{index}</td><td>材料{index}</td><td>企业{index}</td><td>省内首批次</td></tr>"
        for index in range(1, 65)
    )
    source = tmp_path / "first-batch.html"
    source.write_text(
        "<table><tr><th>序号</th><th>材料名称</th><th>企业名称</th><th>认定档次</th></tr>"
        + rows
        + "</table>",
        encoding="utf-8",
    )

    records = parse_2024_first_batch(source)

    assert len(records) == 64
    assert records[0]["product_name"] == "材料1"
    assert records[-1]["enterprise_name"] == "企业64"


def test_three_first_public_supplement_includes_2021_non_reward_rows():
    from scripts.collect_three_first_public_supplements import (
        curated_2021_first_batch_non_reward,
    )

    records = curated_2021_first_batch_non_reward()

    assert len(records) == 22
    assert [record["sequence_no"] for record in records] == list(range(1, 23))
    assert records[0]["enterprise_name"] == "中钢新型材料股份有限公司"
    assert records[19]["product_name"] == "注塑钐铁氮稀土永磁复合材料"
    assert records[-1]["recognition_tier"] == "其他"


def test_first_batch_directory_sources_form_continuous_version_chain():
    from scripts.collect_first_batch_material_directories import DRAFT_FILES, EXPECTED_COUNTS, SOURCES

    assert sorted(SOURCES) == list(range(2020, 2026))
    assert EXPECTED_COUNTS[2025] == 445
    assert SOURCES[2025]["status"] == "active"
    assert all(SOURCES[year]["status"] == "superseded" for year in range(2020, 2025))
    assert DRAFT_FILES[2025]["validity_status"] == "draft_superseded"
    assert DRAFT_FILES[2025]["superseded_by"] == "浙经信材料〔2025〕234号"


def test_guidance_directory_diff_tracks_clause_changes_and_additions():
    from scripts.build_three_first_benchmark_graph import directory_version_diffs

    rows = [
        {
            "directory_year": 2024,
            "sequence_no": 1,
            "material_name": "高性能复合材料",
            "top_category": "关键战略材料",
            "major_category": "复合材料",
            "sub_category": "",
            "performance_requirements": "拉伸强度≥100MPa",
            "application_field": "新能源汽车",
        },
        {
            "directory_year": 2025,
            "sequence_no": 2,
            "material_name": "高性能复合材料",
            "top_category": "关键战略材料",
            "major_category": "复合材料",
            "sub_category": "",
            "performance_requirements": "拉伸强度≥120MPa",
            "application_field": "新能源汽车",
        },
        {
            "directory_year": 2025,
            "sequence_no": 3,
            "material_name": "低介电复合材料",
            "top_category": "关键战略材料",
            "major_category": "复合材料",
            "sub_category": "",
            "performance_requirements": "介电常数≤2.5",
            "application_field": "通信",
        },
    ]

    differences = directory_version_diffs(rows)

    assert [row["change_type"] for row in differences] == ["added", "modified"]
    modified = next(row for row in differences if row["change_type"] == "modified")
    assert modified["changed_fields"] == ["performance_requirements"]


def test_enterprise_product_automatically_matches_best_directory_candidate():
    from scripts.build_three_first_benchmark_graph import (
        enterprise_product_directory_matches,
    )

    records = [
        {
            "project_id": "11",
            "enterprise_name": "测试材料有限公司",
            "year": 2025,
            "product_name": "车用高性能生物基TPV材料",
        }
    ]
    directories = [
        {
            "directory_year": 2025,
            "sequence_no": 27,
            "material_name": "车用高性能生物基 TPV 材料",
        },
        {
            "directory_year": 2025,
            "sequence_no": 28,
            "material_name": "高性能生物基聚酰胺材料",
        },
    ]

    matches = enterprise_product_directory_matches(records, directories)

    assert len(matches) == 1
    assert matches[0]["directory_sequence_no"] == 27
    assert matches[0]["match_type"] == "exact_material_name"
    assert matches[0]["match_confidence"] == "high"
    assert matches[0]["review_status"] == "auto_confirmed"


def test_three_first_public_supplement_parses_2025_first_version_final(tmp_path):
    from scripts.collect_three_first_public_supplements import parse_2025_first_version

    rows = "".join(
        f"<tr><td>{index}</td><td>工业软件</td><td>软件产品{index}</td><td>企业{index}</td></tr>"
        for index in range(1, 85)
    )
    source = tmp_path / "first-version.json"
    source.write_text(
        json.dumps(
            {
                "body": {
                    "TITLE": "浙江省经济和信息化厅关于公布《2025年浙江省首版次软件产品应用推广指导目录》的通知",
                    "CONTENT": "<table>" + rows + "</table>",
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    records = parse_2025_first_version(source)

    assert len(records) == 84
    assert records[0]["list_status"] == "final_recognition"
    assert records[-1]["product_name"] == "软件产品84"


def test_confirmed_alias_correction_overrides_automatic_project_match():
    metadata = infer_document_metadata(
        "2025年浙江省制造精品征集通知",
        "10_政策与通知/制造精品通知.docx",
        "组织企业申报。",
        "10_政策与通知",
        corrections=[
            {
                "id": 7,
                "raw_project_name": "制造精品",
                "canonical_project_name": "浙江制造精品",
                "region": "浙江省",
                "start_year": 2024,
                "end_year": 2026,
                "status": "confirmed",
            }
        ],
    )

    assert metadata["canonical_project_name"] == "浙江制造精品"
    project_evidence = next(
        item
        for item in metadata["match_evidence"]
        if item["field_name"] == "canonical_project_name"
    )
    assert project_evidence["match_method"] == "manual_alias"
    assert project_evidence["review_status"] == "confirmed"
    assert project_evidence["correction_id"] == 7


def test_gold_standard_contains_sixty_cases_and_metadata_is_exact():
    cases = load_cases(DEFAULT_GOLD_SET)
    metadata_cases = [case for case in cases if case["kind"] == "metadata"]

    assert len(cases) == 60
    assert {case["kind"] for case in cases} == {
        "metadata",
        "list_query",
        "policy_query",
        "project_match",
    }
    assert evaluate(metadata_cases)["core_field_accuracy"] == 1.0


def test_small_giant_platform_year_claims_are_split_without_promoting_cohorts():
    from scripts.build_national_small_giant_master import record_year, record_years

    assert record_years("2025年,2021年") == [2021, 2025]
    assert record_year("2025年,2021年") == 2021
    assert record_year("2024年,2020年") == 2020
    assert record_year("2026年") is None


def test_small_giant_batch_sources_preserve_required_provenance():
    from scripts.build_national_small_giant_master import DEFAULT_SOURCES

    payload = json.loads(DEFAULT_SOURCES.read_text(encoding="utf-8"))
    assert len(payload["batches"]) == 7
    for item in payload["batches"]:
        assert item["batch"]
        assert item["year"]
        assert item["expected_count"] > 0
        assert item["official_url"].startswith("https://")
        assert item["official_url_role"]


def test_small_giant_identity_rules_do_not_infer_invalid_credit_codes():
    assert USCC_PATTERN.fullmatch("91330100MA2B12345X")
    assert not USCC_PATTERN.fullmatch("91330100MA2B12345I")
    assert not USCC_PATTERN.fullmatch("杭州某某科技有限公司")
    assert normalize_identity_name("浙江 某某（杭州）有限公司") == "浙江某某杭州有限公司"


def test_small_giant_fragment_collector_only_accepts_government_hosts():
    assert official_fragment_url_allowed("https://gxt.guizhou.gov.cn/example")
    assert official_fragment_url_allowed("https://www.miit.gov.cn/example")
    assert not official_fragment_url_allowed("https://aiqice.cn/example")
    assert not official_fragment_url_allowed("https://example.com/example")


def test_qice_snapshot_resolution_never_promotes_platform_data_to_official():
    from scripts.build_qice_small_giant_snapshot_matrix import resolution_status

    assert (
        resolution_status(0, 0, 15, 15)
        == "qice_enterprise_snapshot_present_official_fragment_missing"
    )
    assert (
        resolution_status(12, 0, 12, 12)
        == "official_enterprises_closed_source_url_pending"
    )
    assert (
        resolution_status(12, 1, 12, 12)
        == "official_count_enterprise_source_closed"
    )
    assert resolution_status(0, 0, 0, 0, True) == "confirmed_zero_enterprises"


def test_gsxt_identity_mapping_only_accepts_official_hosts():
    from scripts.prepare_gsxt_identity_mapping import official_gsxt_url

    assert official_gsxt_url("https://www.gsxt.gov.cn/index.html")
    assert official_gsxt_url("https://bt.gsxt.gov.cn/affiche-query-info-help-330000.html")
    assert not official_gsxt_url("https://aiqice.cn/example")
    assert not official_gsxt_url("https://qcc.com/example")
