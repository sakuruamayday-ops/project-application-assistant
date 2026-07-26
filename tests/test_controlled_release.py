from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "controlled_release.py"
SPEC = importlib.util.spec_from_file_location("controlled_release", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def runner(name: str, os_name: str, *labels: str, status: str = "online", busy=False):
    return {
        "name": name,
        "os": os_name,
        "status": status,
        "busy": busy,
        "labels": [{"name": label} for label in ("self-hosted", "workbuddy", *labels)],
    }


def test_normalize_version_uses_one_public_version_model() -> None:
    assert MODULE.normalize_version("V1.2") == ("1.2", "1.2.0", "V1.2")
    assert MODULE.normalize_version("1.2.0") == ("1.2", "1.2.0", "V1.2")
    with pytest.raises(ValueError):
        MODULE.normalize_version("1.2.3")


def test_runner_preflight_requires_both_unique_online_idle_hosts() -> None:
    payload = {
        "runners": [
            runner("jiaotang-mac", "macos", "macOS"),
            runner("jiaotang-win", "windows", "Windows"),
        ]
    }
    selected = MODULE.validate_runners(payload)
    assert selected["macos"]["name"] == "jiaotang-mac"
    assert selected["windows"]["name"] == "jiaotang-win"

    with pytest.raises(RuntimeError, match="windows"):
        MODULE.validate_runners({"runners": payload["runners"][:1]})
    payload["runners"][1]["busy"] = True
    with pytest.raises(RuntimeError, match="windows"):
        MODULE.validate_runners(payload)


def attested_payload(host: str) -> dict[str, object]:
    return {
        "schema": "jiaotang-workbuddy-host-evidence/v1",
        "status": "pass",
        "host": host,
        "release_tag": "V1.3",
        "runner": f"jiaotang-{host}",
        "system_name": "macOS" if host == "macos" else "Windows",
        "system_version": "26.5.2" if host == "macos" else "11.0.26100",
        "arch": "ARM64" if host == "macos" else "X64",
        "workbuddy_version": "5.3.3",
        "codebuddy_version": "2.115.0",
        "archive_sha256": "a" * 64,
        "evidence_sha256": "b" * 64,
        "attestation": {
            "status": "verified",
            "id": f"attestation-{host}",
            "url": f"https://github.com/example/attestations/{host}",
            "source_digest": "d" * 40,
            "signer_workflow": ".github/workflows/workbuddy-host-matrix.yml",
        },
    }


def test_attested_payload_requires_versions_and_signature() -> None:
    payload = attested_payload("macos")
    locator = {
        "schema": "jiaotang-github-attestation-locator/v1",
        "attestation_id": "123",
        "attestation_url": "https://github.com/example/attestations/123",
    }
    validated = MODULE.validate_attested_host_payload(
        "macos", payload, locator, [{"verificationResult": {}}], "V1.3"
    )
    assert validated["attestation"]["status"] == "verified"
    payload["workbuddy_version"] = ""
    with pytest.raises(RuntimeError, match="缺少"):
        MODULE.validate_attested_host_payload(
            "macos", payload, locator, [{"verificationResult": {}}], "V1.3"
        )


def test_host_evidence_requires_two_successful_jobs() -> None:
    gate = {
        "url": "https://github.example/actions/runs/1",
        "jobs": [
            {
                "name": "real-host (macos)",
                "databaseId": 10,
                "url": "https://github.example/jobs/10",
                "completedAt": "2026-07-26T00:00:00Z",
            },
            {
                "name": "real-host (windows)",
                "databaseId": 11,
                "url": "https://github.example/jobs/11",
                "completedAt": "2026-07-26T00:00:01Z",
            },
        ],
    }
    evidence = MODULE.host_evidence(
        gate,
        "V1.3",
        1,
        {
            "macos": attested_payload("macos"),
            "windows": attested_payload("windows"),
        },
    )
    assert evidence["status"] == "pass"
    assert set(evidence["hosts"]) == {"macos", "windows"}
    assert evidence["hosts"]["macos"]["attestation"]["status"] == "verified"
