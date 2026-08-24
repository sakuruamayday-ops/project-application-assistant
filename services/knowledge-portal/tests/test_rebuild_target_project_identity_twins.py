from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

from app.project_identity_twin import next_state, replay_steps


PORTAL_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = (
    PORTAL_DIR / "scripts" / "rebuild_target_project_identity_twins.py"
)
SPEC = importlib.util.spec_from_file_location("target_twin_rebuild", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_candidate_database_guards_configured_active_index(
    tmp_path: Path, monkeypatch
) -> None:
    index_root = tmp_path / "indexes"
    current = index_root / "current"
    current.mkdir(parents=True)
    database = current / "knowledge_content.sqlite3"
    database.write_bytes(b"sqlite")
    monkeypatch.setenv("JIAOTANG_INDEX_DIR", str(index_root))

    try:
        MODULE.ensure_candidate_database(database, allow_active=False)
    except RuntimeError as error:
        assert "禁止直接修改活动索引" in str(error)
    else:
        raise AssertionError("配置的活动索引必须保持写保护")


def test_large_candidate_database_only_blocks_explicit_synced_roots(
    tmp_path: Path, monkeypatch
) -> None:
    synced_root = tmp_path / "synced"
    local_root = tmp_path / "local"
    synced_root.mkdir()
    local_root.mkdir()
    synced_database = synced_root / "knowledge_content.sqlite3"
    local_database = local_root / "knowledge_content.sqlite3"
    synced_database.write_bytes(b"sqlite")
    local_database.write_bytes(b"sqlite")
    monkeypatch.setattr(MODULE, "DEFAULT_MAX_SYNCED_CANDIDATE_BYTES", 1)
    monkeypatch.setenv("JIAOTANG_SYNCED_ROOTS", str(synced_root))

    try:
        MODULE.ensure_candidate_database(synced_database, allow_active=False)
    except RuntimeError as error:
        assert "明确配置的同步目录" in str(error)
    else:
        raise AssertionError("大型候选库位于明确同步目录时必须失败关闭")

    MODULE.ensure_candidate_database(local_database, allow_active=False)


def create_twin_tables(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE enterprise_project_identity_twins(
            twin_id TEXT PRIMARY KEY,
            identity_key TEXT NOT NULL,
            project_name TEXT NOT NULL,
            lifecycle_rule_id TEXT NOT NULL,
            policy_version_id TEXT NOT NULL,
            current_state TEXT NOT NULL,
            current_as_of_year INTEGER,
            trace_hash TEXT NOT NULL,
            identity_match_json TEXT NOT NULL,
            policy_version_json TEXT NOT NULL,
            list_attachment_trace_json TEXT NOT NULL,
            coverage_trace_json TEXT NOT NULL,
            lifecycle_trace_json TEXT NOT NULL,
            replayable_years_json TEXT NOT NULL
        );
        CREATE TABLE enterprise_project_identity_twin_steps(
            twin_id TEXT NOT NULL,
            identity_key TEXT NOT NULL,
            project_name TEXT NOT NULL,
            step INTEGER NOT NULL,
            event_year INTEGER,
            event_type TEXT NOT NULL,
            previous_state TEXT NOT NULL,
            next_state TEXT NOT NULL,
            reason TEXT NOT NULL,
            evidence_hash TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY(twin_id,step)
        );
        """
    )


def insert_existing_twin(
    connection: sqlite3.Connection,
    twin_id: str,
    identity_key: str,
    project_name: str,
) -> None:
    connection.execute(
        "INSERT INTO enterprise_project_identity_twins VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            twin_id,
            identity_key,
            project_name,
            "rule",
            "policy",
            "active",
            2025,
            "trace",
            "{}",
            "{}",
            "[]",
            "[]",
            "[]",
            "[]",
        ),
    )
    connection.execute(
        "INSERT INTO enterprise_project_identity_twin_steps VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            twin_id,
            identity_key,
            project_name,
            1,
            2025,
            "recognition",
            "not_recorded",
            "active",
            "existing",
            "existing-hash",
            "{}",
        ),
    )


def test_source_lineage_wins_over_shared_historical_name():
    profiles = {
        "old": {"founded_date": "2013-10-22"},
        "other": {"founded_date": "1995-03-13"},
    }
    memberships = {
        ("old", "浙江省专精特新中小企业"),
        ("other", "浙江省专精特新中小企业"),
    }
    aliases = {"浙江蓝天制衣有限公司": {"old", "other"}}
    title = "2023年度第一批浙江省专精特新中小企业正式名单"
    source_names = {
        ("old", "浙江蓝天制衣有限公司"): [title],
        ("other", "浙江蓝天制衣有限公司"): ["共创研究院知识库"],
    }
    identity_key, method, candidates = MODULE.resolve_record_identity(
        {
            "project_name": "浙江省专精特新中小企业",
            "enterprise_name_at_recognition": "浙江蓝天制衣有限公司",
            "enterprise_id": "浙江蓝天制衣有限公司",
            "source_title": title,
            "year": 2023,
        },
        profiles=profiles,
        memberships=memberships,
        aliases=aliases,
        source_names=source_names,
        name_fields=("enterprise_id", "enterprise_name_at_recognition"),
    )

    assert identity_key == "old"
    assert method == "source-linked-name"
    assert candidates == ["old", "other"]


def test_event_time_excludes_entity_founded_after_recognition():
    profiles = {
        "historical": {"founded_date": "2018-01-01"},
        "new-subject": {"founded_date": "2024-01-01"},
    }
    memberships = {
        ("historical", "国家专精特新“小巨人”企业"),
        ("new-subject", "国家专精特新“小巨人”企业"),
    }
    aliases = {"示例企业有限公司": {"historical", "new-subject"}}
    identity_key, method, _ = MODULE.resolve_record_identity(
        {
            "project_name": "国家专精特新“小巨人”企业",
            "enterprise_name_at_recognition": "示例企业有限公司",
            "enterprise_id": "示例企业有限公司",
            "source_title": "",
            "year": 2022,
        },
        profiles=profiles,
        memberships=memberships,
        aliases=aliases,
        source_names={},
        name_fields=("enterprise_id", "enterprise_name_at_recognition"),
    )

    assert identity_key == "historical"
    assert method == "event-time-identity"


def test_audited_lineage_correction_moves_alias_to_supported_subject():
    alias = "浙江华邦安全封条股份有限公司"
    normalized = MODULE.normalize_name(alias)
    profiles = {
        "913306815877655972": {"recognition_names_json": json.dumps([alias])},
        "913303006807061374": {
            "recognition_names_json": json.dumps(["浙江华邦物联技术股份有限公司"])
        },
    }
    aliases = {normalized: {"913306815877655972"}}
    source_names = {
        ("913306815877655972", normalized): [
            "1.建议继续支持的专精特新“小巨人”企业名单（第一批第三年）.pdf"
        ]
    }

    MODULE.apply_loaded_lineage_corrections(profiles, aliases, source_names)

    assert aliases[normalized] == {"913303006807061374"}
    assert ("913306815877655972", normalized) not in source_names
    assert alias not in MODULE.as_list(
        profiles["913306815877655972"]["recognition_names_json"]
    )
    assert alias in MODULE.as_list(
        profiles["913303006807061374"]["recognition_names_json"]
    )


def test_audited_lineage_correction_is_idempotent_after_quarantine():
    alias = "浙江华邦安全封条股份有限公司"
    normalized = MODULE.normalize_name(alias)
    profiles = {
        "913303006807061374": {
            "recognition_names_json": json.dumps(
                ["浙江华邦物联技术股份有限公司", alias]
            )
        }
    }
    aliases = {normalized: {"913303006807061374"}}
    source_names = {
        ("913303006807061374", normalized): [
            "1.建议继续支持的专精特新“小巨人”企业名单（第一批第三年）.pdf"
        ]
    }

    MODULE.apply_loaded_lineage_corrections(profiles, aliases, source_names)

    assert aliases[normalized] == {"913303006807061374"}
    assert MODULE.as_list(
        profiles["913303006807061374"]["recognition_names_json"]
    ).count(alias) == 1


def test_three_first_discovery_without_product_remains_gap():
    assert MODULE.weak_three_first_record(
        {
            "project_name": "浙江省首批次新材料",
            "verification_status": "discovery_only",
            "recognition_status": "platform_history",
            "product_name": "",
        }
    )
    assert not MODULE.weak_three_first_record(
        {
            "project_name": "浙江省首批次新材料",
            "verification_status": "official_or_archived_list",
            "recognition_status": "final_recognition",
            "product_name": "高性能示例材料",
        }
    )


def test_three_first_rules_are_product_timeline_rules():
    payload = json.loads(
        (PORTAL_DIR / "references" / "enterprise-lifecycle-rules.json").read_text(
            encoding="utf-8"
        )
    )
    rules = {
        item["project_name"]: item
        for item in payload["projects"]
        if item["project_name"] in MODULE.THREE_FIRST_PROJECTS
    }

    assert set(rules) == set(MODULE.THREE_FIRST_PROJECTS)
    assert all(
        item["cycle_type"] == "product_recognition_timeline"
        for item in rules.values()
    )
    assert all("directory_exit" in item["supported_event_types"] for item in rules.values())


def test_reward_and_directory_exit_preserve_historical_semantics():
    assert next_state("active", "award") == (
        "active",
        "奖励事件不等同于新增认定，不覆盖历史资格状态",
    )
    assert next_state("active", "directory_exit") == (
        "directory_exited",
        "目录退出仅更新产品目录状态，不删除历史认定事实",
    )


def test_three_first_product_is_preserved_in_replay_step():
    steps = replay_steps(
        [
            {
                "event_year": 2025,
                "event_type": "recognition",
                "status": "final_recognition",
                "subject_type": "product",
                "subject_key": "五轴联动数控机床",
                "subject_name": "五轴联动数控机床",
                "product_name": "五轴联动数控机床",
                "product_category": "整机装备",
                "recognition_level": "国内首台（套）",
            }
        ],
        {"validity_years": None},
    )

    assert steps[0]["subject_type"] == "product"
    assert steps[0]["product_name"] == "五轴联动数控机床"
    assert steps[0]["product_category"] == "整机装备"
    assert steps[0]["recognition_level"] == "国内首台（套）"


def test_product_correction_turns_weak_record_into_product_event(tmp_path):
    source = tmp_path / "guide.wps"
    source.write_bytes(b"guide-evidence")
    source_hash = MODULE.sha256_file(source)
    correction_file = tmp_path / "corrections.json"
    correction_file.write_text(
        json.dumps(
            {
                "corrections": [
                    {
                        "identity_key": "91331021MA2HET773R",
                        "project_name": "浙江省制造业首台（套）装备",
                        "year": 2025,
                        "product_name": "重载工业机器人RV减速器",
                        "product_category": "首台（套）装备",
                        "recognition_level": "国内",
                        "source_title": "2025年版推广目录第329行",
                        "source_path": str(source),
                        "source_sha256": source_hash,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    correction = MODULE.load_product_corrections(correction_file, tmp_path)[0]
    row = MODULE.corrected_recognition_row(
        {
            "project_name": "浙江省制造业首台（套）装备",
            "year": 2025,
            "product_name": "",
            "recognition_status": "platform_history",
            "verification_status": "discovery_only",
        },
        correction,
        {"current_name": "浙江环动机器人关节科技股份有限公司"},
    )
    event = MODULE.recognition_event(
        row,
        "91331021MA2HET773R",
        "user-confirmed-product-correction",
    )

    assert not MODULE.weak_three_first_record(row)
    assert event["product_name"] == "重载工业机器人RV减速器"
    assert event["recognition_level"] == "国内"
    assert event["source_paths"] == [str(source)]


def test_incremental_identity_scope_validates_and_deduplicates():
    assert MODULE.normalize_identity_scope(
        [" 91330401ma28a7n16u ", "91330401MA28A7N16U"]
    ) == {"91330401MA28A7N16U"}

    try:
        MODULE.normalize_identity_scope(["not-a-uscc"])
    except RuntimeError as error:
        assert "统一社会信用代码无效" in str(error)
    else:
        raise AssertionError("invalid identity key was accepted")


def test_replace_selected_twins_preserves_unselected_and_other_projects():
    connection = sqlite3.connect(":memory:")
    create_twin_tables(connection)
    selected = "91330401MA28A7N16U"
    unselected = "91331000563304198L"
    insert_existing_twin(
        connection,
        "selected-old",
        selected,
        "浙江省首批次新材料",
    )
    insert_existing_twin(
        connection,
        "unselected-old",
        unselected,
        "浙江省首批次新材料",
    )
    insert_existing_twin(
        connection,
        "selected-other-project",
        selected,
        "浙江省隐形冠军企业",
    )
    new_twin = {
        "twin_id": "selected-new",
        "identity_key": selected,
        "project_name": "浙江省首批次新材料",
        "lifecycle_rule_id": "rule-v2",
        "policy_version": {"policy_version_id": "policy-v2"},
        "current_replay": {"state": "active", "as_of_year": 2025},
        "trace_hash": "new-trace",
        "identity_match": {},
        "list_attachment_trace": [],
        "coverage_trace": [],
        "lifecycle_trace": [],
        "replayable_years": [2025],
    }
    new_step = {
        "twin_id": "selected-new",
        "identity_key": selected,
        "project_name": "浙江省首批次新材料",
        "step": 1,
        "event_year": 2025,
        "event_type": "recognition",
        "previous_state": "not_recorded",
        "next_state": "active",
        "reason": "incremental",
        "evidence_hash": "new-evidence",
    }

    MODULE.replace_selected_twins(
        connection,
        {selected},
        [new_twin],
        [new_step],
    )

    twins = {
        row[0]
        for row in connection.execute(
            "SELECT twin_id FROM enterprise_project_identity_twins"
        )
    }
    steps = {
        row[0]
        for row in connection.execute(
            "SELECT twin_id FROM enterprise_project_identity_twin_steps"
        )
    }
    assert twins == {
        "selected-new",
        "unselected-old",
        "selected-other-project",
    }
    assert steps == twins


def test_incremental_audit_preserves_full_baseline_and_correction_without_input():
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE enterprise_project_relation_quarantine(
            identity_key TEXT, current_name TEXT, project_name TEXT,
            reason TEXT, evidence_json TEXT, source TEXT,
            PRIMARY KEY(identity_key,project_name)
        );
        CREATE TABLE enterprise_project_twin_gaps(
            identity_key TEXT, current_name TEXT, project_name TEXT,
            gap_type TEXT, details_json TEXT, source TEXT,
            PRIMARY KEY(identity_key,project_name,gap_type)
        );
        CREATE TABLE enterprise_project_twin_rebuild_audit(
            audit_key TEXT PRIMARY KEY, audit_value_json TEXT, source TEXT
        );
        CREATE TABLE enterprise_project_product_corrections(
            identity_key TEXT, current_name TEXT, project_name TEXT,
            recognition_year INTEGER, product_name TEXT,
            verification_status TEXT, source_title TEXT, source_path TEXT,
            source_sha256 TEXT, evidence_json TEXT, source TEXT,
            PRIMARY KEY(identity_key,project_name,recognition_year)
        );
        """
    )
    selected = "91330401MA28A7N16U"
    connection.execute(
        "INSERT INTO enterprise_project_twin_rebuild_audit VALUES(?,?,?)",
        ("rebuild_report", '{"mode":"full"}', MODULE.PUBLIC_SOURCE),
    )
    connection.execute(
        "INSERT INTO enterprise_project_product_corrections VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            selected,
            "浙江中泽精密科技股份有限公司",
            "浙江省首批次新材料",
            2025,
            "新能源锂电特种铝制安全防爆材料",
            "user_confirmed_final_recognition",
            "source",
            "",
            "",
            "{}",
            MODULE.PUBLIC_SOURCE,
        ),
    )

    MODULE.write_incremental_audit_tables(
        connection,
        {selected},
        [],
        [],
        [],
        {"replay_mode": "incremental"},
        replace_product_corrections=False,
    )

    assert connection.execute(
        "SELECT audit_value_json FROM enterprise_project_twin_rebuild_audit "
        "WHERE audit_key='rebuild_report'"
    ).fetchone()[0] == '{"mode":"full"}'
    assert connection.execute(
        "SELECT COUNT(*) FROM enterprise_project_product_corrections"
    ).fetchone()[0] == 1
    assert connection.execute(
        "SELECT COUNT(*) FROM enterprise_project_twin_rebuild_audit "
        "WHERE audit_key='last_incremental_replay'"
    ).fetchone()[0] == 1
