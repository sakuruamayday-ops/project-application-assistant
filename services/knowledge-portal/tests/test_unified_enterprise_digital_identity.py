import importlib.util
import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = ROOT / "scripts" / "build_unified_enterprise_digital_identity.py"
LOOKUP_PATH = ROOT / "app" / "enterprise_identity_lineage.py"
LINEAGE_BUILDER_PATH = ROOT / "scripts" / "build_enterprise_identity_lineage.py"


def load_module(path: Path, name: str):
    specification = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(specification)
    assert specification and specification.loader
    specification.loader.exec_module(module)
    return module


BUILDER = load_module(BUILDER_PATH, "unified_enterprise_identity_builder")
LOOKUP = load_module(LOOKUP_PATH, "unified_enterprise_identity_lookup")
LINEAGE_BUILDER = load_module(LINEAGE_BUILDER_PATH, "unified_identity_lineage_builder")


def test_identity_evidence_is_not_mislabeled_as_business_profile_evidence():
    assert BUILDER.has_business_profile_data(
        {
            "current_name": "只有身份信息有限公司",
            "unified_social_credit_code": "91330100123456789X",
        }
    ) is False
    assert BUILDER.has_business_profile_data(
        {"current_name": "有产品信息有限公司", "main_product_tags": ["工业机器人"]}
    ) is True


def make_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE enterprise_identity_profiles(
            identity_key TEXT PRIMARY KEY,
            unified_social_credit_code TEXT NOT NULL,
            current_name TEXT NOT NULL,
            verification_status TEXT NOT NULL,
            recognition_projects_json TEXT NOT NULL,
            project_lifecycles_json TEXT NOT NULL
        );
        INSERT INTO enterprise_identity_profiles VALUES
          ('913301001111111111','913301001111111111','甲机器人有限公司','knowledge_verified',
           '["浙江省专精特新中小企业"]','[]'),
          ('913301003333333333','913301003333333333','丙装备有限公司','knowledge_verified',
           '["浙江省制造业首台（套）装备"]','[]');
        CREATE TABLE enterprise_identity_names(
            id INTEGER PRIMARY KEY,
            identity_key TEXT NOT NULL,
            alias_name TEXT NOT NULL,
            alias_type TEXT NOT NULL,
            valid_from TEXT NOT NULL DEFAULT '',
            valid_to TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE small_giant_enterprise_identity_profiles(
            identity_key TEXT PRIMARY KEY,
            unified_social_credit_code TEXT NOT NULL,
            current_name TEXT NOT NULL,
            verification_status TEXT NOT NULL,
            profile_json TEXT NOT NULL,
            captured_at TEXT NOT NULL
        );
        CREATE TABLE three_first_project_awards(
            enterprise_key TEXT NOT NULL,
            enterprise_name TEXT NOT NULL,
            enterprise_aliases TEXT NOT NULL,
            province TEXT NOT NULL,
            city TEXT NOT NULL,
            county TEXT NOT NULL,
            project_name TEXT NOT NULL,
            year INTEGER,
            product_name TEXT NOT NULL,
            recognition_tier TEXT NOT NULL,
            product_category TEXT NOT NULL,
            list_status TEXT NOT NULL
        );
        INSERT INTO three_first_project_awards VALUES(
          'c-key','丙装备有限公司','[]','浙江省','杭州市','萧山区',
          '浙江省制造业首台（套）装备',2025,'高速精密加工中心','省级','数控机床','final_recognition'
        );
        CREATE TABLE enterprise_identity_lineage_nodes(
            node_id TEXT PRIMARY KEY, master_identity_key TEXT NOT NULL,
            node_type TEXT NOT NULL, node_value TEXT NOT NULL,
            normalized_value TEXT NOT NULL, verification_status TEXT NOT NULL,
            source TEXT NOT NULL
        );
        CREATE TABLE enterprise_identity_lineage_edges(
            edge_id TEXT PRIMARY KEY, master_identity_key TEXT NOT NULL,
            from_node_id TEXT NOT NULL, to_node_id TEXT NOT NULL,
            from_node_type TEXT NOT NULL, to_node_type TEXT NOT NULL,
            from_value TEXT NOT NULL, to_value TEXT NOT NULL,
            relation_type TEXT NOT NULL, unified_social_credit_code TEXT NOT NULL,
            verification_status TEXT NOT NULL, source TEXT NOT NULL
        );
        INSERT INTO enterprise_identity_lineage_nodes VALUES
          ('subject:a','913301001111111111','identity_subject','913301001111111111',
           '913301001111111111','knowledge_verified','共创研究院知识库'),
          ('current:a','913301001111111111','current_name','甲机器人有限公司',
           '甲机器人有限公司','knowledge_verified','共创研究院知识库'),
          ('code:a','913301001111111111','unified_social_credit_code','913301001111111111',
           '913301001111111111','knowledge_verified','共创研究院知识库');
        INSERT INTO enterprise_identity_lineage_edges VALUES
          ('e1','913301001111111111','subject:a','current:a','identity_subject','current_name',
           '913301001111111111','甲机器人有限公司','current_name','913301001111111111',
           'knowledge_verified','共创研究院知识库'),
          ('e2','913301001111111111','subject:a','code:a','identity_subject','unified_social_credit_code',
           '913301001111111111','913301001111111111','unified_social_credit_code','913301001111111111',
           'knowledge_verified','共创研究院知识库');
        """
    )
    candidate = {
        "identity_key": "913201002222222222",
        "unified_social_credit_code": "913201002222222222",
        "current_name": "乙智能制造有限公司",
        "company_introduction": "通过企知道大数据分析，该企业从事工业机器人系统集成",
        "business_scope": "工业机器人研发、生产与销售",
        "main_product_tags": ["工业机器人"],
        "industry_track_tags": ["机器视觉"],
        "source_provider": "不得进入公共投影",
    }
    connection.execute(
        "INSERT INTO small_giant_enterprise_identity_profiles VALUES(?,?,?,?,?,?)",
        (
            candidate["identity_key"], candidate["unified_social_credit_code"],
            candidate["current_name"], "audited_single_source_candidate",
            json.dumps(candidate, ensure_ascii=False), "2026-08-09T00:00:00+08:00",
        ),
    )
    connection.commit()
    connection.close()


def write_snapshot(path: Path) -> None:
    rows = [
        {
            "identity_key": "913301001111111111",
            "unified_social_credit_code": "913301001111111111",
            "current_name": "甲机器人有限公司",
            "former_names": ["甲自动化有限公司"],
            "company_introduction": "工业机器人本体与系统研发企业",
            "business_scope": "工业机器人研发、生产与销售",
            "main_product_tags": ["工业机器人"],
            "industry_track_tags": ["机器视觉"],
            "recognition_projects": ["国家专精特新“小巨人”企业"],
            "knowledge_verification_status": "knowledge_verified",
        },
        {
            "identity_key": "913301003333333333",
            "unified_social_credit_code": "913301003333333333",
            "current_name": "丙装备有限公司",
            "company_introduction": "精密数控装备制造企业",
            "business_scope": "数控机床研发、生产与销售",
            "main_product_tags": ["高速加工中心"],
            "industry_track_tags": ["数控机床"],
            "knowledge_verification_status": "knowledge_verified",
        },
    ]
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_builder_preserves_evidence_layers_and_enriches_three_first(tmp_path: Path):
    database = tmp_path / "knowledge.sqlite3"
    snapshot = tmp_path / "identities.jsonl"
    output = tmp_path / "unified.jsonl"
    make_database(database)
    write_snapshot(snapshot)

    report = BUILDER.build(database, snapshot, output)

    assert report["unified_profiles"] == 3
    assert report["peer_ready_profiles"] == 2
    assert report["three_first_enriched_profiles"] == 1
    assert report["coverage"]["specialized_sme_peer_comparison"] == {
        "total_subjects": 1,
        "ready_subjects": 1,
        "missing_profile_subjects": 0,
    }
    assert report["coverage"]["small_giant_peer_comparison"] == {
        "total_subjects": 2,
        "ready_subjects": 2,
        "missing_profile_subjects": 0,
    }
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    specialized = connection.execute(
        "SELECT * FROM enterprise_unified_digital_identities WHERE identity_key=?",
        ("913301001111111111",),
    ).fetchone()
    assert set(json.loads(specialized["recognition_projects_json"])) == {
        "浙江省专精特新中小企业",
        "国家专精特新“小巨人”企业",
    }
    candidate = connection.execute(
        "SELECT * FROM enterprise_unified_digital_identities WHERE identity_key=?",
        ("913201002222222222",),
    ).fetchone()
    assert candidate["identity_verification_status"] == "audited_single_source_candidate"
    assert candidate["business_profile_evidence_status"] == "audited_single_source_candidate"
    assert candidate["recognition_evidence_status"] == "knowledge_list_linked"
    three_first = connection.execute(
        "SELECT * FROM enterprise_unified_digital_identities WHERE identity_key=?",
        ("913301003333333333",),
    ).fetchone()
    assert json.loads(three_first["three_first_products_json"])[0]["product_name"] == "高速精密加工中心"
    assert three_first["three_first_product_enriched"] == 1
    assert {row[0] for row in connection.execute(
        "SELECT DISTINCT source FROM enterprise_peer_comparison_terms"
    )} == {"共创研究院知识库"}
    connection.close()
    projection = output.read_text(encoding="utf-8")
    assert "不得进入公共投影" not in projection
    assert "企知道" not in projection
    assert all(
        json.loads(line)["source"] == "共创研究院知识库"
        for line in projection.splitlines()
    )


def test_identity_lookup_returns_profile_and_cross_program_peers(tmp_path: Path):
    database = tmp_path / "knowledge.sqlite3"
    snapshot = tmp_path / "identities.jsonl"
    make_database(database)
    write_snapshot(snapshot)
    BUILDER.build(database, snapshot, None)

    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    result = LOOKUP.lookup_identity_lineage(connection, "甲机器人有限公司")
    connection.close()

    assert result["result_count"] == 1
    item = result["results"][0]
    assert item["business_profile"]["peer_comparison_ready"] is True
    assert set(item["business_profile"]["recognition_projects"]) == {
        "浙江省专精特新中小企业",
        "国家专精特新“小巨人”企业",
    }
    assert item["peer_comparison"]["ready"] is True
    assert item["peer_comparison"]["peers"][0]["name"] == "乙智能制造有限公司"
    assert item["peer_comparison"]["peers"][0]["business_profile_evidence_status"] == (
        "audited_single_source_candidate"
    )
    assert item["peer_comparison"]["peers"][0]["recognition_evidence_status"] == (
        "knowledge_list_linked"
    )
    assert result["profile_coverage"]["three_first_enterprise_enrichment"][
        "missing_profile_subjects"
    ] == 0
    serialized = json.dumps(result, ensure_ascii=False)
    assert "source_provider" not in serialized
    assert "不得进入公共投影" not in serialized


def test_lineage_builder_adds_nationwide_profiles_not_in_zhejiang_timeline(tmp_path: Path):
    database = tmp_path / "knowledge.sqlite3"
    snapshot = tmp_path / "identities.jsonl"
    make_database(database)
    write_snapshot(snapshot)
    BUILDER.build(database, snapshot, None)

    rows = LINEAGE_BUILDER.build_lineage_rows(database, snapshot)
    nationwide = next(
        row for row in rows if row["identity_key"] == "913201002222222222"
    )

    assert nationwide["current_name"] == "乙智能制造有限公司"
    assert nationwide["unified_social_credit_code"] == "913201002222222222"
    assert nationwide["entity_resolution_status"] == "audited_single_source_candidate"
    assert {edge["relation_type"] for edge in nationwide["edges"]} >= {
        "current_name",
        "unified_social_credit_code",
    }
