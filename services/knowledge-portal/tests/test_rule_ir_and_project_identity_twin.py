from __future__ import annotations

import json
from pathlib import Path

from app.project_identity_twin import (
    build_project_identity_twins,
    replay_twin,
)
from app.rule_ir import (
    apply_policy_baselines,
    compile_rule_ir,
    compiled_projects,
    write_compiled_rule_ir,
)
from app.policy_lifecycle import (
    build_policy_dependency_graph,
    policy_document_in_execution_window,
    rolling_policy_window,
)


def sample_pack(project_id: str = "sample") -> dict[str, object]:
    return {
        "schema_version": 1,
        "project_id": project_id,
        "project_name": "示例项目",
        "version": "1.0",
        "coverage_status": "rules-confirmed",
        "aliases": ["示例"],
        "source_retrieval_rule_ids": ["sample"],
        "fact_fields": [{"field": "revenue"}],
        "rule_cards": [],
        "rule_layers": [
            {
                "layer_id": "stable",
                "layer_type": "stable",
                "applicability": {},
                "rules": [
                    {
                        "rule_id": "revenue",
                        "review_status": "confirmed",
                    }
                ],
            }
        ],
        "gold_cases": [{"case_id": "sample"}],
    }


def test_rule_ir_compiles_once_and_reuses_source_digest(tmp_path: Path):
    lifecycle = {
        "projects": [
            {
                "rule_id": "sample-lifecycle",
                "project_name": "示例项目",
                "validity_years": 3,
            }
        ]
    }
    payload = compile_rule_ir(
        [sample_pack()],
        lifecycle,
        {"fields": [{"field": "revenue"}]},
    )
    output = tmp_path / "compiled.json"

    assert write_compiled_rule_ir(output, payload) == "compiled"
    assert write_compiled_rule_ir(output, payload) == "hash_reused"
    assert payload["metrics"]["project_count"] == 1
    assert payload["metrics"]["shared_kernel_count"] == 9
    assert compiled_projects(payload)[0]["policy_version_id"].startswith("policy-")


def test_rule_ir_changes_only_when_source_content_changes():
    lifecycle = {"projects": []}
    first = compile_rule_ir([sample_pack()], lifecycle, {"fields": []})
    changed_pack = sample_pack()
    changed_pack["version"] = "1.1"
    changed = compile_rule_ir([changed_pack], lifecycle, {"fields": []})

    assert first["source_digest"] != changed["source_digest"]
    assert (
        first["projects"]["sample"]["source_content_hash"]
        != changed["projects"]["sample"]["source_content_hash"]
    )


def test_rolling_policy_window_keeps_current_old_policy_as_exception():
    assert rolling_policy_window(2026) == {
        "start_year": 2022,
        "end_year": 2026,
        "window_years": 5,
    }
    included, reason = policy_document_in_execution_window(
        {
            "issued_year": 2019,
            "status": "current",
            "cited_by_current_notice": True,
        },
        as_of_year=2026,
    )
    assert included is True
    assert reason == "cited-by-current-notice"
    archived, archive_reason = policy_document_in_execution_window(
        {"issued_year": 2019, "status": "historical"},
        as_of_year=2026,
    )
    assert archived is False
    assert archive_reason == "cold-archive"


def test_policy_baseline_enrichment_and_dependency_graph():
    baseline = {
        "as_of_year": 2026,
        "window_years": 5,
        "baselines": [
            {
                "project_id": "sample",
                "baseline_status": "complete",
                "decision_mode": "latest-rule",
                "policy_documents": [
                    {
                        "document_id": "sample-method",
                        "title": "示例管理办法",
                        "issued_year": 2021,
                        "status": "current",
                        "authority": "示例主管部门",
                        "official_url": "https://example.gov.cn/method",
                        "relation": "governed-by",
                        "still_effective": True,
                    },
                    {
                        "document_id": "sample-notice",
                        "title": "2025年度通知",
                        "issued_year": 2025,
                        "status": "latest-complete-cycle",
                        "authority": "示例主管部门",
                        "official_url": "https://example.gov.cn/notice",
                        "relation": "announced-by",
                    },
                ],
                "dependencies": [
                    {
                        "from_document_id": "sample-notice",
                        "to_document_id": "sample-method",
                        "relation": "cites",
                    }
                ],
            }
        ],
    }
    routing_pack = sample_pack()
    routing_pack["coverage_status"] = "routing-only"
    routing_pack["rule_cards"] = []
    routing_pack["rule_layers"] = []
    enriched = apply_policy_baselines([routing_pack], baseline)
    assert enriched[0]["coverage_status"] == "policy-baseline-confirmed"
    graph = build_policy_dependency_graph(enriched, as_of_year=2026)
    assert len(graph["nodes"]) == 3
    assert any(edge["relation"] == "cites" for edge in graph["edges"])
    assert graph["cold_archive_document_ids"] == []


def test_repository_policy_baselines_cover_every_nonformal_project():
    portal_dir = Path(__file__).resolve().parents[1]
    baseline_registry = json.loads(
        (
            portal_dir / "references" / "project-policy-baselines.json"
        ).read_text(encoding="utf-8")
    )
    packs = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(
            (
                portal_dir / "references" / "project-algorithm-packs"
            ).glob("*.json")
        )
    ]
    routing_ids = {
        str(pack["project_id"])
        for pack in packs
        if pack.get("coverage_status") == "routing-only"
    }
    baseline_ids = {
        str(item["project_id"])
        for item in baseline_registry["baselines"]
        if item.get("baseline_status") == "complete"
    }
    assert len(routing_ids) == 21
    assert baseline_ids == routing_ids
    assert all(
        str(document.get("official_url") or "").startswith("https://")
        for item in baseline_registry["baselines"]
        for document in item["policy_documents"]
    )


def test_project_identity_twin_replays_policy_attachment_match_and_lifecycle():
    profiles = [
        {
            "identity_key": "91330000TEST000001",
            "unified_social_credit_code": "91330000TEST000001",
            "current_name": "浙江示例科技有限公司",
            "recognition_names": ["浙江示例技术有限公司"],
            "verification_status": "tyc_verified",
            "identity_source": "tyc-it",
            "verified_at": "2026-07-29",
        }
    ]
    events = [
        {
            "identity_key": "91330000TEST000001",
            "enterprise_name_at_event": "浙江示例技术有限公司",
            "project_name": "浙江省专精特新中小企业",
            "event_year": 2022,
            "event_type": "recognition",
            "status": "认定",
            "cohort_year": 2022,
            "batch": "第一批",
            "recognition_province": "浙江省",
            "recognition_city": "杭州市",
            "recognition_county": "",
            "source_title": "2022年度认定名单",
            "source_paths": ["附件/2022名单.xlsx"],
            "source_urls": ["https://example.gov.cn/2022"],
            "source_kinds": ["official_final_list"],
            "evidence_status": "official_final_list",
        },
        {
            "identity_key": "91330000TEST000001",
            "enterprise_name_at_event": "浙江示例科技有限公司",
            "project_name": "浙江省专精特新中小企业",
            "event_year": 2025,
            "event_type": "review_passed",
            "status": "复核通过",
            "cohort_year": 2022,
            "batch": "第一批",
            "recognition_province": "浙江省",
            "recognition_city": "杭州市",
            "recognition_county": "",
            "source_title": "2025年度复核通过名单",
            "source_paths": ["附件/2025复核名单.pdf"],
            "source_urls": ["https://example.gov.cn/2025"],
            "source_kinds": ["official_final_list"],
            "evidence_status": "official_final_list",
        },
    ]
    rules = {
        "浙江省专精特新中小企业": {
            "rule_id": "zhejiang-specialized-sme",
            "project_name": "浙江省专精特新中小企业",
            "cycle_type": "qualification_review",
            "validity_years": 3,
            "current_rule_state": "confirmed",
            "local_rule_sources": ["政策/现行办法.md"],
            "official_rule_urls": ["https://example.gov.cn/policy"],
        }
    }
    coverage = {
        "rows": [
            {
                "coverage_group_id": "review-2025",
                "project_name": "浙江省专精特新中小企业",
                "event_year": 2025,
                "batch": "第一批",
                "event_type": "review_passed",
                "city": "杭州市",
                "coverage_state": "hash_reused",
                "content_fingerprint": "a" * 64,
            }
        ]
    }

    twins, steps = build_project_identity_twins(
        profiles,
        events,
        rules,
        coverage,
    )
    assert len(twins) == 1
    assert len(steps) == 2
    twin = twins[0]
    assert twin["identity_match"]["method"] == "unified-social-credit-code"
    assert twin["policy_version"]["policy_version_id"].startswith(
        "lifecycle-policy-"
    )
    assert twin["list_attachment_trace"][1]["source_paths"] == [
        "附件/2025复核名单.pdf"
    ]
    assert twin["lifecycle_trace"][0]["next_state"] == "active"
    assert twin["lifecycle_trace"][1]["previous_state"] == "active"
    assert twin["lifecycle_trace"][1]["valid_through_year"] == 2028
    assert replay_twin(twin, 2024)["as_of"]["state"] == "active"
    assert replay_twin(twin, 2026)["as_of"]["state"] == "active"
    json.dumps(twin, ensure_ascii=False)
