import sqlite3
from contextlib import closing

from scripts.build_knowledge_content_index import create_database
from scripts.build_knowledge_content_index import infer_document_metadata
from scripts.upgrade_structured_knowledge_index import upgrade_database
from scripts.evaluate_structured_knowledge import DEFAULT_GOLD_SET, evaluate, load_cases


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

    assert old_sme["validity_status"] == "superseded"
    assert "2026" in old_sme["replacement_title"]
    assert current_sme["validity_status"] == "active_candidate"
    assert old_provincial_rd["validity_status"] == "superseded"
    assert old_provincial_rd["replacement_title"] == "浙江省企业研究院"
    assert current_hangzhou["validity_status"] == "active_candidate"
    assert hangzhou_draft["validity_status"] == "draft"


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
