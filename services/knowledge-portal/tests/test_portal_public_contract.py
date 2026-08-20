from __future__ import annotations

import ast
from pathlib import Path

from fastapi.testclient import TestClient

from app.public_errors import public_error, public_error_text, redacted_log_detail
from test_portal import load_app


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
TEMPLATES = ROOT / "templates"


def test_public_error_redacts_secrets_paths_stacks_and_upstream_details() -> None:
    raw = (
        "Traceback: FileNotFoundError /Users/example/private/config.json "
        "api_key=sk-live-secret upstream connection refused"
    )

    controlled = public_error(503, raw)
    logged = redacted_log_detail(raw)
    html_text = public_error_text(503, raw)

    assert controlled.detail == "服务暂时不可用，请稍后重试。"
    assert controlled.diagnostic_code == "GC-SVC-503"
    assert controlled.redacted is True
    assert "sk-live-secret" not in logged
    assert "/Users/example" not in logged
    assert "[已脱敏]" in logged
    assert html_text == "服务暂时不可用，请稍后重试。（诊断码：GC-SVC-503）"
    assert public_error(502, "RuntimeError: provider failed").detail == (
        "服务暂时不可用，请稍后重试。"
    )


def test_http_and_unexpected_errors_return_controlled_chinese_with_codes(tmp_path) -> None:
    module = load_app(tmp_path)

    def unsafe_http_error():
        raise module.HTTPException(
            status_code=503,
            detail="upstream said sk-live-secret at /opt/provider/private.json",
        )

    def unsafe_unexpected_error():
        raise RuntimeError("Traceback /private/tmp/internal.py sk-live-secret")

    module.app.add_api_route("/v1/test-public-http-error", unsafe_http_error)
    module.app.add_api_route("/v1/test-public-unexpected-error", unsafe_unexpected_error)

    with TestClient(module.app, raise_server_exceptions=False) as client:
        http_response = client.get("/v1/test-public-http-error")
        unexpected_response = client.get("/v1/test-public-unexpected-error")

    assert http_response.status_code == 503
    assert http_response.json() == {
        "detail": "服务暂时不可用，请稍后重试。",
        "diagnostic_code": "GC-SVC-503",
    }
    assert unexpected_response.status_code == 500
    assert unexpected_response.json() == {
        "detail": "服务暂时不可用，请稍后重试。",
        "diagnostic_code": "GC-SVC-UNEXPECTED",
    }
    for response in (http_response, unexpected_response):
        assert "sk-live-secret" not in response.text
        assert "/opt/" not in response.text
        assert "/private/" not in response.text
        assert "Traceback" not in response.text


def test_validation_errors_do_not_echo_submitted_values(tmp_path) -> None:
    module = load_app(tmp_path)
    secret_input = "sk-secret-input-that-must-not-return"

    with TestClient(module.app) as client:
        response = client.post(
            "/v1/client-login",
            json={"client_id": secret_input},
        )

    assert response.status_code == 422
    assert response.json() == {
        "detail": "请求参数不完整或格式不正确。",
        "diagnostic_code": "GC-REQ-422",
    }
    assert secret_input not in response.text


def test_user_visible_assets_use_gongchuang_name_and_controlled_errors() -> None:
    visible_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [
            *TEMPLATES.glob("*.html"),
            STATIC / "portal.js",
            ROOT / "installers" / "jiaotang-agent.mjs",
            ROOT / "references" / "release-function-introductions.json",
        ]
    )
    portal_js = (STATIC / "portal.js").read_text(encoding="utf-8")

    assert "WorkBuddy" not in visible_text
    assert "portalResponseError" in portal_js
    assert "portalErrorText" in portal_js
    assert "throw new Error(payload.detail" not in portal_js
    assert "textContent = error.message" not in portal_js


def test_workbuddy_protocol_keys_and_legacy_filenames_are_the_only_source_mentions() -> None:
    main_path = ROOT / "app" / "main.py"
    tree = ast.parse(main_path.read_text(encoding="utf-8"))
    mentions = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and "WorkBuddy" in node.value
    ]

    assert mentions
    assert all("-WorkBuddy.zip" in value for value in mentions)
    source = main_path.read_text(encoding="utf-8")
    for compatibility_key in (
        '"workbuddy_version"',
        '"workbuddy_sha256"',
        '"host": "workbuddy"',
        '"type": "signed_workbuddy_plugin"',
    ):
        assert compatibility_key in source


def test_skill_center_css_has_no_unused_workbuddy_variant_or_exact_duplicate() -> None:
    css = (STATIC / "skill-center.css").read_text(encoding="utf-8")

    assert ".skill-platform-card.is-workbuddy" not in css
    assert css.count(".skill-list-heading .skill-kicker { display:none; }") == 1
