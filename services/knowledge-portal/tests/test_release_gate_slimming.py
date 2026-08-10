from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def test_release_gate_is_four_layers_and_uses_reusable_harness_receipt():
    content = (SCRIPTS / "release_gate.sh").read_text(encoding="utf-8")

    assert "[1/4]" in content
    assert "[2/4]" in content
    assert "[3/4]" in content
    assert "[4/4]" in content
    assert "verify_acceptance_receipt.py" in content
    assert "verify_index_release_binding.py" in content
    assert "public_namespace_gate.py" in content
    assert '--archive "${generic_archive}"' in content
    assert '--archive "${workbuddy_archive}"' in content
    assert 'if [[ "${release_mode}" == "index" ]]' in content
    assert "JIAOTANG_RELEASE_MODE=code 或 index" in content
    assert "run_acceptance_harness.py" not in content
    assert "总墙钟" in content


def test_release_gate_matches_v145_bearer_only_install_boundary():
    release_gate = (SCRIPTS / "release_gate.sh").read_text(encoding="utf-8")
    smoke_gate = (SCRIPTS / "smoke_test_production.sh").read_text(
        encoding="utf-8"
    )
    combined = release_gate + smoke_gate

    for legacy in (
        "JIAOTANG_KB_DEVICE_ID",
        "X-Jiaotang-Device-ID",
        "test_three_step_install_e2e.py",
        "manage_project_algorithm_packs.py",
        "validate_project_algorithm_packs.py",
        "merge_three_way",
        "migrate_skill_preferences.py",
    ):
        assert legacy not in combined
    assert '"method":"tools/list"' in release_gate
    assert '"name":"knowledge_service_status"' in release_gate
    assert 'status.get("connected") is True' in release_gate
