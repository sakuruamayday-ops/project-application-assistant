import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_product_configuration_validator_passes_on_v1613_release_candidate(tmp_path):
    manager = tmp_path / "skill-release-manager"
    hook = manager / "scripts" / "windows_hook"
    hook.mkdir(parents=True)
    (hook / "main.go").write_text('const runtimeVersion = "1.6.6"\n', encoding="utf-8")
    (hook / "contract.go").write_text(
        'const intentRuleVersion = "7-delivery-action-scoped-negation"\n',
        encoding="utf-8",
    )
    (hook / "events.go").write_text(
        "func loadValidatorReceipts() {}\nvar effectiveBusinessDomain bool\n",
        encoding="utf-8",
    )
    (manager / "scripts" / "workbuddy_behavior_hook.py").write_text(
        'INTENT_RULE_VERSION = "7-delivery-action-scoped-negation"\n'
        "def load_validator_receipts(): pass\neffective_business_domain = True\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "scripts/validate_grounded_product_config.py",
            "--release-manager-root",
            str(manager),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    receipt = json.loads(result.stdout)
    assert receipt["status"] == "pass"
    assert receipt["channels"] == {
        "workbuddy_windows_stable": "V1.6.1",
        "workbuddy_macos_stable": "V1.6.1",
        "candidate": "V1.6.1.4",
    }
    assert receipt["skills_contract"] == "V1.6.1.4"
    assert receipt["grounded_candidate_release"] == "V1.6.1.4"


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
