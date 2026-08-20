import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_product_configuration_validator_passes_on_current_formal_release():
    result = subprocess.run(
        [
            sys.executable,
            "scripts/validate_grounded_product_config.py",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    receipt = json.loads(result.stdout)
    release_tag = load(ROOT / "skills" / "suite-manifest.json")["release"]["tag"]
    assert receipt["status"] == "pass"
    assert receipt["channels"] == {
        "client_windows_candidate": release_tag,
        "client_macos_candidate": release_tag,
        "skills_candidate": release_tag,
    }
    assert receipt["skills_contract"] == release_tag
    assert receipt["grounded_candidate_release"] == release_tag


def test_grounded_host_adapters_are_in_the_shared_package_surface():
    manifest = load(ROOT / "skills" / "suite-manifest.json")
    registry = load(ROOT / "skills" / "report-skill-registry.json")
    assert "_runtime/grounded-citations" in manifest["shared_paths"]
    assert set(registry["host_adapters"]) == {"codex", "workbuddy"}
    for relative in registry["host_adapters"].values():
        assert relative.startswith("_runtime/grounded-citations/")
        assert (ROOT / "skills" / relative).is_file()


def test_product_gate_excludes_permissions_and_external_mcp_checks():
    source = (ROOT / "scripts" / "run_grounded_citations_gate.py").read_text(encoding="utf-8")
    assert "workbuddy_mcp_receipt" not in source
    assert "--skip-workbuddy-mcp" not in source
    assert '"bash-permission-policy"' in source
    assert '"external-mcp"' in source
