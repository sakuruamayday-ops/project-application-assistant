import importlib.util
import json
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
              <si><t>浙江省示例勘测设计院</t></si>
              <si><t>浙江示例新材料科技有限公司-1006217</t></si>
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
                <row r="4"><c r="A4"><v>3</v></c><c r="B4" t="s"><v>4</v></c></row>
                <row r="5"><c r="A5"><v>4</v></c><c r="B5" t="s"><v>5</v></c></row>
              </sheetData>
            </worksheet>""",
        )

    assert MODULE.xlsx_enterprise_column(workbook) == [
        ("浙江示例科技有限公司", "1"),
        ("嘉兴示例制造厂", "2"),
        ("浙江省示例勘测设计院", "3"),
        ("浙江示例新材料科技有限公司", "4"),
    ]


def test_xlsx_enterprise_column_splits_review_and_active_discovery_sections(
    tmp_path: Path,
):
    workbook = tmp_path / "合并名单.xlsx"
    with zipfile.ZipFile(workbook, "w") as archive:
        archive.writestr(
            "xl/sharedStrings.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
            <sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
              <si><t>拟复核通过名单</t></si><si><t>序号</t></si>
              <si><t>企业名称</t></si><si><t>浙江复核企业有限公司</t></si>
              <si><t>主动发现机制拟新增名单</t></si>
              <si><t>浙江新增企业有限公司</t></si>
            </sst>""",
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
            <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
              <sheetData>
                <row r="1"><c r="A1" t="s"><v>0</v></c></row>
                <row r="2"><c r="A2" t="s"><v>1</v></c><c r="B2" t="s"><v>2</v></c></row>
                <row r="3"><c r="A3"><v>1</v></c><c r="B3" t="s"><v>3</v></c></row>
                <row r="4"><c r="A4" t="s"><v>4</v></c></row>
                <row r="5"><c r="A5" t="s"><v>1</v></c><c r="B5" t="s"><v>2</v></c></row>
                <row r="6"><c r="A6"><v>1</v></c><c r="B6" t="s"><v>5</v></c></row>
              </sheetData>
            </worksheet>""",
        )

    assert MODULE.xlsx_enterprise_column(
        workbook,
        "拟复核通过名单",
        "主动发现机制拟新增名单",
    ) == [("浙江复核企业有限公司", "1")]
    assert MODULE.xlsx_enterprise_column(
        workbook,
        "主动发现机制拟新增名单",
    ) == [("浙江新增企业有限公司", "1")]


def test_docx_enterprise_rows_reads_table_and_paragraph_lists(tmp_path: Path):
    table_docx = tmp_path / "表格名单.docx"
    paragraph_docx = tmp_path / "段落名单.docx"
    document_xml = """<?xml version="1.0" encoding="UTF-8"?>
      <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
        <w:body><w:tbl>
          <w:tr><w:tc><w:p><w:r><w:t>序号</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>企业名称</w:t></w:r></w:p></w:tc></w:tr>
          <w:tr><w:tc><w:p><w:r><w:t>1</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>浙江表格企业有限公司</w:t></w:r></w:p></w:tc></w:tr>
        </w:tbl></w:body></w:document>"""
    with zipfile.ZipFile(table_docx, "w") as archive:
        archive.writestr("word/document.xml", document_xml)
    paragraph_xml = """<?xml version="1.0" encoding="UTF-8"?>
      <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
        <w:body><w:p><w:r><w:t>拟认定名单</w:t></w:r></w:p>
        <w:p><w:r><w:t>浙江段落企业有限公司</w:t></w:r></w:p></w:body></w:document>"""
    with zipfile.ZipFile(paragraph_docx, "w") as archive:
        archive.writestr("word/document.xml", paragraph_xml)

    assert MODULE.docx_enterprise_rows(table_docx) == [
        ("浙江表格企业有限公司", "1")
    ]
    assert MODULE.docx_enterprise_rows(paragraph_docx) == [
        ("浙江段落企业有限公司", "1")
    ]


def test_structured_entity_source_preserves_event_city_and_county(tmp_path: Path):
    database = tmp_path / "knowledge.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE documents(id INTEGER PRIMARY KEY)")
    connection.commit()
    connection.close()
    entities_path = tmp_path / "entities.json"
    entities_path.write_text(
        json.dumps(
            {
                "entities": [
                    {
                        "sequence_no": 1,
                        "enterprise_name": "杭州示例科技有限公司",
                        "province": "浙江省",
                        "city": "杭州市",
                        "county": "余杭区",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    events = {}
    _, audits = MODULE.load_manifest_lifecycle_events(
        database,
        [
            {
                "source_id": "structured-source",
                "document_title": "结构化地市名单",
                "source_path": str(entities_path),
                "project_name": "浙江省专精特新中小企业",
                "event_year": 2023,
                "batch": "第一批",
                "status": "认定",
                "event_type": "recognition",
                "event_scope": "qualification",
                "evidence_status": "official_final_list",
                "entity_extraction": "structured_entities_json",
                "expected_count": 1,
                "city": "杭州市",
            }
        ],
        {},
        events,
    )
    event = next(iter(events.values()))
    assert event["recognition_city"] == "杭州市"
    assert event["recognition_county"] == "余杭区"
    assert audits[0]["actual_count"] == 1
    assert audits[0]["completeness_claim_allowed"] is True


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


def test_product_subjects_do_not_collapse_in_same_enterprise_year():
    base = {
        "identity_key": "91330000TEST000001",
        "project_name": "浙江省首版次软件产品",
        "event_year": 2025,
        "batch": "",
        "status": "认定",
        "event_type": "recognition",
        "enterprise_name_at_event": "浙江示例软件有限公司",
        "normalized_name": "浙江示例软件有限公司",
        "source_paths": ["名单.pdf"],
        "source_urls": [],
        "sequence_numbers": [],
        "source_kinds": ["three_first_product_record"],
    }
    rows = MODULE.merge_identity_event_rows(
        [
            {**base, "subject_key": "产品甲", "product_name": "产品甲"},
            {**base, "subject_key": "产品乙", "product_name": "产品乙"},
        ]
    )
    assert len(rows) == 2


def test_lifecycle_rules_cover_four_core_projects():
    rules_path = (
        Path(__file__).resolve().parents[1]
        / "references"
        / "enterprise-lifecycle-rules.json"
    )
    rules, lifecycle_sources, _, aliases, discovery = MODULE.load_lifecycle_config(rules_path)
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
    hangzhou_2023_second = next(
        source
        for source in lifecycle_sources
        if source["source_id"]
        == "zhejiang-specialized-sme-2023-second-hangzhou-publicity"
    )
    assert hangzhou_2023_second["expected_count"] == 1030
    assert hangzhou_2023_second["city"] == "杭州市"
    assert (
        hangzhou_2023_second["entity_extraction"]
        == "spreadsheet_enterprise_column"
    )
    hangzhou_2023_new_small_giant = next(
        source
        for source in lifecycle_sources
        if source["source_id"]
        == "national-small-giant-2023-fifth-hangzhou-publicity"
    )
    assert hangzhou_2023_new_small_giant["event_type"] == "recognition_publicity"
    assert hangzhou_2023_new_small_giant["expected_count"] == 117
    assert (
        hangzhou_2023_new_small_giant["entity_extraction"]
        == "structured_entities_json"
    )
    zhejiang_2023_review = next(
        source
        for source in lifecycle_sources
        if source["source_id"]
        == "national-small-giant-2023-second-review-zhejiang-non-ningbo-publicity"
    )
    assert zhejiang_2023_review["event_type"] == "review_publicity"
    assert zhejiang_2023_review["cohort_year"] == 2020
    assert zhejiang_2023_review["expected_count"] == 75
    ningbo_2022_review = next(
        source
        for source in lifecycle_sources
        if source["source_id"]
        == "national-small-giant-2022-first-review-ningbo-publicity"
    )
    assert ningbo_2022_review["expected_count"] == 4
    assert ningbo_2022_review["city"] == "宁波市"
    hangzhou_2023_first = next(
        source
        for source in lifecycle_sources
        if source["source_id"]
        == "zhejiang-specialized-sme-2023-first-hangzhou-final-crosscheck"
    )
    assert hangzhou_2023_first["expected_count"] == 676
    assert hangzhou_2023_first["entity_extraction"] == "structured_entities_json"


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


def test_supplemental_final_events_preserve_source_name_and_review_cohort(tmp_path):
    path = tmp_path / "supplemental.jsonl"
    row = {
        "enterprise_name": "钱潮轴承有限公司-1005600",
        "project_name": "浙江省专精特新中小企业",
        "event_year": 2025,
        "cohort_year": 2022,
        "event_type": "review_passed",
        "event_scope": "qualification",
        "evidence_status": "official_final_list",
        "batch": "第二批",
        "status": "复核通过",
        "recognition_province": "浙江省",
        "recognition_city": "",
        "recognition_county": "",
        "source_title": "浙经信企业〔2026〕4号",
        "source_path": "/tmp/source.pdf",
        "source_url": "",
        "sequence_no": "233",
        "source_kind": "official_final_list_user_attachment",
    }
    path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    rules = {
        "浙江省专精特新中小企业": {
            "rule_id": "zhejiang-specialized-sme",
            "cycle_type": "qualification_review",
            "validity_years": 3,
        }
    }
    aliases = {
        MODULE.normalize_name("浙江省专精特新中小企业"): "浙江省专精特新中小企业"
    }
    events = {}
    loaded = MODULE.load_supplemental_events(path, events, rules, aliases)
    assert loaded == 1
    event = next(iter(events.values()))
    assert event["enterprise_name_at_event"] == "钱潮轴承有限公司-1005600"
    assert event["event_type"] == "review_passed"
    assert event["cohort_year"] == 2022
    assert event["evidence_status"] == "official_final_list"
    assert MODULE.supplemental_source_basenames(path) == {"source.pdf"}


def test_generic_list_loader_skips_curated_supplemental_document(tmp_path):
    database = tmp_path / "test.sqlite3"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE documents(
          id INTEGER PRIMARY KEY,
          document_role TEXT,
          region TEXT,
          title TEXT,
          source TEXT,
          cloud_path TEXT,
          canonical_project_name TEXT,
          policy_year INTEGER
        );
        CREATE TABLE public_list_entities(
          id INTEGER PRIMARY KEY,
          document_id INTEGER,
          enterprise_name TEXT,
          sequence_no TEXT,
          canonical_project_name TEXT,
          policy_year INTEGER,
          batch TEXT,
          region TEXT,
          list_status TEXT
        );
        """
    )
    connection.execute(
        "INSERT INTO documents VALUES(1,?,?,?,?,?,?,?)",
        (
            "50_名单与对标",
            "浙江省",
            "浙经信企业〔2026〕4号",
            "",
            "50_名单与对标/source.pdf",
            "浙江省专精特新中小企业",
            2026,
        ),
    )
    connection.execute(
        "INSERT INTO public_list_entities VALUES(1,1,?,?,?,?,?,?,?)",
        (
            "测试企业有限公司",
            "1",
            "浙江省专精特新中小企业",
            2026,
            "第二批",
            "浙江省",
            "认定名单",
        ),
    )
    connection.commit()
    connection.close()
    events = {}
    MODULE.load_list_events(database, events, {}, {}, set(), {"source.pdf"})
    assert events == {}
