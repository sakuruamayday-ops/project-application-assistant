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


def test_qcc_requirement_is_independent_from_evidence_grade():
    audited_ready = {
        "identity_verification_status": "audited_single_source_candidate",
        "recognition_projects": ["国家专精特新“小巨人”企业"],
        "peer_comparison_ready": 1,
    }
    assert BUILDER.qcc_requirement(audited_ready) == (0, [])

    exempt_pending = {
        "identity_verification_status": "pending_business_identity",
        "recognition_projects": ["浙江制造精品", "地方科技小巨人企业"],
        "peer_comparison_ready": 0,
    }
    assert BUILDER.qcc_requirement(exempt_pending) == (0, [])

    mixed_pending = {
        "identity_verification_status": "pending_business_identity",
        "recognition_projects": ["浙江制造精品", "浙江省专精特新中小企业"],
        "peer_comparison_ready": 0,
    }
    assert BUILDER.qcc_requirement(mixed_pending) == (
        1,
        ["identity_resolution_pending", "peer_profile_incomplete"],
    )


def test_temporal_identity_candidates_reject_subject_founded_after_award():
    profiles = {
        "old": {"founded_date": "2011-04-19"},
        "new": {"founded_date": "2024-08-01"},
    }
    assert BUILDER.temporal_identity_candidates(
        profiles, {"old", "new"}, 2020
    ) == {"old"}
    assert BUILDER.temporal_identity_candidates(
        profiles, {"old", "new"}, 2025
    ) == {"old", "new"}


def test_collapse_unambiguous_name_only_profile_preserves_ambiguous_alias():
    profiles = {
        "code-a": BUILDER.empty_profile("code-a", "现名甲有限公司"),
        "code-b": BUILDER.empty_profile("code-b", "同名乙有限公司"),
        "name:old-a": BUILDER.empty_profile("name:old-a", "旧名甲有限公司"),
        "name:ambiguous": BUILDER.empty_profile(
            "name:ambiguous", "共同旧名有限公司"
        ),
    }
    profiles["code-a"]["unified_social_credit_code"] = "913301001111111111"
    profiles["code-a"]["former_names"] = [
        "旧名甲有限公司", "共同旧名有限公司"
    ]
    profiles["code-b"]["unified_social_credit_code"] = "913301002222222222"
    profiles["code-b"]["former_names"] = ["共同旧名有限公司"]
    stats = BUILDER.defaultdict(int)

    BUILDER.collapse_unambiguous_name_only_profiles(profiles, stats)

    assert "name:old-a" not in profiles
    assert "旧名甲有限公司" in profiles["code-a"]["recognition_names"]
    assert "name:ambiguous" in profiles
    assert stats["unambiguous_name_only_profiles_collapsed"] == 1
    assert stats["ambiguous_name_only_profiles_retained"] == 1


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


def write_business_profile_candidates(path: Path) -> None:
    rows = [
        {
            "identity_key": "913201002222222222",
            "unified_social_credit_code": "913201002222222222",
            "current_name": "乙智能制造有限公司",
            "former_names": ["乙数字工程有限公司"],
            "recognition_names": ["乙智能制造有限公司"],
            "company_introduction": "工业机器人系统集成企业",
            "business_scope": "工业机器人研发、生产与销售",
            "main_product_tags": ["工业机器人"],
            "industry_track_tags": ["机器视觉"],
            "recognition_projects": ["国家专精特新“小巨人”企业"],
            "identity_verification_status": "candidate_alias_closed",
            "business_profile_evidence_status": "candidate_profile_complete",
            "recognition_evidence_status": "knowledge_list_linked",
            "peer_comparison_ready": 1,
            "source": "共创研究院知识库",
            "merged_source_identity_keys": ["913201002222222222"],
        },
        {
            "identity_key": "913301004444444444",
            "unified_social_credit_code": "913301004444444444",
            "current_name": "丁听力科技有限公司",
            "company_introduction": "听力设备研发企业",
            "business_scope": "助听设备研发与销售",
            "main_product_tags": [],
            "industry_track_tags": ["助听器"],
            "recognition_projects": ["浙江省专精特新中小企业"],
            "identity_verification_status": "knowledge_verified",
            "business_profile_evidence_status": "candidate_profile_partial",
            "recognition_evidence_status": "knowledge_list_linked",
            "peer_comparison_ready": 0,
            "source": "共创研究院知识库",
            "merged_source_identity_keys": ["913301004444444444"],
        },
    ]
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def write_theme_enrichment_candidates(path: Path) -> None:
    rows = [
        {
            "identity_key": "913301003333333333",
            "current_name": "丙装备有限公司",
            "match_status": "exact_enterprise_name",
            "candidate_main_product_tags": ["精密加工中心"],
            "candidate_industry_track_tags": ["金属切削机床制造"],
            "source": "共创研究院知识库",
        },
        {
            "identity_key": "name:错误产品名",
            "current_name": "错误产品名",
            "match_status": "product_name_candidate",
            "candidate_main_product_tags": ["不得自动合并"],
            "candidate_industry_track_tags": ["制造业"],
            "source": "共创研究院知识库",
        },
    ]
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_builder_promotes_audited_delta_and_preserves_partial_queue(tmp_path: Path):
    database = tmp_path / "knowledge.sqlite3"
    snapshot = tmp_path / "identities.jsonl"
    candidates = tmp_path / "business-profile-candidates.jsonl"
    make_database(database)
    write_snapshot(snapshot)
    write_business_profile_candidates(candidates)
    connection = sqlite3.connect(database)
    connection.execute(
        "INSERT INTO three_first_project_awards VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "candidate-alias",
            "乙数字工程有限公司",
            "[]",
            "浙江省",
            "杭州市",
            "滨江区",
            "浙江省首版次软件产品",
            2024,
            "乙工业软件V1.0",
            "省级",
            "工业软件",
            "final_recognition",
        ),
    )
    connection.commit()
    connection.close()

    report = BUILDER.build(database, snapshot, None, candidates)

    assert report["promoted_business_profile_candidates"] == 2
    assert report["promoted_complete_business_profiles"] == 1
    assert report["promoted_partial_business_profiles"] == 1
    assert report["coverage"]["specialized_sme_peer_comparison"] == {
        "total_subjects": 2,
        "ready_subjects": 1,
        "missing_profile_subjects": 1,
    }
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    promoted = connection.execute(
        "SELECT * FROM enterprise_unified_digital_identities WHERE identity_key=?",
        ("913201002222222222",),
    ).fetchone()
    assert promoted["identity_verification_status"] == "knowledge_alias_closed"
    assert promoted["business_profile_evidence_status"] == "knowledge_profile_complete"
    assert promoted["three_first_product_enriched"] == 1
    assert "乙数字工程有限公司" in json.loads(promoted["former_names_json"])
    assert connection.execute(
        "SELECT COUNT(*) FROM enterprise_unified_digital_identities WHERE current_name=?",
        ("乙数字工程有限公司",),
    ).fetchone()[0] == 0
    partial = connection.execute(
        "SELECT * FROM enterprise_unified_digital_identities WHERE identity_key=?",
        ("913301004444444444",),
    ).fetchone()
    assert partial["business_profile_evidence_status"] == "knowledge_profile_partial"
    assert partial["peer_comparison_ready"] == 0
    assert partial["requires_qcc"] == 1
    assert json.loads(partial["qcc_requirement_reasons_json"]) == [
        "peer_profile_incomplete"
    ]
    assert connection.execute(
        "SELECT COUNT(*) FROM enterprise_profile_enrichment_queue WHERE identity_key=?",
        ("913301004444444444",),
    ).fetchone()[0] == 1
    connection.close()


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
    assert candidate["requires_qcc"] == 0
    assert json.loads(candidate["qcc_requirement_reasons_json"]) == []
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


def test_theme_enrichment_applies_exact_names_and_builds_empty_topic_queue(
    tmp_path: Path,
):
    database = tmp_path / "knowledge.sqlite3"
    snapshot = tmp_path / "identities.jsonl"
    themes = tmp_path / "theme-candidates.jsonl"
    make_database(database)
    write_snapshot(snapshot)
    write_theme_enrichment_candidates(themes)

    report = BUILDER.build(database, snapshot, None, None, themes)

    assert report["theme_enrichment_profiles"] == 1
    assert report["coverage"]["topic_enrichment"] == {
        "total_subjects": 3,
        "ready_subjects": 3,
        "missing_profile_subjects": 0,
    }
    connection = sqlite3.connect(database)
    enriched = connection.execute(
        "SELECT main_product_tags_json,industry_track_tags_json "
        "FROM enterprise_unified_digital_identities WHERE identity_key=?",
        ("913301003333333333",),
    ).fetchone()
    connection.close()
    assert "精密加工中心" in json.loads(enriched[0])
    assert "金属切削机床制造" in json.loads(enriched[1])


def test_batch_profile_provenance_merges_aliases_and_excludes_reviewed_noise(
    tmp_path: Path,
):
    database = tmp_path / "knowledge.sqlite3"
    provenance = tmp_path / "batch-provenance.jsonl"
    review = tmp_path / "batch-review.jsonl"
    connection = sqlite3.connect(database)
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
          ('name:旧名企业','', '旧名企业有限公司','pending_business_identity',
           '["浙江省专精特新中小企业"]','[]'),
          ('name:噪声','', 'BFL2030H 动柱高速铣削中心','pending_business_identity',
           '["浙江省制造业首台（套）装备"]','[]');
        """
    )
    connection.commit()
    connection.close()
    provenance.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False) + "\n"
            for row in [
                {
                    "identity_key": "913301001111111111",
                    "unified_social_credit_code": "913301001111111111",
                    "current_name": "现名企业有限公司",
                    "imported_names": ["旧名企业有限公司"],
                    "observed_current_names": ["现名企业有限公司"],
                    "former_names": [],
                    "company_introduction": "工业装备制造企业",
                    "business_scope": "工业装备研发制造",
                    "main_product_tags": ["工业装备"],
                    "industry_track_tags": ["装备制造"],
                    "identity_candidate_status": "accepted_reviewed_alias",
                    "source": "共创研究院知识库",
                    "captured_at": "20260811",
                },
                {
                    "identity_key": "913301002222222222",
                    "unified_social_credit_code": "913301002222222222",
                    "current_name": "新增企业有限公司",
                    "imported_names": ["新增企业有限公司"],
                    "observed_current_names": ["新增企业有限公司"],
                    "former_names": [],
                    "company_introduction": "新材料企业",
                    "business_scope": "新材料研发制造",
                    "main_product_tags": ["新材料"],
                    "industry_track_tags": ["材料制造"],
                    "identity_candidate_status": "accepted_exact_current_name",
                    "source": "共创研究院知识库",
                    "captured_at": "20260811",
                },
                {
                    "identity_key": "91370785MA3X04GX5J",
                    "unified_social_credit_code": "91370785MA3X04GX5J",
                    "current_name": "高密市文利铣床销售中心",
                    "imported_names": ["BFL2030H 动柱高速铣削中心"],
                    "observed_current_names": ["高密市文利铣床销售中心"],
                    "former_names": [],
                    "identity_candidate_status": "excluded_unrelated_return",
                    "source": "共创研究院知识库",
                    "captured_at": "20260811",
                },
            ]
        ),
        encoding="utf-8",
    )
    review.write_text(
        json.dumps(
            {
                "master_name": "BFL2030H 动柱高速铣削中心",
                "decision": "exclude_unrelated_return",
                "exclude_from_unified_master": True,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    report = BUILDER.build(
        database,
        tmp_path / "missing-snapshot.jsonl",
        None,
        None,
        None,
        provenance,
        review,
    )

    assert report["batch_profile_provenance_subjects"] == 3
    assert report["batch_profile_accepted_subjects"] == 2
    assert report["batch_profile_manual_or_excluded_subjects"] == 1
    assert report["batch_profile_alias_rows_merged"] == 1
    assert report["batch_profile_new_subjects"] == 1
    assert report["reviewed_non_enterprise_master_rows_excluded"] == 1
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        "SELECT * FROM enterprise_unified_digital_identities ORDER BY identity_key"
    ).fetchall()
    connection.close()
    assert [row["identity_key"] for row in rows] == [
        "913301001111111111",
        "913301002222222222",
    ]
    renamed = rows[0]
    assert renamed["current_name"] == "现名企业有限公司"
    assert "旧名企业有限公司" in json.loads(renamed["recognition_names_json"])
    assert "浙江省专精特新中小企业" in json.loads(
        renamed["recognition_projects_json"]
    )
    assert renamed["identity_verification_status"] == (
        "licensed_batch_identity_candidate"
    )
    assert renamed["recognition_evidence_status"] == "knowledge_list_linked"


def test_identity_closure_patches_keep_candidate_honors_out_of_project_scope(
    tmp_path: Path,
):
    database = tmp_path / "knowledge.sqlite3"
    snapshot = tmp_path / "identities.jsonl"
    patches = tmp_path / "identity-closure-patches.jsonl"
    make_database(database)
    write_snapshot(snapshot)
    rows = [
        {
            "schema_version": "enterprise-identity-closure-candidate-v1",
            "patch_type": "small_giant_recognition_closure",
            "candidate_only": True,
            "production_promoted": False,
            "source": "共创研究院知识库",
            "identity_key": "913301001111111111",
            "unified_social_credit_code": "913301001111111111",
            "current_name": "甲机器人有限公司",
            "recognition_name": "甲自动化有限公司",
            "recognition_project": "国家专精特新“小巨人”企业",
            "recognition_region": "浙江省",
            "recognition_year": "2022",
            "recognition_evidence_status": "knowledge_list_linked",
            "identity_verification_status": "knowledge_alias_closed",
            "closure_basis": "统一代码一致＋名称链一致",
            "lineage_verification_method": "已闭合现名和曾用名链",
            "lineage_evidence_urls": [],
        },
        {
            "schema_version": "enterprise-identity-closure-candidate-v1",
            "patch_type": "small_giant_recognition_closure",
            "candidate_only": True,
            "production_promoted": False,
            "source": "共创研究院知识库",
            "identity_key": "913301003333333333",
            "unified_social_credit_code": "913301003333333333",
            "current_name": "丙装备有限公司",
            "recognition_name": "丙装备有限公司",
            "recognition_project": "国家专精特新“小巨人”企业",
            "recognition_region": "浙江省",
            "recognition_year": "2023",
            "recognition_evidence_status": "knowledge_list_linked",
            "identity_verification_status": "knowledge_alias_closed",
            "closure_basis": "单源荣誉候选",
            "lineage_verification_method": "主体已闭合，项目尚未闭合",
            "lineage_evidence_urls": [],
        },
        {
            "schema_version": "enterprise-identity-closure-candidate-v1",
            "patch_type": "profile_topic_inference",
            "candidate_only": True,
            "production_promoted": False,
            "source": "共创研究院知识库",
            "identity_key": "913301003333333333",
            "unified_social_credit_code": "913301003333333333",
            "current_name": "丙装备有限公司",
            "inference_scope": "产品主题，不生成具体产品型号",
            "main_product_tags": ["精密加工中心"],
            "business_profile_evidence_status": "knowledge_profile_inferred",
            "peer_comparison_ready": 1,
        },
        {
            "schema_version": "enterprise-identity-closure-candidate-v1",
            "patch_type": "peer_comparison_ready_flag_repair",
            "candidate_only": True,
            "production_promoted": False,
            "source": "共创研究院知识库",
            "identity_key": "913301003333333333",
            "unified_social_credit_code": "913301003333333333",
            "current_name": "丙装备有限公司",
            "peer_comparison_ready": 1,
        },
        {
            "schema_version": "enterprise-identity-closure-candidate-v1",
            "patch_type": "false_recognition_quarantine",
            "candidate_only": True,
            "production_promoted": False,
            "source": "共创研究院知识库",
            "identity_key": "913301003333333333",
            "unified_social_credit_code": "913301003333333333",
            "current_name": "丙装备有限公司",
            "preserve_enterprise_identity": True,
            "remove_recognition_names": [],
            "remove_recognition_projects": ["浙江省制造业首台（套）装备"],
        },
    ]
    patches.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in rows),
        encoding="utf-8",
    )

    report = BUILDER.build(
        database,
        snapshot,
        None,
        identity_closure_patches=patches,
    )

    assert report["identity_closure_patch_records_promoted"] == 5
    assert report["small_giant_closure_existing_project_rows"] == 1
    assert report["small_giant_closure_candidate_only_project_rows"] == 1
    assert report["peer_comparison_ready_patches_promoted"] == 1
    assert report["profile_topic_inference_patches_promoted"] == 1
    assert report["false_recognition_relationships_quarantined"] == 1
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    existing = connection.execute(
        "SELECT recognition_names_json FROM enterprise_unified_digital_identities "
        "WHERE identity_key='913301001111111111'"
    ).fetchone()
    candidate_only = connection.execute(
        "SELECT recognition_projects_json,peer_comparison_ready "
        "FROM enterprise_unified_digital_identities "
        "WHERE identity_key='913301003333333333'"
    ).fetchone()
    promotion_scope = connection.execute(
        "SELECT recognition_year,project_scope_included "
        "FROM enterprise_identity_closure_promotions ORDER BY recognition_year"
    ).fetchall()
    connection.close()
    assert "甲自动化有限公司" in json.loads(
        existing["recognition_names_json"]
    )
    assert "国家专精特新“小巨人”企业" not in json.loads(
        candidate_only["recognition_projects_json"]
    )
    assert candidate_only["peer_comparison_ready"] == 1
    assert [(row["recognition_year"], row["project_scope_included"]) for row in promotion_scope] == [
        ("2022", 1),
        ("2023", 0),
    ]


def test_qizhidao_queue_reuse_closes_without_new_external_query(tmp_path: Path):
    database = tmp_path / "knowledge.sqlite3"
    snapshot = tmp_path / "identities.jsonl"
    queue = tmp_path / "qizhidao-reuse.jsonl"
    make_database(database)
    write_snapshot(snapshot)
    queue.write_text(
        json.dumps(
            {
                "schema_version": "enterprise-source-alias-merge-candidate-v1",
                "patch_type": "deferred_qizhidao_queue_local_master_reuse",
                "candidate_only": True,
                "production_promoted": False,
                "source": "共创研究院知识库",
                "master_identity_key": "913301001111111111",
                "unified_social_credit_code": "913301001111111111",
                "current_name": "甲机器人有限公司",
                "source_enterprise_name": "甲机器人有限公司",
                "source_identity_keys": ["qice:test-subject"],
                "match_method": "normalized_name_unique_exact_match",
                "business_profile_reuse_status": "knowledge_verified",
                "identity_verification_status": "knowledge_alias_closed",
                "peer_comparison_ready": 1,
                "qizhidao_requery_required": False,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    report = BUILDER.build(
        database,
        snapshot,
        None,
        qizhidao_queue_reuse_candidates=queue,
    )

    assert report["qizhidao_queue_local_master_reuse_promoted"] == 1
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    resolution = connection.execute(
        "SELECT * FROM enterprise_qizhidao_queue_resolutions"
    ).fetchone()
    connection.close()
    assert resolution["identity_key"] == "913301001111111111"
    assert resolution["qizhidao_requery_required"] == 0
    assert resolution["resolution_status"] == "local_master_reused"
    assert json.loads(resolution["source_identity_keys_json"]) == ["qice:test-subject"]


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
    assert item["business_profile"]["requires_qcc"] is False
    assert item["business_profile"]["qcc_requirement_reasons"] == []
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
