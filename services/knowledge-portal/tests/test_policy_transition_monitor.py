import json
import sqlite3
from copy import deepcopy
from pathlib import Path

from app.policy_transition_monitor import (
    affected_enterprises_for_policy_cell,
    build_policy_transition_snapshot,
    diff_policy_transition_snapshots,
    promote_verified_formal_candidate,
)


PORTAL_DIR = Path(__file__).resolve().parents[1]


def load(name):
    return json.loads(
        (PORTAL_DIR / "references" / name).read_text(encoding="utf-8")
    )


def test_city_family_hash_only_invalidates_changed_cell():
    policy = load("four-city-rd-platform-policy-registry.json")
    thresholds = load("four-city-rd-platform-threshold-packs.json")
    before = build_policy_transition_snapshot(policy, thresholds)
    changed = deepcopy(thresholds)
    changed["city_variants"][2]["tracks"][0]["score_threshold"] = 61
    after = build_policy_transition_snapshot(policy, changed)

    result = diff_policy_transition_snapshots(before, after)

    assert result["change_count"] == 1
    assert result["changed_cells"][0]["cell_key"] == (
        "municipal-enterprise-rd-platform|绍兴市"
    )
    assert result["compile_project_ids"] == [
        "hangzhou-enterprise-institute"
    ]
    assert result["reused_cell_count"] == 7


def test_unofficial_formal_candidate_cannot_replace_draft():
    policy = load("four-city-rd-platform-policy-registry.json")
    thresholds = load("four-city-rd-platform-threshold-packs.json")
    result = promote_verified_formal_candidate(
        policy,
        thresholds,
        {
            "family_id": "municipal-enterprise-rd-platform",
            "city": "杭州市",
            "title": "杭州市企业研究院建设管理办法",
            "policy_status": "current",
            "verification_status": "verified",
            "source_url": "https://example.com/policy.html",
            "threshold_tracks": thresholds["city_variants"][0]["tracks"],
        },
    )

    assert result["status"] == "rejected"
    assert "官方域名" in result["reason"]


def test_verified_official_candidate_promotes_and_preserves_historical_draft():
    policy = load("four-city-rd-platform-policy-registry.json")
    thresholds = load("four-city-rd-platform-threshold-packs.json")
    formal_tracks = deepcopy(thresholds["city_variants"][0]["tracks"])
    formal_tracks = [formal_tracks[1]]
    formal_tracks[0]["track_id"] = "hangzhou-formal-enterprise-institute"
    formal_tracks[0]["policy_status"] = "current"
    formal_tracks[0]["formal_conclusion_allowed"] = True
    result = promote_verified_formal_candidate(
        policy,
        thresholds,
        {
            "family_id": "municipal-enterprise-rd-platform",
            "city": "杭州市",
            "title": "杭州市重点企业研究院、企业研究院建设管理办法",
            "policy_status": "current",
            "verification_status": "official-verified",
            "source_url": "https://kj.hangzhou.gov.cn/art/2026/formal.html",
            "replaces_prospective_policy": (
                "《杭州市重点企业研究院、企业研究院建设管理办法"
                "（征求意见稿）》"
            ),
            "threshold_tracks": formal_tracks,
        },
    )

    assert result["status"] == "promoted"
    assert result["change_set"]["change_count"] == 1
    assert result["change_set"]["changed_cells"][0]["city"] == "杭州市"
    variant = result["policy_registry"]["project_families"][1][
        "city_variants"
    ][0]
    assert "prospective_policy" not in variant
    assert variant["historical_drafts"][0]["status"] == "draft"


def test_policy_monitor_lists_affected_enterprises_without_mutating_facts(
    tmp_path,
):
    database = tmp_path / "knowledge.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE enterprise_recognition_events(
                enterprise_name_at_event TEXT,
                project_name TEXT,
                recognition_year INTEGER
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO enterprise_recognition_events
            VALUES(?,?,?)
            """,
            [
                ("甲企业", "杭州市企业研究院", 2026),
                ("乙企业", "其他项目", 2025),
            ],
        )

    result = affected_enterprises_for_policy_cell(
        database,
        project_names=["杭州市企业研究院"],
    )

    assert result == [
        {
            "enterprise_name": "甲企业",
            "project_name": "杭州市企业研究院",
            "event_year": 2026,
            "source_table": "enterprise_recognition_events",
        }
    ]
