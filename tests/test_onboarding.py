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
        "GONGCHUANG_KB_ENDPOINT": "https://knowledge.example.com",
        "GONGCHUANG_KB_TOKEN": "jtk-test-secret",
        "TYC_MCP_READY": "true",
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
    assert report["capabilities"]["tyc"]["status"] == "ready"
    assert report["capabilities"]["qcc"]["status"] == "ready"
    assert report["capabilities"]["patent_data"]["status"] == "ready"


def test_credentials_file_excludes_system_store_only_secrets(tmp_path):
    target = tmp_path / "credentials.env"
    MODULE.write_credentials(
        target,
        {
            "GONGCHUANG_KB_ENDPOINT": "https://knowledge.example.com",
            "GONGCHUANG_KB_TOKEN": "token with spaces",
            "QCC_API_KEY": "qcc with spaces",
        },
    )
    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == 0o600
    values = MODULE.read_env_file(target)
    assert "GONGCHUANG_KB_TOKEN" not in values
    assert values["QCC_API_KEY"] == "qcc with spaces"


def test_existing_plaintext_team_token_is_scrubbed_without_losing_other_values(tmp_path):
    target = tmp_path / "credentials.env"
    target.write_text(
        "\n".join(
            [
                "GONGCHUANG_KB_TOKEN=legacy-team-token",
                "QCC_API_KEY=retained-qcc-token",
                "PROJECT_ASSISTANT_BROWSER_READY=true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    report, _, _ = MODULE.run(
        tmp_path,
        non_interactive=True,
        network=False,
        environment={},
    )

    values = MODULE.read_env_file(target)
    assert "GONGCHUANG_KB_TOKEN" not in values
    assert values["QCC_API_KEY"] == "retained-qcc-token"
    assert values["PROJECT_ASSISTANT_BROWSER_READY"] == "true"
    assert report["credentials"]["removed_from_plaintext_file"] == [
        "GONGCHUANG_KB_TOKEN"
    ]


def test_first_run_can_persist_default_policy_region(tmp_path):
    target = tmp_path / "profile.json"
    MODULE.write_region_profile("浙江省杭州市", target)
    profile = json.loads(target.read_text(encoding="utf-8"))
    assert profile["default_region"] == "浙江省杭州市"
    assert profile["scope"] == ["杭州市", "浙江省", "全国"]


def test_capability_profile_contains_names_not_secret_values(tmp_path):
    report, profile_file, _ = MODULE.run(
        tmp_path,
        non_interactive=True,
        network=False,
        environment={"GONGCHUANG_KB_ENDPOINT": "https://knowledge.example.com", "GONGCHUANG_KB_TOKEN": "hidden-value"},
    )
    saved = json.loads(profile_file.read_text(encoding="utf-8"))
    assert "GONGCHUANG_KB_TOKEN" in saved["credentials"]["detected_names"]
    assert "hidden-value" not in profile_file.read_text(encoding="utf-8")
    assert report["capabilities"]["team_knowledge"]["endpoint"] == "https://knowledge.example.com"


def test_first_run_uses_actual_capabilities_without_requiring_knowledge_or_host_skills(tmp_path):
    report, _, report_file = MODULE.run(
        tmp_path,
        non_interactive=True,
        network=False,
        environment={},
    )
    onboarding = report["onboarding"]
    assert onboarding["controlled_evolution_enabled"] is True
    assert onboarding["four_question_review_enabled"] is True
    assert onboarding["startup_protocol_completed"] is True
    assert onboarding["knowledge_connection_check_required"] is False
    assert onboarding["knowledge_connection_check_prompt"] == ""
    assert "host_skill_install_prompt" not in onboarding
    report_text = report_file.read_text(encoding="utf-8")
    assert "受控自进化能力可用" in report_text
    assert "检查下知识库连接状态" not in report_text
    assert "帮我安装OCR、PDF、Word、PPT、Excel和联网检索这几个Skills" not in report_text
    assert not (tmp_path / "preferences.json").exists()
    assert report["personal_preferences"]["status"] == "not-created"
    assert report["report_role"] == "historical-capability-snapshot"


def test_first_run_requires_knowledge_only_for_a_task_that_needs_it(tmp_path):
    report, _, report_file = MODULE.run(
        tmp_path,
        non_interactive=True,
        network=False,
        environment={"PROJECT_ASSISTANT_KNOWLEDGE_REQUIRED": "true"},
    )
    onboarding = report["onboarding"]
    assert onboarding["startup_protocol_completed"] is False
    assert onboarding["knowledge_connection_check_required"] is True
    assert report["capabilities"]["team_knowledge"]["required"] is True
    assert "检查下知识库连接状态" in report_file.read_text(encoding="utf-8")


def test_first_run_initializes_preferences_only_with_explicit_authorization(tmp_path):
    report, _, _ = MODULE.run(
        tmp_path,
        non_interactive=True,
        network=False,
        environment={},
        persist_preferences=True,
    )
    preferences = json.loads((tmp_path / "preferences.json").read_text(encoding="utf-8"))
    assert preferences["schema_version"] == 1
    assert preferences["_meta"]["dirty"] is False
    assert report["personal_preferences"]["status"] == "local"


def test_knowledge_connection_does_not_trigger_host_skill_install_prompt(tmp_path):
    report, _, report_file = MODULE.run(
        tmp_path,
        non_interactive=True,
        network=False,
        environment={"GONGCHUANG_KB_MCP_READY": "true"},
    )
    onboarding = report["onboarding"]
    assert onboarding["startup_protocol_completed"] is True
    assert onboarding["knowledge_connection_check_required"] is False
    assert onboarding["knowledge_connection_check_prompt"] == ""
    assert "host_skill_install_prompt" not in onboarding
    report_text = report_file.read_text(encoding="utf-8")
    assert "检查下知识库连接状态" not in report_text
    assert "帮我安装OCR、PDF、Word、PPT、Excel和联网检索这几个Skills" not in report_text
    assert report["capabilities"]["team_knowledge"]["status"] == "ready"


def test_api_probe_does_not_replace_runtime_mcp_connection(tmp_path, monkeypatch):
    monkeypatch.setattr(
        MODULE,
        "probe_cloud",
        lambda *_args, **_kwargs: ("ready", "身份验证通过"),
    )
    report, _, report_file = MODULE.run(
        tmp_path,
        non_interactive=True,
        network=True,
        environment={
            "GONGCHUANG_KB_ENDPOINT": "https://knowledge.example.com",
            "GONGCHUANG_KB_TOKEN": "hidden-value",
            "PROJECT_ASSISTANT_KNOWLEDGE_REQUIRED": "true",
        },
    )
    assert report["capabilities"]["team_knowledge"]["status"] == "ready"
    assert report["onboarding"]["startup_protocol_completed"] is False
    assert report["onboarding"]["knowledge_connection_check_required"] is True
    assert "host_skill_install_prompt" not in report["onboarding"]
    assert "检查下知识库连接状态" in report_file.read_text(encoding="utf-8")


def test_incomplete_required_knowledge_connection_remains_in_startup_protocol(tmp_path):
    first, _, first_report = MODULE.run(
        tmp_path,
        non_interactive=True,
        network=False,
        environment={"PROJECT_ASSISTANT_KNOWLEDGE_REQUIRED": "true"},
    )
    second, _, second_report = MODULE.run(
        tmp_path,
        non_interactive=True,
        network=False,
        environment={"PROJECT_ASSISTANT_KNOWLEDGE_REQUIRED": "true"},
    )
    assert first["onboarding"]["startup_prompt_required"] is True
    assert second["onboarding"]["startup_prompt_required"] is True
    assert second["onboarding"]["startup_protocol_completed"] is False
    assert "检查下知识库连接状态" in first_report.read_text(encoding="utf-8")
    assert "检查下知识库连接状态" in second_report.read_text(encoding="utf-8")


def test_startup_prompt_only_appears_once_per_protocol_version(tmp_path):
    first, _, first_report = MODULE.run(
        tmp_path,
        non_interactive=True,
        network=False,
        environment={"GONGCHUANG_KB_MCP_READY": "true"},
    )
    assert first["onboarding"]["startup_prompt_required"] is True
    assert "帮我安装OCR、PDF、Word、PPT、Excel和联网检索这几个Skills" not in first_report.read_text(encoding="utf-8")

    second, _, second_report = MODULE.run(
        tmp_path,
        non_interactive=True,
        network=False,
        environment={"GONGCHUANG_KB_MCP_READY": "true"},
    )
    assert second["onboarding"]["startup_prompt_required"] is False
    assert "帮我安装OCR、PDF、Word、PPT、Excel和联网检索这几个Skills" not in second_report.read_text(encoding="utf-8")
