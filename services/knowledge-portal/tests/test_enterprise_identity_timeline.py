import importlib.util
import sqlite3
import zipfile
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "build_zhejiang_enterprise_identity_timeline.py"
)
SPEC = importlib.util.spec_from_file_location("identity_timeline", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_normalize_name_removes_punctuation():
    assert MODULE.normalize_name("浙江申新（原名）有限公司") == "浙江申新原名有限公司"


def test_normalize_region_keeps_recognition_layers():
    assert MODULE.normalize_region("台州市|浙江省|临海市") == ("浙江省", "台州市", "临海市")


def test_first_year_uses_earliest_explicit_year():
    assert MODULE.first_year("2025年复核2022年名单") == 2022


def test_numbered_organization_lines_accepts_markdown_and_official_text():
    assert MODULE.numbered_organization_lines(
        "1. 浙江示例科技有限公司\n2 浙江示例研究院\n3、非企业说明"
    ) == [
        ("浙江示例科技有限公司", "1"),
        ("浙江示例研究院", "2"),
    ]


def test_xlsx_enterprise_column_reads_unindexed_official_attachment(
    tmp_path: Path,
):
    workbook = tmp_path / "名单.xlsx"
    with zipfile.ZipFile(workbook, "w") as archive:
        archive.writestr(
            "xl/sharedStrings.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
            <sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
              <si><t>序号</t></si><si><t>企业名称</t></si>
              <si><t>浙江示例科技有限公司</t></si>
              <si><t>嘉兴示例制造厂</t></si>
            </sst>""",
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
            <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
              <sheetData>
                <row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>
                <row r="2"><c r="A2"><v>1</v></c><c r="B2" t="s"><v>2</v></c></row>
                <row r="3"><c r="A3"><v>2</v></c><c r="B3" t="s"><v>3</v></c></row>
              </sheetData>
            </worksheet>""",
        )

    assert MODULE.xlsx_enterprise_column(workbook) == [
        ("浙江示例科技有限公司", "1"),
        ("嘉兴示例制造厂", "2"),
    ]


def test_identity_matched_aliases_collapse_to_one_project_event():
    base = {
        "identity_key": "91330000TEST000001",
        "project_name": "国家专精特新“小巨人”企业",
        "event_year": 2024,
        "batch": "财政支持第一批第三年",
        "status": "建议继续支持",
        "event_type": "continued_support",
        "source_urls": [],
        "sequence_numbers": [],
        "source_kinds": ["lifecycle_manifest"],
    }
    rows = MODULE.merge_identity_event_rows(
        [
            {
                **base,
                "enterprise_name_at_event": "浙江示例技术有限公司",
                "normalized_name": "浙江示例技术有限公司",
                "source_paths": ["名单.pdf"],
            },
            {
                **base,
                "enterprise_name_at_event": "浙江示例科技有限公司",
                "normalized_name": "浙江示例科技有限公司",
                "source_paths": ["名单.pdf", "名单镜像.pdf"],
            },
        ]
    )

    assert len(rows) == 1
    assert rows[0]["enterprise_name_at_event"] == "浙江示例技术有限公司"
    assert rows[0]["source_paths"] == ["名单.pdf", "名单镜像.pdf"]


def test_lifecycle_rules_cover_four_core_projects():
    rules_path = (
        Path(__file__).resolve().parents[1]
        / "references"
        / "enterprise-lifecycle-rules.json"
    )
    rules, _, _, aliases, discovery = MODULE.load_lifecycle_config(rules_path)
    assert {
        "国家专精特新“小巨人”企业",
        "浙江省专精特新中小企业",
        "国家高新技术企业",
        "浙江省隐形冠军企业",
        "国家级工业设计中心",
        "浙江省工业设计中心",
        "浙江省绿色低碳工业园区和工厂",
        "杭州老字号",
        "杭州市企业技术中心",
    }.issubset(rules)
    assert (
        MODULE.canonical_lifecycle_project("高企", aliases)
        == "国家高新技术企业"
    )
    assert set(discovery["expected_regions"]) == set(
        MODULE.ZHEJIANG_PREFECTURE_CITIES
    )


def test_event_type_keeps_high_tech_rerecognition_separate_from_review():
    assert MODULE.infer_event_type("高新技术企业重新认定名单", "", "国家高新技术企业") == "re_recognition"
    assert MODULE.infer_event_type("隐形冠军拟复核通过名单", "", "浙江省隐形冠军企业") == "review_publicity"
    assert MODULE.infer_event_type("建议继续支持的小巨人名单", "", "国家专精特新“小巨人”企业") == "continued_support"


def test_coverage_event_types_split_combined_recognition_and_review_title():
    assert MODULE.coverage_event_types(
        "2025年浙江省专精特新中小企业拟认定名单、2022年度拟复核通过名单",
        "公示名单",
        "浙江省专精特新中小企业",
    ) == ["review_publicity", "recognition_publicity"]


def test_document_prefecture_city_does_not_infer_city_from_enterprises():
    assert (
        MODULE.document_prefecture_city(
            "2025年浙江省专精特新中小企业名单",
            "浙江省",
            "50_名单与对标/省级汇总名单.xlsx",
        )
        == ""
    )
    assert (
        MODULE.document_prefecture_city(
            "2025年浙江省专精特新中小企业名单",
            "浙江省|金华市",
            "50_名单与对标/省级汇总名单.xlsx",
        )
        == "金华市"
    )


def test_auto_discovers_provincial_city_files_and_independent_ningbo_files(
    tmp_path,
):
    database = tmp_path / "coverage.sqlite3"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE documents(
            id INTEGER PRIMARY KEY,
            title TEXT,
            source TEXT,
            cloud_path TEXT,
            document_role TEXT,
            canonical_project_name TEXT,
            policy_year INTEGER,
            batch TEXT,
            region TEXT,
            document_stage TEXT,
            sha256 TEXT,
            updated_at TEXT
        );
        CREATE TABLE public_list_entities(
            id INTEGER PRIMARY KEY,
            document_id INTEGER
        );
        """
    )
    connection.executemany(
        """
        INSERT INTO documents VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                1,
                "2024年第一批浙江省专精特新中小企业公示名单（杭州市）",
                "50_名单与对标/杭州.xlsx",
                "",
                "50_名单与对标",
                "浙江省专精特新中小企业",
                2024,
                "第一批",
                "浙江省|杭州市",
                "公示名单",
                "a" * 64,
                "2026-07-29",
            ),
            (
                2,
                "2024年第一批浙江省专精特新中小企业公示名单",
                "50_名单与对标/全省.xlsx",
                "",
                "50_名单与对标",
                "浙江省专精特新中小企业",
                2024,
                "第一批",
                "浙江省",
                "公示名单",
                "b" * 64,
                "2026-07-29",
            ),
            (
                3,
                "2024年度宁波市专精特新中小企业公示名单",
                "50_名单与对标/宁波市级.xlsx",
                "",
                "50_名单与对标",
                "专精特新中小企业",
                2024,
                "第一批",
                "宁波市",
                "公示名单",
                "c" * 64,
                "2026-07-29",
            ),
        ],
    )
    connection.executemany(
        "INSERT INTO public_list_entities(document_id) VALUES(?)",
        [(1,), (1,), (2,), (3,)],
    )
    connection.commit()
    connection.close()
    rules = {
        "浙江省专精特新中小企业": {
            "rule_id": "zhejiang-specialized-sme"
        }
    }
    aliases = {
        MODULE.normalize_name("浙江省专精特新中小企业"):
            "浙江省专精特新中小企业",
        MODULE.normalize_name("专精特新中小企业"):
            "浙江省专精特新中小企业",
    }
    sources = MODULE.discover_regional_coverage_sources(
        database,
        rules,
        aliases,
    )
    assert {source["city"] for source in sources} == {"杭州市", "宁波市"}
    assert next(
        source for source in sources if source["city"] == "杭州市"
    )["entity_count"] == 2


def test_coverage_matrix_reuses_hash_and_queues_only_missing_or_changed(tmp_path):
    rules = {
        "浙江省专精特新中小企业": {
            "rule_id": "zhejiang-specialized-sme"
        }
    }
    source = {
        "source_id": "document-1-recognition_publicity",
        "document_id": 1,
        "document_title": "杭州市名单",
        "project_name": "浙江省专精特新中小企业",
        "event_year": 2024,
        "event_type": "recognition_publicity",
        "batch": "第一批",
        "city": "杭州市",
        "source_path": "杭州.xlsx",
        "official_url": "",
        "evidence_archive_url": "",
        "source_fingerprint": "a" * 64,
        "entity_count": 2,
        "coverage_confirmed_empty": False,
        "registration_source": "knowledge_index_auto_discovery",
    }
    settings = {"expected_regions": list(MODULE.ZHEJIANG_PREFECTURE_CITIES)}
    first = MODULE.build_regional_coverage_matrix(
        tmp_path,
        rules,
        [],
        [],
        [source],
        settings,
    )
    assert len(first["groups"]) == 1
    assert len(first["rows"]) == 11
    assert len(first["collection_queue"]) == 10
    assert next(
        row for row in first["rows"] if row["city"] == "杭州市"
    )["coverage_state"] == "new_source_registered"

    second = MODULE.build_regional_coverage_matrix(
        tmp_path,
        rules,
        [],
        [],
        [source],
        settings,
    )
    assert len(second["collection_queue"]) == 10
    assert next(
        row for row in second["rows"] if row["city"] == "杭州市"
    )["coverage_state"] == "hash_reused"

    changed_source = {**source, "source_fingerprint": "c" * 64}
    changed = MODULE.build_regional_coverage_matrix(
        tmp_path,
        rules,
        [],
        [],
        [changed_source],
        settings,
    )
    assert len(changed["collection_queue"]) == 11
    assert next(
        row for row in changed["rows"] if row["city"] == "杭州市"
    )["coverage_state"] == "source_changed"


def test_coverage_matrix_accepts_one_provincial_master_for_multiple_cities(
    tmp_path,
):
    rules = {
        "浙江省专精特新中小企业": {
            "rule_id": "zhejiang-specialized-sme"
        }
    }
    source = {
        "source_id": "final-master",
        "document_title": "全省正式名单",
        "project_name": "浙江省专精特新中小企业",
        "event_year": 2025,
        "event_type": "recognition_publicity",
        "batch": "第一批",
        "city": "",
        "covered_cities": list(MODULE.ZHEJIANG_PREFECTURE_CITIES),
        "coverage_basis": "superseding_official_final_list",
        "source_path": "全省正式名单.pdf",
        "official_url": "https://example.gov.cn/final.pdf",
        "evidence_archive_url": "",
        "source_fingerprint": "d" * 64,
        "entity_count": 100,
        "coverage_confirmed_empty": False,
        "registration_source": "configured_manifest",
    }
    result = MODULE.build_regional_coverage_matrix(
        tmp_path,
        rules,
        [],
        [],
        [source],
        {"expected_regions": list(MODULE.ZHEJIANG_PREFECTURE_CITIES)},
    )

    assert result["groups"][0]["complete"] is True
    assert result["collection_queue"] == []
    assert {
        row["sources"][0]["coverage_basis"] for row in result["rows"]
    } == {"superseding_official_final_list"}


def test_manifest_lifecycle_source_splits_review_section(tmp_path):
    database = tmp_path / "test.sqlite3"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE documents(
            id INTEGER PRIMARY KEY,
            title TEXT,
            content TEXT,
            source TEXT,
            cloud_path TEXT
        );
        CREATE TABLE enterprise_mentions(
            id INTEGER PRIMARY KEY,
            document_id INTEGER,
            enterprise_name TEXT,
            sequence_no TEXT
        );
        """
    )
    connection.execute(
        "INSERT INTO documents VALUES(1,?,?,?,?)",
        (
            "测试名单",
            "认定名单\n甲有限公司\n复核名单\n乙有限公司\n结束",
            "测试/名单.txt",
            "",
        ),
    )
    connection.executemany(
        "INSERT INTO enterprise_mentions(document_id,enterprise_name,sequence_no) VALUES(1,?,?)",
        [("甲有限公司", "1"), ("乙有限公司", "2")],
    )
    connection.commit()
    connection.close()

    rules = {
        "浙江省隐形冠军企业": {
            "rule_id": "zhejiang-hidden-champion",
            "cycle_type": "qualification_review",
            "validity_years": 3,
        }
    }
    sources = [
        {
            "source_id": "test-review",
            "document_title": "测试名单",
            "project_name": "浙江省隐形冠军企业",
            "event_year": 2025,
            "cohort_year": 2022,
            "batch": "2022年度",
            "status": "复核通过",
            "event_type": "review_passed",
            "event_scope": "qualification",
            "evidence_status": "official_final_list",
            "start_pattern": "复核名单",
            "end_pattern": "结束",
            "expected_count": 1,
            "official_url": "",
        }
    ]
    events = {}
    exclusions, audits = MODULE.load_manifest_lifecycle_events(
        database,
        sources,
        rules,
        events,
    )
    assert len(events) == 1
    event = next(iter(events.values()))
    assert event["enterprise_name_at_event"] == "乙有限公司"
    assert event["event_type"] == "review_passed"
    assert event["cohort_year"] == 2022
    assert exclusions == {(1, "乙有限公司")}
    assert audits[0]["count_aligned"] is True


def test_manifest_lifecycle_source_accepts_audited_inline_entities(tmp_path):
    database = tmp_path / "test.sqlite3"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE documents(
            id INTEGER PRIMARY KEY,
            title TEXT,
            content TEXT,
            source TEXT,
            cloud_path TEXT
        );
        CREATE TABLE enterprise_mentions(
            id INTEGER PRIMARY KEY,
            document_id INTEGER,
            enterprise_name TEXT,
            sequence_no TEXT
        );
        """
    )
    connection.close()

    rules = {
        "浙江省隐形冠军企业": {
            "rule_id": "zhejiang-hidden-champion",
            "cycle_type": "qualification_review",
            "validity_years": 3,
        }
    }
    sources = [
        {
            "source_id": "test-inline-publicity",
            "document_title": "衢州市拟复核通过名单",
            "project_name": "浙江省隐形冠军企业",
            "event_year": 2025,
            "cohort_year": 2022,
            "city": "衢州市",
            "batch": "2025年度衢州市公示",
            "status": "拟复核通过",
            "event_type": "review_publicity",
            "event_scope": "qualification",
            "evidence_status": "official_publicity",
            "entities": ["甲有限公司", "乙有限公司"],
            "expected_count": 2,
            "official_url": "https://example.gov.cn/publicity",
        }
    ]
    events = {}
    exclusions, audits = MODULE.load_manifest_lifecycle_events(
        database,
        sources,
        rules,
        events,
    )
    assert len(events) == 2
    assert exclusions == set()
    event = next(
        item
        for item in events.values()
        if item["enterprise_name_at_event"] == "乙有限公司"
    )
    assert event["event_type"] == "review_publicity"
    assert event["recognition_city"] == "衢州市"
    assert event["evidence_status"] == "official_publicity"
    assert audits[0]["document_id"] is None
    assert audits[0]["actual_count"] == 2


def test_manifest_lifecycle_source_accepts_confirmed_empty_inline_entities(tmp_path):
    database = tmp_path / "test.sqlite3"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE documents(
            id INTEGER PRIMARY KEY,
            title TEXT,
            content TEXT,
            source TEXT,
            cloud_path TEXT
        );
        CREATE TABLE enterprise_mentions(
            id INTEGER PRIMARY KEY,
            document_id INTEGER,
            enterprise_name TEXT,
            sequence_no TEXT
        );
        """
    )
    connection.close()

    sources = [
        {
            "source_id": "test-empty-city",
            "document_title": "某市复核名单为空",
            "project_name": "浙江省隐形冠军企业",
            "event_year": 2025,
            "city": "某市",
            "event_type": "review_publicity",
            "entities": [],
            "expected_count": 0,
            "coverage_confirmed_empty": True,
        }
    ]
    events = {}
    _, audits = MODULE.load_manifest_lifecycle_events(
        database,
        sources,
        {},
        events,
    )
    assert events == {}
    assert audits[0]["actual_count"] == 0
    assert audits[0]["count_aligned"] is True
    assert audits[0]["coverage_confirmed_empty"] is True


def test_regional_coverage_audit_requires_every_configured_region():
    rules = [
        {
            "coverage_group_id": "test-group",
            "project_name": "测试项目",
            "event_year": 2025,
            "event_type": "review_publicity",
            "expected_regions": ["甲市", "乙市"],
            "strict": False,
        }
    ]
    source_audits = [
        {
            "source_id": "test-city-a",
            "coverage_group_id": "test-group",
            "city": "甲市",
            "document_title": "甲市名单",
            "published_at": "2026-01-01",
            "source_path": "",
            "official_url": "",
            "evidence_archive_url": "",
            "expected_count": 1,
            "actual_count": 1,
            "count_aligned": True,
            "coverage_confirmed_empty": False,
        }
    ]
    audits = MODULE.audit_regional_source_coverage(rules, source_audits)
    assert audits[0]["complete"] is False
    assert audits[0]["missing_regions"] == ["乙市"]


def test_regional_coverage_audit_accepts_complete_region_set():
    rules = [
        {
            "coverage_group_id": "test-group",
            "project_name": "测试项目",
            "event_year": 2025,
            "event_type": "review_publicity",
            "expected_regions": ["甲市", "乙市"],
            "strict": True,
        }
    ]
    source_audits = [
        {
            "source_id": f"test-{city}",
            "coverage_group_id": "test-group",
            "city": city,
            "document_title": f"{city}名单",
            "published_at": "2026-01-01",
            "source_path": "",
            "official_url": "",
            "evidence_archive_url": "",
            "expected_count": count,
            "actual_count": count,
            "count_aligned": True,
            "coverage_confirmed_empty": count == 0,
        }
        for city, count in (("甲市", 1), ("乙市", 0))
    ]
    audits = MODULE.audit_regional_source_coverage(rules, source_audits)
    assert audits[0]["complete"] is True
    assert audits[0]["covered_region_count"] == 2
    assert audits[0]["entity_count"] == 1
