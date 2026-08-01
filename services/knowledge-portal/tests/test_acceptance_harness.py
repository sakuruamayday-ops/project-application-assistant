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
        "blocking_failed": 1,
        "failures_by_severity": {"P0": 1},
    }
    assert report["results"][0]["observed"] == 42


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
