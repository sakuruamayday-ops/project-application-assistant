from __future__ import annotations

import json
import os
import re
import subprocess
from contextlib import closing
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.device_security import (
    base64url_encode,
    device_key_id,
    enrollment_canonical_value,
)

from three_step_install_fixture import (
    PLATFORM_CASES,
    allow_fixture_release,
    build_workbuddy_connector_fixture,
    enrollment_row,
    load_isolated_portal,
    run_live_portal,
    seed_registered_member,
)


BASE_DIR = Path(__file__).resolve().parent.parent
CONNECTOR = BASE_DIR / "installers" / "jiaotang-agent.mjs"
NODE_BINARY = os.environ.get("JIAOTANG_E2E_NODE_BINARY", "node")


def csrf_from_skills_page(client: httpx.Client) -> str:
    response = client.get("/skills")
    assert response.status_code == 200
    match = re.search(r'data-csrf-token="([^"]+)"', response.text)
    assert match is not None
    return match.group(1)


@pytest.mark.parametrize(
    "platform_case",
    PLATFORM_CASES,
    ids=lambda case: case.test_id,
)
def test_three_step_install_reaches_verified_mcp_on_both_platforms(
    tmp_path,
    monkeypatch,
    platform_case,
):
    portal = load_isolated_portal(tmp_path / "portal", monkeypatch)
    artifact = build_workbuddy_connector_fixture(tmp_path, CONNECTOR)
    allow_fixture_release(portal, monkeypatch, artifact)
    username, password = seed_registered_member(portal)

    with run_live_portal(portal) as base_url:
        with httpx.Client(base_url=base_url, follow_redirects=False) as client:
            login = client.post(
                "/login",
                data={"username": username, "password": password},
            )
            assert login.status_code == 303
            csrf_token = csrf_from_skills_page(client)

            # Step 1: review only. No bootstrap endpoint is disclosed or usable.
            review_response = client.post(
                "/agent-bootstrap-codes",
                data={"csrf_token": csrf_token},
            )
            assert review_response.status_code == 200
            review = review_response.json()
            assert review["phase"] == "review"
            assert "/v1/agent-bootstrap/" not in json.dumps(review)
            enrollment_code = review["review_code"]
            review_protocol = client.get(
                f"/v1/agent-install/{enrollment_code}",
                params={"platform": platform_case.portal_platform},
            )
            assert review_protocol.status_code == 200
            assert review_protocol.json()["phase"] == "review"
            assert review_protocol.json()["installation"]["authorized"] is False
            assert client.get(f"/v1/agent-bootstrap/{enrollment_code}").status_code == 403

            # Step 2: signed plugin installation is authorized, but binding is not.
            install_response = client.post(
                "/agent-bootstrap-codes/confirm",
                data={
                    "csrf_token": csrf_token,
                    "enrollment_code": enrollment_code,
                    "platform": platform_case.portal_platform,
                },
            )
            assert install_response.status_code == 200
            installation = install_response.json()
            assert installation["phase"] == "install_authorized"
            assert "/v1/agent-bootstrap/" not in json.dumps(installation)
            authorized_protocol = client.get(
                f"/v1/agent-install/{enrollment_code}",
                params={"platform": platform_case.portal_platform},
            ).json()
            assert authorized_protocol["installation"]["authorized"] is True
            assert (
                authorized_protocol["installation"]["mcp_configuration"]["mode"]
                == platform_case.expected_mcp_mode
            )
            assert platform_case.expected_host_path in (
                authorized_protocol["review"]["storage_model"]["layers"][0]["path"]
            )
            if platform_case.runtime_platform == "win32":
                compatibility = authorized_protocol["installation"][
                    "workbuddy_5_3_compatibility"
                ]
                assert "${CODEBUDDY_PLUGIN_ROOT}" in compatibility["trigger"]
                assert compatibility["scope"] == "user_mcp_jiaotang_kb_entry_only"
                assert compatibility["preserve_other_servers"] is True
                assert compatibility["modify_signed_plugin_files"] is False
            assert client.get(f"/v1/agent-bootstrap/{enrollment_code}").status_code == 403
            state_after_install = enrollment_row(portal, enrollment_code)
            assert state_after_install["confirmed_at"]
            assert state_after_install["binding_authorized_at"] is None

            prebinding_private_key = Ed25519PrivateKey.generate()
            prebinding_public_key = base64url_encode(
                prebinding_private_key.public_key().public_bytes(
                    Encoding.DER,
                    PublicFormat.SubjectPublicKeyInfo,
                )
            )
            prebinding_device_id = f"device:prebinding-{platform_case.test_id}-0001"
            prebinding_registration = {
                "device_id": prebinding_device_id,
                "device_name": f"prebinding-{platform_case.test_id}",
                "platform": f"{platform_case.runtime_platform}-fixture",
                "agent_host": "workbuddy",
                "public_key": prebinding_public_key,
                "transaction_mode": "credential_activation_v1",
            }
            prebinding_registration["proof"] = base64url_encode(
                prebinding_private_key.sign(
                    enrollment_canonical_value(
                        enrollment_code=enrollment_code,
                        **prebinding_registration,
                    )
                )
            )
            register_before_binding = client.post(
                f"/v1/agent-bootstrap/{enrollment_code}/register",
                json=prebinding_registration,
            )
            assert register_before_binding.status_code == 403
            assert "第三步知识库绑定授权" in register_before_binding.json()[
                "detail"
            ]
            activate_before_binding = client.post(
                f"/v1/agent-bootstrap/{enrollment_code}/activate",
                json={
                    "device_id": prebinding_device_id,
                    "key_id": device_key_id(prebinding_public_key),
                    "token": "prebinding-test-token-0001",
                    "proof": "prebinding-test-proof-value-that-is-not-used",
                },
            )
            assert activate_before_binding.status_code == 403
            assert "第三步知识库绑定授权" in activate_before_binding.json()[
                "detail"
            ]

            # Step 3: only this authenticated action unlocks the bootstrap manifest.
            binding_response = client.post(
                "/agent-bootstrap-codes/binding",
                data={
                    "csrf_token": csrf_token,
                    "enrollment_code": enrollment_code,
                },
            )
            assert binding_response.status_code == 200
            binding = binding_response.json()
            assert binding["phase"] == "binding_authorized"
            bootstrap_url = binding["manual_configuration"]["bootstrap_url"]
            assert bootstrap_url.startswith(
                f"{base_url}/v1/agent-bootstrap/{enrollment_code}"
            )
            manifest = client.get(bootstrap_url)
            assert manifest.status_code == 200
            assert manifest.json()["supported_platforms"] == ["darwin", "win32"]

            credential_file = tmp_path / f"{platform_case.test_id}-credential"
            agent_home = tmp_path / f"{platform_case.test_id}-home"
            completed = subprocess.run(
                [
                    NODE_BINARY,
                    str(CONNECTOR),
                    "install",
                    "--plugin-mode",
                    "--bootstrap-url",
                    bootstrap_url,
                    "--platform",
                    platform_case.runtime_platform,
                    "--home",
                    str(agent_home),
                    "--host",
                    "workbuddy",
                    "--device-name",
                    f"three-step-{platform_case.test_id}",
                ],
                capture_output=True,
                check=False,
                text=True,
                timeout=90,
                env={
                    **os.environ,
                    "JIAOTANG_ENABLE_TEST_CREDENTIAL_FILE": "1",
                    "JIAOTANG_TEST_CREDENTIAL_FILE": str(credential_file),
                },
            )
            assert completed.returncode == 0, completed.stderr
            result = json.loads(completed.stdout)
            assert result["schema"] == "jiaotang-agent-result/v1"
            assert result["ok"] is True
            assert result["status"] == "configured"
            assert result["host"] == "workbuddy"
            assert result["platform"] == platform_case.runtime_platform
            assert result["mcp"] == "connected"
            assert result["reported_to_portal"] is True
            assert all(
                stage["completed"] for stage in result["stages"].values()
            )
            assert credential_file.is_file()
            assert credential_file.stat().st_mode & 0o777 == 0o600
            combined_output = f"{completed.stdout}\n{completed.stderr}"
            assert enrollment_code not in combined_output
            assert not re.search(r"jtk_[A-Za-z0-9_-]+", combined_output)

            status = client.get("/agent-installation-status")
            assert status.status_code == 200
            portal_status = status.json()
            assert portal_status["configured"] is True
            assert all(
                stage["complete"] for stage in portal_status["stages"].values()
            )
            final_state = enrollment_row(portal, enrollment_code)
            assert final_state["binding_authorized_at"]
            assert final_state["registered_at"]
            assert final_state["consumed_at"]
            assert final_state["result_status"] == "configured"
            assert final_state["result_ok"] == 1
            assert final_state["result_platform"] == platform_case.runtime_platform
            assert client.post(
                "/agent-bootstrap-codes/binding",
                data={
                    "csrf_token": csrf_token,
                    "enrollment_code": enrollment_code,
                },
            ).status_code == 410

        with closing(portal.database()) as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM device_bindings WHERE revoked_at IS NULL"
            ).fetchone()[0] == 1
            assert connection.execute(
                "SELECT COUNT(*) FROM device_keys WHERE revoked_at IS NULL"
            ).fetchone()[0] == 1
            stored_platform = connection.execute(
                "SELECT platform FROM device_keys WHERE revoked_at IS NULL"
            ).fetchone()["platform"]
            assert stored_platform.startswith(f"{platform_case.runtime_platform}-")
