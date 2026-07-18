import importlib.util
import json
import stat
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "first-run-configuration" / "scripts" / "configure.py"
SPEC = importlib.util.spec_from_file_location("first_run_configuration", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_unified_report_redacts_all_secret_values(tmp_path):
    secrets = {
        "JIAOTANG_KB_ENDPOINT": "https://knowledge.example.com",
        "JIAOTANG_KB_TOKEN": "jtk-test-secret",
        "QCC_API_KEY": "qcc-test-secret",
        "PATENT_DATA_PROVIDER": "test-provider",
        "PATENT_API_KEY": "patent-test-secret",
        "PROJECT_ASSISTANT_BROWSER_READY": "true",
    }
    report, profile_file, report_file = MODULE.run(
        tmp_path,
        non_interactive=True,
        network=False,
        environment=secrets,
    )
    profile_text = profile_file.read_text(encoding="utf-8")
    report_text = report_file.read_text(encoding="utf-8")
    for secret in ("jtk-test-secret", "qcc-test-secret", "patent-test-secret"):
        assert secret not in profile_text
        assert secret not in report_text
    assert report["capabilities"]["team_knowledge"]["status"] == "configured"
    assert report["capabilities"]["qcc"]["status"] == "ready"
    assert report["capabilities"]["patent_data"]["status"] == "ready"


def test_credentials_file_is_current_user_only(tmp_path):
    target = tmp_path / "credentials.env"
    MODULE.write_credentials(
        target,
        {
            "JIAOTANG_KB_ENDPOINT": "https://knowledge.example.com",
            "JIAOTANG_KB_TOKEN": "token with spaces",
        },
    )
    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == 0o600
    values = MODULE.read_env_file(target)
    assert values["JIAOTANG_KB_TOKEN"] == "token with spaces"


def test_capability_profile_contains_names_not_secret_values(tmp_path):
    report, profile_file, _ = MODULE.run(
        tmp_path,
        non_interactive=True,
        network=False,
        environment={"JIAOTANG_KB_ENDPOINT": "https://knowledge.example.com", "JIAOTANG_KB_TOKEN": "hidden-value"},
    )
    saved = json.loads(profile_file.read_text(encoding="utf-8"))
    assert "JIAOTANG_KB_TOKEN" in saved["credentials"]["detected_names"]
    assert "hidden-value" not in profile_file.read_text(encoding="utf-8")
    assert report["capabilities"]["team_knowledge"]["endpoint"] == "https://knowledge.example.com"


def test_first_run_enables_evolution_and_prompts_host_skills(tmp_path):
    report, _, report_file = MODULE.run(
        tmp_path,
        non_interactive=True,
        network=False,
        environment={},
    )
    onboarding = report["onboarding"]
    assert onboarding["controlled_evolution_enabled"] is True
    assert onboarding["four_question_review_enabled"] is True
    assert onboarding["host_skill_install_prompt"] == "帮我安装OCR、PDF、Word、PPT、Excel和联网检索这几个Skills"
    report_text = report_file.read_text(encoding="utf-8")
    assert "受控自进化已启用" in report_text
    assert "帮我安装OCR、PDF、Word、PPT、Excel和联网检索这几个Skills" in report_text


def test_startup_prompt_only_appears_once_per_protocol_version(tmp_path):
    first, _, first_report = MODULE.run(
        tmp_path,
        non_interactive=True,
        network=False,
        environment={},
    )
    assert first["onboarding"]["startup_prompt_required"] is True
    assert "帮我安装OCR、PDF、Word、PPT、Excel和联网检索这几个Skills" in first_report.read_text(encoding="utf-8")

    second, _, second_report = MODULE.run(
        tmp_path,
        non_interactive=True,
        network=False,
        environment={},
    )
    assert second["onboarding"]["startup_prompt_required"] is False
    assert "帮我安装OCR、PDF、Word、PPT、Excel和联网检索这几个Skills" not in second_report.read_text(encoding="utf-8")
