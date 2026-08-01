from __future__ import annotations

import pytest

from app.acceptance_harness import AcceptanceHarness


def test_harness_selects_suites_and_blocks_p0_failures():
    harness = AcceptanceHarness()

    def adapter(config, context):
        return bool(config["passed"]), context["value"], ["evidence"]

    harness.register("fixture", adapter)
    profile = {
        "profile_id": "fixture",
        "target_type": "fixture",
        "blocking_severities": ["P0", "P1"],
        "checks": [
            {
                "id": "blocking",
                "suite": "knowledge",
                "severity": "P0",
                "adapter": "fixture",
                "description": "blocking",
                "config": {"passed": False},
            },
            {
                "id": "unselected",
                "suite": "website",
                "severity": "P0",
                "adapter": "fixture",
                "description": "unselected",
                "config": {"passed": False},
            },
        ],
    }

    report = harness.run(profile, {"value": 42}, suites=["knowledge"])

    assert report["status"] == "fail"
    assert report["release_allowed"] is False
    assert report["summary"] == {
        "checks": 1,
        "passed": 0,
        "failed": 1,
        "blocked": 0,
        "blocking_failed": 1,
        "blocking_blocked": 0,
        "failures_by_severity": {"P0": 1},
    }
    assert report["results"][0]["observed"] == 42
    assert report["results"][0]["status"] == "fail"


def test_harness_allows_non_blocking_p2_failure():
    harness = AcceptanceHarness()
    harness.register("fixture", lambda config, context: (False, "minor", []))
    report = harness.run(
        {
            "profile_id": "fixture",
            "target_type": "fixture",
            "blocking_severities": ["P0", "P1"],
            "checks": [
                {
                    "id": "minor",
                    "suite": "default",
                    "severity": "P2",
                    "adapter": "fixture",
                    "description": "minor",
                    "config": {},
                }
            ],
        },
        {},
    )

    assert report["status"] == "pass"
    assert report["release_allowed"] is True
    assert report["summary"]["failed"] == 1


def test_harness_expands_suite_group_and_rejects_unknown_suite():
    harness = AcceptanceHarness()
    harness.register("fixture", lambda config, context: (True, "ok", []))
    profile = {
        "profile_id": "fixture",
        "target_type": "fixture",
        "suite_groups": {"all": ["knowledge", "website"]},
        "checks": [
            {
                "id": "knowledge",
                "suite": "knowledge",
                "severity": "P0",
                "adapter": "fixture",
                "description": "knowledge",
                "config": {},
            },
            {
                "id": "website",
                "suite": "website",
                "severity": "P0",
                "adapter": "fixture",
                "description": "website",
                "config": {},
            },
        ],
    }

    report = harness.run(profile, {}, suites=["all"])

    assert report["requested_suites"] == ["all"]
    assert report["selected_suites"] == ["knowledge", "website"]
    assert report["summary"]["checks"] == 2
    with pytest.raises(ValueError, match="unknown acceptance suite"):
        harness.run(profile, {}, suites=["missing"])
    with pytest.raises(ValueError, match="must not be empty"):
        harness.run({"checks": []}, {})


def test_harness_blocks_dependants_without_cascading_adapter_errors():
    harness = AcceptanceHarness()
    calls: list[str] = []

    def adapter(config, context):
        calls.append(str(config["name"]))
        if config["name"] == "schema":
            return False, "missing table", ["case_packs"]
        raise AssertionError("dependent adapter must not run")

    harness.register("fixture", adapter)
    report = harness.run(
        {
            "profile_id": "fixture",
            "target_type": "fixture",
            "blocking_severities": ["P0"],
            "checks": [
                {
                    "id": "schema",
                    "suite": "case_pack",
                    "severity": "P0",
                    "adapter": "fixture",
                    "description": "schema",
                    "config": {"name": "schema"},
                },
                {
                    "id": "relations",
                    "suite": "case_pack",
                    "severity": "P0",
                    "adapter": "fixture",
                    "description": "relations",
                    "depends_on": ["schema"],
                    "config": {"name": "relations"},
                },
            ],
        },
        {},
    )

    assert calls == ["schema"]
    assert report["summary"]["failed"] == 1
    assert report["summary"]["blocked"] == 1
    assert report["results"][1]["status"] == "blocked"
    assert report["results"][1]["blocked_by"] == ("schema",)


def test_harness_rejects_invalid_dependency_graphs():
    harness = AcceptanceHarness()
    harness.register("fixture", lambda config, context: (True, "ok", []))
    base = {
        "profile_id": "fixture",
        "target_type": "fixture",
        "checks": [
            {
                "id": "dependent",
                "suite": "default",
                "severity": "P0",
                "adapter": "fixture",
                "description": "dependent",
                "depends_on": ["root"],
                "config": {},
            },
            {
                "id": "root",
                "suite": "default",
                "severity": "P0",
                "adapter": "fixture",
                "description": "root",
                "config": {},
            },
        ],
    }

    with pytest.raises(ValueError, match="must appear earlier"):
        harness.run(base, {})
    base["checks"][0]["depends_on"] = ["missing"]
    with pytest.raises(ValueError, match="unknown dependencies"):
        harness.run(base, {})
