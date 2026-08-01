from __future__ import annotations

import hashlib
import importlib
import json
import socket
import sqlite3
import threading
import time
import zipfile
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import httpx
import uvicorn


@dataclass(frozen=True)
class InstallPlatformCase:
    test_id: str
    runtime_platform: str
    portal_platform: str
    expected_host_path: str
    expected_mcp_mode: str


PLATFORM_CASES = (
    InstallPlatformCase(
        test_id="macos",
        runtime_platform="darwin",
        portal_platform="macos",
        expected_host_path="~/.workbuddy/plugins",
        expected_mcp_mode="signed_external_plugin_mcp_file",
    ),
    InstallPlatformCase(
        test_id="windows",
        runtime_platform="win32",
        portal_platform="windows",
        expected_host_path="~/.workbuddy/plugins",
        expected_mcp_mode="signed_external_plugin_mcp_file",
    ),
)


def load_isolated_portal(data_dir: Path, monkeypatch):
    monkeypatch.setenv("JIAOTANG_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JIAOTANG_INDEX_DIR", str(data_dir / "knowledge-index"))
    monkeypatch.setenv("JIAOTANG_SETUP_KEY", "three-step-e2e-setup")
    monkeypatch.setenv(
        "JIAOTANG_TOKEN_DERIVATION_SECRET",
        "three-step-e2e-token-derivation-secret",
    )
    monkeypatch.setenv("JIAOTANG_SECURE_COOKIES", "false")
    monkeypatch.setenv("JIAOTANG_PUBLIC_HOST", "127.0.0.1")
    monkeypatch.setenv("JIAOTANG_WEB_SEARCH_RSS_URL", "")
    monkeypatch.delenv("JIAOTANG_AI_API_BASE", raising=False)
    monkeypatch.delenv("JIAOTANG_AI_API_KEY", raising=False)
    monkeypatch.delenv("JIAOTANG_AI_MODEL", raising=False)

    from app import main as portal

    portal = importlib.reload(portal)
    portal.init_database()
    return portal


def build_workbuddy_connector_fixture(
    fixture_dir: Path,
    connector_path: Path,
) -> dict[str, object]:
    connector = connector_path.read_bytes()
    connector_sha256 = hashlib.sha256(connector).hexdigest()
    package = fixture_dir / "three-step-workbuddy.zip"
    plugin_root = "fixture/plugins/jiaotang-workbuddy-skills"
    manifest = {
        "files": {
            "mcp/jiaotang-agent.mjs": connector_sha256,
        }
    }
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{plugin_root}/mcp/jiaotang-agent.mjs", connector)
        archive.writestr(
            f"{plugin_root}/plugin-release-manifest.json",
            json.dumps(manifest, sort_keys=True),
        )
        archive.writestr(
            f"{plugin_root}/.mcp.json",
            json.dumps(
                {
                    "mcpServers": {
                        "jiaotang-kb": {
                            "command": "${CODEBUDDY_PLUGIN_ROOT}/bin/run-node",
                            "args": [
                                "${CODEBUDDY_PLUGIN_ROOT}/mcp/jiaotang-agent.mjs",
                                "plugin-serve",
                            ],
                        }
                    }
                },
                sort_keys=True,
            ),
        )
    return {
        "version": "1.4.3",
        "file_name": package.name,
        "file_path": str(package),
        "sha256": hashlib.sha256(package.read_bytes()).hexdigest(),
        "target": "workbuddy",
    }


def allow_fixture_release(portal, monkeypatch, artifact: dict[str, object]) -> None:
    monkeypatch.setattr(
        portal,
        "latest_skill_artifact",
        lambda target: dict(artifact) if target == "workbuddy" else None,
    )
    monkeypatch.setattr(
        portal,
        "validate_release_artifact_for_serving",
        lambda selected, *, target, require_signature: {
            "status": "verified",
            "signed_format": bool(require_signature),
            "mcp_configuration_mode": "signed_external_plugin_mcp_file",
            "sha256": str((selected or {}).get("sha256") or ""),
        },
    )


def seed_registered_member(portal) -> tuple[str, str]:
    username = "three-step-member"
    password = "three-step-password-123"
    now = portal.isoformat(portal.utc_now())
    with closing(portal.database()) as connection:
        cursor = connection.execute(
            """
            INSERT INTO users(username,real_name,company_name,password_hash,created_at)
            VALUES (?,?,?,?,?)
            """,
            (
                username,
                "端到端测试",
                "焦糖测试",
                portal.password_hasher.hash(password),
                now,
            ),
        )
        user_id = int(cursor.lastrowid)
        connection.execute(
            """
            INSERT INTO registration_authorizations(
                real_name,identity_code,status,user_id,created_at,registered_at
            ) VALUES (?,?,'registered',?,?,?)
            """,
            ("端到端测试", "0801", user_id, now, now),
        )
        connection.commit()
    return username, password


@contextmanager
def run_live_portal(portal) -> Iterator[str]:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = int(listener.getsockname()[1])
    allowed_hosts = portal.knowledge_mcp.settings.transport_security.allowed_hosts
    allowed_hosts.append(f"127.0.0.1:{port}")
    server = uvicorn.Server(
        uvicorn.Config(
            portal.app,
            host="127.0.0.1",
            port=port,
            log_level="critical",
            access_log=False,
            lifespan="on",
        )
    )
    server.install_signal_handlers = lambda: None
    thread = threading.Thread(
        target=server.run,
        kwargs={"sockets": [listener]},
        name=f"three-step-install-{port}",
        daemon=True,
    )
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 15
    try:
        while time.monotonic() < deadline:
            if not thread.is_alive():
                raise RuntimeError("三步安装测试门户提前退出")
            try:
                if httpx.get(f"{base_url}/login", timeout=0.5).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.05)
        else:
            raise RuntimeError("三步安装测试门户启动超时")
        yield base_url
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        listener.close()
        if thread.is_alive():
            raise RuntimeError("三步安装测试门户未正常停止")


def enrollment_row(portal, enrollment_code: str) -> sqlite3.Row:
    with closing(portal.database()) as connection:
        row = connection.execute(
            """
            SELECT confirmed_at,binding_authorized_at,registered_at,consumed_at,
                   result_status,result_ok,result_platform
            FROM agent_enrollment_codes
            WHERE code_hash=?
            """,
            (portal.token_hash(enrollment_code),),
        ).fetchone()
    if row is None:
        raise AssertionError("未找到三步安装登记记录")
    return row
