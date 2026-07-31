from __future__ import annotations

from pathlib import Path


PORTAL_DIR = Path(__file__).resolve().parents[1]
REPOSITORY_DIR = PORTAL_DIR.parents[1]
WORKFLOW = (
    REPOSITORY_DIR
    / ".github"
    / "workflows"
    / "skills-manager-release-gates.yml"
)


def test_ci_uses_hash_locked_offline_install_and_publishes_production_wheelhouse():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert 'python-version: "3.12"' in workflow
    assert "lock-metadata-verify" in workflow
    assert "--lock services/knowledge-portal/requirements.lock" in workflow
    assert "--lock services/knowledge-portal/requirements-test.lock" in workflow
    assert "--build-lock services/knowledge-portal/requirements-build.lock" in workflow
    assert "python_supply_chain.py install" in workflow
    assert "portal-python312-linux-x86_64-wheelhouse" in workflow
    assert "portal-production-dependency-release-record.json" in workflow
    assert '"source_event": os.environ["GITHUB_EVENT_NAME"]' in workflow
    assert "branches:" in workflow
    assert "- main" in workflow
    assert (
        "actions/upload-artifact@"
        "ea165f8d65b6e75b540449e92b4886f43607fa02"
    ) in workflow
    assert "pip install -r services/knowledge-portal/requirements.txt pytest" not in workflow


def test_dependency_inputs_separate_production_and_test_tools():
    production = (PORTAL_DIR / "requirements.in").read_text(encoding="utf-8")
    test = (PORTAL_DIR / "requirements-test.in").read_text(encoding="utf-8")
    build = (PORTAL_DIR / "requirements-build.in").read_text(encoding="utf-8")
    compatibility = (PORTAL_DIR / "requirements.txt").read_text(encoding="utf-8")

    assert "pytest" not in production.lower()
    assert "-r requirements.in" in test
    assert "pytest==8.4.1" in test
    assert "setuptools==83.0.0" in build
    assert "wheel==0.47.0" in build
    assert "--require-hashes" in compatibility
    assert "-r requirements.lock" in compatibility
    assert "fastapi==" not in compatibility


def test_offline_install_policy_is_documented_as_fail_closed():
    readme = (PORTAL_DIR / "README.md").read_text(encoding="utf-8")

    for marker in (
        "--no-index",
        "--require-hashes",
        "--only-binary=:all:",
        "--no-deps",
        "EXPECTED_WHEELHOUSE_MANIFEST_SHA256",
        "dependency_identity_sha256",
    ):
        assert marker in readme
