import asyncio
import hashlib
import importlib
import io
import json
import os
import re
import sqlite3
import subprocess
import time
import uuid
import zipfile
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi.testclient import TestClient

from app.device_security import (
    activation_canonical_value,
    base64url_encode,
    device_key_id,
    enrollment_canonical_value,
    request_canonical_value,
)
from scripts.build_knowledge_content_index import cache_status_reusable


TEST_DEVICE_ID = "device:test-installation-0001"
TEST_DEVICE_NAME = "Test Device"


def complete_skill_release_fixture(skill_source_dir) -> bytes:
    """Build a structurally complete archive for portal upload-flow tests."""
    suite = json.loads(
        (skill_source_dir / "suite-manifest.json").read_text(encoding="utf-8")
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "fixture/skills/suite-manifest.json",
            json.dumps(suite, ensure_ascii=False, sort_keys=True),
        )
        for skill_name in suite["skills"]:
            skill_body = f"# {skill_name}\n".encode()
            skill_root = f"fixture/skills/{skill_name}/"
            manifest = {
                "skill_name": skill_name,
                "required_paths": ["SKILL.md"],
                "files": {"SKILL.md": hashlib.sha256(skill_body).hexdigest()},
            }
            archive.writestr(f"{skill_root}SKILL.md", skill_body)
            archive.writestr(
                f"{skill_root}release-manifest.json",
                json.dumps(manifest, ensure_ascii=False, sort_keys=True),
            )
            archive.writestr(f"{skill_root}release-manifest.json.sig", "fixture")
            archive.writestr(f"{skill_root}release-signature.json", "{}")
            archive.writestr(f"{skill_root}publisher-ed25519.pub", "fixture")
    return buffer.getvalue()


def invalidly_signed_complete_skill_release_fixture(
    skill_source_dir,
    *,
    version: str,
) -> bytes:
    """Build a structurally complete package whose publisher signature is invalid."""
    suite = json.loads(
        (skill_source_dir / "suite-manifest.json").read_text(encoding="utf-8")
    )
    suite["release"] = {"tag": f"V{version}", "version": version}
    files: dict[str, bytes] = {
        "skills/suite-manifest.json": json.dumps(
            suite,
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8"),
    }
    for skill_name in suite["skills"]:
        skill_body = f"# {skill_name}\n".encode()
        skill_root = f"skills/{skill_name}/"
        skill_manifest = {
            "skill_name": skill_name,
            "required_paths": ["SKILL.md"],
            "files": {"SKILL.md": hashlib.sha256(skill_body).hexdigest()},
        }
        files[f"{skill_root}SKILL.md"] = skill_body
        files[f"{skill_root}release-manifest.json"] = json.dumps(
            skill_manifest,
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
        files[f"{skill_root}release-manifest.json.sig"] = b"invalid"
        files[f"{skill_root}release-signature.json"] = b"{}"
        files[f"{skill_root}publisher-ed25519.pub"] = b"invalid"

    suite_manifest = {
        "schema_version": 1,
        "artifact_type": "skill-suite",
        "release_tag": f"V{version}",
        "release_version": version,
        "skill_count": len(suite["skills"]),
        "skills": suite["skills"],
        "files": {
            name: hashlib.sha256(content).hexdigest()
            for name, content in files.items()
        },
    }
    files["suite-release-manifest.json"] = json.dumps(
        suite_manifest,
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    files["suite-release-manifest.sig"] = b"invalid-publisher-signature"
    files["publisher-ed25519.pub"] = b"invalid-publisher-key"
    files["publisher-key.json"] = json.dumps(
        {
            "algorithm": "Ed25519",
            "fingerprint_sha256": (
                "SHA256:+BLR7x5xFci+u1Ue3KoFs9jFzzS+ebNk46JlfDUoEJI"
            ),
        },
        sort_keys=True,
    ).encode("utf-8")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(f"fixture/{name}", content)
    return buffer.getvalue()


def api_headers(token: str, device_id: str = TEST_DEVICE_ID) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Jiaotang-Device-ID": device_id,
        "X-Jiaotang-Device-Name": TEST_DEVICE_NAME,
    }


def provision_signed_device(module, user_id: int, *, agent_host: str = "pytest"):
    private_key = Ed25519PrivateKey.generate()
    public_key = base64url_encode(
        private_key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    )
    key_id = device_key_id(public_key)
    now = module.isoformat(module.utc_now())
    with closing(module.database()) as connection:
        binding = connection.execute(
            """
            INSERT INTO device_bindings(
                user_id,device_id_hash,device_id_prefix,device_name,auth_method,
                first_bound_at,last_seen_at,last_ip,user_agent
            ) VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                user_id,
                hashlib.sha256(TEST_DEVICE_ID.encode("utf-8")).hexdigest(),
                TEST_DEVICE_ID[:12],
                TEST_DEVICE_NAME,
                "device_signature",
                now,
                now,
                "testclient",
                "pytest",
            ),
        )
        connection.execute(
            """
            INSERT INTO device_keys(
                user_id,binding_id,key_id,public_key,platform,agent_host,created_at
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (user_id, binding.lastrowid, key_id, public_key, "test", agent_host, now),
        )
        connection.commit()
    return private_key, key_id


def active_user_token(module, user_id: int) -> str:
    with closing(module.database()) as connection:
        row = connection.execute(
            """
            SELECT token_seed FROM device_tokens
            WHERE user_id=? AND revoked_at IS NULL
            ORDER BY id DESC LIMIT 1
            """,
            (user_id,),
        ).fetchone()
    assert row is not None
    return module.user_access_token(user_id, str(row["token_seed"]))


def signed_api_headers(
    module,
    token: str,
    private_key: Ed25519PrivateKey,
    key_id: str,
    *,
    method: str,
    request_target: str,
    body: bytes = b"",
    nonce: str | None = None,
) -> dict[str, str]:
    timestamp = str(int(time.time()))
    nonce_value = nonce or base64url_encode(uuid.uuid4().bytes)
    canonical = request_canonical_value(
        method=method,
        request_target=request_target,
        timestamp=timestamp,
        nonce=nonce_value,
        body_hash=hashlib.sha256(body).hexdigest(),
        token_fingerprint=module.token_hash(token),
    )
    return {
        **api_headers(token),
        "X-Jiaotang-Key-ID": key_id,
        "X-Jiaotang-Timestamp": timestamp,
        "X-Jiaotang-Nonce": nonce_value,
        "X-Jiaotang-Signature": base64url_encode(private_key.sign(canonical)),
    }


def create_test_content_index(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript(
            """
            CREATE TABLE documents (
                id INTEGER PRIMARY KEY,
                source_key TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                source TEXT NOT NULL,
                cloud_path TEXT NOT NULL,
                document_role TEXT NOT NULL,
                sensitivity TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                canonical_project_name TEXT NOT NULL DEFAULT '',
                region TEXT NOT NULL DEFAULT '',
                document_stage TEXT NOT NULL DEFAULT '其他',
                validity_status TEXT NOT NULL DEFAULT 'active_candidate',
                policy_year INTEGER,
                batch TEXT NOT NULL DEFAULT '',
                replacement_title TEXT NOT NULL DEFAULT '',
                replacement_basis TEXT NOT NULL DEFAULT '',
                replacement_url TEXT NOT NULL DEFAULT ''
            );
            CREATE VIRTUAL TABLE documents_fts_trigram USING fts5(
                title,
                content,
                source,
                document_role,
                content='documents',
                content_rowid='id',
                tokenize='trigram'
            );
            CREATE VIRTUAL TABLE documents_fts USING fts5(
                title,
                content,
                source,
                document_role,
                content='documents',
                content_rowid='id',
                tokenize='unicode61'
            );
            CREATE TABLE document_chunks (
                id INTEGER PRIMARY KEY,
                document_id INTEGER NOT NULL REFERENCES documents(id),
                chunk_number INTEGER NOT NULL,
                content TEXT NOT NULL,
                UNIQUE(document_id, chunk_number)
            );
            CREATE VIRTUAL TABLE document_chunks_fts USING fts5(
                document_id UNINDEXED,
                chunk_number UNINDEXED,
                title,
                content,
                source,
                tokenize='trigram'
            );
            CREATE TABLE enterprise_mentions (
                id INTEGER PRIMARY KEY,
                document_id INTEGER NOT NULL REFERENCES documents(id),
                enterprise_name TEXT NOT NULL,
                sequence_no TEXT NOT NULL,
                context TEXT NOT NULL,
                UNIQUE(document_id, enterprise_name, sequence_no)
            );
            CREATE INDEX enterprise_mentions_name_idx ON enterprise_mentions(enterprise_name);
            CREATE TABLE public_list_entities (
                id INTEGER PRIMARY KEY,
                document_id INTEGER NOT NULL REFERENCES documents(id),
                enterprise_name TEXT NOT NULL,
                sequence_no TEXT NOT NULL,
                canonical_project_name TEXT NOT NULL,
                policy_year INTEGER,
                batch TEXT NOT NULL,
                region TEXT NOT NULL,
                list_status TEXT NOT NULL,
                context TEXT NOT NULL,
                confidence TEXT NOT NULL,
                UNIQUE(document_id, enterprise_name, sequence_no)
            );
            CREATE TABLE project_alias_corrections (
                id INTEGER PRIMARY KEY,
                raw_project_name TEXT NOT NULL,
                canonical_project_name TEXT NOT NULL,
                region TEXT NOT NULL DEFAULT '',
                start_year INTEGER,
                end_year INTEGER,
                status TEXT NOT NULL DEFAULT 'pending',
                confirmed_by TEXT NOT NULL DEFAULT '',
                confirmed_at TEXT,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(raw_project_name,canonical_project_name,region,start_year,end_year)
            );
            CREATE TABLE metadata_match_evidence (
                id INTEGER PRIMARY KEY,
                document_id INTEGER NOT NULL REFERENCES documents(id),
                field_name TEXT NOT NULL,
                inferred_value TEXT NOT NULL,
                matched_term TEXT NOT NULL,
                match_method TEXT NOT NULL,
                source_scope TEXT NOT NULL,
                source_excerpt TEXT NOT NULL,
                rule_version TEXT NOT NULL,
                confidence TEXT NOT NULL,
                review_status TEXT NOT NULL DEFAULT 'unreviewed',
                correction_id INTEGER REFERENCES project_alias_corrections(id),
                created_at TEXT NOT NULL,
                UNIQUE(document_id,field_name,rule_version)
            );
            CREATE TABLE policy_verification_queue (
                id INTEGER PRIMARY KEY,
                document_id INTEGER NOT NULL REFERENCES documents(id),
                reason TEXT NOT NULL,
                priority TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                official_source_url TEXT NOT NULL DEFAULT '',
                official_document_title TEXT NOT NULL DEFAULT '',
                official_published_at TEXT,
                verification_note TEXT NOT NULL DEFAULT '',
                verified_by TEXT NOT NULL DEFAULT '',
                verified_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(document_id,reason)
            );
            CREATE TABLE policy_document_clusters (
                id INTEGER PRIMARY KEY,
                cluster_key TEXT NOT NULL UNIQUE,
                normalized_title TEXT NOT NULL,
                document_number TEXT NOT NULL DEFAULT '',
                canonical_project_name TEXT NOT NULL DEFAULT '',
                region TEXT NOT NULL DEFAULT '',
                policy_year INTEGER,
                representative_document_id INTEGER NOT NULL REFERENCES documents(id),
                match_method TEXT NOT NULL,
                confidence TEXT NOT NULL,
                rule_version TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE policy_document_cluster_members (
                id INTEGER PRIMARY KEY,
                cluster_id INTEGER NOT NULL REFERENCES policy_document_clusters(id),
                document_id INTEGER NOT NULL UNIQUE REFERENCES documents(id),
                membership_basis TEXT NOT NULL,
                confidence TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE policy_verification_propagations (
                id INTEGER PRIMARY KEY,
                source_queue_id INTEGER NOT NULL REFERENCES policy_verification_queue(id),
                cluster_id INTEGER NOT NULL REFERENCES policy_document_clusters(id),
                source_document_id INTEGER NOT NULL REFERENCES documents(id),
                target_document_id INTEGER NOT NULL REFERENCES documents(id),
                field_name TEXT NOT NULL,
                propagated_value TEXT NOT NULL,
                official_source_url TEXT NOT NULL DEFAULT '',
                evidence_excerpt TEXT NOT NULL,
                rule_version TEXT NOT NULL,
                propagated_by TEXT NOT NULL,
                propagated_at TEXT NOT NULL,
                UNIQUE(source_queue_id,target_document_id,field_name)
            );
            """
        )
        connection.execute(
            """
            INSERT INTO documents(
                source_key, title, content, source, cloud_path, document_role,
                sensitivity, sha256, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "doc-one",
                "小巨人测试资料",
                "产业链关键环节与工业六基匹配",
                "测试来源/小巨人测试资料.md",
                "60_申报案例与建设方案/小巨人测试资料.md",
                "60_申报案例与建设方案",
                "internal",
                "test-sha256",
                "2026-07-18T00:00:00+00:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO documents(
                source_key, title, content, source, cloud_path, document_role,
                sensitivity, sha256, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "doc-two",
                "后添加测试资料",
                "用于验证生产知识库按编号升序排列",
                "测试来源/后添加测试资料.md",
                "40_内部培训与方法/后添加测试资料.md",
                "40_内部培训与方法",
                "internal",
                "test-sha256-two",
                "2026-07-19T00:00:00+00:00",
            ),
        )
        list_document_id = connection.execute(
            """
            INSERT INTO documents(
                source_key,title,content,source,cloud_path,document_role,
                sensitivity,sha256,updated_at,canonical_project_name,region,
                document_stage,validity_status,policy_year,batch
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "doc-list",
                "2025年浙江省第六批专精特新小巨人认定名单",
                "1 | 杭州测试装备有限公司",
                "50_名单与对标/2025年浙江省第六批小巨人名单.md",
                "50_名单与对标/2025年浙江省第六批小巨人名单.md",
                "50_名单与对标",
                "public",
                "test-list-sha256",
                "2025-10-01T00:00:00+00:00",
                "国家专精特新“小巨人”企业",
                "浙江省",
                "认定名单",
                "active_candidate",
                2025,
                "第六批",
            ),
        ).lastrowid
        connection.execute(
            """
            INSERT INTO public_list_entities(
                document_id,enterprise_name,sequence_no,canonical_project_name,
                policy_year,batch,region,list_status,context,confidence
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                list_document_id,
                "杭州测试装备有限公司",
                "1",
                "国家专精特新“小巨人”企业",
                2025,
                "第六批",
                "浙江省",
                "认定名单",
                "1 | 杭州测试装备有限公司",
                "high",
            ),
        )
        connection.execute(
            """
            INSERT INTO documents(
                source_key,title,content,source,cloud_path,document_role,
                sensitivity,sha256,updated_at,canonical_project_name,region,
                document_stage,validity_status,policy_year,batch
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "doc-policy",
                "2025年浙江省专精特新小巨人申报通知",
                "申报企业应当符合专精特新发展方向。",
                "10_政策与通知/2025年浙江省小巨人申报通知.md",
                "10_政策与通知/2025年浙江省小巨人申报通知.md",
                "10_政策与通知",
                "public",
                "test-policy-sha256",
                "2025-06-01T00:00:00+00:00",
                "国家专精特新“小巨人”企业",
                "浙江省",
                "申报通知",
                "active_candidate",
                2025,
                "",
            ),
        )
        connection.execute("INSERT INTO documents_fts(documents_fts) VALUES ('rebuild')")
        connection.execute("INSERT INTO documents_fts_trigram(documents_fts_trigram) VALUES ('rebuild')")
        connection.commit()


def load_app(tmp_path):
    os.environ["JIAOTANG_DATA_DIR"] = str(tmp_path)
    os.environ["JIAOTANG_INDEX_DIR"] = str(tmp_path / "knowledge-index")
    os.environ["JIAOTANG_FIRST_PUBLIC_SKILL_VERSION"] = "1.0"
    os.environ["JIAOTANG_SETUP_KEY"] = "setup-secret"
    os.environ["JIAOTANG_TOKEN_DERIVATION_SECRET"] = "test-token-derivation-secret"
    os.environ["JIAOTANG_SECURE_COOKIES"] = "false"
    os.environ["JIAOTANG_PUBLIC_HOST"] = "testserver"
    os.environ.pop("JIAOTANG_AI_API_BASE", None)
    os.environ.pop("JIAOTANG_AI_API_KEY", None)
    os.environ.pop("JIAOTANG_AI_MODEL", None)
    os.environ["JIAOTANG_WEB_SEARCH_RSS_URL"] = ""
    create_test_content_index(tmp_path / "knowledge-index" / "knowledge_content.sqlite3")
    import app.main

    module = importlib.reload(app.main)
    module.init_database()
    return module


def test_active_index_release_id_resolves_current_release_symlink(tmp_path):
    module = load_app(tmp_path)
    release_id = "policy-test-release-0001"
    release_dir = tmp_path / "knowledge-index" / "releases" / release_id
    release_dir.mkdir(parents=True)
    original = module.CONTENT_DATABASE_PATH
    release_database = release_dir / "knowledge_content.sqlite3"
    original.replace(release_database)
    original.symlink_to(Path("releases") / release_id / release_database.name)

    assert module.active_index_release_id() == release_id


def issue_test_invitation(module, connection, authorization_id: int) -> str:
    authorization = module.issue_registration_invite(
        connection,
        authorization_id,
        issued_by=None,
    )
    return module.registration_invite_token(authorization)


def allow_test_release_artifacts(monkeypatch, module) -> None:
    monkeypatch.setattr(
        module,
        "validate_release_artifact_for_serving",
        lambda artifact, *, target, require_signature: {
            "status": "verified",
            "signed_format": bool(require_signature),
            "mcp_configuration_mode": "signed_external_plugin_mcp_file",
        },
    )


def test_user_guide_is_removed_from_public_site(tmp_path):
    module = load_app(tmp_path)
    with TestClient(module.app) as client:
        guide = client.get("/guide")
        assert guide.status_code == 404

        client.post(
            "/setup",
            data={"setup_key": "setup-secret", "username": "owner", "password": "correct-horse-battery"},
        )
        login = client.get("/login")
        assert login.status_code == 200
        assert 'href="/guide"' not in login.text


def test_public_demo_uses_published_release_state_instead_of_hardcoded_version(tmp_path):
    module = load_app(tmp_path)
    with TestClient(module.app) as client:
        response = client.get("/demo")

    assert response.status_code == 200
    assert "尚未正式发布 · PRODUCT DEMO" in response.text
    assert "候选版本不会冒充正式下载" in response.text
    assert "V1.4.1 · PRODUCT DEMO" not in response.text
    assert "企业项目身份、政策规则与交付质量" in response.text
    assert "统一进入可追溯执行链" in response.text
    assert "项目决策算法" in response.text
    assert "企业项目身份数字孪生" in response.text
    assert "政策变化影响模拟" in response.text
    assert "交付契约自动修复" in response.text
    assert "专利全流程" in response.text
    assert "跨版本升级与失败回滚" in response.text


def test_personal_preferences_api_sync_history_undo_and_reset(tmp_path):
    module = load_app(tmp_path)
    with TestClient(module.app) as client:
        client.post(
            "/setup",
            data={"setup_key": "setup-secret", "username": "owner", "password": "correct-horse-battery"},
        )
        login = client.post(
            "/login",
            data={"username": "owner", "password": "correct-horse-battery"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)
        user = module.session_user(login.cookies[module.SESSION_COOKIE])[0]
        token_page = client.post(
            "/device-tokens",
            data={
                "real_name": "王小明",
                "company_name": "共创集团",
                "csrf_token": user["csrf_token"],
            },
        )
        token = active_user_token(module, int(user["id"]))
        headers = api_headers(token)

        initial = client.get("/v1/preferences", headers=headers)
        assert initial.status_code == 200
        assert initial.json()["revision"] == 0
        assert initial.json()["preferences"]["output"]["detail_level"] == "detailed"

        first = client.put(
            "/v1/preferences",
            headers=headers,
            json={
                "base_revision": 0,
                "change_summary": "设置默认城市",
                "preferences": {"region": {"province": "浙江省", "city": "杭州市"}},
            },
        )
        assert first.status_code == 200
        assert first.json()["revision"] == 1
        assert first.json()["preferences"]["region"]["city"] == "杭州市"

        stale = client.put(
            "/v1/preferences",
            headers=headers,
            json={"base_revision": 0, "preferences": {"output": {"tone": "formal"}}},
        )
        assert stale.status_code == 409

        second = client.put(
            "/v1/preferences",
            headers=headers,
            json={
                "base_revision": 1,
                "change_summary": "调整语气",
                "preferences": {"output": {"tone": "formal"}},
            },
        )
        assert second.status_code == 200
        assert second.json()["revision"] == 2
        assert second.json()["preferences"]["output"]["tone"] == "formal"

        undo = client.post("/v1/preferences/undo", headers=headers)
        assert undo.status_code == 200
        assert undo.json()["revision"] == 3
        assert undo.json()["preferences"]["region"]["city"] == "杭州市"

        history = client.get("/v1/preferences/history", headers=headers)
        assert history.status_code == 200
        assert [item["revision"] for item in history.json()][:3] == [3, 2, 1]

        reset = client.post("/v1/preferences/reset", headers=headers)
        assert reset.status_code == 200
        assert reset.json()["revision"] == 4
        assert reset.json()["preferences"]["region"]["city"] == ""

        protected = client.put(
            "/v1/preferences",
            headers=headers,
            json={"base_revision": 4, "preferences": {"skill_preferences": {"token": "no"}}},
        )
        assert protected.status_code == 422

        page = client.get("/preferences")
        assert page.status_code == 200
        assert "我的使用习惯" in page.text
        assert "请迁移我的旧版Skills个人习惯，并同步到云端" in page.text
        assert "撤销上一版" in page.text
        assert "恢复官方默认" in page.text


def test_oauth_routes_and_tables_are_removed(tmp_path):
    module = load_app(tmp_path)
    with closing(module.database()) as connection:
        for table_name in (
            "oauth_clients",
            "oauth_authorization_codes",
            "oauth_access_tokens",
            "oauth_refresh_tokens",
        ):
            connection.execute(f"CREATE TABLE {table_name}(id INTEGER PRIMARY KEY)")
            connection.execute(f"INSERT INTO {table_name}(id) VALUES (1)")
        connection.commit()
    module.init_database()
    with TestClient(module.app) as client:
        client.post(
            "/setup",
            data={"setup_key": "setup-secret", "username": "owner", "password": "correct-horse-battery"},
        )
        login = client.post(
            "/login",
            data={"username": "owner", "password": "correct-horse-battery"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)
        removed_paths = (
            "/.well-known/oauth-protected-resource",
            "/.well-known/oauth-authorization-server",
            "/authorize",
        )
        for path in removed_paths:
            assert client.get(path).status_code == 404
        for path in ("/oauth/register", "/oauth/authorize", "/oauth/token", "/oauth/revoke"):
            assert client.post(path).status_code == 404
        with closing(module.database()) as connection:
            tables = {
                str(row["name"])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert not {
            "oauth_clients",
            "oauth_authorization_codes",
            "oauth_access_tokens",
            "oauth_refresh_tokens",
        } & tables
        access_page = client.get("/access")
        assert access_page.status_code == 200
        assert "已授权 OAuth 客户端" not in access_page.text
        access_health = client.get("/admin/health/access")
        assert access_health.status_code == 200
        assert "OAuth授权与调用" not in access_health.text
        assert "累计OAuth调用" not in access_health.text


def test_admin_access_health_shows_connection_device_credentials_and_toggle(tmp_path):
    module = load_app(tmp_path)
    now = module.isoformat(module.utc_now())
    revoked_at = module.isoformat(module.utc_now() - timedelta(days=1))
    with closing(module.database()) as connection:
        connection.execute(
            """
            INSERT INTO users(
                username,real_name,company_name,password_hash,is_admin,created_at
            ) VALUES (?,?,?,?,1,?)
            """,
            (
                "owner",
                "管理员",
                "共创集团",
                module.password_hasher.hash("owner-password-123"),
                now,
            ),
        )
        member_id = int(
            connection.execute(
                """
                INSERT INTO users(
                    username,real_name,company_name,password_hash,created_at
                ) VALUES (?,?,?,?,?)
                """,
                (
                    "connected-member",
                    "连接用户",
                    "共创集团",
                    module.password_hasher.hash("member-password-123"),
                    now,
                ),
            ).lastrowid
        )
        disabled_id = int(
            connection.execute(
                """
                INSERT INTO users(
                    username,real_name,company_name,password_hash,active,created_at
                ) VALUES (?,?,?,?,0,?)
                """,
                (
                    "disabled-member",
                    "停用用户",
                    "共创集团",
                    module.password_hasher.hash("disabled-password-123"),
                    now,
                ),
            ).lastrowid
        )
        active_token_id = int(
            connection.execute(
                """
                INSERT INTO device_tokens(
                    user_id,label,token_prefix,token_hash,token_seed,
                    created_at,last_used_at
                ) VALUES (?,?,?,?,?,?,?)
                """,
                (
                    member_id,
                    "连接用户",
                    "jtk_active",
                    "active-token-hash",
                    "active-token-seed",
                    now,
                    now,
                ),
            ).lastrowid
        )
        connection.execute(
            """
            INSERT INTO device_tokens(
                user_id,label,token_prefix,token_hash,token_seed,
                created_at,last_used_at,revoked_at
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                member_id,
                "连接用户旧凭据",
                "jtk_revoked",
                "revoked-token-hash",
                "revoked-token-seed",
                revoked_at,
                revoked_at,
                revoked_at,
            ),
        )
        disabled_token_id = int(
            connection.execute(
                """
                INSERT INTO device_tokens(
                    user_id,label,token_prefix,token_hash,token_seed,
                    created_at,last_used_at
                ) VALUES (?,?,?,?,?,?,?)
                """,
                (
                    disabled_id,
                    "停用用户",
                    "jtk_disabled",
                    "disabled-token-hash",
                    "disabled-token-seed",
                    now,
                    now,
                ),
            ).lastrowid
        )
        connection.execute(
            """
            INSERT INTO api_usage(
                user_id,device_token_id,endpoint,method,activity_type,
                activity_name,counts_toward_usage,called_at
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                member_id,
                active_token_id,
                "/mcp",
                "POST",
                "mcp_connection",
                "MCP连接检测",
                0,
                now,
            ),
        )
        connection.execute(
            """
            INSERT INTO api_usage(
                user_id,device_token_id,endpoint,method,activity_type,
                activity_name,counts_toward_usage,called_at
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                member_id,
                active_token_id,
                "/v1/search",
                "POST",
                "rest_api",
                "知识检索",
                1,
                now,
            ),
        )
        connection.execute(
            """
            INSERT INTO api_usage(
                user_id,device_token_id,endpoint,method,activity_type,
                activity_name,counts_toward_usage,called_at
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                disabled_id,
                disabled_token_id,
                "/mcp",
                "POST",
                "mcp_connection",
                "MCP连接检测",
                0,
                now,
            ),
        )
        connection.execute(
            """
            INSERT INTO device_bindings(
                user_id,device_id_hash,device_id_prefix,device_name,
                auth_method,first_bound_at,last_seen_at
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (
                member_id,
                "device-hash",
                "device-prefix",
                "测试 MacBook Pro",
                "device_signature",
                now,
                now,
            ),
        )
        connection.commit()

    with TestClient(module.app) as client:
        login = client.post(
            "/login",
            data={"username": "owner", "password": "owner-password-123"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)
        owner = module.session_user(login.cookies[module.SESSION_COOKIE])[0]

        access_page = client.get("/admin/health/access")
        assert access_page.status_code == 200
        assert "当前活跃" in access_page.text
        assert "API Key" in access_page.text
        assert "测试 MacBook Pro" in access_page.text
        assert "有效 1" in access_page.text
        assert "已吊销 1" in access_page.text
        assert "访问已阻断" in access_page.text
        assert "随账号停用" in access_page.text
        assert "当前账号" in access_page.text
        assert f'action="/users/{member_id}/toggle"' in access_page.text
        assert 'name="return_to" value="/admin/health/access"' in access_page.text

        disabled = client.post(
            f"/users/{member_id}/toggle",
            data={
                "csrf_token": owner["csrf_token"],
                "return_to": "/admin/health/access",
            },
            follow_redirects=False,
        )
        assert disabled.status_code == 303
        assert disabled.headers["location"] == "/admin/health/access"
        with closing(module.database()) as connection:
            assert connection.execute(
                "SELECT active FROM users WHERE id=?",
                (member_id,),
            ).fetchone()["active"] == 0

        refreshed = client.get("/admin/health/access")
        assert refreshed.status_code == 200
        assert refreshed.text.count("访问已阻断") >= 2
        assert refreshed.text.count("随账号停用") >= 2
        assert f'action="/users/{member_id}/toggle"' in refreshed.text
        assert "启用" in refreshed.text


def test_admin_can_open_member_credentials_and_revoke_one_or_many(tmp_path):
    module = load_app(tmp_path)
    now = module.isoformat(module.utc_now())
    with closing(module.database()) as connection:
        connection.execute(
            """
            INSERT INTO users(
                username,real_name,company_name,password_hash,is_admin,created_at
            ) VALUES (?,?,?,?,1,?)
            """,
            (
                "owner",
                "管理员",
                "共创集团",
                module.password_hasher.hash("owner-password-123"),
                now,
            ),
        )
        member_id = int(
            connection.execute(
                """
                INSERT INTO users(
                    username,real_name,company_name,password_hash,created_at
                ) VALUES (?,?,?,?,?)
                """,
                (
                    "multi-device-member",
                    "多设备成员",
                    "共创集团",
                    module.password_hasher.hash("member-password-123"),
                    now,
                ),
            ).lastrowid
        )
        other_member_id = int(
            connection.execute(
                """
                INSERT INTO users(
                    username,real_name,company_name,password_hash,created_at
                ) VALUES (?,?,?,?,?)
                """,
                (
                    "other-member",
                    "其他成员",
                    "共创集团",
                    module.password_hasher.hash("other-password-123"),
                    now,
                ),
            ).lastrowid
        )
        first_token_id = int(
            connection.execute(
                """
                INSERT INTO device_tokens(
                    user_id,label,token_prefix,token_hash,token_seed,created_at,
                    last_used_at,credential_kind
                ) VALUES (?,?,?,?,?,?,?,'installation')
                """,
                (
                    member_id,
                    "办公室 MacBook",
                    "jtk_office",
                    "office-token-hash",
                    "office-token-seed",
                    now,
                    now,
                ),
            ).lastrowid
        )
        binding_id = int(
            connection.execute(
                """
                INSERT INTO device_bindings(
                    user_id,device_id_hash,device_id_prefix,device_name,
                    auth_method,first_bound_at,last_seen_at
                ) VALUES (?,?,?,?,?,?,?)
                """,
                (
                    member_id,
                    "home-device-hash",
                    "home-device",
                    "家中 Windows",
                    "device_signature",
                    now,
                    now,
                ),
            ).lastrowid
        )
        second_token_id = int(
            connection.execute(
                """
                INSERT INTO device_tokens(
                    user_id,label,token_prefix,token_hash,token_seed,created_at,
                    last_used_at,credential_kind,binding_id,activation_state
                ) VALUES (?,?,?,?,?,?,?,'device',?,'pending')
                """,
                (
                    member_id,
                    "家中 Windows",
                    "jtk_home",
                    "home-token-hash",
                    "home-token-seed",
                    now,
                    now,
                    binding_id,
                ),
            ).lastrowid
        )
        other_token_id = int(
            connection.execute(
                """
                INSERT INTO device_tokens(
                    user_id,label,token_prefix,token_hash,token_seed,created_at,
                    last_used_at,credential_kind
                ) VALUES (?,?,?,?,?,?,?,'personal')
                """,
                (
                    other_member_id,
                    "其他成员 API Key",
                    "jtk_other",
                    "other-token-hash",
                    "other-token-seed",
                    now,
                    now,
                ),
            ).lastrowid
        )
        connection.execute(
            """
            INSERT INTO device_keys(
                user_id,binding_id,key_id,public_key,platform,agent_host,created_at
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (
                member_id,
                binding_id,
                "home-key",
                "home-public-key",
                "windows-amd64",
                "workbuddy",
                now,
            ),
        )
        connection.commit()

    with TestClient(module.app) as client:
        login = client.post(
            "/login",
            data={"username": "owner", "password": "owner-password-123"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)
        owner = module.session_user(login.cookies[module.SESSION_COOKIE])[0]

        access = client.get("/admin/health/access")
        assert f'/admin/users/{member_id}#access-credentials' in access.text
        detail = client.get(f"/admin/users/{member_id}")
        assert detail.status_code == 200
        assert "访问凭据与接入方式" in detail.text
        assert "办公室 MacBook" in detail.text
        assert "家中 Windows" in detail.text
        assert 'name="credential_ids"' in detail.text
        assert f"/admin/users/{member_id}/credentials/revoke" in detail.text
        assert f"/admin/users/{member_id}/credentials/{first_token_id}/revoke" in detail.text

        wrong_member = client.post(
            f"/admin/users/{member_id}/credentials/{other_token_id}/revoke",
            data={"csrf_token": owner["csrf_token"]},
            follow_redirects=False,
        )
        assert wrong_member.status_code == 404
        with closing(module.database()) as connection:
            assert connection.execute(
                "SELECT revoked_at FROM device_tokens WHERE id=?",
                (other_token_id,),
            ).fetchone()["revoked_at"] is None

        one = client.post(
            f"/admin/users/{member_id}/credentials/{first_token_id}/revoke",
            data={"csrf_token": owner["csrf_token"]},
            follow_redirects=False,
        )
        assert one.status_code == 303
        assert "credentials_revoked=1" in one.headers["location"]
        with closing(module.database()) as connection:
            first = connection.execute(
                "SELECT revoked_at,revoked_reason,revoked_by FROM device_tokens WHERE id=?",
                (first_token_id,),
            ).fetchone()
            second = connection.execute(
                "SELECT revoked_at FROM device_tokens WHERE id=?",
                (second_token_id,),
            ).fetchone()
            assert first["revoked_at"]
            assert first["revoked_reason"] == "admin_credential_revoked"
            assert first["revoked_by"] == "owner"
            assert second["revoked_at"] is None
            assert connection.execute(
                "SELECT revoked_at FROM device_bindings WHERE id=?",
                (binding_id,),
            ).fetchone()["revoked_at"] is None

        many = client.post(
            f"/admin/users/{member_id}/credentials/revoke",
            data={
                "csrf_token": owner["csrf_token"],
                "credential_ids": [second_token_id],
            },
            follow_redirects=False,
        )
        assert many.status_code == 303
        assert "credentials_revoked=1" in many.headers["location"]
        with closing(module.database()) as connection:
            assert connection.execute(
                "SELECT revoked_at FROM device_tokens WHERE id=?",
                (second_token_id,),
            ).fetchone()["revoked_at"]
            assert connection.execute(
                "SELECT revoked_at,revoked_reason FROM device_bindings WHERE id=?",
                (binding_id,),
            ).fetchone()["revoked_reason"] == "admin_credential_revoked"
            assert connection.execute(
                "SELECT revoked_at,revoked_reason FROM device_keys WHERE binding_id=?",
                (binding_id,),
            ).fetchone()["revoked_reason"] == "admin_credential_revoked"
            assert connection.execute(
                "SELECT active FROM users WHERE id=?",
                (member_id,),
            ).fetchone()["active"] == 1

        client.cookies.clear()
        member_login = client.post(
            "/login",
            data={
                "username": "other-member",
                "password": "other-password-123",
            },
            follow_redirects=False,
        )
        client.cookies.update(member_login.cookies)
        regular_member = module.session_user(
            member_login.cookies[module.SESSION_COOKIE]
        )[0]
        forbidden = client.post(
            f"/admin/users/{other_member_id}/credentials/{other_token_id}/revoke",
            data={"csrf_token": regular_member["csrf_token"]},
            follow_redirects=False,
        )
        assert forbidden.status_code == 403
        with closing(module.database()) as connection:
            assert connection.execute(
                "SELECT revoked_at FROM device_tokens WHERE id=?",
                (other_token_id,),
            ).fetchone()["revoked_at"] is None


def test_directory_storage_size_ignores_inaccessible_path(tmp_path, monkeypatch):
    module = load_app(tmp_path)

    def inaccessible(*args, **kwargs):
        raise PermissionError("not readable")

    monkeypatch.setattr(module.Path, "exists", inaccessible)
    assert module.directory_storage_size(module.Path("/restricted")) == 0


def test_skill_catalog_is_available_to_regular_members_and_blocks_unknown_paths(tmp_path):
    module = load_app(tmp_path)
    with closing(module.database()) as connection:
        connection.execute(
            """
            INSERT INTO users(username,real_name,company_name,password_hash,created_at)
            VALUES (?,?,?,?,?)
            """,
            (
                "member",
                "王小明",
                "共创集团",
                module.password_hasher.hash("member-password-123"),
                module.isoformat(module.utc_now()),
            ),
        )
        connection.commit()

    with TestClient(module.app) as client:
        anonymous = client.get("/skills", follow_redirects=False)
        assert anonymous.status_code == 303
        assert anonymous.headers["location"].startswith("/login")

        login = client.post(
            "/login",
            data={"username": "member", "password": "member-password-123"},
            follow_redirects=False,
        )
        assert login.status_code == 303
        client.cookies.update(login.cookies)

        catalog = client.get("/skills")
        assert catalog.status_code == 200
        assert "正式发布清单" in catalog.text
        assert "技能清单" in catalog.text
        assert "版本与下载" in catalog.text
        assert "安装与连接" in catalog.text
        assert "生成安全安装计划" in catalog.text
        assert 'data-skill-open="project-application-assistant"' in catalog.text
        assert 'data-skill-row' in catalog.text
        expected_skill_count = len(module.skill_catalog_payload()["skills"])
        assert f"{expected_skill_count} / {expected_skill_count}" in catalog.text

        installation_status = client.get("/agent-installation-status")
        assert installation_status.status_code == 200
        assert installation_status.json()["schema"] == "gongchuang-web-install-status/v2"
        assert not installation_status.json()["configured"]
        assert set(installation_status.json()["stages"]) == {
            "skills",
            "tools_list",
            "service_status",
            "configuration_merge",
        }

        detail = client.get("/skills/catalog/project-application-assistant")
        assert detail.status_code == 200
        payload = detail.json()
        assert payload["name"] == "project-application-assistant"
        assert payload["title"] == "企业全生命周期助手"
        assert payload["file_count"] >= 1
        assert payload["fingerprint"]
        assert "企业全生命周期助手" in payload["skill_html"]
        assert any(item["path"] == "SKILL.md" for item in payload["files"])

        assert client.get("/skills/catalog/not-a-real-skill").status_code == 404
        assert client.get("/skills/catalog/%2E%2E%2Fapp%2Fmain.py").status_code == 404


def test_admin_portal_section_order_and_mcp_activity_status(tmp_path):
    module = load_app(tmp_path)
    with TestClient(module.app) as client:
        client.post(
            "/setup",
            data={
                "setup_key": "setup-secret",
                "username": "owner",
                "password": "owner-password-123",
            },
        )
        login = client.post(
            "/login",
            data={"username": "owner", "password": "owner-password-123"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)
        user = module.session_user(login.cookies[module.SESSION_COOKIE])[0]
        module.ensure_personal_access_token(int(user["id"]), "管理员个人 Token")
        now = module.isoformat(module.utc_now())
        with closing(module.database()) as connection:
            token_id = int(
                connection.execute(
                    "SELECT id FROM device_tokens WHERE user_id=? AND revoked_at IS NULL",
                    (int(user["id"]),),
                ).fetchone()["id"]
            )
            connection.execute(
                """
                INSERT INTO api_usage(
                    user_id,device_token_id,endpoint,method,activity_type,
                    activity_name,counts_toward_usage,called_at
                ) VALUES (?,?,'/mcp','POST','mcp_connection','MCP连接检测',0,?)
                """,
                (int(user["id"]), token_id, now),
            )
            connection.commit()

        portal = client.get("/portal")
        assert portal.status_code == 200
        section_order = [
            portal.text.index('id="algorithms"'),
            portal.text.index('id="api-access"'),
            portal.text.index('id="feedback"'),
            portal.text.index('id="skills"'),
            portal.text.index('id="health-admin"'),
        ]
        assert section_order == sorted(section_order)
        assert "MCP 最近活跃" in portal.text
        assert "评价插件包" not in portal.text
        assert "查看常用指令" not in portal.text

        status = client.get("/agent-installation-status")
        assert status.status_code == 200
        payload = status.json()
        assert payload["schema"] == "gongchuang-web-install-status/v2"
        assert payload["configured"] is True
        assert payload["connection"]["state"] == "recently_active"
        assert payload["connection"]["last_activity_type"] == "mcp_connection"
        assert payload["stages"]["service_status"]["complete"] is True


def test_project_algorithm_catalog_is_visible_to_regular_members(tmp_path):
    module = load_app(tmp_path)
    hangzhou_guardrail = module.current_policy_guardrail(
        "今年杭州市研发中心还没开始申报，企业能不能报？"
    )
    assert "市级研发中心（四市属地版）" in hangzhou_guardrail
    assert "作为准备和差距评估主基线" in hangzhou_guardrail
    assert "draft（尚未正式生效）" in hangzhou_guardrail
    assert "正式项目名称为杭州市企业高新技术研究开发中心" not in (
        hangzhou_guardrail
    )
    hangzhou_fallback = module.current_policy_fallback(
        "今年杭州市研发中心还没开始申报，企业能不能报？"
    )
    assert "2026年《杭州市重点企业研究院、企业研究院建设管理办法" in (
        hangzhou_fallback
    )
    assert "不能宣称正式符合" in hangzhou_fallback
    municipal_detail = module.project_algorithm_detail_payload(
        "municipal-enterprise-technology-center"
    )
    assert municipal_detail is not None
    municipal_source_titles = {
        source["title"] for source in municipal_detail["sources"]
    }
    assert {
        "杭州市企业技术中心管理办法",
        "绍兴市市级企业技术中心管理办法",
        "金华市企业技术中心管理办法（2024年版）",
        "宁波市企业技术中心项目路由说明",
    }.issubset(municipal_source_titles)
    assert "浙江省企业技术中心管理办法" not in municipal_source_titles
    assert all(
        "浙江省企业技术中心管理办法" not in rule["source"]
        for rule in municipal_detail["rules"]
    )
    institute_detail = module.project_algorithm_detail_payload(
        "hangzhou-enterprise-institute"
    )
    assert institute_detail is not None
    assert institute_detail["has_prospective_layer"] is True
    assert institute_detail["transition_notices"]
    district_green_detail = module.project_algorithm_detail_payload(
        "green-factory-1"
    )
    assert district_green_detail is not None
    assert district_green_detail["jurisdiction_resolution"]["status"] == (
        "resolved"
    )
    assert district_green_detail["jurisdiction_resolution"][
        "formal_conclusion_allowed"
    ] is True
    assert all(
        source["role"] == "上位依赖/非区级门槛"
        for source in district_green_detail["sources"]
        if "浙江省绿色" in source["title"]
    )
    assert '"registered_administrative_unit_count": 38' in (
        district_green_detail["raw_json"]
    )
    with closing(module.database()) as connection:
        connection.execute(
            """
            INSERT INTO users(username,real_name,company_name,password_hash,created_at)
            VALUES (?,?,?,?,?)
            """,
            (
                "algorithm-member",
                "算法成员",
                "共创集团",
                module.password_hasher.hash("member-password-123"),
                module.isoformat(module.utc_now()),
            ),
        )
        connection.commit()

    with TestClient(module.app) as client:
        anonymous = client.get("/algorithms", follow_redirects=False)
        assert anonymous.status_code == 303
        login = client.post(
            "/login",
            data={
                "username": "algorithm-member",
                "password": "member-password-123",
            },
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)
        response = client.get("/algorithms")
        confirmed_response = client.get("/algorithms?coverage=rules-confirmed")
        baseline_catalog_response = client.get(
            "/algorithms?coverage=policy-baseline-confirmed"
        )
        detail_response = client.get("/algorithms?project=little-giant")
        routing_response = client.get("/algorithms?project=first-equipment")
        municipal_response = client.get(
            "/algorithms?project=municipal-enterprise-technology-center"
        )
        institute_response = client.get(
            "/algorithms?project=hangzhou-enterprise-institute"
        )

    assert response.status_code == 200
    assert 'data-section-link="algorithms"' in response.text
    assert "项目算法包" in response.text
    assert "显示 29 / 29 个主项目" in response.text
    assert "另有 1 个兼容别名包" in response.text
    assert "正式规则包" in response.text
    assert "政策基线包" not in response.text
    assert "近7日查询" in response.text
    assert "纯检索路由" not in response.text
    assert (
        "29 类常规项目均已形成正式阈值规则包。系统会读取企业事实字段，"
        "按稳定管理办法、年度通知、属地规则和已核验征求意见前瞻层逐项核对。"
        in response.text
    )
    assert "政策变化只重编受影响项目" in response.text
    assert "Four-city Policy Router" not in response.text
    assert "四市研发平台与企业技术中心版本" not in response.text
    assert "宁波市重点企业研究院、企业技术研发中心" not in response.text
    assert "市级研发中心（四市属地版）" in response.text
    assert "稳定管理办法" in response.text
    assert 'href="/algorithms?coverage=rules-confirmed#algorithm-catalog"' in response.text
    assert 'href="/algorithms#algorithm-catalog" data-force-navigation' in response.text
    assert confirmed_response.status_code == 200
    assert "显示 29 / 29 个主项目" in confirmed_response.text
    assert "专精特新小巨人" in confirmed_response.text
    assert "区级绿色工厂" in confirmed_response.text
    assert baseline_catalog_response.status_code == 200
    assert "显示 0 / 29 个主项目" in baseline_catalog_response.text
    assert "区级绿色工厂" not in baseline_catalog_response.text
    assert 'href="/algorithms?project=little-giant#algorithm-detail"' not in baseline_catalog_response.text
    assert detail_response.status_code == 200
    assert 'href="/algorithms#algorithm-catalog" data-force-navigation' in detail_response.text
    assert "用途说明" in detail_response.text
    assert "查看算法包源配置 JSON" in detail_response.text
    assert "little-giant-revenue" in detail_response.text
    assert "查看原文" in detail_response.text
    assert routing_response.status_code == 200
    assert "为什么尚不直接给出符合或不符合" not in routing_response.text
    assert "first-equipment-1" in routing_response.text
    assert "2025年度通知" in routing_response.text
    assert municipal_response.status_code == 200
    assert "市级企业技术中心（四市属地版）" in municipal_response.text
    assert "杭州市企业技术中心管理办法" in municipal_response.text
    assert "金华市企业技术中心管理办法（2024年版）" in municipal_response.text
    assert institute_response.status_code == 200
    assert "市级研发中心（四市属地版）" in institute_response.text
    assert "政策过渡提示" in institute_response.text
    assert "当年尚未开放申报的准备评估与下一年度预测" in institute_response.text
    assert "征求意见稿的法律状态仍为草案" in institute_response.text


def test_project_usage_metadata_covers_rest_and_mcp_searches(tmp_path):
    module = load_app(tmp_path)

    rest_rule, rest_alias = module.project_usage_metadata_from_request(
        "/v1/search",
        json.dumps({"query": "国家高企申报条件"}).encode(),
    )
    mcp_rule, mcp_alias = module.project_usage_metadata_from_request(
        "/mcp",
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "knowledge_search",
                    "arguments": {"query": "国家高企申报条件"},
                },
            }
        ).encode(),
    )

    assert rest_rule == "national-high-tech-enterprise"
    assert rest_alias == "国家高企"
    assert (mcp_rule, mcp_alias) == (rest_rule, rest_alias)


def test_mcp_usage_persists_project_without_storing_raw_query(tmp_path):
    module = load_app(tmp_path)
    module.init_database()
    now = module.isoformat(module.utc_now())
    with closing(module.database()) as connection:
        user_id = connection.execute(
            """
            INSERT INTO users(username,real_name,password_hash,created_at)
            VALUES (?,?,?,?)
            """,
            ("usage-member", "使用成员", "hash", now),
        ).lastrowid
        token_id = connection.execute(
            """
            INSERT INTO device_tokens(
                user_id,label,token_prefix,token_hash,created_at
            ) VALUES (?,?,?,?,?)
            """,
            (user_id, "成员", "jtk_test", "token-hash", now),
        ).lastrowid
        connection.commit()
        user = connection.execute(
            """
            SELECT users.id,device_tokens.id AS device_token_id
            FROM users JOIN device_tokens ON device_tokens.user_id=users.id
            WHERE users.id=?
            """,
            (user_id,),
        ).fetchone()
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "knowledge_search",
                "arguments": {"query": "国家高企申报条件"},
            },
        }
    ).encode()

    module.record_api_usage(
        user,
        "/mcp",
        "POST",
        "mcp_search",
        "实际检索",
        True,
        body=body,
    )

    with closing(module.database()) as connection:
        usage = connection.execute(
            """
            SELECT project_rule_id,project_alias
            FROM api_usage WHERE device_token_id=?
            """,
            (token_id,),
        ).fetchone()
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(api_usage)")
        }
    assert dict(usage) == {
        "project_rule_id": "national-high-tech-enterprise",
        "project_alias": "国家高企",
    }
    assert "query" not in columns
    assert "question" not in columns


def test_setup_login_and_device_token(tmp_path):
    module = load_app(tmp_path)
    with TestClient(module.app) as client:
        home = client.get("/", follow_redirects=False)
        assert home.status_code == 303
        assert home.headers["location"] == "/login"

        response = client.post(
            "/setup",
            data={"setup_key": "setup-secret", "username": "owner", "password": "correct-horse-battery"},
            follow_redirects=False,
        )
        assert response.status_code == 303

        response = client.post(
            "/login",
            data={"username": "owner", "password": "correct-horse-battery"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert module.SESSION_COOKIE in response.cookies

        client.cookies.update(response.cookies)
        portal = client.get("/portal")
        assert portal.status_code == 200
        assert "退出当前账号" in portal.text
        assert "page-overview" in portal.text
        assert re.search(r'/static/app\.css\?v=[0-9a-f]{16}', portal.text)
        assert re.search(r'/static/portal\.js\?v=[0-9a-f]{16}', portal.text)
        assert 'class="app-layout portal-page single-page' in portal.text
        assert 'id="cockpit"' in portal.text
        assert 'id="api-access"' in portal.text
        assert 'id="skills"' in portal.text
        assert 'class="page-continuation"' not in portal.text
        access_page = client.get("/access")
        assert "WorkBuddy 新安装已暂停" in access_page.text
        assert "管理员 API Key" not in access_page.text
        assert "管理员豁免" not in access_page.text
        assert "data-copy-agent-bootstrap" not in access_page.text
        assert 'data-skill-open="first-run-configuration"' in access_page.text
        cockpit_page = client.get("/cockpit")
        assert "驾驶舱智能看板" in cockpit_page.text
        assert "免费知识检索" in cockpit_page.text
        assert "管理员不限次数" in cockpit_page.text
        assert "实时推导轨迹" in cockpit_page.text
        assert ">如何使用<" in cockpit_page.text
        assert ">导入 API / MCP<" in cockpit_page.text
        assert ">导入企查查 MCP<" in cockpit_page.text
        user = module.session_user(response.cookies[module.SESSION_COOKIE])[0]

        feedback = client.post(
            "/feedback",
            data={
                "category": "bug",
                "subject": "省研究院检索未命中",
                "content": "使用简称检索时错误进入联网搜索。",
                "page_url": "/cockpit",
                "csrf_token": user["csrf_token"],
            },
            follow_redirects=False,
        )
        assert feedback.status_code == 303
        assert feedback.headers["location"] == "/feedback?submitted=1#feedback"
        feedback_page = client.get("/feedback")
        assert "省研究院检索未命中" in feedback_page.text
        assert "故障与 Bug" in feedback_page.text
        with closing(module.database()) as connection:
            feedback_id = int(
                connection.execute("SELECT id FROM feedback_messages").fetchone()["id"]
            )
        update_feedback = client.post(
            f"/admin/feedback/{feedback_id}",
            data={
                "feedback_status": "resolved",
                "admin_note": "已加入项目简称召回。",
                "csrf_token": user["csrf_token"],
            },
            follow_redirects=False,
        )
        assert update_feedback.status_code == 303
        assert "已加入项目简称召回" in client.get("/feedback").text

        assistant = client.post(
            "/assistant/answer",
            data={"question": "小巨人", "csrf_token": user["csrf_token"]},
        )
        assert assistant.status_code == 200
        assert assistant.json()["mode"] == "policy-guardrail"
        assert "2026" in assistant.json()["answer"]
        assert "小巨人" in assistant.json()["sources"][0]["title"]
        assert "project-matching" in assistant.json()["skills"]
        assert assistant.json()["quota"] == {
            "remaining": None,
            "limit": None,
            "counted": False,
            "unlimited": True,
        }

        usage_guide = client.post(
            "/assistant/answer",
            data={
                "question": "企业全生命周期助手如何导入我的Agent？",
                "csrf_token": user["csrf_token"],
            },
        )
        assert usage_guide.status_code == 200
        assert usage_guide.json()["mode"] == "usage-guide"
        assert "当前 Agent" in usage_guide.json()["answer"]
        assert usage_guide.json()["sources"] == []

        api_guide = client.post(
            "/assistant/answer",
            data={
                "question": "企业全生命周期助手自带的API和MCP如何导入Agent？",
                "csrf_token": user["csrf_token"],
            },
        )
        assert api_guide.status_code == 200
        assert "点击“一键安装”" in api_guide.json()["answer"]
        assert "不需要设备绑定" in api_guide.json()["answer"]
        assert "自动复用或生成" in api_guide.json()["answer"]
        assert "macOS 或 Windows" in api_guide.json()["answer"]

        qcc_guide = client.post(
            "/assistant/answer",
            data={
                "question": "企查查MCP如何导入Agent？",
                "csrf_token": user["csrf_token"],
            },
        )
        assert qcc_guide.status_code == 200
        assert "agent.qcc.com/invitation" in qcc_guide.json()["answer"]
        assert "QCC_API_KEY" in qcc_guide.json()["answer"]

        token_page = client.post(
            "/device-tokens",
            data={
                "real_name": "王小明",
                "company_name": "共创集团",
                "csrf_token": user["csrf_token"],
            },
        )
        assert token_page.status_code == 200
        assert "WorkBuddy 新安装已暂停" in token_page.text
        assert "管理员凭据" not in token_page.text
        assert 'data-toggle-secret="personal-access"' not in token_page.text
        with closing(module.database()) as connection:
            assert connection.execute("SELECT label FROM device_tokens").fetchone()["label"] == "王小明"
        token = active_user_token(module, int(user["id"]))

        access_page = client.get("/access")
        assert access_page.status_code == 200
        assert "page-access" in access_page.text
        assert 'class="page-continuation"' not in access_page.text
        assert 'class="page-step' not in access_page.text
        assert token not in access_page.text
        assert "REST Base URL、MCP URL 与个人访问凭据缺一不可" not in access_page.text
        assert "当前唯一访问凭据" not in access_page.text
        repeat_page = client.post(
            "/device-tokens",
            data={
                "real_name": "王小明",
                "company_name": "共创集团",
                "csrf_token": user["csrf_token"],
            },
        )
        assert repeat_page.status_code == 200
        assert token not in repeat_page.text
        with closing(module.database()) as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM device_tokens WHERE user_id=? AND revoked_at IS NULL",
                (user["id"],),
            ).fetchone()[0] == 1

        cockpit = client.get("/cockpit")
        assert cockpit.status_code == 200
        assert "page-cockpit" in cockpit.text

        missing_device = client.get(
            "/v1/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert missing_device.status_code == 200
        assert missing_device.json() == {"username": "owner", "access": "unified"}

        me = client.get("/v1/me", headers=api_headers(token))
        assert me.status_code == 200
        assert me.json() == {"username": "owner", "access": "unified"}

        search = client.post(
            "/v1/search",
            headers=api_headers(token),
            json={"query": "小巨人", "limit": 5},
        )
        assert search.status_code == 200
        assert "小巨人" in search.json()["results"][0]["title"]
        assert "source_layer" not in search.json()["results"][0]
        assert "source_labels" not in search.json()["results"][0]
        assert "verification_status" not in search.json()["results"][0]
        document_id = search.json()["results"][0]["document_id"]
        document = client.get(
            f"/v1/documents/{document_id}",
            headers=api_headers(token),
        )
        assert document.status_code == 200
        assert document.json()["content"]
        assert "小巨人" in document.json()["title"]

        list_search = client.post(
            "/v1/lists/search",
            headers=api_headers(token),
            json={"project_name": "小巨人", "year": 2025, "region": "浙江省"},
        )
        assert list_search.status_code == 200
        assert list_search.json()["results"][0]["enterprise_name"] == "杭州测试装备有限公司"

        policy_search = client.post(
            "/v1/policies/search",
            headers=api_headers(token),
            json={"project_name": "小巨人", "document_stage": "申报通知", "year": 2025},
        )
        assert policy_search.status_code == 200
        assert policy_search.json()["results"][0]["validity_status"] == "active_candidate"

        project_match = client.post(
            "/v1/projects/match",
            headers=api_headers(token),
            json={"regions": ["全国"], "keywords": ["小巨人"]},
        )
        assert project_match.status_code == 200
        assert project_match.json()["status"] == "candidate_only"

        usage = client.get("/v1/usage", headers=api_headers(token))
        assert usage.status_code == 200
        assert usage.json()["total_calls"] >= 4
        assert any(item["endpoint"] == "/v1/search" for item in usage.json()["by_endpoint"])

        latest = client.get("/v1/skills/latest", headers=api_headers(token))
        assert latest.status_code == 200
        assert latest.json() == {
            "available": False,
            "version": None,
            "file_name": None,
            "sha256": None,
            "file_size": None,
            "release_notes": None,
            "published_at": None,
            "download_url": None,
        }

        bound_page = client.get("/access")
        assert "管理员豁免" not in bound_page.text
        assert "当前尚未绑定" not in bound_page.text
        assert "DEVICE SIGNATURE" not in bound_page.text
        second_device = client.get(
            "/v1/me",
            headers=api_headers(token, "device:test-installation-0002"),
        )
        assert second_device.status_code == 200

        replaced = client.post(
            "/device-binding/replace",
            data={"csrf_token": user["csrf_token"]},
        )
        assert replaced.status_code == 410
        assert client.get("/v1/me", headers=api_headers(token)).status_code == 200
        with closing(module.database()) as connection:
            bindings = connection.execute(
                """
                SELECT device_id_prefix,revoked_at,revoked_reason
                FROM device_bindings WHERE user_id=? ORDER BY id
                """,
                (int(user["id"]),),
            ).fetchall()
        assert bindings == []

        created = client.post(
            "/users",
            data={
                "username": "member-one",
                "initial_password": "initial-password-123",
                "csrf_token": user["csrf_token"],
            },
            follow_redirects=False,
        )
        assert created.status_code == 303

        reset_page = client.get("/password/reset")
        assert reset_page.status_code == 200
        assert "自助密码重置已经停用" in reset_page.text
        assert '<form method="post" action="/password/reset"' not in reset_page.text
        failed_reset = client.post(
            "/password/reset",
            data={
                "username": "owner",
                "real_name": "王小明",
                "company_name": "错误公司",
                "password": "new-owner-password-123",
                "confirm_password": "new-owner-password-123",
            },
        )
        assert failed_reset.status_code == 410
        reset = client.post(
            "/password/reset",
            data={
                "username": "owner",
                "real_name": "王小明",
                "company_name": "共创集团",
                "password": "new-owner-password-123",
                "confirm_password": "new-owner-password-123",
            },
            follow_redirects=False,
        )
        assert reset.status_code == 410
        assert "自助找回已停用" in reset.text
        assert client.get("/portal", follow_redirects=False).status_code == 200
        assert client.post(
            "/login",
            data={"username": "owner", "password": "correct-horse-battery"},
            follow_redirects=False,
        ).status_code == 303
        assert client.post(
            "/login",
            data={"username": "owner", "password": "new-owner-password-123"},
            follow_redirects=False,
        ).status_code == 401


def test_self_service_password_reset_is_disabled(tmp_path):
    module = load_app(tmp_path)
    with closing(module.database()) as connection:
        connection.execute(
            """
            INSERT INTO users(username,real_name,company_name,password_hash,created_at)
            VALUES (?,?,?,?,?)
            """,
            (
                "member",
                "王小明",
                "共创集团",
                module.password_hasher.hash("member-password-123"),
                module.isoformat(module.utc_now()),
            ),
        )
        member_id = connection.execute(
            "SELECT id FROM users WHERE username='member'"
        ).fetchone()["id"]
        connection.execute(
            """
            INSERT INTO registration_authorizations(
                real_name,identity_code,status,user_id,created_at,registered_at
            ) VALUES (?,?,'registered',?,?,?)
            """,
            (
                "王小明",
                "0826",
                member_id,
                module.isoformat(module.utc_now()),
                module.isoformat(module.utc_now()),
            ),
        )
        connection.commit()
    payload = {
        "username": "member",
        "real_name": "王小明",
        "company_name": "错误公司",
        "password": "new-member-password-123",
        "confirm_password": "new-member-password-123",
    }
    with TestClient(module.app) as client:
        for _ in range(6):
            response = client.post("/password/reset", data=payload)
            assert response.status_code == 410
            assert "自助找回已停用" in response.text
        assert client.post(
            "/login",
            data={"username": "member", "password": "member-password-123"},
            follow_redirects=False,
        ).status_code == 303
        assert client.post(
            "/login",
            data={"username": "member", "password": "new-member-password-123"},
            follow_redirects=False,
        ).status_code == 401


def test_admin_can_reset_member_password_and_revoke_sessions(tmp_path):
    module = load_app(tmp_path)
    now = module.isoformat(module.utc_now())
    with closing(module.database()) as connection:
        connection.execute(
            "INSERT INTO users(username,password_hash,is_admin,created_at) VALUES (?,?,1,?)",
            ("owner", module.password_hasher.hash("owner-password-123"), now),
        )
        connection.execute(
            "INSERT INTO users(username,password_hash,created_at) VALUES (?,?,?)",
            ("member", module.password_hasher.hash("member-password-123"), now),
        )
        member_id = connection.execute(
            "SELECT id FROM users WHERE username='member'"
        ).fetchone()["id"]
        connection.execute(
            """
            INSERT INTO registration_authorizations(
                real_name,identity_code,status,user_id,created_at,registered_at
            ) VALUES (?,?,'registered',?,?,?)
            """,
            ("成员", "0826", member_id, now, now),
        )
        connection.commit()

    with TestClient(module.app) as client:
        member_login = client.post(
            "/login",
            data={"username": "member", "password": "member-password-123"},
            follow_redirects=False,
        )
        member_session_token = member_login.cookies[module.SESSION_COOKIE]
        client.cookies.update(member_login.cookies)
        assert client.get("/portal").status_code == 200
        client.cookies.clear()

        admin_login = client.post(
            "/login",
            data={"username": "owner", "password": "owner-password-123"},
            follow_redirects=False,
        )
        client.cookies.update(admin_login.cookies)
        admin = module.session_user(admin_login.cookies[module.SESSION_COOKIE])[0]
        detail = client.get(f"/admin/users/{member_id}")
        assert f'action="/admin/users/{member_id}/password-reset"' in detail.text

        mismatch = client.post(
            f"/admin/users/{member_id}/password-reset",
            data={
                "new_password": "new-member-password-456",
                "confirm_password": "different-password-456",
                "csrf_token": admin["csrf_token"],
            },
        )
        assert mismatch.status_code == 400

        reset = client.post(
            f"/admin/users/{member_id}/password-reset",
            data={
                "new_password": "new-member-password-456",
                "confirm_password": "new-member-password-456",
                "csrf_token": admin["csrf_token"],
            },
            follow_redirects=False,
        )
        assert reset.status_code == 303
        assert reset.headers["location"] == f"/admin/users/{member_id}?password_reset=1"
        assert module.session_user(member_session_token) is None

        self_reset = client.post(
            f"/admin/users/{admin['id']}/password-reset",
            data={
                "new_password": "new-owner-password-456",
                "confirm_password": "new-owner-password-456",
                "csrf_token": admin["csrf_token"],
            },
        )
        assert self_reset.status_code == 400

        assert client.post(
            "/login",
            data={"username": "member", "password": "member-password-123"},
            follow_redirects=False,
        ).status_code == 401
        assert client.post(
            "/login",
            data={"username": "member", "password": "new-member-password-456"},
            follow_redirects=False,
        ).status_code == 303


def test_assistant_skill_router_and_read_only_tool_loop(tmp_path, monkeypatch):
    module = load_app(tmp_path)
    monkeypatch.setattr(module, "AI_API_BASE", "https://model.example.com")
    monkeypatch.setattr(module, "AI_API_KEY", "test-key")
    monkeypatch.setattr(module, "AI_MODEL", "test-model")
    replies = iter(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-search",
                        "type": "function",
                        "function": {"name": "knowledge_search", "arguments": '{"query":"小巨人","limit":3}'},
                    }
                ],
            },
            {"role": "assistant", "content": "已依据项目匹配Skill和知识库资料形成答复。"},
        ]
    )
    monkeypatch.setattr(
        module, "request_assistant_model", lambda messages, model_config=None: next(replies)
    )

    answer, mode, sources, skills = module.answer_with_knowledge("这家企业能报什么小巨人项目？", [])

    assert mode == "language-model"
    assert "知识库资料" in answer
    assert "小巨人" in sources[0]["title"]
    assert "project-matching" in skills
    assert set(module.route_assistant_skills("分析专利侵权和法律状态")) >= {"patent-router"}

    repeated_calls = 0

    def repeat_search(messages, model_config=None):
        nonlocal repeated_calls
        repeated_calls += 1
        return {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call-repeat-search",
                    "type": "function",
                    "function": {"name": "knowledge_search", "arguments": '{"query":"小巨人","limit":3}'},
                }
            ],
        }

    monkeypatch.setattr(module, "request_assistant_model", repeat_search)
    fallback_answer, fallback_mode, fallback_sources, _ = module.answer_with_knowledge("继续检索小巨人", [])
    assert fallback_mode == "policy-guardrail"
    assert "现行版本" in fallback_answer
    assert "小巨人" in fallback_sources[0]["title"]
    assert repeated_calls == 4


def test_assistant_execution_policy_uses_dynamic_12_or_16_rounds(tmp_path):
    module = load_app(tmp_path)

    default_policy = module.assistant_execution_policy("查询一条政策", ["policy-retrieval"])
    complex_policy = module.assistant_execution_policy(
        "请撰写完整的金税四期分析报告",
        ["manufacturing-tax-risk-analysis"],
    )

    assert default_policy == {
        "tier": "default",
        "complex": False,
        "max_rounds": 12,
        "max_seconds": 180,
        "max_tool_calls": 24,
        "max_no_progress_rounds": 3,
    }
    assert complex_policy == {
        "tier": "complex",
        "complex": True,
        "max_rounds": 16,
        "max_seconds": 300,
        "max_tool_calls": 40,
        "max_no_progress_rounds": 3,
    }


def test_assistant_stops_at_round_and_tool_call_budgets(tmp_path, monkeypatch):
    module = load_app(tmp_path)
    monkeypatch.setattr(module, "AI_API_BASE", "https://model.example.com")
    monkeypatch.setattr(module, "AI_API_KEY", "test-key")
    monkeypatch.setattr(module, "AI_MODEL", "test-model")
    monkeypatch.setattr(module, "ASSISTANT_MAX_NO_PROGRESS_ROUNDS", 100)
    source = {
        "document_id": 901,
        "title": "测试知识资料",
        "excerpt": "用于验证动态执行门禁。",
        "source": "test",
    }
    model_calls = 0
    tool_results = 0

    def endless_model(messages, model_config=None):
        nonlocal model_calls
        model_calls += 1
        return {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": f"call-{model_calls}",
                    "type": "function",
                    "function": {
                        "name": "knowledge_search",
                        "arguments": json.dumps({"query": f"轮次{model_calls}"}),
                    },
                }
            ],
        }

    def unique_tool_result(name, arguments):
        nonlocal tool_results
        tool_results += 1
        return {"sequence": tool_results}, []

    monkeypatch.setattr(module, "request_assistant_model", endless_model)
    monkeypatch.setattr(module, "execute_assistant_tool", unique_tool_result)
    answer, mode, _, _ = module.answer_with_knowledge("普通资料整理", [source])
    assert mode == "knowledge-search"
    assert "达到12轮安全上限" in answer
    assert model_calls == 12
    assert tool_results == 12

    monkeypatch.setattr(module, "ASSISTANT_DEFAULT_MAX_TOOL_CALLS", 2)
    monkeypatch.setattr(
        module,
        "request_assistant_model",
        lambda messages, model_config=None: {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": f"batch-{index}",
                    "type": "function",
                    "function": {
                        "name": "knowledge_search",
                        "arguments": json.dumps({"query": f"批次{index}"}),
                    },
                }
                for index in range(3)
            ],
        },
    )
    tool_results = 0
    answer, mode, _, _ = module.answer_with_knowledge("普通资料整理", [source])
    assert mode == "knowledge-search"
    assert "达到2次上限" in answer
    assert tool_results == 2

    clock = iter((0.0, 0.0, 181.0))
    monkeypatch.setattr(module, "ASSISTANT_DEFAULT_MAX_TOOL_CALLS", 24)
    monkeypatch.setattr(module, "assistant_monotonic", lambda: next(clock))
    monkeypatch.setattr(
        module,
        "request_assistant_model",
        lambda messages, model_config=None: {
            "role": "assistant",
            "content": "本应被总时限门禁拦截",
            "tool_calls": [],
        },
    )
    answer, mode, _, _ = module.answer_with_knowledge("普通资料整理", [source])
    assert mode == "knowledge-search"
    assert "达到180秒总时限" in answer


def test_assistant_searches_web_only_after_knowledge_miss(tmp_path, monkeypatch):
    module = load_app(tmp_path)
    calls = []

    def fake_web_search(query, limit=5):
        calls.append((query, limit))
        return [
            {
                "title": "官方公开结果",
                "excerpt": "公开网页摘要",
                "source": "https://www.gov.cn/example",
                "url": "https://www.gov.cn/example",
            }
        ]

    monkeypatch.setattr(module, "search_public_web", fake_web_search)
    answer, mode, sources, _ = module.answer_with_knowledge_then_web("未收录的新政策", [])
    assert mode == "web-search"
    assert "团队知识库未命中" in answer
    assert sources[0]["url"] == "https://www.gov.cn/example"
    assert calls == [("未收录的新政策", 5)]

    calls.clear()
    knowledge_result = {
        "document_id": 1,
        "title": "知识库文件",
        "excerpt": "知识库正文",
        "source": "内部索引",
    }
    _, mode, sources, _ = module.answer_with_knowledge_then_web(
        "已有知识", [knowledge_result]
    )
    assert mode == "knowledge-search"
    assert sources[0]["document_id"] == 1
    assert calls == []


def test_structured_list_policy_and_project_tools(tmp_path):
    module = load_app(tmp_path)
    with closing(sqlite3.connect(module.CONTENT_DATABASE_PATH)) as connection:
        document_id = connection.execute(
            "SELECT id FROM documents WHERE source_key = 'doc-list'"
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO public_list_entities(
                document_id,enterprise_name,sequence_no,canonical_project_name,
                policy_year,batch,region,list_status,context,confidence
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                document_id,
                "杭州分页验证有限公司",
                "2",
                "国家专精特新“小巨人”企业",
                2025,
                "第六批",
                "浙江省",
                "认定名单",
                "2 | 杭州分页验证有限公司",
                "high",
            ),
        )
        connection.commit()

    list_result = module.search_public_list_entities(
        project_name="小巨人",
        year=2025,
        batch="第六批",
        region="浙江省",
        offset=0,
        limit=1,
    )
    assert list_result["results"][0]["list_status"] == "认定名单"
    assert list_result["total"] == 2
    assert list_result["pagination"]["is_truncated"] is True
    assert list_result["pagination"]["next_offset"] == 1

    second_page = module.search_public_list_entities(
        project_name="小巨人",
        year=2025,
        batch="第六批",
        region="浙江省",
        offset=1,
        limit=1,
    )
    assert second_page["total"] == 2
    assert {
        list_result["results"][0]["enterprise_name"],
        second_page["results"][0]["enterprise_name"],
    } == {"杭州测试装备有限公司", "杭州分页验证有限公司"}
    assert second_page["pagination"]["has_more"] is False
    assert second_page["pagination"]["next_offset"] is None

    policy_result = module.search_policy_documents(
        project_name="小巨人",
        region="浙江省",
        document_stage="申报通知",
        validity_status="active_candidate",
        year=2025,
    )
    assert policy_result["results"][0]["title"] == "2025年浙江省专精特新小巨人申报通知"

    project_result = module.match_project_catalog(
        regions=["全国"], keywords=["小巨人"], limit=10
    )
    assert project_result["status"] == "candidate_only"
    assert any("小巨人" in item["canonical_project_name"] for item in project_result["results"])

    ranked_result = module.match_project_catalog(
        regions=["浙江省"], keywords=["专精特新", "研发"], limit=5
    )
    assert any(
        item["canonical_project_name"] == "国家专精特新“小巨人”企业"
        for item in ranked_result["results"][:3]
    )

    tool_names = {
        item["function"]["name"] for item in module.assistant_tool_schemas()
    }
    assert {
        "authoritative_list_search",
        "public_list_search",
        "policy_search",
        "project_catalog_match",
        "policy_evidence_select",
        "delivery_contract_audit",
    }.issubset(tool_names)


def test_legacy_public_list_search_routes_authoritative_projects_to_master(tmp_path):
    module = load_app(tmp_path)
    with closing(sqlite3.connect(module.CONTENT_DATABASE_PATH)) as connection:
        connection.executescript(
            """
            CREATE TABLE national_small_giant_master(
                id INTEGER PRIMARY KEY,
                enterprise_name TEXT,normalized_name TEXT,unified_social_credit_code TEXT,qice_eid TEXT,
                region TEXT,city TEXT,county TEXT,recognition_year INTEGER,batch TEXT,status TEXT,
                official_url TEXT,official_url_role TEXT,official_fragment_key TEXT,verification_status TEXT,
                sequence_no TEXT,platform_year_raw TEXT,former_names_json TEXT,
                source_documents_json TEXT,source_paths_json TEXT
            );
            INSERT INTO national_small_giant_master VALUES
                (1,'杭州权威甲公司','','','','浙江省','杭州市','余杭区',2024,'第六批','认定',
                 'https://example.gov.cn/list','official_batch_notice','',
                 'official_local_fragment_match','','','[]','[1]','["官方名单.pdf"]'),
                (2,'杭州权威乙公司','','','','浙江省','杭州市','滨江区',2024,'第六批','认定',
                 'https://example.gov.cn/list','official_batch_notice','',
                 'dynamic_candidate_pending_official_fragment','','','[]','[]','[]');
            """
        )
        connection.commit()

    result = module.search_public_list_entities(
        project_name="国家专精特新小巨人",
        year=2024,
        batch="第六批",
        region="杭州市",
        limit=1,
    )
    assert result["legacy_route"]["effective_tool"] == "authoritative_list_search"
    assert result["authority"]["table"] == "national_small_giant_master"
    assert result["total"] == 2
    assert result["summary"]["official_match_count"] == 1
    assert result["pagination"]["is_truncated"] is True


def test_legacy_public_list_search_never_falls_back_when_authority_table_is_missing(tmp_path):
    module = load_app(tmp_path)
    with pytest.raises(module.HTTPException) as error:
        module.search_public_list_entities(
            project_name="国家专精特新小巨人",
            year=2025,
            batch="第六批",
            region="浙江省",
        )
    assert error.value.status_code == 503
    assert "national_small_giant_master" in str(error.value.detail)


def test_three_first_directory_diff_and_product_match_tools(tmp_path):
    module = load_app(tmp_path)
    with closing(sqlite3.connect(module.CONTENT_DATABASE_PATH)) as connection:
        connection.executescript(
            """
            CREATE TABLE three_first_project_awards(
                id INTEGER PRIMARY KEY,
                enterprise_name TEXT,product_name TEXT,project_name TEXT,list_status TEXT,
                year INTEGER,province TEXT,city TEXT,county TEXT,source_tier TEXT,confidence TEXT
            );
            CREATE TABLE three_first_guidance_directory_diffs(
                id INTEGER PRIMARY KEY,
                from_year INTEGER NOT NULL,
                to_year INTEGER NOT NULL,
                change_type TEXT NOT NULL,
                from_sequence_no INTEGER,
                to_sequence_no INTEGER,
                from_material_name TEXT NOT NULL,
                to_material_name TEXT NOT NULL,
                match_type TEXT NOT NULL,
                match_score REAL NOT NULL,
                changed_fields TEXT NOT NULL,
                before_values TEXT NOT NULL,
                after_values TEXT NOT NULL
            );
            CREATE TABLE three_first_award_directory_links(
                id INTEGER PRIMARY KEY,
                enterprise_name TEXT NOT NULL,
                award_year INTEGER,
                product_name TEXT NOT NULL,
                directory_year INTEGER NOT NULL,
                directory_sequence_no INTEGER NOT NULL,
                directory_material_name TEXT NOT NULL,
                match_type TEXT NOT NULL,
                match_score REAL NOT NULL,
                match_confidence TEXT NOT NULL,
                review_status TEXT NOT NULL
            );
            """
        )
        connection.execute(
            """
            INSERT INTO three_first_guidance_directory_diffs VALUES
            (1,2023,2025,'modified',8,9,'高性能复合材料','高性能复合材料',
             'exact',1.0,'["performance_requirement"]',
             '{"performance_requirement":"旧指标"}',
             '{"performance_requirement":"新指标"}')
            """
        )
        connection.executemany(
            """
            INSERT INTO three_first_award_directory_links VALUES
            (?,?,?,?,?,?,?,?,?,?,?)
            """,
            [
                (
                    1,
                    "浙江测试材料有限公司",
                    2024,
                    "高性能复合材料",
                    2025,
                    9,
                    "高性能复合材料",
                    "exact",
                    1.0,
                    "high",
                    "auto_confirmed",
                ),
                (
                    2,
                    "浙江测试材料有限公司",
                    2024,
                    "高性能复合材",
                    2025,
                    9,
                    "高性能复合材料",
                    "fuzzy",
                    0.91,
                    "medium",
                    "candidate_requires_review",
                ),
            ],
        )
        connection.commit()

    diff_result = module.search_three_first_directory_diffs(
        from_year=2023,
        to_year=2025,
        material_name="复合材料",
    )
    assert diff_result["results"][0]["changed_fields"] == ["performance_requirement"]
    assert diff_result["results"][0]["before_values"]["performance_requirement"] == "旧指标"

    confirmed = module.search_three_first_product_matches(
        enterprise_name="浙江测试材料有限公司"
    )
    assert len(confirmed["results"]) == 1
    assert confirmed["results"][0]["review_status"] == "auto_confirmed"

    with_candidates = module.search_three_first_product_matches(
        enterprise_name="浙江测试材料有限公司",
        include_review_candidates=True,
    )
    assert len(with_candidates["results"]) == 2
    assert with_candidates["candidate_notice"]

    analysis = module.analyze_three_first(
        query="对比2023年和2025年首批次目录条款差异",
        enterprise_name="浙江测试材料有限公司",
        product_name="高性能复合材料",
        from_year=2023,
        to_year=2025,
    )
    assert analysis["project_type"] == "首批次"
    assert analysis["directory_diffs"][0]["change_type"] == "modified"
    assert analysis["product_matches"][0]["review_status"] == "auto_confirmed"
    assert analysis["internal_routing"]["knowledge_search"]


def test_three_first_topic_only_query_returns_official_recognition_facts(tmp_path):
    module = load_app(tmp_path)
    with closing(sqlite3.connect(module.CONTENT_DATABASE_PATH)) as connection:
        connection.executescript(
            """
            CREATE TABLE three_first_project_awards(
                id INTEGER PRIMARY KEY,
                enterprise_key TEXT NOT NULL,
                eid TEXT NOT NULL,
                enterprise_name TEXT NOT NULL,
                enterprise_aliases TEXT NOT NULL,
                province TEXT NOT NULL,
                city TEXT NOT NULL,
                county TEXT NOT NULL,
                industry TEXT NOT NULL,
                project_id TEXT NOT NULL,
                project_name TEXT NOT NULL,
                year INTEGER,
                product_name TEXT NOT NULL,
                recognition_tier TEXT NOT NULL,
                product_category TEXT NOT NULL,
                list_status TEXT NOT NULL,
                source_policy_id TEXT NOT NULL,
                source_index_id TEXT NOT NULL,
                source_title TEXT NOT NULL,
                source_url TEXT NOT NULL,
                source_tier TEXT NOT NULL,
                evidence_semantics TEXT NOT NULL,
                confidence TEXT NOT NULL,
                product_name_status TEXT NOT NULL,
                user_action TEXT NOT NULL
            );
            INSERT INTO three_first_project_awards VALUES
                (1,'ningbo-water','','宁波水表（集团）股份有限公司','[]',
                 '浙江省','宁波市','江北区','仪器仪表','first-equipment',
                 '浙江省制造业首台（套）装备',2023,'NWM-MW100多参数智能水表',
                 '国内首台（套）','整机装备','正式认定','policy-2023','row-42',
                 '2023年度浙江省首台（套）装备名单','https://example.gov.cn/2023',
                 'official','final_recognition','verified','structured_product_name','none'),
                (2,'ningbo-donghai','','宁波东海集团有限公司','[]',
                 '浙江省','宁波市','海曙区','仪器仪表','first-equipment',
                 '浙江省制造业首台（套）装备',2021,'LXE智能电磁水表',
                 '省内首台（套）','整机装备','正式认定','policy-2021','row-224',
                 '2021年度浙江省首台（套）装备名单','https://example.gov.cn/2021',
                 'official','final_recognition','verified','structured_product_name','none');
            """
        )
        connection.execute(
            """
            INSERT INTO documents(
                source_key,title,content,source,cloud_path,document_role,
                sensitivity,sha256,updated_at,canonical_project_name,region,
                document_stage,validity_status,policy_year,batch
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "smart-meter-guidance",
                "浙江省首台套产品推广应用指导目录2025年版",
                "NWM-MW100多参数智能水表退出目录时间为2026年底",
                "10_政策与目录/推广目录.wps",
                "10_政策与目录/推广目录.wps",
                "10_政策与目录",
                "public",
                "smart-meter-guidance-sha",
                "2025-03-21T00:00:00+00:00",
                "浙江省制造业首台（套）装备",
                "浙江省",
                "推广目录",
                "active_candidate",
                2025,
                "",
            ),
        )
        connection.execute("INSERT INTO documents_fts(documents_fts) VALUES ('rebuild')")
        connection.execute(
            "INSERT INTO documents_fts_trigram(documents_fts_trigram) VALUES ('rebuild')"
        )
        connection.commit()

    result = module.analyze_three_first(
        query="智能水表",
        regions=["浙江省"],
        limit=50,
    )

    assert result["project_types"] == ["首台套", "首版次", "首批次"]
    assert result["internal_routing"]["public_list_search"] is True
    assert result["internal_routing"]["recognition_search"] is True
    assert result["recognition_results"]["route_to"] == "recognition_reverse_lookup"
    exact = result["recognition_results"]["exact_results"]
    assert {
        (
            item["recognition_fact"]["enterprise_name"],
            item["recognition_fact"]["recognition_year"],
            item["recognition_fact"]["product_name"],
        )
        for item in exact
    } == {
        ("宁波水表（集团）股份有限公司", 2023, "NWM-MW100多参数智能水表"),
        ("宁波东海集团有限公司", 2021, "LXE智能电磁水表"),
    }
    assert all("推广" not in item["recognition_fact"]["source_title"] for item in exact)
    assert result["coverage_complete"] is False
    assert result["truncated"] is False
    assert any("推广" in item["title"] for item in result["knowledge_results"])

    grouped = module.analyze_three_first(
        query="智能水表 × 首台套/首版次",
        regions=["浙江省"],
        limit=50,
    )
    assert grouped["project_types"] == ["首台套", "首版次"]
    assert grouped["list_groups"][0]["project_name"] == "浙江省制造业首台（套）装备"
    assert len(grouped["recognition_results"]["exact_results"]) == 2


def test_three_first_directory_diff_falls_back_to_transition_chain(tmp_path):
    module = load_app(tmp_path)
    with closing(sqlite3.connect(module.CONTENT_DATABASE_PATH)) as connection:
        connection.executescript(
            """
            CREATE TABLE three_first_guidance_directory_diffs(
                id INTEGER PRIMARY KEY,
                from_year INTEGER NOT NULL,
                to_year INTEGER NOT NULL,
                change_type TEXT NOT NULL,
                from_sequence_no INTEGER,
                to_sequence_no INTEGER,
                from_material_name TEXT NOT NULL,
                to_material_name TEXT NOT NULL,
                match_type TEXT NOT NULL,
                match_score REAL NOT NULL,
                changed_fields TEXT NOT NULL,
                before_values TEXT NOT NULL,
                after_values TEXT NOT NULL
            );
            """
        )
        connection.executemany(
            """
            INSERT INTO three_first_guidance_directory_diffs VALUES
            (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            [
                (
                    1, 2023, 2024, "modified", 1, 1, "测试材料", "测试材料",
                    "exact", 1.0, '["performance_requirements"]',
                    '{"performance_requirements":"A"}',
                    '{"performance_requirements":"B"}',
                ),
                (
                    2, 2024, 2025, "modified", 1, 1, "测试材料", "测试材料",
                    "exact", 1.0, '["performance_requirements"]',
                    '{"performance_requirements":"B"}',
                    '{"performance_requirements":"C"}',
                ),
            ],
        )
        connection.commit()

    result = module.search_three_first_directory_diffs(
        from_year=2023,
        to_year=2025,
        material_name="测试材料",
    )
    assert result["filters"]["comparison_mode"] == "transition_chain"
    assert [(item["from_year"], item["to_year"]) for item in result["results"]] == [
        (2023, 2024),
        (2024, 2025),
    ]


def test_alias_correction_evidence_and_policy_verification_workflow(tmp_path):
    module = load_app(tmp_path)
    assert module._active_learning_project_phrase("2026年度未来工厂申报通知") == "未来工厂"
    assert (
        module._active_learning_project_phrase("某协会关于开展2026年度职称评审工作的")
        == "职称评审"
    )

    correction = module.create_project_alias_correction(
        module.ProjectAliasCorrectionRequest(
            raw_project_name="小巨人测试资料",
            canonical_project_name="人工确认测试项目",
            note="金标准人工确认",
        ),
        "admin",
    )
    assert correction["matched_documents"] == 1
    assert correction["correction"]["status"] == "confirmed"
    evidence = module.list_metadata_evidence(review_status="confirmed")
    assert any(
        item["inferred_value"] == "人工确认测试项目"
        and item["match_method"] == "manual_alias"
        for item in evidence["results"]
    )

    with closing(sqlite3.connect(module.CONTENT_DATABASE_PATH)) as connection:
        document_id = connection.execute(
            "SELECT id FROM documents WHERE source_key='doc-policy'"
        ).fetchone()[0]
        now = "2026-07-19T00:00:00+00:00"
        cursor = connection.execute(
            """
            INSERT INTO policy_verification_queue(
                document_id,reason,priority,status,created_at,updated_at
            ) VALUES (?,'有效性需要官方网站复核','high','pending',?,?)
            """,
            (document_id, now, now),
        )
        queue_id = int(cursor.lastrowid)
        duplicate_document_id = int(
            connection.execute(
                """
                INSERT INTO documents(
                    source_key,title,content,source,cloud_path,document_role,
                    sensitivity,sha256,updated_at,canonical_project_name,region,
                    document_stage,validity_status,policy_year,batch
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    "doc-policy-pdf", "2025年浙江省专精特新小巨人申报通知",
                    "申报企业应当符合专精特新发展方向。",
                    "10_政策与通知/2025年浙江省小巨人申报通知.pdf",
                    "10_政策与通知/2025年浙江省小巨人申报通知.pdf",
                    "10_政策与通知", "public", "test-policy-pdf-sha", now,
                    "国家专精特新“小巨人”企业", "浙江省", "申报通知",
                    "active_candidate", 2025, "",
                ),
            ).lastrowid
        )
        connection.execute(
            """
            INSERT INTO policy_verification_queue(
                document_id,reason,priority,status,created_at,updated_at
            ) VALUES (?,'有效性需要官方网站复核','high','pending',?,?)
            """,
            (duplicate_document_id, now, now),
        )
        connection.executemany(
            """
            INSERT INTO documents(
                source_key,title,content,source,cloud_path,document_role,
                sensitivity,sha256,updated_at,document_stage,validity_status,policy_year
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            [
                (
                    "alias-risk-one", "2026年未来工厂申报通知", "申报条件", "10_政策与通知/未来工厂.md",
                    "10_政策与通知/未来工厂.md", "10_政策与通知", "public", "alias-risk-1", now,
                    "申报通知", "active_candidate", 2026,
                ),
                (
                    "alias-risk-two", "2025年未来工厂管理办法", "认定规则", "20_项目规则与指南/未来工厂.md",
                    "20_项目规则与指南/未来工厂.md", "20_项目规则与指南", "public", "alias-risk-2", now,
                    "管理办法", "active_candidate", 2025,
                ),
                (
                    "alias-low", "2020年冷门项目名单", "公示内容", "50_名单与对标/冷门项目.md",
                    "50_名单与对标/冷门项目.md", "50_名单与对标", "public", "alias-low", now,
                    "认定名单", "historical_reference", 2020,
                ),
            ],
        )
        connection.commit()
    from scripts.build_knowledge_content_index import rebuild_policy_document_clusters

    with closing(sqlite3.connect(module.CONTENT_DATABASE_PATH)) as connection:
        rebuild_policy_document_clusters(connection)
        connection.commit()

    candidates = module.list_active_learning_alias_candidates()
    assert candidates["results"][0]["raw_project_name"] == "未来工厂"
    assert candidates["results"][0]["impacted_documents"] == 2
    assert candidates["results"][0]["learning_score"] > candidates["results"][-1]["learning_score"]
    assert "score_breakdown" in candidates["results"][0]

    queue = module.list_policy_verification_queue()
    assert queue["results"][0]["id"] == queue_id
    assert queue["results"][0]["learning_score"] > 0
    assert queue["results"][0]["learning_reasons"]
    assert queue["results"][0]["cluster_document_count"] == 2
    assert queue["results"][0]["cluster_pending_tasks"] == 2

    reviewed = module.review_policy_verification(
        module.PolicyVerificationReviewRequest(
            queue_id=queue_id,
            status="verified",
            official_source_url="https://example.gov.cn/policy/1",
            official_document_title="官方网站现行政策",
            validity_status="active_candidate",
        ),
        "admin",
    )
    assert reviewed["review"]["status"] == "verified"
    assert reviewed["review"]["official_source_url"].startswith("https://")
    assert reviewed["propagated_documents"] == 1
    with closing(sqlite3.connect(module.CONTENT_DATABASE_PATH)) as connection:
        assert connection.execute(
            "SELECT validity_status FROM documents WHERE id=?", (duplicate_document_id,)
        ).fetchone()[0] == "active_candidate"
        assert connection.execute(
            "SELECT status FROM policy_verification_queue WHERE document_id=?",
            (duplicate_document_id,),
        ).fetchone()[0] == "verified"
        propagation = connection.execute(
            """
            SELECT source_document_id,target_document_id,field_name,rule_version
            FROM policy_verification_propagations WHERE target_document_id=?
            """,
            (duplicate_document_id,),
        ).fetchone()
        assert propagation == (
            document_id, duplicate_document_id, "validity_status", "policy-cluster-v1.0.0"
        )
        evidence = connection.execute(
            """
            SELECT match_method,review_status FROM metadata_match_evidence
            WHERE document_id=? AND field_name='validity_status'
              AND match_method='official_cluster_propagation'
            """,
            (duplicate_document_id,),
        ).fetchone()
        assert evidence == ("official_cluster_propagation", "confirmed")
    propagation_history = module.list_policy_verification_propagations()
    assert propagation_history["total"] == 1
    assert propagation_history["results"][0]["target_document_id"] == duplicate_document_id


def test_admin_metadata_review_page_is_visual_and_admin_only(tmp_path):
    module = load_app(tmp_path)
    with TestClient(module.app) as client:
        setup = client.post(
            "/setup",
            data={"setup_key": "setup-secret", "username": "owner", "password": "correct-horse-battery"},
            follow_redirects=False,
        )
        assert setup.status_code == 303
        login = client.post(
            "/login",
            data={"username": "owner", "password": "correct-horse-battery"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)
        user = module.session_user(login.cookies[module.SESSION_COOKIE])[0]
        page = client.get("/admin/metadata-review")
        assert page.status_code == 200
        assert "知识校准台" in page.text
        assert "别名确认" in page.text
        assert "排序依据" in page.text
        policy_page = client.get("/admin/metadata-review?view=policies")
        assert policy_page.status_code == 200
        assert "政策核验队列" in policy_page.text
        assert "人工拆分与合并记录" in policy_page.text
        assert "别名候选队列" in page.text
        alias_payload = {
                "raw_project_name": "小巨人测试资料",
                "canonical_project_name": "管理页面确认项目",
                "region": "",
                "start_year": "",
                "end_year": "",
                "note": "表单链路测试",
                "csrf_token": user["csrf_token"],
            }
        alias_preview = client.post("/admin/metadata-review/aliases/preview", data=alias_payload)
        assert alias_preview.status_code == 200
        assert "别名确认预览" in alias_preview.text
        alias_submit = client.post(
            "/admin/metadata-review/aliases",
            data=alias_payload,
            follow_redirects=False,
        )
        assert alias_submit.status_code == 303
        assert "view=aliases" in alias_submit.headers["location"]

        with closing(sqlite3.connect(module.CONTENT_DATABASE_PATH)) as connection:
            document_id = connection.execute(
                "SELECT id FROM documents WHERE source_key='doc-policy'"
            ).fetchone()[0]
            now = "2026-07-19T00:00:00+00:00"
            queue_id = connection.execute(
                """
                INSERT INTO policy_verification_queue(
                    document_id,reason,priority,status,created_at,updated_at
                ) VALUES (?,'表单核验测试','high','pending',?,?)
                """,
                (document_id, now, now),
            ).lastrowid
            connection.commit()
        policy_payload = {
                "queue_id": queue_id,
                "review_status": "verified",
                "official_source_url": "https://example.gov.cn/policy/form-test",
                "official_document_title": "官方政策原文",
                "official_published_at": "2026-07-19",
                "validity_status": "active_candidate",
                "verification_note": "已核对官方页面",
                "csrf_token": user["csrf_token"],
            }
        policy_preview = client.post("/admin/metadata-review/policies/preview", data=policy_payload)
        assert policy_preview.status_code == 200
        assert "政策核验预览" in policy_preview.text
        policy_submit = client.post(
            "/admin/metadata-review/policies",
            data=policy_payload,
            follow_redirects=False,
        )
        assert policy_submit.status_code == 303
        assert "view=policies" in policy_submit.headers["location"]
        client.cookies.clear()
        response = client.get("/admin/metadata-review", follow_redirects=False)
        assert response.status_code == 303


def test_manual_policy_cluster_split_merge_survives_rebuild(tmp_path):
    module = load_app(tmp_path)
    from scripts.build_knowledge_content_index import rebuild_policy_document_clusters

    with closing(sqlite3.connect(module.CONTENT_DATABASE_PATH)) as connection:
        now = "2026-07-19T00:00:00+00:00"
        connection.executemany(
            """
            INSERT INTO documents(
                source_key,title,content,source,cloud_path,document_role,
                sensitivity,sha256,updated_at,canonical_project_name,region,
                document_stage,validity_status,policy_year
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            [
                (
                    "cluster-a-2", "2025年浙江省专精特新小巨人申报通知", "第二份",
                    "10_政策与通知/副本通知.md", "10_政策与通知/副本通知.md",
                    "10_政策与通知", "public", "cluster-a-2", now,
                    "国家专精特新“小巨人”企业", "浙江省", "申报通知",
                    "active_candidate", 2025,
                ),
                (
                    "cluster-b-1", "2026年浙江省制造精品申报通知", "另一政策",
                    "10_政策与通知/制造精品.md", "10_政策与通知/制造精品.md",
                    "10_政策与通知", "public", "cluster-b-1", now,
                    "浙江制造精品", "浙江省", "申报通知", "active_candidate", 2026,
                ),
            ],
        )
        rebuild_policy_document_clusters(connection)
        source_cluster_id = connection.execute(
            """
            SELECT m.cluster_id FROM policy_document_cluster_members m
            JOIN documents d ON d.id=m.document_id WHERE d.source_key='doc-policy'
            """
        ).fetchone()[0]
        split_document_id = connection.execute(
            "SELECT id FROM documents WHERE source_key='cluster-a-2'"
        ).fetchone()[0]
        target_cluster_id = connection.execute(
            """
            SELECT m.cluster_id FROM policy_document_cluster_members m
            JOIN documents d ON d.id=m.document_id WHERE d.source_key='cluster-b-1'
            """
        ).fetchone()[0]
        connection.commit()

    split_result = module.split_policy_document_cluster(
        source_cluster_id, [split_document_id], "标题相同但官方文号不同", "owner"
    )
    assert split_result["moved_documents"] == 1
    split_cluster_id = split_result["target_cluster_id"]

    with closing(sqlite3.connect(module.CONTENT_DATABASE_PATH)) as connection:
        rebuild_policy_document_clusters(connection)
        persisted_cluster_id = connection.execute(
            "SELECT cluster_id FROM policy_document_cluster_members WHERE document_id=?",
            (split_document_id,),
        ).fetchone()[0]
        assignment = connection.execute(
            "SELECT operation_type FROM policy_cluster_manual_assignments WHERE document_id=?",
            (split_document_id,),
        ).fetchone()[0]
        connection.commit()
    assert persisted_cluster_id == split_cluster_id
    assert assignment == "split"

    merge_result = module.merge_policy_document_clusters(
        split_cluster_id, target_cluster_id, "经官方来源确认属于同一政策", "owner"
    )
    assert merge_result["merged_documents"] == 2
    with closing(sqlite3.connect(module.CONTENT_DATABASE_PATH)) as connection:
        merged_cluster_ids = {
            row[0]
            for row in connection.execute(
                """
                SELECT cluster_id FROM policy_document_cluster_members
                WHERE document_id IN (?,?)
                """,
                (
                    split_document_id,
                    connection.execute(
                        "SELECT id FROM documents WHERE source_key='cluster-b-1'"
                    ).fetchone()[0],
                ),
            ).fetchall()
        }
        operations = connection.execute(
            "SELECT operation_type FROM policy_cluster_manual_operations ORDER BY id"
        ).fetchall()
    assert merged_cluster_ids == {merge_result["target_cluster_id"]}
    assert operations == [("split",), ("merge",)]

    operations = module.list_policy_cluster_manual_operations()["results"]
    merge_operation_id = operations[0]["id"]
    split_operation_id = operations[1]["id"]
    undo_merge = module.undo_policy_cluster_operation(merge_operation_id, "owner")
    assert undo_merge["restored_documents"] == 2
    with closing(sqlite3.connect(module.CONTENT_DATABASE_PATH)) as connection:
        restored_assignment = connection.execute(
            "SELECT operation_type FROM policy_cluster_manual_assignments WHERE document_id=?",
            (split_document_id,),
        ).fetchone()[0]
    assert restored_assignment == "split"

    undo_split = module.undo_policy_cluster_operation(split_operation_id, "owner")
    assert undo_split["restored_documents"] == 1
    with closing(sqlite3.connect(module.CONTENT_DATABASE_PATH)) as connection:
        assignment_count = connection.execute(
            "SELECT COUNT(*) FROM policy_cluster_manual_assignments WHERE document_id=?",
            (split_document_id,),
        ).fetchone()[0]
        undone_count = connection.execute(
            "SELECT COUNT(*) FROM policy_cluster_manual_operations WHERE undone_at IS NOT NULL"
        ).fetchone()[0]
    assert assignment_count == 0
    assert undone_count == 2


def test_document_metadata_derivation_uses_project_region_stage_and_validity():
    from scripts.build_knowledge_content_index import infer_document_metadata

    metadata = infer_document_metadata(
        "2025年浙江省第六批专精特新小巨人认定名单",
        "50_名单与对标/浙江省小巨人名单.pdf",
        "1 | 杭州测试装备有限公司",
        "50_名单与对标",
    )

    assert metadata["canonical_project_name"] == "国家专精特新“小巨人”企业"
    assert metadata["policy_year"] == 2025
    assert metadata["batch"] == "第六批"
    assert "浙江省" in metadata["region"]
    assert metadata["document_stage"] == "认定名单"
    assert metadata["validity_status"] == "active_candidate"

def test_assistant_daily_limit_and_stream_progress(tmp_path):
    module = load_app(tmp_path)
    with TestClient(module.app) as client:
        setup = client.post(
            "/setup",
            data={"setup_key": "setup-secret", "username": "owner", "password": "correct-horse-battery"},
            follow_redirects=False,
        )
        assert setup.status_code == 303
        login = client.post(
            "/login",
            data={"username": "owner", "password": "correct-horse-battery"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)
        user = module.session_user(login.cookies[module.SESSION_COOKIE])[0]

        guide = client.post(
            "/assistant/answer",
            data={
                "question": "企业全生命周期助手如何导入我的Agent？",
                "csrf_token": user["csrf_token"],
                "stream": "true",
            },
        )
        assert guide.status_code == 200
        assert "event: progress" in guide.text
        assert '"counted": false' in guide.text
        assert '"unlimited": true' in guide.text
        assert module.assistant_usage_today(user["id"]) == 0

        stale_usage_id, _, _ = module.reserve_assistant_usage(user["id"], "模拟服务重启中的问答")
        assert module.assistant_usage_today(user["id"]) == 1
        module.init_database()
        assert module.assistant_usage_today(user["id"]) == 0
        with closing(module.database()) as connection:
            assert connection.execute(
                "SELECT status FROM assistant_usage WHERE id = ?", (stale_usage_id,)
            ).fetchone()["status"] == "failed"

        for used in range(1, 7):
            response = client.post(
                "/assistant/answer",
                data={
                    "question": f"小巨人项目条件第{used}次查询",
                    "csrf_token": user["csrf_token"],
                    "stream": "true",
                },
            )
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            assert "event: progress" in response.text
            assert "event: result" in response.text
            assert "正在检索团队知识库" in response.text
            assert '"unlimited": true' in response.text
            assert '"counted": false' in response.text

        assert module.assistant_usage_today(user["id"]) == 0

        assistant_health = client.get("/admin/health/assistant")
        assert assistant_health.status_code == 200
        assert "用户每日额度" in assistant_health.text
        assert "近7日真实问题样本" in assistant_health.text
        assert "小巨人项目条件第1次查询" in assistant_health.text

        raised_limit = client.post(
            f"/admin/users/{user['id']}/assistant-limit",
            data={"daily_limit": "8", "csrf_token": user["csrf_token"]},
            follow_redirects=False,
        )
        assert raised_limit.status_code == 303
        assert module.assistant_limit_for_user(user["id"]) == 8
        sixth = client.post(
            "/assistant/answer",
            data={"question": "额度调整后的第六次问答", "csrf_token": user["csrf_token"], "stream": "true"},
        )
        assert sixth.status_code == 200
        assert '"unlimited": true' in sixth.text
        assert '"counted": false' in sixth.text

        reset_limit = client.post(
            f"/admin/users/{user['id']}/assistant-limit",
            data={"daily_limit": "", "csrf_token": user["csrf_token"]},
            follow_redirects=False,
        )
        assert reset_limit.status_code == 303
        assert module.assistant_limit_for_user(user["id"]) == 5
        with closing(module.database()) as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS total FROM assistant_usage GROUP BY status"
            ).fetchall()
            latest = connection.execute(
                "SELECT answer_mode, routed_skills, source_count, duration_ms, fallback_reason FROM assistant_usage ORDER BY id DESC LIMIT 1"
            ).fetchone()
        assert {row["status"]: row["total"] for row in rows} == {"completed": 7, "failed": 1}
        assert latest["answer_mode"] == "knowledge-search"
        assert json.loads(latest["routed_skills"])
        assert latest["duration_ms"] is not None
        assert latest["fallback_reason"] == "model_unconfigured"


def test_user_supplied_model_api_is_unmetered_and_not_persisted(tmp_path, monkeypatch):
    module = load_app(tmp_path)
    monkeypatch.setattr(
        module,
        "USER_AI_ALLOWED_HOSTS",
        frozenset({"model.example.com"}),
    )
    monkeypatch.setattr(
        module,
        "public_model_addresses",
        lambda hostname, port=443: ("203.0.113.10",),
    )
    monkeypatch.setattr(
        module,
        "request_assistant_model",
        lambda messages, model_config=None: {"content": "自带API回答", "tool_calls": []},
    )
    with TestClient(module.app) as client:
        client.post(
            "/setup",
            data={"setup_key": "setup-secret", "username": "owner", "password": "correct-horse-battery"},
        )
        login = client.post(
            "/login",
            data={"username": "owner", "password": "correct-horse-battery"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)
        user = module.session_user(login.cookies[module.SESSION_COOKIE])[0]
        for index in range(5):
            usage_id, _, _ = module.reserve_assistant_usage(user["id"], f"计费问题{index}")
            module.complete_assistant_usage(usage_id, "completed")
        assert module.assistant_usage_today(user["id"]) == 5

        response = client.post(
            "/assistant/answer",
            data={
                "question": "使用自带API继续问答",
                "csrf_token": user["csrf_token"],
                "user_api_base": "https://model.example.com",
                "user_api_key": "user-secret-key",
                "user_api_model": "example-chat",
            },
        )
        assert response.status_code == 200
        assert response.json()["answer"] == "自带API回答"
        assert response.json()["quota"]["counted"] is False
        assert module.assistant_usage_today(user["id"]) == 5
        with closing(module.database()) as connection:
            latest = connection.execute(
                "SELECT provider_mode,quota_counted,error_message FROM assistant_usage ORDER BY id DESC LIMIT 1"
            ).fetchone()
            serialized_database = " ".join(
                str(value)
                for row in connection.execute("SELECT * FROM assistant_usage").fetchall()
                for value in row
                if value is not None
            )
        assert latest["provider_mode"] == "user-api"
        assert latest["quota_counted"] == 0
        assert "user-secret-key" not in serialized_database

        cockpit = client.get("/cockpit")
        assert "使用我自己的大模型 API" in cockpit.text
        assert "服务端不保存 API Key" in cockpit.text


def test_setup_password_requires_nine_characters(tmp_path):
    module = load_app(tmp_path)
    with TestClient(module.app) as client:
        too_short = client.post(
            "/setup",
            data={"setup_key": "setup-secret", "username": "owner", "password": "12345678"},
            follow_redirects=False,
        )
        assert too_short.status_code == 422

        accepted = client.post(
            "/setup",
            data={"setup_key": "setup-secret", "username": "owner", "password": "123456789"},
            follow_redirects=False,
        )
        assert accepted.status_code == 303


def test_login_can_remember_user_for_seven_days(tmp_path):
    module = load_app(tmp_path)
    with TestClient(module.app) as client:
        setup = client.post(
            "/setup",
            data={"setup_key": "setup-secret", "username": "wangxiaoming", "password": "123456789"},
            follow_redirects=False,
        )
        assert setup.status_code == 303

        login = client.post(
            "/login",
            data={"username": "wangxiaoming", "password": "123456789", "remember_me": "7_days"},
            follow_redirects=False,
        )
        assert login.status_code == 303
        assert "Max-Age=604800" in login.headers["set-cookie"]
        with closing(module.database()) as connection:
            session = connection.execute(
                "SELECT created_at, expires_at FROM sessions ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        duration = datetime.fromisoformat(session["expires_at"]) - datetime.fromisoformat(
            session["created_at"]
        )
        assert duration == timedelta(days=7)


def test_topbar_logout_clears_session(tmp_path):
    module = load_app(tmp_path)
    with TestClient(module.app) as client:
        setup = client.post(
            "/setup",
            data={"setup_key": "setup-secret", "username": "owner", "password": "123456789"},
            follow_redirects=False,
        )
        assert setup.status_code == 303
        login = client.post(
            "/login",
            data={"username": "owner", "password": "123456789"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)
        user = module.session_user(login.cookies[module.SESSION_COOKIE])[0]

        logout = client.post(
            "/logout",
            data={"csrf_token": user["csrf_token"]},
            follow_redirects=False,
        )

        assert logout.status_code == 303
        assert logout.headers["location"] == "/login"
        assert client.get("/portal", follow_redirects=False).status_code == 303


def test_registration_requires_english_account_name(tmp_path):
    module = load_app(tmp_path)
    with closing(module.database()) as connection:
        connection.execute(
            "INSERT INTO users(username, password_hash, is_admin, created_at) VALUES (?, ?, 1, ?)",
            ("owner", module.password_hasher.hash("owner-password-123"), module.isoformat(module.utc_now())),
        )
        authorization_id = connection.execute(
            """
            INSERT INTO registration_authorizations(
                real_name,identity_code,status,created_at
            ) VALUES (?,?,'pending',?)
            """,
            ("王小明", "0001", module.isoformat(module.utc_now())),
        ).lastrowid
        invite_token = issue_test_invitation(module, connection, authorization_id)
        connection.commit()
    with TestClient(module.app) as client:
        response = client.post(
            "/register",
            data={
                "username": "王小明",
                "real_name": "王小明",
                "identity_code": "0001",
                "company_name": "共创集团",
                "password": "member-password-123",
                "confirm_password": "member-password-123",
                "invite_token": invite_token,
            },
            follow_redirects=False,
        )
        assert response.status_code == 400
        assert "登录账号须使用" in response.text


def test_member_cannot_create_users(tmp_path):
    module = load_app(tmp_path)
    with closing(module.database()) as connection:
        connection.execute(
            "INSERT INTO users(username, password_hash, created_at) VALUES (?, ?, ?)",
            ("member", module.password_hasher.hash("member-password-123"), module.isoformat(module.utc_now())),
        )
        member_id = connection.execute(
            "SELECT id FROM users WHERE username='member'"
        ).fetchone()["id"]
        connection.execute(
            """
            INSERT INTO registration_authorizations(
                real_name,identity_code,status,user_id,created_at,registered_at
            ) VALUES (?,?, 'registered', ?, ?, ?)
            """,
            (
                "王小明",
                "0826",
                member_id,
                module.isoformat(module.utc_now()),
                module.isoformat(module.utc_now()),
            ),
        )
        connection.commit()
    with TestClient(module.app) as client:
        login = client.post(
            "/login",
            data={"username": "member", "password": "member-password-123"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)
        user = module.session_user(login.cookies[module.SESSION_COOKIE])[0]
        response = client.post(
            "/users",
            data={
                "username": "forbidden",
                "initial_password": "forbidden-password-123",
                "csrf_token": user["csrf_token"],
            },
        )
        assert response.status_code == 403


def test_registration_requires_company_verification(tmp_path):
    module = load_app(tmp_path)
    with closing(module.database()) as connection:
        connection.execute(
            "INSERT INTO users(username, password_hash, is_admin, created_at) VALUES (?, ?, 1, ?)",
            ("owner", module.password_hasher.hash("owner-password-123"), module.isoformat(module.utc_now())),
        )
        connection.execute(
            "INSERT INTO registration_authorizations(real_name, identity_code, status, created_at) VALUES (?, ?, 'pending', ?)",
            ("王小明", "0001", module.isoformat(module.utc_now())),
        )
        authorization_id = connection.execute(
            "SELECT id FROM registration_authorizations WHERE real_name='王小明'"
        ).fetchone()["id"]
        invite_token = issue_test_invitation(module, connection, authorization_id)
        connection.commit()
    with TestClient(module.app) as client:
        rejected = client.post(
            "/register",
            data={
                "username": "member-one",
                "real_name": "王小明",
                "identity_code": "0001",
                "company_name": "错误公司",
                "password": "member-password-123",
                "confirm_password": "member-password-123",
                "invite_token": invite_token,
            },
        )
        assert rejected.status_code == 403
        created = client.post(
            "/register",
            data={
                "username": "member-one",
                "real_name": "王小明",
                "identity_code": "0001",
                "company_name": "共创集团",
                "password": "member-password-123",
                "confirm_password": "member-password-123",
                "invite_token": invite_token,
            },
            follow_redirects=False,
        )
        assert created.status_code == 303
        login = client.post(
            "/login",
            data={"username": "member-one", "password": "member-password-123"},
            follow_redirects=False,
        )
        assert login.status_code == 303

        with closing(module.database()) as connection:
            registered_user = connection.execute(
                "SELECT real_name FROM users WHERE username='member-one'"
            ).fetchone()
            authorization = connection.execute(
                "SELECT status FROM registration_authorizations WHERE real_name='王小明'"
            ).fetchone()
        assert registered_user["real_name"] == "王小明"
        assert authorization["status"] == "registered"


def test_internal_member_can_self_register_with_name_and_phone_tail(tmp_path):
    module = load_app(tmp_path)
    now = module.isoformat(module.utc_now())
    with closing(module.database()) as connection:
        connection.execute(
            "INSERT INTO users(username, password_hash, is_admin, created_at) VALUES (?, ?, 1, ?)",
            ("owner", module.password_hasher.hash("owner-password-123"), now),
        )
        connection.execute(
            """
            INSERT INTO registration_authorizations(
                real_name,identity_code,status,created_at,invite_secret,
                invite_issued_at,invite_expires_at
            ) VALUES (?,?,'pending',?,?,?,?)
            """,
            (
                "王小明",
                "0826",
                now,
                "x" * 43,
                now,
                module.isoformat(module.utc_now() + timedelta(hours=48)),
            ),
        )
        connection.commit()

    registration = {
        "username": "member-self-service",
        "real_name": "王小明",
        "identity_code": "13800000826",
        "company_name": "共创集团",
        "password": "member-password-123",
        "confirm_password": "member-password-123",
    }
    with TestClient(module.app) as client:
        registration_page = client.get("/register")
        assert registration_page.status_code == 200
        assert "名单中的内部成员无需等待邀请链接" in registration_page.text
        assert "核验名单并注册" in registration_page.text

        wrong_tail = client.post(
            "/register",
            data={**registration, "identity_code": "9999"},
            follow_redirects=False,
        )
        assert wrong_tail.status_code == 403
        assert "未获得注册权限" in wrong_tail.text

        accepted = client.post(
            "/register",
            data=registration,
            follow_redirects=False,
        )
        assert accepted.status_code == 303
        assert accepted.headers["location"] == "/login?registered=1"

        duplicate = client.post(
            "/register",
            data={**registration, "username": "member-self-service-copy"},
            follow_redirects=False,
        )
        assert duplicate.status_code == 409
        assert "已完成注册" in duplicate.text

    with closing(module.database()) as connection:
        user = connection.execute(
            "SELECT id,real_name FROM users WHERE username=?",
            ("member-self-service",),
        ).fetchone()
        authorization = connection.execute(
            """
            SELECT status,user_id,invite_secret,invite_consumed_at
            FROM registration_authorizations
            WHERE real_name='王小明' AND identity_code='0826'
            """
        ).fetchone()
        duplicate_count = connection.execute(
            "SELECT COUNT(*) FROM users WHERE real_name='王小明'"
        ).fetchone()[0]
    assert user is not None
    assert user["real_name"] == "王小明"
    assert authorization["status"] == "registered"
    assert authorization["user_id"] == user["id"]
    assert authorization["invite_secret"] == ""
    assert authorization["invite_consumed_at"]
    assert duplicate_count == 1


def test_member_import_template_overwrite_and_authorization_controls_access(tmp_path):
    module = load_app(tmp_path)
    with closing(module.database()) as connection:
        connection.execute(
            "INSERT INTO users(username, password_hash, is_admin, created_at) VALUES (?, ?, 1, ?)",
            ("owner", module.password_hasher.hash("owner-password-123"), module.isoformat(module.utc_now())),
        )
        connection.commit()

    with TestClient(module.app) as client:
        owner_login = client.post(
            "/login",
            data={"username": "owner", "password": "owner-password-123"},
            follow_redirects=False,
        )
        client.cookies.update(owner_login.cookies)
        owner = module.session_user(owner_login.cookies[module.SESSION_COOKIE])[0]

        template = client.get("/admin/registration-authorizations/template.csv")
        assert template.status_code == 200
        assert template.content.startswith(b"\xef\xbb\xbf")
        assert "中文真实姓名" in template.content.decode("utf-8-sig")

        member_csv = "中文真实姓名,企业微信绑定手机号或后四位\n王小明,13800000826\n".encode("utf-8-sig")
        imported = client.post(
            "/admin/registration-authorizations/import",
            files={"member_file": ("members.csv", member_csv, "text/csv")},
            data={"csrf_token": owner["csrf_token"]},
        )
        overwritten = client.post(
            "/admin/registration-authorizations/import",
            files={"member_file": ("members.csv", member_csv, "text/csv")},
            data={"csrf_token": owner["csrf_token"]},
        )
        assert imported.status_code == 200
        assert "新增1人" in imported.text
        assert "刷新注册权限1人" in overwritten.text
        assert "王小明" in overwritten.text

        registered = client.post(
            "/register",
            data={
                "username": "member-one",
                "real_name": "王小明",
                "identity_code": "0826",
                "company_name": "共创集团",
                "password": "member-password-123",
                "confirm_password": "member-password-123",
            },
            follow_redirects=False,
        )
        assert registered.status_code == 303
        with closing(module.database()) as connection:
            authorization_id = connection.execute(
                "SELECT id FROM registration_authorizations WHERE real_name='王小明' AND identity_code='0826'"
            ).fetchone()["id"]
            assert connection.execute(
                "SELECT COUNT(*) FROM registration_authorizations WHERE real_name='王小明' AND identity_code='0826'"
            ).fetchone()[0] == 1

        owner_login = client.post(
            "/login",
            data={"username": "owner", "password": "owner-password-123"},
            follow_redirects=False,
        )
        client.cookies.update(owner_login.cookies)
        owner = module.session_user(owner_login.cookies[module.SESSION_COOKIE])[0]
        removed = client.post(
            f"/admin/registration-authorizations/{authorization_id}/trash",
            data={"csrf_token": owner["csrf_token"]},
            follow_redirects=False,
        )
        assert removed.status_code == 303
        denied = client.post(
            "/login",
            data={"username": "member-one", "password": "member-password-123"},
            follow_redirects=False,
        )
        assert denied.status_code == 401

        owner_login = client.post(
            "/login",
            data={"username": "owner", "password": "owner-password-123"},
            follow_redirects=False,
        )
        client.cookies.update(owner_login.cookies)
        owner = module.session_user(owner_login.cookies[module.SESSION_COOKIE])[0]
        readded = client.post(
            "/admin/registration-authorizations",
            data={
                "real_name": "王小明",
                "identity_code": "0826",
                "csrf_token": owner["csrf_token"],
            },
            follow_redirects=False,
        )
        assert readded.status_code == 409
        restored = client.post(
            f"/admin/registration-authorizations/{authorization_id}/restore",
            data={"csrf_token": owner["csrf_token"]},
            follow_redirects=False,
        )
        assert restored.status_code == 303
        restored_login = client.post(
            "/login",
            data={"username": "member-one", "password": "member-password-123"},
            follow_redirects=False,
        )
        assert restored_login.status_code == 303

        duplicate_account = client.post(
            "/register",
            data={
                "username": "member-two",
                "real_name": "王小明",
                "identity_code": "0826",
                "company_name": "共创集团",
                "password": "member-password-456",
                "confirm_password": "member-password-456",
            },
        )
        assert duplicate_account.status_code == 409
        assert "已完成注册" in duplicate_account.text


def test_signed_invitation_link_prefills_and_registers_authorized_member(tmp_path):
    module = load_app(tmp_path)
    with closing(module.database()) as connection:
        connection.execute(
            "INSERT INTO users(username, password_hash, is_admin, created_at) VALUES (?, ?, 1, ?)",
            ("owner", module.password_hasher.hash("owner-password-123"), module.isoformat(module.utc_now())),
        )
        connection.execute(
            "INSERT INTO registration_authorizations(real_name, identity_code, status, created_at) VALUES (?, ?, 'pending', ?)",
            ("王小明", "0826", module.isoformat(module.utc_now())),
        )
        authorization_id = connection.execute(
            "SELECT id FROM registration_authorizations WHERE real_name='王小明'"
        ).fetchone()["id"]
        invite_token = issue_test_invitation(module, connection, authorization_id)
        authorization = connection.execute(
            "SELECT * FROM registration_authorizations WHERE real_name='王小明'"
        ).fetchone()
        connection.commit()

    with TestClient(module.app) as client:
        invitation_page = client.get(f"/register?invite={invite_token}")
        assert invitation_page.status_code == 200
        assert "专属邀请已识别" in invitation_page.text
        assert 'value="王小明"' in invitation_page.text
        assert 'value="0826"' in invitation_page.text

        created = client.post(
            "/register",
            data={
                "invite_token": invite_token,
                "username": "member-invited",
                "real_name": "伪造姓名",
                "identity_code": "9999",
                "company_name": "共创集团",
                "password": "member-password-123",
                "confirm_password": "member-password-123",
            },
            follow_redirects=False,
        )
        assert created.status_code == 303

    with closing(module.database()) as connection:
        registered_user = connection.execute(
            "SELECT real_name FROM users WHERE username='member-invited'"
        ).fetchone()
        status_row = connection.execute(
            "SELECT status FROM registration_authorizations WHERE id=?",
            (authorization["id"],),
        ).fetchone()
    assert registered_user["real_name"] == "王小明"
    assert status_row["status"] == "registered"


def test_disabled_member_cannot_be_reinvited_to_take_over_password(tmp_path):
    module = load_app(tmp_path)
    now = module.isoformat(module.utc_now())
    with closing(module.database()) as connection:
        connection.execute(
            "INSERT INTO users(username,real_name,password_hash,is_admin,created_at) VALUES (?,?,?,?,?)",
            ("owner", "管理员", module.password_hasher.hash("owner-password-123"), 1, now),
        )
        connection.execute(
            "INSERT INTO users(username,real_name,password_hash,active,created_at) VALUES (?,?,?,?,?)",
            ("member-one", "王小明", module.password_hasher.hash("old-password-123"), 0, now),
        )
        member_id = connection.execute("SELECT id FROM users WHERE username='member-one'").fetchone()["id"]
        connection.execute(
            "INSERT INTO registration_authorizations(real_name,identity_code,status,user_id,created_at,registered_at) VALUES (?,?,'registered',?,?,?)",
            ("王小明", "0826", member_id, now, now),
        )
        connection.commit()

    with TestClient(module.app) as client:
        login = client.post(
            "/login",
            data={"username": "owner", "password": "owner-password-123"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)
        owner = module.session_user(login.cookies[module.SESSION_COOKIE])[0]
        reinvite = client.post(
            f"/admin/users/{member_id}/reinvite",
            data={"csrf_token": owner["csrf_token"]},
            follow_redirects=False,
        )
        assert reinvite.status_code == 409
        assert "不能通过重新邀请重设密码" in reinvite.text
        enabled = client.post(
            f"/users/{member_id}/toggle",
            data={"csrf_token": owner["csrf_token"]},
            follow_redirects=False,
        )
        assert enabled.status_code == 303
        member_login = client.post(
            "/login",
            data={"username": "member-one", "password": "old-password-123"},
            follow_redirects=False,
        )
        assert member_login.status_code == 303


def test_trashed_account_can_be_purged_and_same_identity_registered_again(tmp_path):
    module = load_app(tmp_path)
    now = module.isoformat(module.utc_now())
    with closing(module.database()) as connection:
        connection.execute(
            "INSERT INTO users(username,real_name,password_hash,is_admin,created_at) VALUES (?,?,?,?,?)",
            ("owner", "管理员", module.password_hasher.hash("owner-password-123"), 1, now),
        )
        connection.execute(
            "INSERT INTO users(username,real_name,password_hash,active,created_at,deleted_at) VALUES (?,?,?,?,?,?)",
            ("member-one", "王小明", module.password_hasher.hash("old-password-123"), 0, now, now),
        )
        member_id = connection.execute("SELECT id FROM users WHERE username='member-one'").fetchone()["id"]
        connection.execute(
            "INSERT INTO registration_authorizations(real_name,identity_code,status,user_id,created_at,deleted_at) VALUES (?,?,'revoked',?,?,?)",
            ("王小明", "0826", member_id, now, now),
        )
        connection.commit()

    with TestClient(module.app) as client:
        login = client.post(
            "/login",
            data={"username": "owner", "password": "owner-password-123"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)
        owner = module.session_user(login.cookies[module.SESSION_COOKIE])[0]
        wrong = client.post(
            f"/admin/users/{member_id}/purge",
            data={"confirmation": "wrong", "csrf_token": owner["csrf_token"]},
        )
        assert wrong.status_code == 400
        purged = client.post(
            f"/admin/users/{member_id}/purge",
            data={"confirmation": "member-one", "csrf_token": owner["csrf_token"]},
            follow_redirects=False,
        )
        assert purged.status_code == 303
    with closing(module.database()) as connection:
        assert connection.execute("SELECT 1 FROM users WHERE id=?", (member_id,)).fetchone() is None
        assert connection.execute(
            "SELECT 1 FROM registration_authorizations WHERE real_name='王小明' AND identity_code='0826'"
        ).fetchone() is None


def test_identity_code_requires_wecom_phone_last_four_digits(tmp_path):
    module = load_app(tmp_path)
    assert module.normalize_identity_code("0826") == "0826"
    assert module.normalize_identity_code("13800000826") == "0826"
    assert module.normalize_identity_code("+86 138-0000-0826") == "0826"
    with pytest.raises(ValueError, match="完整11位手机号或手机号后四位"):
        module.normalize_identity_code("A826")


def test_policy_queries_choose_expected_source_layer(tmp_path):
    module = load_app(tmp_path)
    assert module.policy_source_layer("高新申报条件") == "curated"
    assert module.policy_source_layer("杭州市2026年高新公示名单") == "dynamic"
    assert module.policy_source_layer("高新") == "mixed"
    assert module.knowledge_search_query("高新申报条件") == "高新技术企业"
    assert module.knowledge_search_query("杭州市2026年高新公示名单") == "杭州市 高新技术企业"
    assert module.knowledge_search_query("公司法注册资本五年") == "公司法 注册资本"
    assert module.project_query_variants("省研究院的申报要求") == [
        "浙江省企业研究院",
        "浙江省重点企业研究院",
    ]
    assert module.project_selection_prompt("未来工厂怎么申报")
    assert module.project_query_variants("未来工厂怎么申报") == [
        "杭州市AI工厂",
        "浙江省未来工厂",
    ]
    assert module.project_query_variants("浙江省重点企业研究院申报要求") == [
        "浙江省重点企业研究院"
    ]
    with closing(sqlite3.connect(module.CONTENT_DATABASE_PATH)) as connection:
        connection.execute(
            """
            INSERT INTO documents(
                source_key,title,content,source,cloud_path,document_role,sensitivity,
                sha256,updated_at,canonical_project_name,region,document_stage,
                validity_status,policy_year,batch
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "research-institute-current",
                "浙江省企业研究院建设与管理办法",
                "浙江省企业研究院申报要求和认定条件。",
                "10_政策与目录/研究院/现行办法.md",
                "10_政策与目录/研究院/现行办法.md",
                "10_政策与目录",
                "public",
                "research-institute-sha",
                "2026-01-01T00:00:00+00:00",
                "浙江省企业研究院",
                "浙江省",
                "管理办法",
                "active_candidate",
                2026,
                "",
            ),
        )
        connection.execute("INSERT INTO documents_fts_trigram(documents_fts_trigram) VALUES ('rebuild')")
        connection.commit()
    research_results = module.search_knowledge("省研究院的申报要求")["results"]
    assert research_results
    assert research_results[0]["title"] == "浙江省企业研究院建设与管理办法"

    with closing(sqlite3.connect(module.CONTENT_DATABASE_PATH)) as connection:
        for source_key, title, content in (
            (
                "high-tech-misleading",
                "台州市级高新技术企业研究开发中心认定管理办法",
                "正文提到高新技术企业可以参与研究院建设。",
            ),
            (
                "high-tech-current",
                "高新技术企业认定管理办法",
                "高新技术企业申报条件、认定要求和材料清单。",
            ),
            (
                "high-tech-list",
                "2020年国家高新技术企业补助资金拟兑现名单",
                "高新技术企业补助资金拟兑现企业名单。",
            ),
        ):
            connection.execute(
                """
                INSERT INTO documents(
                    source_key,title,content,source,cloud_path,document_role,sensitivity,
                    sha256,updated_at,canonical_project_name,region,document_stage,
                    validity_status,policy_year,batch
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    source_key,
                    title,
                    content,
                    f"10_政策与目录/高新技术企业/{title}.md",
                    f"10_政策与目录/高新技术企业/{title}.md",
                    "10_政策与目录",
                    "public",
                    f"{source_key}-sha",
                    "2026-01-01T00:00:00+00:00",
                    "高新技术企业",
                    "全国",
                    "管理办法" if source_key == "high-tech-current" else "申报通知",
                    "active_candidate",
                    2026,
                    "",
                ),
            )
        connection.execute("INSERT INTO documents_fts_trigram(documents_fts_trigram) VALUES ('rebuild')")
        connection.commit()
    high_tech_results = module.search_knowledge("高新申报条件")["results"]
    assert high_tech_results
    assert high_tech_results[0]["title"] == "高新技术企业认定管理办法"
    assert all("研究开发中心" not in item["title"] for item in high_tech_results)
    assert all("名单" not in item["title"] for item in high_tech_results)
    assert all("2020年" not in item["title"] for item in high_tech_results)


def test_fuzzy_search_recalls_year_notice_list_and_similar_general_content(tmp_path):
    module = load_app(tmp_path)
    with closing(sqlite3.connect(module.CONTENT_DATABASE_PATH)) as connection:
        documents = [
            (
                "little-giant-2024-notice",
                "2024年专精特新“小巨人”企业申报通知",
                "组织开展第六批专精特新小巨人申报工作。",
                "10_政策与目录/优质中小企业梯度培育/2024年小巨人申报通知.pdf",
                "国家专精特新“小巨人”企业",
                "申报通知",
                None,
            ),
            (
                "little-giant-2024-list",
                "2024年专精特新“小巨人”企业公示名单",
                "附件为拟认定企业名单。",
                "10_政策与目录/优质中小企业梯度培育/2024年小巨人公示名单.pdf",
                "国家专精特新“小巨人”企业",
                "公示名单",
                2024,
            ),
            (
                "specialized-sme-2024-notice",
                "2024年专精特新中小企业申报通知",
                "省级专精特新中小企业申报。",
                "10_政策与目录/优质中小企业梯度培育/2024年省专通知.pdf",
                "专精特新中小企业",
                "申报通知",
                2024,
            ),
            (
                "company-law-compliance",
                "新公司法下企业合规自查与风险防范",
                "覆盖注册资本、股东出资和公司治理风险排查。",
                "30_法律法规与合规/新公司法合规指南.md",
                "",
                "其他",
                2024,
            ),
        ]
        for source_key, title, content, source, project_name, stage, policy_year in documents:
            connection.execute(
                """
                INSERT INTO documents(
                    source_key,title,content,source,cloud_path,document_role,sensitivity,
                    sha256,updated_at,canonical_project_name,region,document_stage,
                    validity_status,policy_year,batch
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    source_key,
                    title,
                    content,
                    source,
                    source,
                    "10_政策与目录",
                    "public",
                    f"{source_key}-sha",
                    "2026-07-22T00:00:00+00:00",
                    project_name,
                    "全国",
                    stage,
                    "active_candidate",
                    policy_year,
                    "",
                ),
            )
        connection.execute(
            """
            INSERT INTO documents(
                source_key,title,content,source,cloud_path,document_role,sensitivity,
                sha256,updated_at,canonical_project_name,region,document_stage,
                validity_status,policy_year,batch
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "little-giant-fourth-batch",
                "附件1：第四批专精特新“小巨人”企业公示名单.xls",
                "第四批专精特新小巨人企业名单。",
                "50_名单与对标/第四批小巨人名单.xls",
                "50_名单与对标/第四批小巨人名单.xls",
                "50_名单与对标",
                "public",
                "little-giant-fourth-batch-sha",
                "2026-07-22T00:00:00+00:00",
                "国家专精特新“小巨人”企业",
                "全国",
                "公示名单",
                "historical_reference",
                None,
                "第四批",
            ),
        )
        connection.execute("INSERT INTO documents_fts_trigram(documents_fts_trigram) VALUES ('rebuild')")
        connection.commit()

    year_results = module.search_knowledge("2024小巨人", limit=8)["results"]
    year_titles = [item["title"] for item in year_results]
    assert year_titles[:2] == [
        "2024年专精特新“小巨人”企业申报通知",
        "2024年专精特新“小巨人”企业公示名单",
    ]
    assert "2024年专精特新中小企业申报通知" not in year_titles
    notice_results = module.search_knowledge("2024小巨人申报通知", limit=8)["results"]
    assert notice_results[0]["title"] == "2024年专精特新“小巨人”企业申报通知"
    assert all("公示名单" not in item["title"] for item in notice_results)
    explicit_list_results = module.search_knowledge(
        "2024年第六批浙江省专精特新小巨人公示名单",
        limit=8,
    )["results"]
    assert explicit_list_results[0]["title"] == "2024年专精特新“小巨人”企业公示名单"
    fourth_batch_results = module.search_knowledge("2022小巨人名单", limit=8)["results"]
    assert fourth_batch_results[0]["title"] == "附件1：第四批专精特新“小巨人”企业公示名单.xls"
    explicit_fourth_batch_results = module.search_knowledge(
        "第四批专精特新小巨人公示名单",
        limit=8,
    )["results"]
    assert explicit_fourth_batch_results[0]["title"] == "附件1：第四批专精特新“小巨人”企业公示名单.xls"

    general_results = module.search_knowledge("公司合规风险排查", limit=5)["results"]
    assert general_results[0]["title"] == "新公司法下企业合规自查与风险防范"


def test_search_result_deduplication_collapses_same_title_project_year_and_stage(tmp_path):
    module = load_app(tmp_path)
    rows = [
        {
            "id": 1,
            "title": "2025年浙江省首版次软件产品申报通知",
            "canonical_project_name": "浙江省首版次软件产品",
            "policy_year": 2025,
            "document_stage": "申报通知",
        },
        {
            "id": 2,
            "title": "2025年浙江省首版次软件产品申报通知",
            "canonical_project_name": "浙江省首版次软件产品",
            "policy_year": 2025,
            "document_stage": "申报通知",
        },
        {
            "id": 3,
            "title": "2025年浙江省首版次软件产品认定名单",
            "canonical_project_name": "浙江省首版次软件产品",
            "policy_year": 2025,
            "document_stage": "认定名单",
        },
    ]
    assert [row["id"] for row in module.deduplicate_search_results(rows)] == [1, 3]


def test_every_high_frequency_alias_has_positive_cross_project_and_stale_gates(tmp_path):
    module = load_app(tmp_path)
    gold_path = (
        module.PROJECT_INDEX_PATH.parent / "high-frequency-project-gold-standard.jsonl"
    )
    rules_path = module.PROJECT_INDEX_PATH.parent / "high-frequency-project-retrieval-rules.json"
    cases = [json.loads(line) for line in gold_path.read_text(encoding="utf-8").splitlines() if line]
    aliases = {case["alias"] for case in cases}
    rules = json.loads(rules_path.read_text(encoding="utf-8"))["rules"]
    expected_aliases = {alias for rule in rules for alias in rule["aliases"]}
    assert aliases == expected_aliases
    assert len(cases) == len(aliases) * 3
    assert {
        (case["alias"], case["kind"]) for case in cases
    } == {
        (alias, kind)
        for alias in aliases
        for kind in ("positive", "cross-project", "stale")
    }
    for case in cases:
        query = case["query"]
        if case["kind"] == "positive":
            clarification = module.project_selection_prompt(query)
            if case["expected_clarification"]:
                assert clarification
            else:
                assert clarification is None
                assert module.project_query_variants(query) == case["expected_targets"]
        elif case["kind"] == "cross-project":
            rows = [
                {"document_id": 1, "title": case["allowed_title"], "source": case["allowed_title"]},
                {"document_id": 2, "title": case["excluded_title"], "source": case["excluded_title"]},
            ]
            filtered = module.filter_project_results(query, rows)
            assert [row["document_id"] for row in filtered] == [1], case
        else:
            rows = [
                {"document_id": 1, "title": case["current_title"], "source": case["current_title"]},
                {"document_id": 2, "title": case["stale_title"], "source": case["stale_title"]},
            ]
            filtered = module.filter_project_results(query, rows)
            assert [row["document_id"] for row in filtered] == [1]


def test_municipal_projects_require_city_and_accept_explicit_city(tmp_path):
    module = load_app(tmp_path)
    assert "所在城市" in module.project_selection_prompt("市企业技术中心申报条件")
    assert module.project_selection_prompt("宁波市企业技术中心申报条件") is None
    assert module.project_query_variants("宁波市企业技术中心申报条件") == [
        "宁波市 市级企业技术中心（四市属地版）"
    ]


def test_local_green_factory_requires_matching_region_level(tmp_path):
    module = load_app(tmp_path)
    assert "所在区县和城市" in module.project_selection_prompt("市级绿色工厂申报条件")
    assert module.project_selection_prompt("绍兴市市级绿色工厂申报条件") is None
    assert module.project_selection_prompt("区级绿色工厂申报条件")
    assert module.project_selection_prompt("余杭区区级绿色工厂申报条件") is None


def test_admin_can_search_registration_authorizations(tmp_path):
    module = load_app(tmp_path)
    now = module.isoformat(module.utc_now())
    with closing(module.database()) as connection:
        connection.execute(
            "INSERT INTO users(username, real_name, password_hash, is_admin, created_at) VALUES (?, ?, ?, 1, ?)",
            ("owner", "管理员", module.password_hasher.hash("owner-password-123"), now),
        )
        connection.execute(
            "INSERT INTO users(username, real_name, password_hash, created_at) VALUES (?, ?, ?, ?)",
            ("zhangsan", "张三", module.password_hasher.hash("member-password-123"), now),
        )
        member_id = connection.execute(
            "SELECT id FROM users WHERE username='zhangsan'"
        ).fetchone()["id"]
        connection.executemany(
            """
            INSERT INTO registration_authorizations(
                real_name,identity_code,status,user_id,created_at,registered_at
            ) VALUES (?,?,?,?,?,?)
            """,
            [
                ("张三", "8899", "registered", member_id, now, now),
                ("李四", "6677", "pending", None, now, None),
                ("王五", "4455", "revoked", None, now, None),
            ],
        )
        authorization_ids = {
            row["real_name"]: row["id"]
            for row in connection.execute(
                "SELECT id,real_name FROM registration_authorizations"
            ).fetchall()
        }
        connection.commit()

    with TestClient(module.app) as client:
        login = client.post(
            "/login",
            data={"username": "owner", "password": "owner-password-123"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)

        by_name = client.get("/admin/members?invite_query=张三")
        assert f'id="invite-{authorization_ids["张三"]}"' in by_name.text
        assert f'id="invite-{authorization_ids["李四"]}"' not in by_name.text

        by_tail = client.get("/admin/members?invite_query=6677")
        assert f'id="invite-{authorization_ids["李四"]}"' in by_tail.text
        assert f'id="invite-{authorization_ids["张三"]}"' not in by_tail.text

        by_username = client.get("/admin/members?invite_query=zhangsan")
        assert f'id="invite-{authorization_ids["张三"]}"' in by_username.text
        assert f'id="invite-{authorization_ids["李四"]}"' not in by_username.text

        by_status = client.get("/admin/members?invite_query=已撤销")
        assert f'id="invite-{authorization_ids["王五"]}"' in by_status.text
        assert f'id="invite-{authorization_ids["张三"]}"' not in by_status.text

        empty = client.get("/admin/members?invite_query=不存在")
        assert "未找到匹配的注册授权记录" in empty.text


def test_admin_can_open_member_details_and_restore_soft_deleted_records(tmp_path):
    module = load_app(tmp_path)
    now = module.isoformat(module.utc_now())
    with closing(module.database()) as connection:
        connection.execute(
            "INSERT INTO users(username, real_name, password_hash, is_admin, created_at) VALUES (?, ?, ?, 1, ?)",
            ("owner", "管理员", module.password_hasher.hash("owner-password-123"), now),
        )
        connection.execute(
            "INSERT INTO users(username, real_name, password_hash, created_at) VALUES (?, ?, ?, ?)",
            ("member-one", "王小明", module.password_hasher.hash("member-password-123"), now),
        )
        member_id = connection.execute(
            "SELECT id FROM users WHERE username='member-one'"
        ).fetchone()["id"]
        connection.execute(
            """
            INSERT INTO agent_enrollment_codes(
                user_id,code_hash,created_at,expires_at,result_schema,result_ok,
                result_status,result_error_stage,result_user_message,
                result_next_action,result_reported_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                member_id,
                module.token_hash("jbe_admin-detail-test"),
                now,
                module.isoformat(module.utc_now() + timedelta(hours=1)),
                "jiaotang-agent-result/v1",
                0,
                "failed",
                "mcp_connection",
                "安装失败：MCP 初始化超时",
                "请重新执行安装。",
                now,
            ),
        )
        connection.execute(
            "INSERT INTO registration_authorizations(real_name, identity_code, status, created_at) VALUES (?, ?, 'pending', ?)",
            ("李小红", "0826", now),
        )
        authorization_id = connection.execute(
            "SELECT id FROM registration_authorizations WHERE real_name='李小红'"
        ).fetchone()["id"]
        connection.commit()

    with TestClient(module.app) as client:
        login = client.post(
            "/login",
            data={"username": "owner", "password": "owner-password-123"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)
        user = module.session_user(login.cookies[module.SESSION_COOKIE])[0]

        members = client.get("/admin/members")
        assert f'/admin/users/{member_id}' in members.text
        assert f'/admin/registration-authorizations/{authorization_id}' in members.text
        assert "/admin/members/trash" in members.text

        member_detail = client.get(f"/admin/users/{member_id}")
        assert member_detail.status_code == 200
        assert "最后一次安装或连接结果" in member_detail.text
        assert "mcp_connection" in member_detail.text
        assert "安装失败：MCP 初始化超时" in member_detail.text
        assert client.get(
            f"/admin/registration-authorizations/{authorization_id}"
        ).status_code == 200

        removed_member = client.post(
            f"/admin/users/{member_id}/trash",
            data={"csrf_token": user["csrf_token"]},
            follow_redirects=False,
        )
        removed_invitation = client.post(
            f"/admin/registration-authorizations/{authorization_id}/trash",
            data={"csrf_token": user["csrf_token"]},
            follow_redirects=False,
        )
        assert removed_member.status_code == 303
        assert removed_invitation.status_code == 303

        trash_page = client.get("/admin/members/trash")
        assert "王小明" in trash_page.text
        assert "李小红" in trash_page.text

        restored_member = client.post(
            f"/admin/users/{member_id}/restore",
            data={"csrf_token": user["csrf_token"]},
            follow_redirects=False,
        )
        restored_invitation = client.post(
            f"/admin/registration-authorizations/{authorization_id}/restore",
            data={"csrf_token": user["csrf_token"]},
            follow_redirects=False,
        )
        assert restored_member.status_code == 303
        assert restored_invitation.status_code == 303
        with closing(module.database()) as connection:
            restored_user = connection.execute(
                "SELECT active,deleted_at FROM users WHERE id=?", (member_id,)
            ).fetchone()
            restored_authorization = connection.execute(
                "SELECT status,deleted_at FROM registration_authorizations WHERE id=?",
                (authorization_id,),
            ).fetchone()
        assert restored_user["active"] == 1
        assert restored_user["deleted_at"] is None
        assert restored_authorization["status"] == "pending"
        assert restored_authorization["deleted_at"] is None


def test_admin_can_search_registration_authorizations(tmp_path):
    module = load_app(tmp_path)
    now = module.isoformat(module.utc_now())
    with closing(module.database()) as connection:
        connection.execute(
            "INSERT INTO users(username, real_name, password_hash, is_admin, created_at) VALUES (?, ?, ?, 1, ?)",
            ("owner", "管理员", module.password_hasher.hash("owner-password-123"), now),
        )
        member_id = connection.execute(
            """
            INSERT INTO users(username, real_name, password_hash, created_at)
            VALUES (?, ?, ?, ?)
            """,
            ("lisi", "李四", module.password_hasher.hash("member-password-123"), now),
        ).lastrowid
        connection.executemany(
            """
            INSERT INTO registration_authorizations(
                real_name,identity_code,user_id,status,created_at,registered_at,revoked_at
            ) VALUES (?,?,?,?,?,?,?)
            """,
            [
                ("张三", "1234", None, "pending", now, None, None),
                ("李四", "5678", member_id, "registered", now, now, None),
                ("王五", "9999", None, "revoked", now, None, now),
            ],
        )
        authorization_ids = {
            row["real_name"]: row["id"]
            for row in connection.execute(
                "SELECT id,real_name FROM registration_authorizations"
            ).fetchall()
        }
        connection.commit()

    with TestClient(module.app) as client:
        login = client.post(
            "/login",
            data={"username": "owner", "password": "owner-password-123"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)

        by_name = client.get("/admin/members", params={"invite_query": "张三"})
        assert by_name.status_code == 200
        assert f'/admin/registration-authorizations/{authorization_ids["张三"]}' in by_name.text
        assert f'/admin/registration-authorizations/{authorization_ids["李四"]}' not in by_name.text
        assert re.search(r"筛选\s*1\s*/\s*\d+\s*人", by_name.text)

        by_tail = client.get("/admin/members", params={"invite_query": "5678"})
        assert f'/admin/registration-authorizations/{authorization_ids["李四"]}' in by_tail.text
        assert f'/admin/registration-authorizations/{authorization_ids["张三"]}' not in by_tail.text

        by_username = client.get("/admin/members", params={"invite_query": "lisi"})
        assert f'/admin/registration-authorizations/{authorization_ids["李四"]}' in by_username.text
        assert f'/admin/registration-authorizations/{authorization_ids["王五"]}' not in by_username.text

        by_status = client.get("/admin/members", params={"invite_query": "已撤销"})
        assert f'/admin/registration-authorizations/{authorization_ids["王五"]}' in by_status.text
        assert f'/admin/registration-authorizations/{authorization_ids["张三"]}' not in by_status.text

        no_match = client.get("/admin/members", params={"invite_query": "不存在"})
        assert "未找到匹配的注册授权记录" in no_match.text


def test_admin_can_search_registered_members(tmp_path):
    module = load_app(tmp_path)
    now = module.isoformat(module.utc_now())
    with closing(module.database()) as connection:
        connection.execute(
            "INSERT INTO users(username, real_name, company_name, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?, 1, ?)",
            ("owner", "管理员", "总部", module.password_hasher.hash("owner-password-123"), now),
        )
        connection.executemany(
            "INSERT INTO users(username, real_name, company_name, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
            [
                ("zhangsan", "张三", "共创集团", module.password_hasher.hash("member-password-123"), now),
                ("lisi", "李四", "示例集团", module.password_hasher.hash("member-password-123"), now),
            ],
        )
        connection.commit()

    with TestClient(module.app) as client:
        login = client.post(
            "/login",
            data={"username": "owner", "password": "owner-password-123"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)

        by_name = client.get("/admin/members", params={"member_query": "张三"})
        assert by_name.status_code == 200
        assert "张三" in by_name.text
        assert "共创集团" in by_name.text
        # 邀请名单会回填全部已注册成员（含李四），用只在账号表出现的公司名做判别
        assert "示例集团" not in by_name.text
        assert re.search(r"筛选\s*1\s*/\s*\d+\s*个账号", by_name.text)

        by_company = client.get("/admin/members", params={"member_query": "示例集团"})
        assert "示例集团" in by_company.text
        assert "共创集团" not in by_company.text

        no_match = client.get("/admin/members", params={"member_query": "不存在"})
        assert "未找到匹配的账号" in no_match.text


def test_admin_members_uses_confirmed_mcp_connection_as_install_success(tmp_path):
    module = load_app(tmp_path)
    now = module.isoformat(module.utc_now())
    with closing(module.database()) as connection:
        connection.execute(
            "INSERT INTO users(username, real_name, company_name, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?, 1, ?)",
            ("owner", "管理员", "总部", module.password_hasher.hash("owner-password-123"), now),
        )
        member_id = int(
            connection.execute(
                "INSERT INTO users(username, real_name, company_name, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                (
                    "guoqingming",
                    "郭庆明",
                    "共创集团",
                    module.password_hasher.hash("member-password-123"),
                    now,
                ),
            ).lastrowid
        )
        connection.commit()

    _, key_id = provision_signed_device(module, member_id, agent_host="workbuddy")
    with closing(module.database()) as connection:
        connection.execute(
            """
            UPDATE device_keys
            SET credential_saved_at=?,first_verified_at=?,mcp_connected_at=?,
                last_verified_at=?
            WHERE user_id=? AND key_id=?
            """,
            (now, now, now, now, member_id, key_id),
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM agent_enrollment_codes WHERE user_id=?",
            (member_id,),
        ).fetchone()[0] == 0
        connection.commit()

    with TestClient(module.app) as client:
        login = client.post(
            "/login",
            data={"username": "owner", "password": "owner-password-123"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)

        members = client.get(
            "/admin/members",
            params={"member_query": "guoqingming"},
        )
        assert members.status_code == 200
        assert "郭庆明" in members.text
        assert "成功" in members.text
        assert "未收到结果" not in members.text


def test_admin_members_uses_remote_mcp_activity_when_install_result_is_missing(tmp_path):
    module = load_app(tmp_path)
    now = module.isoformat(module.utc_now())
    with closing(module.database()) as connection:
        connection.execute(
            """
            INSERT INTO users(
                username,real_name,company_name,password_hash,is_admin,created_at
            ) VALUES (?,?,?,?,1,?)
            """,
            (
                "owner",
                "管理员",
                "总部",
                module.password_hasher.hash("owner-password-123"),
                now,
            ),
        )
        member_id = int(
            connection.execute(
                """
                INSERT INTO users(
                    username,real_name,company_name,password_hash,created_at
                ) VALUES (?,?,?,?,?)
                """,
                (
                    "jinxi",
                    "金玺",
                    "共创集团",
                    module.password_hasher.hash("member-password-123"),
                    now,
                ),
            ).lastrowid
        )
        token_id = int(
            connection.execute(
                """
                INSERT INTO device_tokens(
                    user_id,label,token_prefix,token_hash,token_seed,
                    created_at,last_used_at
                ) VALUES (?,?,?,?,?,?,?)
                """,
                (
                    member_id,
                    "金玺",
                    "jtk_jinxi",
                    "jinxi-token-hash",
                    "jinxi-token-seed",
                    now,
                    now,
                ),
            ).lastrowid
        )
        connection.execute(
            """
            INSERT INTO api_usage(
                user_id,device_token_id,endpoint,method,activity_type,
                activity_name,counts_toward_usage,called_at
            ) VALUES (?,?,?,?,?,?,0,?)
            """,
            (
                member_id,
                token_id,
                "/mcp/",
                "POST",
                "mcp_connection",
                "MCP连接检测",
                now,
            ),
        )
        connection.commit()

    with TestClient(module.app) as client:
        login = client.post(
            "/login",
            data={"username": "owner", "password": "owner-password-123"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)
        members = client.get(
            "/admin/members",
            params={"member_query": "jinxi"},
        )
        assert members.status_code == 200
        assert "金玺" in members.text
        assert "已连接" in members.text
        assert "未收到结果" not in members.text
        detail = client.get(f"/admin/users/{member_id}")
        assert detail.status_code == 200
        assert "最后一次安装或连接结果" in detail.text
        assert "MCP 已连接，等待下次安装或更新自动回传版本" in detail.text
        assert "尚未收到结构化安装结果" not in detail.text


def test_admin_members_displays_installed_version_and_update_state(
    tmp_path,
    monkeypatch,
):
    module = load_app(tmp_path)
    release_guidance = module.public_release_guidance()
    release_guidance["workbuddy_version"] = "1.6.3"
    monkeypatch.setattr(
        module,
        "public_release_guidance",
        lambda: release_guidance,
    )
    now_value = module.utc_now()
    now = module.isoformat(now_value)
    old_time = module.isoformat(now_value - timedelta(days=2))
    with closing(module.database()) as connection:
        connection.execute(
            """
            INSERT INTO users(
                username,real_name,company_name,password_hash,is_admin,created_at
            ) VALUES (?,?,?,?,1,?)
            """,
            (
                "owner",
                "管理员",
                "总部",
                module.password_hasher.hash("owner-password-123"),
                now,
            ),
        )
        member_ids = {}
        for username, real_name in (
            ("current-member", "当前成员"),
            ("old-member", "旧版成员"),
            ("pending-member", "待安装成员"),
        ):
            member_ids[username] = int(
                connection.execute(
                    """
                    INSERT INTO users(
                        username,real_name,company_name,password_hash,created_at
                    ) VALUES (?,?,?,?,?)
                    """,
                    (
                        username,
                        real_name,
                        "共创集团",
                        module.password_hasher.hash("member-password-123"),
                        old_time,
                    ),
                ).lastrowid
            )

        current_enrollment_id = int(
            connection.execute(
                """
                INSERT INTO agent_enrollment_codes(
                    user_id,code_hash,created_at,expires_at,install_platform,
                    workbuddy_version
                ) VALUES (?,?,?,?,?,?)
                """,
                (
                    member_ids["current-member"],
                    "current-member-enrollment",
                    now,
                    now,
                    "macos",
                    "1.6.3",
                ),
            ).lastrowid
        )
        current_token_id = int(
            connection.execute(
                """
                INSERT INTO device_tokens(
                    user_id,label,token_prefix,token_hash,token_seed,created_at,
                    credential_kind,enrollment_id
                ) VALUES (?,?,?,?,?,?,'installation',?)
                """,
                (
                    member_ids["current-member"],
                    "macOS 远程 MCP",
                    "jtk_current",
                    "current-member-token-hash",
                    "current-member-token-seed",
                    now,
                    current_enrollment_id,
                ),
            ).lastrowid
        )
        connection.execute(
            """
            INSERT INTO api_usage(
                user_id,device_token_id,endpoint,method,activity_type,
                activity_name,counts_toward_usage,called_at
            ) VALUES (?,?,?,?,?,?,0,?)
            """,
            (
                member_ids["current-member"],
                current_token_id,
                "/mcp/",
                "POST",
                "mcp_connection",
                "MCP连接检测",
                now,
            ),
        )
        connection.execute(
            """
            INSERT INTO agent_enrollment_codes(
                user_id,code_hash,created_at,expires_at,install_platform,
                workbuddy_version,result_schema,result_ok,result_status,
                result_reported_at
            ) VALUES (?,?,?,?,?,?,?,1,'configured',?)
            """,
            (
                member_ids["old-member"],
                "old-member-enrollment",
                old_time,
                now,
                "windows",
                "1.6.2",
                "gongchuang-agent-result/v2",
                old_time,
            ),
        )
        connection.execute(
            """
            INSERT INTO agent_enrollment_codes(
                user_id,code_hash,created_at,expires_at,install_platform,
                workbuddy_version
            ) VALUES (?,?,?,?,?,?)
            """,
            (
                member_ids["pending-member"],
                "pending-member-enrollment",
                now,
                now,
                "windows",
                "1.6.3",
            ),
        )
        connection.commit()

    def member_row(page_text: str, member_id: int) -> str:
        match = re.search(
            rf'<tr><td><a class="record-link" href="/admin/users/{member_id}">.*?</tr>',
            page_text,
            re.DOTALL,
        )
        assert match is not None
        return match.group(0)

    with TestClient(module.app) as client:
        login = client.post(
            "/login",
            data={"username": "owner", "password": "owner-password-123"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)
        members = client.get("/admin/members")
        outdated = client.get("/admin/members", params={"member_query": "待更新"})

    assert members.status_code == 200
    current_row = member_row(members.text, member_ids["current-member"])
    assert "插件 V1.6.3" in current_row
    assert "连接自动识别版本" in current_row
    assert "最新版本" in current_row
    old_row = member_row(members.text, member_ids["old-member"])
    assert "插件 V1.6.2" in old_row
    assert "客户端安装回执" in old_row
    assert "待更新" in old_row
    pending_row = member_row(members.text, member_ids["pending-member"])
    assert "目标插件 V1.6.3" in pending_row
    assert "尚未确认安装" in pending_row
    assert f'href="/admin/users/{member_ids["current-member"]}"' not in outdated.text
    assert f'href="/admin/users/{member_ids["old-member"]}"' in outdated.text
    assert f'href="/admin/users/{member_ids["pending-member"]}"' not in outdated.text


def test_admin_ignores_legacy_manual_install_confirmation(tmp_path, monkeypatch):
    module = load_app(tmp_path)
    release_guidance = module.public_release_guidance()
    release_guidance["workbuddy_version"] = "1.6.3.1"
    monkeypatch.setattr(module, "public_release_guidance", lambda: release_guidance)
    now = module.isoformat(module.utc_now())
    with closing(module.database()) as connection:
        connection.execute(
            """
            INSERT INTO users(
                username,real_name,company_name,password_hash,is_admin,created_at
            ) VALUES (?,?,?,?,1,?)
            """,
            (
                "owner",
                "管理员",
                "总部",
                module.password_hasher.hash("owner-password-123"),
                now,
            ),
        )
        member_id = int(
            connection.execute(
                """
                INSERT INTO users(
                    username,real_name,company_name,password_hash,created_at
                ) VALUES (?,?,?,?,?)
                """,
                (
                    "legacy-manual-member",
                    "历史人工记录成员",
                    "共创集团",
                    module.password_hasher.hash("member-password-123"),
                    now,
                ),
            ).lastrowid
        )
        enrollment_id = int(
            connection.execute(
                """
                INSERT INTO agent_enrollment_codes(
                    user_id,code_hash,created_at,expires_at,confirmed_at,
                    install_platform,workbuddy_version,workbuddy_sha256,
                    result_schema,result_ok,result_status,result_reported_at
                ) VALUES (?,?,?,?,?,?,?,?,'gongchuang-admin-manual-install-result/v1',1,'configured',?)
                """,
                (
                    member_id,
                    "legacy-manual-enrollment",
                    now,
                    now,
                    now,
                    "macos",
                    "1.6.3.1",
                    "a" * 64,
                    now,
                ),
            ).lastrowid
        )
        connection.commit()

    with TestClient(module.app) as client:
        login = client.post(
            "/login",
            data={"username": "owner", "password": "owner-password-123"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)
        owner = module.session_user(login.cookies[module.SESSION_COOKIE])[0]
        members = client.get(
            "/admin/members",
            params={"member_query": "legacy-manual-member"},
        )
        detail = client.get(f"/admin/users/{member_id}")
        removed_route = client.post(
            f"/admin/users/{member_id}/installations/{enrollment_id}/manual-confirm",
            data={"csrf_token": owner["csrf_token"]},
        )

    assert "管理员确认版本" not in members.text
    assert "目标插件 V1.6.3.1" in members.text
    assert "确认手动安装" not in detail.text
    assert removed_route.status_code == 404


def test_admin_members_ignores_revoked_install_version_evidence(
    tmp_path,
    monkeypatch,
):
    module = load_app(tmp_path)
    release_guidance = module.public_release_guidance()
    release_guidance["workbuddy_version"] = "1.6.3"
    monkeypatch.setattr(
        module,
        "public_release_guidance",
        lambda: release_guidance,
    )
    now_value = module.utc_now()
    now = module.isoformat(now_value)
    old_time = module.isoformat(now_value - timedelta(days=10))
    revoked_time = module.isoformat(now_value - timedelta(days=9))
    with closing(module.database()) as connection:
        connection.execute(
            """
            INSERT INTO users(
                username,real_name,company_name,password_hash,is_admin,created_at
            ) VALUES (?,?,?,?,1,?)
            """,
            (
                "owner",
                "管理员",
                "总部",
                module.password_hasher.hash("owner-password-123"),
                now,
            ),
        )
        member_id = int(
            connection.execute(
                """
                INSERT INTO users(
                    username,real_name,company_name,password_hash,created_at
                ) VALUES (?,?,?,?,?)
                """,
                (
                    "revoked-member",
                    "已撤销旧版成员",
                    "共创集团",
                    module.password_hasher.hash("member-password-123"),
                    old_time,
                ),
            ).lastrowid
        )
        binding_id = int(
            connection.execute(
                """
                INSERT INTO device_bindings(
                    user_id,device_id_hash,device_id_prefix,device_name,
                    auth_method,first_bound_at,last_seen_at,installed_version,
                    installed_at,revoked_at,revoked_reason
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    member_id,
                    "revoked-device-hash",
                    "revoked-device",
                    "historical-device",
                    "device_signature",
                    old_time,
                    revoked_time,
                    "1.4.4",
                    old_time,
                    revoked_time,
                    "replaced",
                ),
            ).lastrowid
        )
        key_id = "jdk_revoked_version_evidence"
        connection.execute(
            """
            INSERT INTO device_keys(
                user_id,binding_id,key_id,public_key,platform,agent_host,
                created_at,last_verified_at,revoked_at,revoked_reason
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                member_id,
                binding_id,
                key_id,
                "revoked-public-key",
                "macos",
                "workbuddy",
                old_time,
                revoked_time,
                revoked_time,
                "replaced",
            ),
        )
        legacy_enrollment_id = int(
            connection.execute(
                """
                INSERT INTO agent_enrollment_codes(
                    user_id,code_hash,created_at,expires_at,install_platform,
                    workbuddy_version,result_schema,result_ok,result_status,
                    result_reported_at,registered_key_id
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    member_id,
                    "revoked-member-legacy-enrollment",
                    old_time,
                    revoked_time,
                    "macos",
                    "1.4.4",
                    "jiaotang-agent-result/v1",
                    1,
                    "configured",
                    old_time,
                    key_id,
                ),
            ).lastrowid
        )
        revoked_token_id = int(
            connection.execute(
                """
                INSERT INTO device_tokens(
                    user_id,label,token_prefix,token_hash,token_seed,created_at,
                    revoked_at,revoked_reason,credential_kind,enrollment_id
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    member_id,
                    "历史安装凭据",
                    "jtk_revoked",
                    "revoked-version-token-hash",
                    "revoked-version-token-seed",
                    old_time,
                    revoked_time,
                    "replaced",
                    "installation",
                    legacy_enrollment_id,
                ),
            ).lastrowid
        )
        connection.execute(
            """
            INSERT INTO api_usage(
                user_id,device_token_id,endpoint,method,activity_type,
                activity_name,counts_toward_usage,called_at
            ) VALUES (?,?,?,?,?,?,0,?)
            """,
            (
                member_id,
                revoked_token_id,
                "/mcp/",
                "POST",
                "mcp_connection",
                "历史 MCP 连接",
                revoked_time,
            ),
        )
        connection.execute(
            """
            INSERT INTO agent_enrollment_codes(
                user_id,code_hash,created_at,expires_at,install_platform,
                workbuddy_version
            ) VALUES (?,?,?,?,?,?)
            """,
            (
                member_id,
                "revoked-member-current-target",
                now,
                now,
                "macos",
                "1.6.3",
            ),
        )
        connection.commit()

    with TestClient(module.app) as client:
        login = client.post(
            "/login",
            data={"username": "owner", "password": "owner-password-123"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)
        members = client.get("/admin/members")

    row = re.search(
        rf'<tr><td><a class="record-link" href="/admin/users/{member_id}">.*?</tr>',
        members.text,
        re.DOTALL,
    )
    assert row is not None
    member_row = row.group(0)
    assert "插件 V1.4.4" not in member_row
    assert "目标插件 V1.6.3" in member_row
    assert "尚未确认安装" in member_row
    assert "待更新" not in member_row


def test_remote_mcp_connection_closes_installation_without_device_reporting(tmp_path):
    module = load_app(tmp_path)
    now = module.isoformat(module.utc_now())
    raw_token = ""
    with closing(module.database()) as connection:
        connection.execute(
            """
            INSERT INTO users(
                username,real_name,company_name,password_hash,is_admin,created_at
            ) VALUES (?,?,?,?,1,?)
            """,
            (
                "owner",
                "管理员",
                "总部",
                module.password_hasher.hash("owner-password-123"),
                now,
            ),
        )
        member_id = int(
            connection.execute(
                """
                INSERT INTO users(
                    username,real_name,company_name,password_hash,created_at
                ) VALUES (?,?,?,?,?)
                """,
                (
                    "remote-member",
                    "远程成员",
                    "共创集团",
                    module.password_hasher.hash("member-password-123"),
                    now,
                ),
            ).lastrowid
        )
        connection.execute(
            """
            INSERT INTO registration_authorizations(
                real_name,identity_code,status,user_id,created_at,registered_at
            ) VALUES (?,?,'registered',?,?,?)
            """,
            ("远程成员", "0811", member_id, now, now),
        )
        enrollment_id = int(
            connection.execute(
                """
                INSERT INTO agent_enrollment_codes(
                    user_id,code_hash,created_at,expires_at,install_platform
                ) VALUES (?,?,?,?,?)
                """,
                (member_id, "remote-enrollment", now, now, "macos"),
            ).lastrowid
        )
        token_seed = "remote-install-token-seed"
        raw_token = module.user_access_token(member_id, token_seed)
        token_id = int(
            connection.execute(
                """
                INSERT INTO device_tokens(
                    user_id,label,token_prefix,token_hash,token_seed,created_at,
                    credential_kind,enrollment_id
                ) VALUES (?,?,?,?,?,?,'installation',?)
                """,
                (
                    member_id,
                    "macOS 安装 · 待上报",
                    raw_token[:12],
                    module.token_hash(raw_token),
                    token_seed,
                    now,
                    enrollment_id,
                ),
            ).lastrowid
        )
        connection.commit()

    with TestClient(module.app) as client:
        ping = client.post(
            "/mcp/",
            headers={
                **api_headers(raw_token),
                "Accept": "application/json, text/event-stream",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}},
        )
        assert ping.status_code == 200

        login = client.post(
            "/login",
            data={"username": "owner", "password": "owner-password-123"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)
        access = client.get("/admin/health/access")
        detail = client.get(f"/admin/users/{member_id}")

    with closing(module.database()) as connection:
        token = connection.execute(
            "SELECT label,last_used_at FROM device_tokens WHERE id=?",
            (token_id,),
        ).fetchone()
        enrollment = connection.execute(
            """
            SELECT consumed_at,result_reported_at,result_status
            FROM agent_enrollment_codes WHERE id=?
            """,
            (enrollment_id,),
        ).fetchone()
        binding_count = connection.execute(
            "SELECT COUNT(*) FROM device_bindings WHERE user_id=?",
            (member_id,),
        ).fetchone()[0]

    assert token["label"] == "macOS 远程 MCP"
    assert token["last_used_at"] is not None
    assert enrollment["consumed_at"] is not None
    assert enrollment["result_reported_at"] is None
    assert enrollment["result_status"] is None
    assert binding_count == 0
    assert access.status_code == 200
    assert "接入方式" in access.text
    assert "远程 MCP" in access.text
    assert "已由服务端确认连接" in access.text
    assert "不采集设备名" in access.text
    assert "未上报" not in access.text
    assert detail.status_code == 200
    assert "服务端连接回执" in detail.text
    assert "MCP 已连接，等待下次安装或更新自动回传版本" in detail.text
    assert "访问凭据与接入方式" in detail.text
    assert "macOS 远程 MCP" in detail.text
    assert "待上报" not in detail.text


def test_unconnected_remote_mcp_is_waiting_not_unreported(tmp_path):
    module = load_app(tmp_path)
    now = module.isoformat(module.utc_now())
    with closing(module.database()) as connection:
        connection.execute(
            """
            INSERT INTO users(
                username,real_name,company_name,password_hash,is_admin,created_at
            ) VALUES (?,?,?,?,1,?)
            """,
            (
                "owner",
                "管理员",
                "总部",
                module.password_hasher.hash("owner-password-123"),
                now,
            ),
        )
        member_id = int(
            connection.execute(
                """
                INSERT INTO users(
                    username,real_name,company_name,password_hash,created_at
                ) VALUES (?,?,?,?,?)
                """,
                (
                    "waiting-member",
                    "待连接成员",
                    "共创集团",
                    module.password_hasher.hash("member-password-123"),
                    now,
                ),
            ).lastrowid
        )
        enrollment_id = int(
            connection.execute(
                """
                INSERT INTO agent_enrollment_codes(
                    user_id,code_hash,created_at,expires_at,install_platform
                ) VALUES (?,?,?,?,?)
                """,
                (member_id, "waiting-enrollment", now, now, "windows"),
            ).lastrowid
        )
        connection.execute(
            """
            INSERT INTO device_tokens(
                user_id,label,token_prefix,token_hash,token_seed,created_at,
                credential_kind,enrollment_id
            ) VALUES (?,?,?,?,?,?,'installation',?)
            """,
            (
                member_id,
                "Windows 安装 · 待上报",
                "jtk_waiting",
                "waiting-token-hash",
                "waiting-token-seed",
                now,
                enrollment_id,
            ),
        )
        connection.commit()

    with TestClient(module.app) as client:
        login = client.post(
            "/login",
            data={"username": "owner", "password": "owner-password-123"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)
        access = client.get("/admin/health/access")
        detail = client.get(f"/admin/users/{member_id}")

    assert access.status_code == 200
    assert "尚未建立连接" in access.text
    assert "不采集设备名" in access.text
    assert "未上报" not in access.text
    assert detail.status_code == 200
    assert "Windows 安装凭据" in detail.text
    assert "尚未检测到 MCP 连接" in detail.text
    assert "待上报" not in detail.text


def test_admin_can_filter_feedback(tmp_path):
    module = load_app(tmp_path)
    now = module.isoformat(module.utc_now())
    with closing(module.database()) as connection:
        connection.execute(
            "INSERT INTO users(username, real_name, password_hash, is_admin, created_at) VALUES (?, ?, ?, 1, ?)",
            ("owner", "管理员", module.password_hasher.hash("owner-password-123"), now),
        )
        member_id = connection.execute(
            "INSERT INTO users(username, real_name, password_hash, created_at) VALUES (?, ?, ?, ?)",
            ("lisi", "李四", module.password_hasher.hash("member-password-123"), now),
        ).lastrowid
        connection.executemany(
            """
            INSERT INTO feedback_messages(user_id,category,subject,content,status,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            [
                (member_id, "bug", "登录页按钮失灵", "点击登录没有反应", "pending", now, now),
                (member_id, "suggestion", "建议增加暗色模式", "夜间使用刺眼", "resolved", now, now),
            ],
        )
        connection.commit()

    with TestClient(module.app) as client:
        login = client.post(
            "/login",
            data={"username": "owner", "password": "owner-password-123"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)

        by_status = client.get("/feedback", params={"feedback_status": "pending"})
        assert by_status.status_code == 200
        assert "登录页按钮失灵" in by_status.text
        assert "建议增加暗色模式" not in by_status.text

        by_query = client.get("/feedback", params={"feedback_query": "暗色"})
        assert "建议增加暗色模式" in by_query.text
        assert "登录页按钮失灵" not in by_query.text

        no_match = client.get("/feedback", params={"feedback_query": "不存在"})
        assert "未找到匹配的留言" in no_match.text


def test_admin_can_search_knowledge_trash(tmp_path):
    module = load_app(tmp_path)
    now = module.isoformat(module.utc_now())
    with closing(module.database()) as connection:
        owner_id = connection.execute(
            "INSERT INTO users(username, real_name, password_hash, is_admin, created_at) VALUES (?, ?, ?, 1, ?)",
            ("owner", "管理员", module.password_hasher.hash("owner-password-123"), now),
        ).lastrowid
        connection.executemany(
            """
            INSERT INTO knowledge_document_trash(document_id,document_payload,status,deleted_by,deleted_at)
            VALUES (?,?,?,?,?)
            """,
            [
                (101, json.dumps({"title": "高新技术企业认定管理办法"}), "trashed", owner_id, now),
                (102, json.dumps({"title": "专精特新申报指南"}), "trashed", owner_id, now),
            ],
        )
        connection.commit()

    with TestClient(module.app) as client:
        login = client.post(
            "/login",
            data={"username": "owner", "password": "owner-password-123"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)

        by_title = client.get("/admin/knowledge-trash", params={"trash_query": "高新技术"})
        assert by_title.status_code == 200
        assert "高新技术企业认定管理办法" in by_title.text
        assert "专精特新申报指南" not in by_title.text

        no_match = client.get("/admin/knowledge-trash", params={"trash_query": "不存在"})
        assert "未找到匹配的回收记录" in no_match.text


def test_admin_can_search_member_trash(tmp_path):
    module = load_app(tmp_path)
    now = module.isoformat(module.utc_now())
    with closing(module.database()) as connection:
        connection.execute(
            "INSERT INTO users(username, real_name, password_hash, is_admin, created_at) VALUES (?, ?, ?, 1, ?)",
            ("owner", "管理员", module.password_hasher.hash("owner-password-123"), now),
        )
        connection.executemany(
            "INSERT INTO users(username, real_name, password_hash, created_at, deleted_at) VALUES (?, ?, ?, ?, ?)",
            [
                ("zhangsan", "张三", module.password_hasher.hash("member-password-123"), now, now),
                ("lisi", "李四", module.password_hasher.hash("member-password-123"), now, now),
            ],
        )
        connection.execute(
            "INSERT INTO registration_authorizations(real_name,identity_code,status,created_at,deleted_at) VALUES (?,?,?,?,?)",
            ("王五", "9999", "pending", now, now),
        )
        connection.commit()

    with TestClient(module.app) as client:
        login = client.post(
            "/login",
            data={"username": "owner", "password": "owner-password-123"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)

        by_name = client.get("/admin/members/trash", params={"trash_query": "张三"})
        assert by_name.status_code == 200
        assert "张三" in by_name.text
        assert "李四" not in by_name.text

        by_tail = client.get("/admin/members/trash", params={"trash_query": "9999"})
        assert "王五" in by_tail.text

        no_match = client.get("/admin/members/trash", params={"trash_query": "不存在"})
        assert "未找到匹配的账号" in no_match.text
        assert "未找到匹配的注册权限" in no_match.text


def test_registration_rejects_name_outside_authorized_list(tmp_path):
    module = load_app(tmp_path)
    with closing(module.database()) as connection:
        connection.execute(
            "INSERT INTO users(username, password_hash, is_admin, created_at) VALUES (?, ?, 1, ?)",
            ("owner", module.password_hasher.hash("owner-password-123"), module.isoformat(module.utc_now())),
        )
        connection.commit()
    with TestClient(module.app) as client:
        response = client.post(
            "/register",
            data={
                "username": "member-two",
                "real_name": "李小红",
                "identity_code": "0002",
                "company_name": "共创集团",
                "password": "member-password-123",
                "confirm_password": "member-password-123",
            },
        )
        assert response.status_code == 403
        assert "姓名或企微手机号后四位未获得注册权限" in response.text


def test_api_rejects_missing_token(tmp_path):
    module = load_app(tmp_path)
    with TestClient(module.app) as client:
        response = client.get("/v1/me")
        assert response.status_code == 401


def test_init_database_reconciles_legacy_active_credentials_and_enforces_one_active(
    tmp_path,
):
    module = load_app(tmp_path)
    with closing(module.database()) as connection:
        connection.execute(
            """
            INSERT INTO users(username,password_hash,created_at)
            VALUES (?,?,?)
            """,
            (
                "legacy-duplicate-tokens",
                module.password_hasher.hash("owner-password-123"),
                "2026-08-01T00:00:00Z",
            ),
        )
        user_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
        connection.execute("DROP INDEX device_tokens_one_active_per_user")
        fixtures = (
            (
                "recent-never-used",
                "legacy-seed-new",
                "2026-08-12T00:00:00Z",
                None,
                "2026-08-12T00:00:00Z",
            ),
            (
                "latest-real-use",
                "legacy-seed-used-latest",
                "2026-08-02T00:00:00Z",
                "2026-08-11T12:00:00Z",
                "2026-08-02T00:00:00Z",
            ),
            (
                "older-real-use",
                "legacy-seed-used-older",
                "2026-08-03T00:00:00Z",
                "2026-08-10T12:00:00Z",
                "2026-08-03T00:00:00Z",
            ),
        )
        for label, seed, created_at, last_used_at, activated_at in fixtures:
            raw_token = module.user_access_token(user_id, seed)
            connection.execute(
                """
                INSERT INTO device_tokens(
                    user_id,label,token_prefix,token_hash,token_seed,created_at,
                    last_used_at,credential_kind,activation_state,activated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    user_id,
                    label,
                    raw_token[:12],
                    module.token_hash(raw_token),
                    seed,
                    created_at,
                    last_used_at,
                    "personal",
                    "active",
                    activated_at,
                ),
            )
        connection.commit()

    module.init_database()

    with closing(module.database()) as connection:
        active = connection.execute(
            """
            SELECT label,token_seed
            FROM device_tokens
            WHERE user_id=? AND revoked_at IS NULL AND activation_state='active'
            """,
            (user_id,),
        ).fetchall()
        assert [row["label"] for row in active] == ["latest-real-use"]
        assert connection.execute(
            """
            SELECT COUNT(*)
            FROM device_tokens
            WHERE user_id=?
              AND revoked_reason='single_active_credential_reconciliation'
              AND revoked_by='system'
            """,
            (user_id,),
        ).fetchone()[0] == 2
        index_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name=?",
            ("device_tokens_one_active_per_user",),
        ).fetchone()["sql"]
        assert "UNIQUE INDEX" in index_sql
        assert "activation_state='active'" in index_sql
        duplicate_token = module.user_access_token(user_id, "duplicate-seed")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO device_tokens(
                    user_id,label,token_prefix,token_hash,token_seed,created_at,
                    credential_kind,activation_state,activated_at
                ) VALUES (?,?,?,?,?,?,'personal','active',?)
                """,
                (
                    user_id,
                    "forbidden-second-active",
                    duplicate_token[:12],
                    module.token_hash(duplicate_token),
                    "duplicate-seed",
                    "2026-08-12T01:00:00Z",
                    "2026-08-12T01:00:00Z",
                ),
            )

    manual_token = module.ensure_personal_access_token(user_id, "手动配置复用")
    assert manual_token == module.user_access_token(user_id, str(active[0]["token_seed"]))
    with closing(module.database()) as connection:
        assert connection.execute(
            """
            SELECT COUNT(*) FROM device_tokens
            WHERE user_id=? AND revoked_at IS NULL AND activation_state='active'
            """,
            (user_id,),
        ).fetchone()[0] == 1


def test_mcp_anomaly_observation_warns_admin_without_revoking_token(tmp_path):
    module = load_app(tmp_path)
    with TestClient(module.app) as client:
        setup = client.post(
            "/setup",
            data={
                "setup_key": "setup-secret",
                "username": "owner",
                "password": "owner-password-123",
            },
        )
        assert setup.status_code == 200
        login = client.post(
            "/login",
            data={"username": "owner", "password": "owner-password-123"},
        )
        assert login.status_code == 200

        with closing(module.database()) as connection:
            owner_id = int(
                connection.execute(
                    "SELECT id FROM users WHERE username='owner'"
                ).fetchone()["id"]
            )
        module.ensure_personal_access_token(owner_id, "MCP异常观测测试")
        with closing(module.database()) as connection:
            api_user = connection.execute(
                """
                SELECT users.id,device_tokens.id AS device_token_id
                FROM users
                JOIN device_tokens ON device_tokens.user_id=users.id
                WHERE users.id=? AND device_tokens.revoked_at IS NULL
                  AND device_tokens.activation_state='active'
                """,
                (owner_id,),
            ).fetchone()

        samples = (
            ("203.0.113.10", "WorkBuddy/macOS"),
            ("198.51.100.20", "WorkBuddy/Windows"),
        )
        for client_ip, user_agent in samples:
            module.record_api_usage(
                api_user,
                "/mcp",
                "POST",
                "mcp_search",
                "knowledge_search",
                True,
                client_ip=client_ip,
                user_agent=user_agent,
            )

        with closing(module.database()) as connection:
            assert module.build_mcp_security_alerts(connection) == []
            observations = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM mcp_access_observations ORDER BY id"
                ).fetchall()
            ]
        assert len(observations) == 2
        assert all(len(item["network_fingerprint"]) == 64 for item in observations)
        assert all(item["network_family"] == "ipv4" for item in observations)
        assert "203.0.113.10" not in json.dumps(observations)
        assert "198.51.100.20" not in json.dumps(observations)

        for client_ip, user_agent in samples:
            module.record_api_usage(
                api_user,
                "/mcp",
                "POST",
                "mcp_search",
                "knowledge_search",
                True,
                client_ip=client_ip,
                user_agent=user_agent,
            )

        with closing(module.database()) as connection:
            alerts = module.build_mcp_security_alerts(connection)
            active_token = connection.execute(
                """
                SELECT revoked_at,activation_state
                FROM device_tokens WHERE id=?
                """,
                (int(api_user["device_token_id"]),),
            ).fetchone()
        assert len(alerts) == 1
        assert alerts[0]["level"] == "high"
        assert "短时多网络并发" in alerts[0]["title"]
        assert "仅预警，未自动吊销" in alerts[0]["detail"]
        assert active_token["revoked_at"] is None
        assert active_token["activation_state"] == "active"

        reconciled_seed = "historical-reconciled-fixture"
        reconciled_token = module.user_access_token(owner_id, reconciled_seed)
        with closing(module.database()) as connection:
            connection.execute(
                """
                INSERT INTO device_tokens(
                    user_id,label,token_prefix,token_hash,token_seed,created_at,
                    revoked_at,revoked_reason,revoked_by,credential_kind,
                    activation_state,activated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,'installation','active',?)
                """,
                (
                    owner_id,
                    "历史重复测试凭据",
                    reconciled_token[:12],
                    module.token_hash(reconciled_token),
                    reconciled_seed,
                    module.isoformat(module.utc_now()),
                    module.isoformat(module.utc_now()),
                    "single_active_credential_reconciliation",
                    "system",
                    module.isoformat(module.utc_now()),
                ),
            )
            connection.commit()

        access = client.get("/admin/health/access")
        assert access.status_code == 200
        assert "MCP 异常使用预警" in access.text
        assert "1 项 · 仅预警，不自动吊销" in access.text
        assert "不保存原始 IP" in access.text
        assert "吊销依据" in access.text
        assert "历史重复凭据归并" in access.text


def test_public_machine_contracts_use_gongchuang_brand(tmp_path):
    module = load_app(tmp_path)
    assert module.build_provenance_payload()["schema"] == (
        "gongchuang-build-provenance/v1"
    )


def test_v150_one_step_install_issues_per_install_token_and_accepts_bearer_only(
    tmp_path,
    monkeypatch,
):
    module = load_app(tmp_path)
    platform_artifacts = {}
    for platform in ("macos", "windows"):
        workbuddy_package = tmp_path / f"workbuddy-{platform}-v1.5.0.zip"
        workbuddy_package.write_bytes(f"workbuddy-{platform}-v1.5.0".encode())
        platform_artifacts[platform] = {
            "file_path": str(workbuddy_package),
            "file_name": workbuddy_package.name,
            "sha256": hashlib.sha256(workbuddy_package.read_bytes()).hexdigest(),
            "target": platform,
            "version": "1.5.0",
        }
    monkeypatch.setattr(
        module,
        "latest_skill_artifact",
        lambda target: dict(platform_artifacts[target]) if target in platform_artifacts else None,
    )
    monkeypatch.setattr(
        module,
        "workbuddy_artifact_is_simple_remote_mcp",
        lambda candidate: bool(candidate),
    )
    with TestClient(module.app) as client:
        client.post(
            "/setup",
            data={
                "setup_key": "setup-secret",
                "username": "owner",
                "password": "owner-password-123",
            },
        )
        login = client.post(
            "/login",
            data={"username": "owner", "password": "owner-password-123"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)
        user = module.session_user(login.cookies[module.SESSION_COOKIE])[0]
        original_guide = client.get("/mcp-guide")
        original_token = re.search(
            r"jtk_[A-Za-z0-9_-]+", original_guide.text
        ).group(0)
        assert client.get(
            "/v1/me",
            headers={"Authorization": f"Bearer {original_token}"},
        ).status_code == 200

        access = client.get("/access")
        assert "一键安装" in access.text
        assert access.text.count("data-copy-agent-bootstrap") >= 2
        assert 'data-agent-platform="macos"' in access.text
        assert 'data-agent-platform="windows"' in access.text
        skills = client.get("/skills")
        assert skills.status_code == 200
        assert "一键安装" in skills.text
        assert skills.text.count("data-copy-agent-bootstrap") >= 2
        assert "只替换" in skills.text
        assert "knowledge_service_status" in skills.text
        assert "data-copy-agent-binding" not in skills.text
        assert "第三步 · 执行 bootstrap" not in skills.text
        assert "设备登记" not in skills.text
        assert "设备签名验证" not in skills.text
        first = client.post(
            "/agent-bootstrap-codes",
            data={"csrf_token": user["csrf_token"], "platform": "macos"},
        )
        assert first.status_code == 200
        assert first.json()["platform"] == "macos"
        assert first.json()["hook_adapter"] == "workbuddy-macos"
        prompt = first.json()["prompt"]
        assert "macOS Hook 启动适配器" in prompt
        assert "`~/.workbuddy/mcp.json`" in prompt
        assert "`~/.workbuddy/.mcp.json`" in prompt
        assert r"%USERPROFILE%\.workbuddy" not in prompt
        assert "Windows Hook 启动适配器" not in prompt
        enrollment_code = re.search(
            r"/v1/agent-install/(jbe_[A-Za-z0-9_-]+)/workbuddy/download",
            prompt,
        ).group(1)
        first_attestation = re.search(
            r'"X-Gongchuang-Install-Attestation": "(gcia1\.[A-Za-z0-9_.-]+)"',
            prompt,
        ).group(1)
        assert module.verified_runtime_install_attestation(
            first_attestation,
            user_id=int(user["id"]),
        )
        first_token = re.search(r"jtk_[A-Za-z0-9_-]+", prompt).group(0)
        assert client.get(
            "/v1/me",
            headers={"Authorization": f"Bearer {first_token}"},
        ).status_code == 403
        assert client.get(
            "/v1/me",
            headers={"Authorization": f"Bearer {original_token}"},
        ).status_code == 200
        protocol = client.get(f"/v1/agent-install/{enrollment_code}")
        assert protocol.status_code == 200
        assert protocol.json()["schema"] == "gongchuang-agent-install/v2"
        assert protocol.headers["content-type"].startswith(
            "application/vnd.gongchuang.agent-install+json"
        )
        assert protocol.json()["platform"] == {
            "id": "macos",
            "label": "macOS",
            "hook_adapter": "workbuddy-macos",
            "pinned": True,
        }
        assert protocol.json()["installation"]["platform_adapter"] == (
            "workbuddy-macos"
        )
        assert protocol.json()["result_reporting"]["schema"] == (
            "gongchuang-agent-result/v2"
        )
        assert protocol.json()["result_reporting"]["required_on_completion"] is True
        assert protocol.json()["result_reporting"]["url"].endswith(
            f"/v1/agent-install-result/{enrollment_code}"
        )
        mismatch = client.get(
            f"/v1/agent-install/{enrollment_code}?platform=windows"
        )
        assert mismatch.status_code == 409
        second = client.post(
            "/agent-bootstrap-codes",
            data={"csrf_token": user["csrf_token"], "platform": "windows"},
        )
        assert second.status_code == 200
        assert second.json()["platform"] == "windows"
        assert second.json()["hook_adapter"] == "workbuddy-windows"
        windows_prompt = second.json()["prompt"]
        assert "Windows 原生 EXE Hook 适配器" in windows_prompt
        assert r"`%USERPROFILE%\.workbuddy\mcp.json`" in windows_prompt
        assert r"`%USERPROFILE%\.workbuddy\.mcp.json`" in windows_prompt
        assert "`~/.workbuddy" not in windows_prompt
        assert "macOS Hook 启动适配器" not in windows_prompt
        assert "workbuddy_behavior_hook_windows.exe" in windows_prompt
        assert "不得改用 PowerShell、CMD、Python" in windows_prompt
        assert first.headers["cache-control"] == "no-store"
        assert first.json()["phase"] == "install_ready"
        assert "V1.5.0" in prompt
        expected_skill_count = len(module.skill_catalog_payload()["skills"])
        assert f"{expected_skill_count} 项 Skills" in prompt
        assert "只替换当前用户配置中的 `mcpServers.jiaotang-kb`" in prompt
        assert "保留所有其他 MCP 条目" in prompt
        assert "文件名是不带点前缀的 `mcp.json`" in prompt
        assert "`~/.workbuddy/.mcp.json`" in prompt
        assert "禁止读取、修改或覆盖" in prompt
        assert "只合并 `jiaotang-kb`" in prompt
        assert "plugin-backups/gongchuang-<旧版本>-<时间戳>" in prompt
        assert "位于 plugins 与 plugins/marketplaces 之外" in prompt
        assert "最终只能保留一个" in prompt
        assert "移入系统回收站" in prompt
        assert "不得永久删除" in prompt
        assert "同时检查当前用户目录下" in prompt
        assert "`~/.workbuddy` 与 `~/.codebuddy`" in prompt
        assert "不含 `.mcp.json`、`bin` 或 `mcp`" in prompt
        assert "手动点击信任" in prompt
        assert "不得尝试绕过宿主安全确认" in prompt
        assert "只重载 WorkBuddy 一次" in prompt
        assert "knowledge_service_status" in prompt
        assert "connected: true" in prompt
        assert "不可变发布产物" in prompt
        assert "不得修改、重写、转码、格式化或补丁处理" in prompt
        assert "不得添加权限绕过参数" in prompt
        assert "移动旧版之前" in prompt
        assert "package_mutated=true" in prompt
        assert "PACKAGE_MUTATION_DETECTED" in prompt
        assert "WINDOWS_NATIVE_HOOK_BLOCKED" in prompt
        assert "rollback_restored" in prompt
        assert f"/v1/agent-install-result/{enrollment_code}" in prompt
        assert "gongchuang-agent-result/v2" in prompt
        assert "installed_version" in prompt
        assert "installed_package_sha256" in prompt
        assert "VERSION_RECEIPT_FAILED" in prompt
        assert "欢迎评价这套Skills插件包" in prompt.replace(" ", "")
        assert "查看常用指令" in prompt
        assert "专精特新前期评估与后期体检" in prompt
        assert "企业分析报告 A 标准版" in prompt
        assert "金税四期分析报告" in prompt
        for capability_group in (
            "总控与配置",
            "知识与证据",
            "企业与项目",
            "专利专业",
            "交付与质检",
            "治理与进化",
        ):
            assert capability_group in prompt
        for capability in (
            "政策现行性与历史资料检索",
            "项目匹配和单项目可行性",
            "高企预评估与申请书撰写",
            "产业链定位",
            "专利检索布局/FTO/交底与申请文件核稿",
            "申报材料撰写/版本对比/一致性检查",
            "证据台账与交付归档",
        ):
            assert capability in prompt
        suite = json.loads(
            (module.SKILL_SOURCE_DIR / "suite-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        graph = json.loads(
            (module.SKILL_SOURCE_DIR / "skill-call-graph.json").read_text(
                encoding="utf-8"
            )
        )
        grouped_skills = [
            skill_name
            for group_skills in graph["groups"].values()
            for skill_name in group_skills
        ]
        assert len(suite["skills"]) == 50
        assert len(grouped_skills) == len(set(grouped_skills)) == 50
        assert set(grouped_skills) == set(suite["skills"])
        second_token = re.search(
            r"jtk_[A-Za-z0-9_-]+", windows_prompt
        ).group(0)
        second_attestation = re.search(
            r'"X-Gongchuang-Install-Attestation": "(gcia1\.[A-Za-z0-9_.-]+)"',
            windows_prompt,
        ).group(1)
        assert first_token != second_token
        assert client.get(
            "/v1/me",
            headers={"Authorization": f"Bearer {second_token}"},
        ).status_code == 403
        assert client.get(
            "/v1/me",
            headers={"Authorization": f"Bearer {first_token}"},
        ).status_code == 401
        assert client.get(
            "/v1/me",
            headers={"Authorization": f"Bearer {original_token}"},
        ).status_code == 200
        second_enrollment_code = re.search(
            r"/v1/agent-install/(jbe_[A-Za-z0-9_-]+)/workbuddy/download",
            windows_prompt,
        ).group(1)
        windows_protocol = client.get(
            f"/v1/agent-install/{second_enrollment_code}"
        )
        assert windows_protocol.status_code == 200
        status_response = client.post(
            "/mcp/",
            headers={
                **api_headers(second_token),
                module.RUNTIME_INSTALL_ATTESTATION_HEADER: second_attestation,
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            json={
                "jsonrpc": "2.0",
                "id": 81,
                "method": "tools/call",
                "params": {
                    "name": "knowledge_service_status",
                    "arguments": {},
                },
            },
        )
        assert status_response.status_code == 200
        assert status_response.json()["result"]["structuredContent"]["connected"] is True
        assert client.get(
            "/v1/me",
            headers={"Authorization": f"Bearer {second_token}"},
        ).status_code == 200
        assert client.get(
            "/v1/me",
            headers={"Authorization": f"Bearer {original_token}"},
        ).status_code == 401
        with closing(module.database()) as connection:
            automatic_receipt = connection.execute(
                """
                SELECT result_schema,result_ok,result_status,result_host
                FROM agent_enrollment_codes WHERE code_hash=?
                """,
                (module.token_hash(second_enrollment_code),),
            ).fetchone()
        assert automatic_receipt["result_schema"] == module.RUNTIME_INSTALL_RESULT_SCHEMA
        assert automatic_receipt["result_ok"] == 1
        assert automatic_receipt["result_status"] == "configured"
        assert automatic_receipt["result_host"] == "WorkBuddy MCP 自动回传"
        mismatched_report = client.post(
            f"/v1/agent-install-result/{second_enrollment_code}",
            json={
                "schema": "gongchuang-agent-result/v2",
                "ok": True,
                "status": "configured",
                "installed_version": "1.4.9",
                "installed_package_sha256": "0" * 64,
                "user_message": "配置成功",
                "platform": "Windows",
                "activation_required": False,
            },
        )
        assert mismatched_report.status_code == 422
        reported = client.post(
            f"/v1/agent-install-result/{second_enrollment_code}",
            json={
                "schema": "gongchuang-agent-result/v2",
                "ok": True,
                "status": "configured",
                "installed_version": windows_protocol.json()["release"]["version"],
                "installed_package_sha256": windows_protocol.json()["release"][
                    "sha256"
                ],
                "user_message": "配置成功",
                "next_action": None,
                "platform": "Windows",
                "activation_required": False,
            },
        )
        assert reported.status_code == 200

        guide = client.get("/mcp-guide")
        assert guide.headers["cache-control"] == "private, no-store"
        guide_token = re.search(r"jtk_[A-Za-z0-9_-]+", guide.text).group(0)
        assert guide_token == second_token
        assert "Bearer 你的个人Token" not in guide.text
        assert r"%USERPROFILE%\.workbuddy\mcp.json" in guide.text
        assert "~/.workbuddy/mcp.json" in guide.text
        assert ".workbuddy/.mcp.json" in guide.text
        assert "手动信任" in guide.text
        assert client.get(
            "/v1/me",
            headers={"Authorization": f"Bearer {guide_token}"},
        ).status_code == 200
        with closing(module.database()) as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM device_tokens "
                "WHERE user_id=? AND revoked_at IS NULL",
                (int(user["id"]),),
            ).fetchone()[0] == 1
            assert connection.execute(
                """
                SELECT COUNT(*) FROM device_tokens
                WHERE user_id=? AND credential_kind='installation'
                  AND revoked_at IS NULL AND activation_state='active'
                """,
                (int(user["id"]),),
            ).fetchone()[0] == 1
            assert connection.execute(
                """
                SELECT COUNT(*) FROM device_tokens
                WHERE user_id=? AND revoked_reason='superseded_by_new_credential'
                """,
                (int(user["id"]),),
            ).fetchone()[0] == 1
            assert connection.execute(
                """
                SELECT label FROM device_tokens
                WHERE enrollment_id=(
                    SELECT id FROM agent_enrollment_codes WHERE code_hash=?
                )
                """,
                (module.token_hash(second_enrollment_code),),
            ).fetchone()["label"] == "Windows 远程 MCP"
            stored_receipt = connection.execute(
                """
                SELECT result_schema,result_ok,result_status,workbuddy_version,
                       workbuddy_sha256
                FROM agent_enrollment_codes WHERE code_hash=?
                """,
                (module.token_hash(second_enrollment_code),),
            ).fetchone()
            assert stored_receipt["result_schema"] == "gongchuang-agent-result/v2"
            assert stored_receipt["result_ok"] == 1
            assert stored_receipt["result_status"] == "configured"
            assert stored_receipt["workbuddy_version"] == (
                windows_protocol.json()["release"]["version"]
            )
            assert stored_receipt["workbuddy_sha256"] == (
                windows_protocol.json()["release"]["sha256"]
            )


def test_runtime_install_attestation_updates_version_with_personal_token(
    tmp_path,
    monkeypatch,
):
    module = load_app(tmp_path)
    release_guidance = module.public_release_guidance()
    release_guidance["workbuddy_version"] = "1.6.3.1"
    monkeypatch.setattr(module, "public_release_guidance", lambda: release_guidance)
    with TestClient(module.app) as client:
        client.post(
            "/setup",
            data={
                "setup_key": "setup-secret",
                "username": "owner",
                "password": "owner-password-123",
            },
        )
        login = client.post(
            "/login",
            data={"username": "owner", "password": "owner-password-123"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)
        user = module.session_user(login.cookies[module.SESSION_COOKIE])[0]
        personal_token = re.search(
            r"jtk_[A-Za-z0-9_-]+",
            client.get("/mcp-guide").text,
        ).group(0)
        now = module.isoformat(module.utc_now())
        package_sha256 = "c" * 64
        with closing(module.database()) as connection:
            enrollment_id = int(
                connection.execute(
                    """
                    INSERT INTO agent_enrollment_codes(
                        user_id,code_hash,created_at,expires_at,confirmed_at,
                        install_platform,workbuddy_version,workbuddy_sha256
                    ) VALUES (?,?,?,?,?,?,?,?)
                    """,
                    (
                        int(user["id"]),
                        "personal-runtime-observation",
                        now,
                        now,
                        now,
                        "macos",
                        "1.6.3.1",
                        package_sha256,
                    ),
                ).lastrowid
            )
            connection.commit()
        attestation = module.runtime_install_attestation(
            user_id=int(user["id"]),
            enrollment_id=enrollment_id,
            version="1.6.3.1",
            package_sha256=package_sha256,
            platform="macos",
        )
        status_payload = {
            "jsonrpc": "2.0",
            "id": 91,
            "method": "tools/call",
            "params": {
                "name": "knowledge_service_status",
                "arguments": {},
            },
        }
        tampered = f"{attestation[:-1]}{'A' if attestation[-1] != 'A' else 'B'}"
        rejected_observation = client.post(
            "/mcp/",
            headers={
                **api_headers(personal_token),
                module.RUNTIME_INSTALL_ATTESTATION_HEADER: tampered,
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            json=status_payload,
        )
        assert rejected_observation.status_code == 200
        with closing(module.database()) as connection:
            assert connection.execute(
                "SELECT result_reported_at FROM agent_enrollment_codes WHERE id=?",
                (enrollment_id,),
            ).fetchone()["result_reported_at"] is None

        status_payload["id"] = 92
        observed = client.post(
            "/mcp/",
            headers={
                **api_headers(personal_token),
                module.RUNTIME_INSTALL_ATTESTATION_HEADER: attestation,
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            json=status_payload,
        )
        assert observed.status_code == 200
        members = client.get(
            "/admin/members",
            params={"member_query": "owner"},
        )

    with closing(module.database()) as connection:
        result = connection.execute(
            """
            SELECT result_schema,result_ok,result_status,result_host,
                   result_platform,result_reported_at
            FROM agent_enrollment_codes WHERE id=?
            """,
            (enrollment_id,),
        ).fetchone()
        active_personal = connection.execute(
            """
            SELECT credential_kind,revoked_at FROM device_tokens
            WHERE token_hash=?
            """,
            (module.token_hash(personal_token),),
        ).fetchone()
    assert result["result_schema"] == module.RUNTIME_INSTALL_RESULT_SCHEMA
    assert result["result_ok"] == 1
    assert result["result_status"] == "configured"
    assert result["result_host"] == "WorkBuddy MCP 自动回传"
    assert result["result_platform"] == "macOS"
    assert result["result_reported_at"]
    assert active_personal["credential_kind"] == "personal"
    assert active_personal["revoked_at"] is None
    assert "插件 V1.6.3.1" in members.text
    assert "客户端自动识别版本" in members.text
    assert "管理员确认版本" not in members.text


def test_pending_installation_credential_preserves_active_token_when_status_is_disconnected_or_expired(
    tmp_path,
    monkeypatch,
):
    module = load_app(tmp_path)
    workbuddy_package = tmp_path / "workbuddy-macos-v1.5.0.zip"
    workbuddy_package.write_bytes(b"workbuddy-macos-v1.5.0")
    artifact = {
        "file_path": str(workbuddy_package),
        "file_name": workbuddy_package.name,
        "sha256": hashlib.sha256(workbuddy_package.read_bytes()).hexdigest(),
        "target": "macos",
        "version": "1.5.0",
    }
    monkeypatch.setattr(
        module,
        "latest_skill_artifact",
        lambda target: dict(artifact) if target == "macos" else None,
    )
    monkeypatch.setattr(
        module,
        "workbuddy_artifact_is_simple_remote_mcp",
        lambda candidate: bool(candidate),
    )

    with TestClient(module.app) as client:
        client.post(
            "/setup",
            data={
                "setup_key": "setup-secret",
                "username": "owner",
                "password": "owner-password-123",
            },
        )
        login = client.post(
            "/login",
            data={"username": "owner", "password": "owner-password-123"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)
        user = module.session_user(login.cookies[module.SESSION_COOKIE])[0]
        original_token = re.search(
            r"jtk_[A-Za-z0-9_-]+", client.get("/mcp-guide").text
        ).group(0)
        pending_response = client.post(
            "/agent-bootstrap-codes",
            data={"csrf_token": user["csrf_token"], "platform": "macos"},
        )
        pending_token = re.search(
            r"jtk_[A-Za-z0-9_-]+", pending_response.json()["prompt"]
        ).group(0)
        enrollment_code = re.search(
            r"/v1/agent-install/(jbe_[A-Za-z0-9_-]+)/workbuddy/download",
            pending_response.json()["prompt"],
        ).group(1)

        disconnected = module.disconnected_knowledge_index_stats()
        monkeypatch.setattr(module, "knowledge_index_stats", lambda: disconnected)
        status_response = client.post(
            "/mcp/",
            headers={
                **api_headers(pending_token),
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            json={
                "jsonrpc": "2.0",
                "id": 82,
                "method": "tools/call",
                "params": {
                    "name": "knowledge_service_status",
                    "arguments": {},
                },
            },
        )
        assert status_response.status_code == 200
        assert status_response.json()["result"]["structuredContent"]["connected"] is False
        assert client.get(
            "/v1/me",
            headers={"Authorization": f"Bearer {pending_token}"},
        ).status_code == 403
        assert client.get(
            "/v1/me",
            headers={"Authorization": f"Bearer {original_token}"},
        ).status_code == 200

        with closing(module.database()) as connection:
            connection.execute(
                "UPDATE agent_enrollment_codes SET expires_at=? WHERE code_hash=?",
                (
                    module.isoformat(module.utc_now() - timedelta(minutes=1)),
                    module.token_hash(enrollment_code),
                ),
            )
            connection.commit()

        expired = client.post(
            "/mcp/",
            headers={
                **api_headers(pending_token),
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            json={"jsonrpc": "2.0", "id": 83, "method": "ping"},
        )
        assert expired.status_code == 401
        assert client.get(
            "/v1/me",
            headers={"Authorization": f"Bearer {original_token}"},
        ).status_code == 200
        with closing(module.database()) as connection:
            pending = connection.execute(
                "SELECT revoked_reason,activation_state FROM device_tokens WHERE token_hash=?",
                (module.token_hash(pending_token),),
            ).fetchone()
            assert pending["activation_state"] == "pending"
            assert pending["revoked_reason"] == "pending_activation_expired"
            assert connection.execute(
                "SELECT COUNT(*) FROM device_tokens WHERE user_id=? "
                "AND revoked_at IS NULL AND activation_state='active'",
                (int(user["id"]),),
            ).fetchone()[0] == 1


@pytest.mark.skip(reason="V1.4.5 已由单段安装指令替代三阶段设备绑定")
def test_admin_uses_same_transactional_agent_onboarding_as_members(
    tmp_path,
    monkeypatch,
):
    module = load_app(tmp_path)
    workbuddy_package = tmp_path / "workbuddy-admin-fixture.zip"
    workbuddy_package.write_bytes(b"workbuddy-admin-fixture")
    monkeypatch.setattr(
        module,
        "latest_skill_artifact",
        lambda target: (
            {
                "file_path": str(workbuddy_package),
                "file_name": workbuddy_package.name,
                "sha256": hashlib.sha256(workbuddy_package.read_bytes()).hexdigest(),
                "target": "workbuddy",
                "version": "1.3.1.6",
            }
            if target == "workbuddy"
            else None
        ),
    )
    monkeypatch.setattr(
        module,
        "workbuddy_artifact_has_signed_root_mcp",
        lambda artifact: bool(artifact),
    )
    with TestClient(module.app) as client:
        client.post(
            "/setup",
            data={
                "setup_key": "setup-secret",
                "username": "owner",
                "password": "owner-password-123",
            },
        )
        login = client.post(
            "/login",
            data={"username": "owner", "password": "owner-password-123"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)
        user = module.session_user(login.cookies[module.SESSION_COOKIE])[0]

        access = client.get("/access")
        assert "连接共创研究院知识库" in access.text
        assert "data-copy-agent-bootstrap" in access.text
        assert "管理员 API Key" not in access.text
        assert "管理员豁免" not in access.text
        skills = client.get("/skills")
        assert "生成一次性安全安装指令" in skills.text
        assert "管理员接入方式" not in skills.text

        review = client.post(
            "/agent-bootstrap-codes",
            data={"csrf_token": user["csrf_token"]},
        )
        assert review.status_code == 200
        assert review.json()["phase"] == "review"
        assert "exempt" not in review.json()
        enrollment_code = review.json()["review_code"]
        confirmed = client.post(
            "/agent-bootstrap-codes/confirm",
            data={
                "csrf_token": user["csrf_token"],
                "enrollment_code": enrollment_code,
                "platform": "unified",
            },
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["phase"] == "install_authorized"
        binding = client.post(
            "/agent-bootstrap-codes/binding",
            data={
                "csrf_token": user["csrf_token"],
                "enrollment_code": enrollment_code,
            },
        )
        assert binding.status_code == 200
        assert binding.json()["phase"] == "binding_authorized"

        private_key = Ed25519PrivateKey.generate()
        public_key = base64url_encode(
            private_key.public_key().public_bytes(
                Encoding.DER,
                PublicFormat.SubjectPublicKeyInfo,
            )
        )
        registration = {
            "device_id": TEST_DEVICE_ID,
            "device_name": TEST_DEVICE_NAME,
            "platform": "darwin-arm64",
            "agent_host": "workbuddy",
            "public_key": public_key,
            "transaction_mode": "credential_activation_v1",
        }
        registration["proof"] = base64url_encode(
            private_key.sign(
                enrollment_canonical_value(
                    enrollment_code=enrollment_code,
                    **registration,
                )
            )
        )
        prepared = client.post(
            f"/v1/agent-bootstrap/{enrollment_code}/register",
            json=registration,
        )
        assert prepared.status_code == 200
        assert prepared.json()["status"] == "prepared"
        token = prepared.json()["token"]
        key_id = prepared.json()["key_id"]
        with closing(module.database()) as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM device_bindings WHERE user_id=?",
                (int(user["id"]),),
            ).fetchone()[0] == 0

        activation_payload = {
            "device_id": TEST_DEVICE_ID,
            "key_id": key_id,
            "token": token,
            "proof": base64url_encode(
                private_key.sign(
                    activation_canonical_value(
                        enrollment_code=enrollment_code,
                        device_id=TEST_DEVICE_ID,
                        key_id=key_id,
                        token_fingerprint=module.token_hash(token),
                    )
                )
            ),
        }
        activated = client.post(
            f"/v1/agent-bootstrap/{enrollment_code}/activate",
            json=activation_payload,
        )
        assert activated.status_code == 200
        assert activated.json()["status"] == "activated"

        unsigned = client.get("/v1/me", headers=api_headers(token))
        assert unsigned.status_code == 428
        signed = client.get(
            "/v1/me",
            headers=signed_api_headers(
                module,
                token,
                private_key,
                key_id,
                method="GET",
                request_target="/v1/me",
            ),
        )
        assert signed.status_code == 200
        assert signed.json()["username"] == "owner"

        mcp_body = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}},
            separators=(",", ":"),
        ).encode()
        connected = client.post(
            "/mcp/",
            headers={
                **signed_api_headers(
                    module,
                    token,
                    private_key,
                    key_id,
                    method="POST",
                    request_target="/mcp/",
                    body=mcp_body,
                ),
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            content=mcp_body,
        )
        assert connected.status_code == 200
        status = client.get("/agent-installation-status").json()
        assert status["configured"] is True
        assert all(stage["complete"] for stage in status["stages"].values())


@pytest.mark.skip(reason="V1.4.5 覆盖升级不再复用设备身份")
def test_connected_device_cross_version_upgrade_reuses_identity(
    tmp_path,
    monkeypatch,
):
    module = load_app(tmp_path)
    allow_test_release_artifacts(monkeypatch, module)
    target_package = tmp_path / "workbuddy-v1.4.1.zip"
    target_package.write_bytes(b"signed-workbuddy-v1.4.1")
    target_sha256 = hashlib.sha256(target_package.read_bytes()).hexdigest()
    source_sha256 = hashlib.sha256(b"signed-workbuddy-v1.4.0").hexdigest()
    monkeypatch.setattr(
        module,
        "latest_skill_artifact",
        lambda target: (
            {
                "file_path": str(target_package),
                "file_name": target_package.name,
                "sha256": target_sha256,
                "target": "workbuddy",
                "version": "1.4.1",
            }
            if target == "workbuddy"
            else None
        ),
    )
    monkeypatch.setattr(
        module,
        "workbuddy_artifact_has_signed_root_mcp",
        lambda artifact: bool(artifact),
    )

    with TestClient(module.app) as client:
        client.post(
            "/setup",
            data={
                "setup_key": "setup-secret",
                "username": "owner",
                "password": "owner-password-123",
            },
        )
        login = client.post(
            "/login",
            data={"username": "owner", "password": "owner-password-123"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)
        user = module.session_user(login.cookies[module.SESSION_COOKIE])[0]
        _, key_id = provision_signed_device(
            module,
            int(user["id"]),
            agent_host="workbuddy",
        )
        now = module.isoformat(module.utc_now())
        token_seed = "test-upgrade-token-seed"
        with closing(module.database()) as connection:
            binding = connection.execute(
                """
                SELECT id FROM device_bindings
                WHERE user_id=? AND revoked_at IS NULL
                """,
                (int(user["id"]),),
            ).fetchone()
            connection.execute(
                """
                UPDATE device_bindings
                SET installed_version='1.4.0',
                    installed_package_sha256=?,installed_at=?
                WHERE id=?
                """,
                (source_sha256, now, int(binding["id"])),
            )
            connection.execute(
                """
                UPDATE device_keys
                SET credential_saved_at=?,first_verified_at=?,mcp_connected_at=?,
                    last_verified_at=?
                WHERE key_id=?
                """,
                (now, now, now, now, key_id),
            )
            connection.execute(
                """
                INSERT INTO device_tokens(
                    user_id,label,token_prefix,token_hash,token_seed,created_at
                ) VALUES (?,?,?,?,?,?)
                """,
                (
                    int(user["id"]),
                    TEST_DEVICE_NAME,
                    "jt_test",
                    module.token_hash("test-upgrade-token"),
                    token_seed,
                    now,
                ),
            )
            connection.commit()

        before = {}
        with closing(module.database()) as connection:
            for table in ("device_bindings", "device_keys", "device_tokens"):
                before[table] = connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE user_id=?",
                    (int(user["id"]),),
                ).fetchone()[0]
            key_before = dict(
                connection.execute(
                    "SELECT key_id,public_key FROM device_keys WHERE user_id=?",
                    (int(user["id"]),),
                ).fetchone()
            )
            token_before = dict(
                connection.execute(
                    "SELECT token_hash,token_seed FROM device_tokens WHERE user_id=?",
                    (int(user["id"]),),
                ).fetchone()
            )

        skills = client.get("/skills")
        assert skills.status_code == 200
        assert "升级到 V1.4.1" in skills.text
        assert "data-copy-agent-upgrade" in skills.text
        assert "升级不会重新登记设备" in skills.text

        review = client.post(
            "/agent-upgrade-codes",
            data={"csrf_token": user["csrf_token"]},
        )
        assert review.status_code == 200
        assert review.json()["phase"] == "review"
        assert review.json()["source_version"] == "1.4.0"
        assert review.json()["target_version"] == "1.4.1"
        assert "不得重新登记设备" in review.json()["prompt"]
        upgrade_code = review.json()["review_code"]

        protocol = client.get(f"/v1/agent-upgrade/{upgrade_code}")
        assert protocol.status_code == 200
        assert protocol.json()["phase"] == "review"
        assert protocol.json()["source"] == {
            "version": "1.4.0",
            "sha256": source_sha256,
        }
        assert protocol.json()["target"]["version"] == "1.4.1"
        assert protocol.json()["target"]["sha256"] == target_sha256
        assert protocol.json()["identity"] == {
            "reuse_existing_device_binding": True,
            "reuse_existing_device_key": True,
            "reuse_existing_api_token": True,
            "reuse_existing_bootstrap_url": False,
            "bootstrap_url_required_for_bound_upgrade": False,
            "device_reregistration": False,
            "credential_rotation": False,
        }
        assert protocol.json()["installation"]["authorized"] is False
        assert client.get(
            f"/v1/agent-upgrade/{upgrade_code}/workbuddy/download"
        ).status_code == 403

        confirmed = client.post(
            "/agent-upgrade-codes/confirm",
            data={
                "csrf_token": user["csrf_token"],
                "upgrade_code": upgrade_code,
            },
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["phase"] == "upgrade_authorized"
        assert "不得重新登记设备" in confirmed.json()["prompt"]

        authorized = client.get(f"/v1/agent-upgrade/{upgrade_code}")
        assert authorized.status_code == 200
        assert authorized.json()["phase"] == "upgrade_authorized"
        assert authorized.json()["installation"]["authorized"] is True
        assert "device_private_key" in authorized.json()["installation"]["preserve"]
        assert authorized.json()["rollback"]["report_failure_stage"] is True
        download = client.get(
            f"/v1/agent-upgrade/{upgrade_code}/workbuddy/download"
        )
        assert download.status_code == 200
        assert download.content == target_package.read_bytes()
        assert download.headers["x-jiaotang-package-sha256"] == target_sha256
        assert download.headers["x-jiaotang-target-version"] == "1.4.1"

        mismatched = client.post(
            f"/v1/agent-upgrade-result/{upgrade_code}",
            json={
                "schema": "jiaotang-agent-upgrade-result/v1",
                "ok": True,
                "status": "upgraded",
                "user_message": "升级完成",
                "installed_version": "1.4.1",
                "installed_package_sha256": "0" * 64,
            },
        )
        assert mismatched.status_code == 422

        upgraded = client.post(
            f"/v1/agent-upgrade-result/{upgrade_code}",
            json={
                "schema": "jiaotang-agent-upgrade-result/v1",
                "ok": True,
                "status": "upgraded",
                "user_message": "签名包升级和知识库连接复核均已通过",
                "installed_version": "1.4.1",
                "installed_package_sha256": target_sha256,
            },
        )
        assert upgraded.status_code == 200
        assert upgraded.json()["upgraded"] is True

        status = client.get("/agent-installation-status")
        assert status.status_code == 200
        assert status.json()["result"]["operation"] == "upgrade"
        assert status.json()["result"]["result_status"] == "upgraded"
        assert status.json()["result"]["workbuddy_version"] == "1.4.1"

        with closing(module.database()) as connection:
            binding_after = dict(
                connection.execute(
                    """
                    SELECT installed_version,installed_package_sha256,last_upgrade_at
                    FROM device_bindings WHERE user_id=?
                    """,
                    (int(user["id"]),),
                ).fetchone()
            )
            key_after = dict(
                connection.execute(
                    "SELECT key_id,public_key FROM device_keys WHERE user_id=?",
                    (int(user["id"]),),
                ).fetchone()
            )
            token_after = dict(
                connection.execute(
                    "SELECT token_hash,token_seed FROM device_tokens WHERE user_id=?",
                    (int(user["id"]),),
                ).fetchone()
            )
            after = {
                table: connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE user_id=?",
                    (int(user["id"]),),
                ).fetchone()[0]
                for table in ("device_bindings", "device_keys", "device_tokens")
            }
            consumed_at = connection.execute(
                """
                SELECT consumed_at FROM agent_enrollment_codes
                WHERE code_hash=? AND operation='upgrade'
                """,
                (module.token_hash(upgrade_code),),
            ).fetchone()["consumed_at"]
        assert binding_after["installed_version"] == "1.4.1"
        assert binding_after["installed_package_sha256"] == target_sha256
        assert binding_after["last_upgrade_at"]
        assert after == before
        assert key_after == key_before
        assert token_after == token_before
        assert consumed_at

        latest = client.get("/skills")
        assert "data-copy-agent-upgrade" not in latest.text
        assert "当前设备已经是最新正式版本" in latest.text


@pytest.mark.skip(reason="V1.4.5 已取消 bootstrap、设备公钥和逐请求签名")
def test_member_agent_bootstrap_device_signature_and_replacement(
    tmp_path,
    monkeypatch,
):
    module = load_app(tmp_path)
    allow_test_release_artifacts(monkeypatch, module)
    connector = module.BASE_DIR / "installers/jiaotang-agent.mjs"
    connector_sha256 = hashlib.sha256(connector.read_bytes()).hexdigest()
    workbuddy_package = tmp_path / "workbuddy-fixture.zip"
    with zipfile.ZipFile(workbuddy_package, "w") as archive:
        prefix = "jiaotang/plugins/jiaotang-workbuddy-skills/"
        archive.write(connector, prefix + "mcp/jiaotang-agent.mjs")
        archive.writestr(
            prefix + "plugin-release-manifest.json",
            json.dumps(
                {"files": {"mcp/jiaotang-agent.mjs": connector_sha256}},
                sort_keys=True,
            ),
        )
    artifact_state = {
        "file_path": str(workbuddy_package),
        "file_name": workbuddy_package.name,
        "sha256": hashlib.sha256(workbuddy_package.read_bytes()).hexdigest(),
        "target": "workbuddy",
        "version": "",
    }
    monkeypatch.setattr(
        module,
        "latest_skill_artifact",
        lambda target: dict(artifact_state) if target == "workbuddy" else None,
    )
    monkeypatch.setattr(
        module,
        "workbuddy_artifact_has_signed_root_mcp",
        lambda artifact: bool(artifact),
    )
    password = "member-password-123"
    with closing(module.database()) as connection:
        connection.execute(
            """
            INSERT INTO users(username,real_name,password_hash,created_at)
            VALUES (?,?,?,?)
            """,
            (
                "member",
                "王小明",
                module.password_hasher.hash(password),
                module.isoformat(module.utc_now()),
            ),
        )
        user_id = int(
            connection.execute(
                "SELECT id FROM users WHERE username='member'"
            ).fetchone()[0]
        )
        connection.execute(
            """
            INSERT INTO registration_authorizations(
                real_name,identity_code,status,user_id,created_at,registered_at
            ) VALUES (?,?,'registered',?,?,?)
            """,
            (
                "王小明",
                "0826",
                user_id,
                module.isoformat(module.utc_now()),
                module.isoformat(module.utc_now()),
            ),
        )
        connection.commit()

    with TestClient(module.app) as client:
        login = client.post(
            "/login",
            data={"username": "member", "password": password},
            follow_redirects=False,
        )
        assert login.status_code == 303
        client.cookies.update(login.cookies)
        user = module.session_user(login.cookies[module.SESSION_COOKIE])[0]

        access = client.get("/access")
        assert "复制给 Agent" in access.text
        assert "非 WorkBuddy 手工配置 MCP" in access.text
        assert "data-toggle-manual-agent-config" not in access.text
        assert "data-confirm-manual-agent-bootstrap" not in access.text
        assert "data-copy-agent-binding" in access.text
        assert "第三步 · 执行 bootstrap" in access.text
        assert 'href="/mcp-guide"' in access.text
        assert "手工配置 WorkBuddy" not in access.text
        assert "data-manual-package-download" not in access.text
        assert "我已审查，复制安装指令" in access.text
        assert "等待配置" in access.text
        portal_script = client.get("/static/portal.js")
        assert portal_script.status_code == 200
        assert "生成手工配置失败" not in portal_script.text
        assert "payload.workbuddy_configuration?.bootstrap_url" in portal_script.text
        assert "浏览器未允许自动复制" in portal_script.text
        assert 'fetch("/agent-bootstrap-codes/binding"' in portal_script.text
        assert "binding_authorized" in portal_script.text
        skills = client.get("/skills")
        assert skills.status_code == 200
        assert "非 WorkBuddy 手工配置 MCP" in skills.text
        assert "data-toggle-manual-agent-config" not in skills.text
        assert "data-confirm-manual-agent-bootstrap" not in skills.text
        assert "data-manual-package-download" not in skills.text
        assert "data-copy-agent-binding" in skills.text
        assert 'href="/mcp-guide"' in skills.text
        mcp_guide = client.get("/mcp-guide")
        assert mcp_guide.status_code == 200
        assert "非 WorkBuddy 用户手工配置 MCP" in mcp_guide.text
        assert "不下载插件包、不使用 bootstrap_url" in mcp_guide.text
        assert "Authorization" in mcp_guide.text

        bootstrap = client.post(
            "/agent-bootstrap-codes",
            data={"csrf_token": user["csrf_token"]},
        )
        assert bootstrap.status_code == 200
        assert bootstrap.json()["expires_in_seconds"] == 60 * 60
        assert bootstrap.json()["phase"] == "review"
        prompt = bootstrap.json()["prompt"]
        assert "不要开始安装" in prompt
        assert "本阶段不包含 bootstrap_url" in prompt
        assert "先确认当前宿主是 WorkBuddy 5" in prompt
        assert "本安装计划只适配 WorkBuddy" in prompt
        assert "不是 WorkBuddy 5 或更高版本" in prompt
        assert "签名插件包" in prompt
        assert "不包含动态命令字段" in prompt
        assert "宿主插件文件" in prompt
        assert "焦糖运行文件" in prompt
        assert "系统凭据" in prompt
        assert "/plugin 是宿主界面入口" in prompt
        assert "execution.command" not in prompt
        assert "安装说明读取失败" in prompt
        assert "node -e" not in prompt
        assert "不透明" not in prompt
        assert "不解释、不改写、不拆分" not in prompt
        protocol_url = re.search(
            r"http://testserver/v1/agent-install/(jbe_[A-Za-z0-9_-]+)",
            prompt,
        )
        assert protocol_url is not None
        enrollment_code = protocol_url.group(1)

        protocol = client.get(f"/v1/agent-install/{enrollment_code}")
        assert protocol.status_code == 200
        assert protocol.headers["content-type"].startswith(
            "application/vnd.jiaotang.agent-install+json"
        )
        assert protocol.headers["x-jiaotang-install-protocol"] == "6"
        assert protocol.headers["x-jiaotang-registration-transaction"] == (
            "prepare-store-activate"
        )
        assert protocol.json()["schema"] == "gongchuang-research-institute-agent-install/v1"
        assert protocol.json()["protocol_version"] == 6
        assert protocol.json()["phase"] == "review"
        assert protocol.json()["action"] == "review_signed_plugin"
        assert protocol.json()["opaque"] is False
        assert protocol.json()["review_required"] is True
        assert protocol.json()["user_confirmation_required"] is True
        host_preflight = protocol.json()["compatibility"]["host_preflight"]
        assert host_preflight["required_before_confirmation"] is True
        assert host_preflight["workbuddy_only"] is True
        assert {
            adapter["host"]: adapter["status"]
            for adapter in host_preflight["adapters"]
        } == {
            "workbuddy": "released",
        }
        review = protocol.json()["review"]
        scoped_download_url = (
            f"http://testserver/v1/agent-install/{enrollment_code}"
            "/workbuddy/download"
        )
        assert review["plugin_package"]["download_url"] == scoped_download_url
        assert review["plugin_package"]["signature_required"] is True
        assert review["plugin_package"]["contains_mcp_server"] == "jiaotang-kb"
        assert review["credential_handling"]["private_key_uploaded"] is False
        assert review["credential_handling"]["registration_transaction"] == (
            "prepare_store_activate"
        )
        assert review["credential_handling"][
            "activation_requires_secure_store_readback"
        ] is True
        storage_model = review["storage_model"]
        assert storage_model["name"] == "three_layer_local_storage"
        assert storage_model["layer_count"] == 3
        storage_layers = storage_model["layers"]
        assert review["local_changes"] == storage_layers
        assert [layer["layer"] for layer in storage_layers] == [
            "host_plugin_files",
            "jiaotang_runtime_files",
            "system_credentials",
        ]
        assert "~/.workbuddy/plugins" in storage_layers[0]["path"]
        assert "~/.codebuddy/plugins" in storage_layers[0]["path"]
        assert "plugins/marketplaces/gongchuang-research-institute" in storage_layers[0]["path"]
        assert "不得使用安装临时目录" in storage_layers[0]["purpose"]
        assert "~/.jiaotang/bin/jiaotang-kb-mcp.mjs" in storage_layers[1]["path"]
        assert storage_layers[1]["required_for_signed_plugin"] is False
        assert "cn.zshjiaotang.knowledge-device" in storage_layers[2]["path"]
        assert "device-credential.dpapi" in storage_layers[2]["path"]
        assert review["rollback"]
        assert "不要把 ~/.workbuddy、~/.codebuddy" in review["rollback"][-1]
        assert "execution" not in protocol.json()
        assert protocol.json()["installation"]["authorized"] is False
        assert protocol.json()["installation"]["dynamic_command"] is False
        assert "bootstrap_url" not in protocol.json()["installation"]
        assert protocol.json()["integrity"]["algorithms"] == ["sha256", "ed25519"]
        assert protocol.json()["completion"]["success_condition"] == (
            "server_confirmed_signed_mcp_connection"
        )
        result_handling = protocol.json()["completion"]["result_handling"]
        assert result_handling["contract"] == "jiaotang-agent-result/v1"
        assert result_handling["required_display_fields"] == [
            "user_message",
            "next_action",
        ]
        assert "summarize_completed_stages" in result_handling["display_rules"]
        assert "explain_failure_stage_without_exposing_secrets" in (
            result_handling["display_rules"]
        )
        workbuddy_instruction = result_handling[
            "workbuddy_instruction"
        ]
        assert "自动启动" in workbuddy_instruction
        assert "`jiaotang-kb`" in workbuddy_instruction
        assert {"workbuddy"} <= set(
            protocol.json()["compatibility"]["agent_hosts"]
        )
        anonymous_client = TestClient(module.app)
        unauthorized_download = anonymous_client.get(
            f"/v1/agent-install/{enrollment_code}/workbuddy/download"
        )
        anonymous_client.close()
        assert unauthorized_download.status_code == 403
        unconfirmed_manifest = client.get(
            f"/v1/agent-bootstrap/{enrollment_code}"
        )
        assert unconfirmed_manifest.status_code == 403
        assert "尚未由用户确认" in unconfirmed_manifest.json()["detail"]
        unconfirmed_binding = client.post(
            "/agent-bootstrap-codes/binding",
            data={
                "csrf_token": user["csrf_token"],
                "enrollment_code": enrollment_code,
            },
        )
        assert unconfirmed_binding.status_code == 403
        assert "先完成第二步" in unconfirmed_binding.json()["detail"]

        newer_package = tmp_path / "workbuddy-newer.zip"
        newer_package.write_bytes(b"newer-release-must-not-replace-pinned-package")
        artifact_state.update(
            {
                "file_path": str(newer_package),
                "file_name": newer_package.name,
                "sha256": hashlib.sha256(newer_package.read_bytes()).hexdigest(),
                "version": "",
            }
        )

        confirmed = client.post(
            "/agent-bootstrap-codes/confirm",
            data={
                "csrf_token": user["csrf_token"],
                "enrollment_code": enrollment_code,
                "platform": "macos",
            },
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["phase"] == "install_authorized"
        assert "明确授权继续安装" in confirmed.json()["prompt"]
        assert "当前宿主仍是 WorkBuddy 5" in confirmed.json()["prompt"]
        assert "`jiaotang-kb`" in confirmed.json()["prompt"]
        assert "不是必须出现在 Agent 工具列表中的工具" in confirmed.json()["prompt"]
        assert "`jiaotang_kb_setup`" in confirmed.json()["prompt"]
        assert "签名插件根目录 .mcp.json" in confirmed.json()["prompt"]
        assert "WorkBuddy 5.3.x" in confirmed.json()["prompt"]
        assert "runtimeInjected=false" in confirmed.json()["prompt"]
        assert "仅合并用户级 ~/.workbuddy/mcp.json" in confirmed.json()["prompt"]
        assert "不得直接注册临时下载或临时解压目录" in confirmed.json()["prompt"]
        assert "不得删除已注册的 jiaotang 市场" in confirmed.json()["prompt"]
        assert "第三步“复制知识库绑定指令”" in confirmed.json()["prompt"]
        workbuddy_configuration = confirmed.json()["workbuddy_configuration"]
        assert workbuddy_configuration["configuration_key"] == "bootstrap_url"
        assert workbuddy_configuration["mcp_server"] == "jiaotang-kb"
        assert workbuddy_configuration["setup_tool"] == "jiaotang_kb_setup"
        assert workbuddy_configuration["configuration_transport"] == "local_mcp_tool_argument"
        assert workbuddy_configuration["platform"] == "unified"
        assert workbuddy_configuration["plugin_download_url"] == scoped_download_url
        assert workbuddy_configuration["plugin_sha256"] == hashlib.sha256(
            workbuddy_package.read_bytes()
        ).hexdigest()
        assert "bootstrap_url" not in workbuddy_configuration
        assert f"?platform=unified" in confirmed.json()["prompt"]

        confirmed_without_binding = client.get(
            f"/v1/agent-bootstrap/{enrollment_code}"
        )
        assert confirmed_without_binding.status_code == 403
        assert "第三步知识库绑定授权" in confirmed_without_binding.json()["detail"]

        binding = client.post(
            "/agent-bootstrap-codes/binding",
            data={
                "csrf_token": user["csrf_token"],
                "enrollment_code": enrollment_code,
            },
        )
        assert binding.status_code == 200
        assert binding.json()["phase"] == "binding_authorized"
        assert "只调用一次本地 `jiaotang_kb_setup`" in binding.json()["prompt"]
        assert "不要在回复中复述" in binding.json()["prompt"]
        assert "`knowledge_service_status`" in binding.json()["prompt"]
        assert "no connector owns resource URI" in binding.json()["prompt"]
        assert "帮我安装OCR、PDF、Word、PPT、Excel和联网检索这几个Skills" in (
            binding.json()["prompt"]
        )
        binding_configuration = binding.json()["workbuddy_configuration"]
        assert binding_configuration["bootstrap_url"].endswith(
            f"/v1/agent-bootstrap/{enrollment_code}?platform=unified"
        )

        authorized_protocol = client.get(
            f"/v1/agent-install/{enrollment_code}?platform=macos"
        )
        assert authorized_protocol.status_code == 200
        assert authorized_protocol.json()["phase"] == "install_authorized"
        assert authorized_protocol.json()["user_confirmation_required"] is False
        assert authorized_protocol.json()["installation"]["authorized"] is True
        assert authorized_protocol.json()["installation"]["type"] == (
            "signed_workbuddy_plugin"
        )
        assert authorized_protocol.json()["installation"]["preflight_recheck"] == {
            "host": "workbuddy",
            "minimum_major_version": 5,
            "artifact_type": "signed_workbuddy_plugin",
            "must_match_review": True,
        }
        host_installation = authorized_protocol.json()["installation"][
            "host_installation"
        ]
        assert host_installation["entry_label"] == "/plugin"
        assert host_installation["entry_is_agent_tool"] is False
        assert host_installation["agent_tool_named_plugin_required"] is False
        assert host_installation["agent_may_use_authorized_host_capabilities"] is True
        assert "safe_extract_without_execution" in host_installation["fixed_actions"]
        assert "persist_declared_local_marketplace" in host_installation["fixed_actions"]
        assert "register_persisted_local_marketplace" in (
            host_installation["fixed_actions"]
        )
        assert "apply_scoped_workbuddy_5_3_mcp_fallback_if_required" in (
            host_installation["fixed_actions"]
        )
        assert "invoke_declared_local_setup_tool" not in (
            host_installation["fixed_actions"]
        )
        assert "cleanup_download_and_staging_only" in (
            host_installation["fixed_actions"]
        )
        persistent_marketplace = host_installation["persistent_marketplace"]
        assert persistent_marketplace["name"] == "gongchuang-research-institute"
        assert persistent_marketplace["relative_path"] == (
            "plugins/marketplaces/gongchuang-research-institute"
        )
        assert persistent_marketplace["select_active_host_root"] is True
        assert persistent_marketplace["register_from_temporary_path"] is False
        assert persistent_marketplace["preserve_after_install"] is True
        mcp_configuration = authorized_protocol.json()["installation"][
            "mcp_configuration"
        ]
        assert mcp_configuration == {
            "mode": "signed_external_plugin_mcp_file",
            "manifest": ".mcp.json",
            "plugin_manifest_reference": (
                ".codebuddy-plugin/plugin.json#mcpServers"
            ),
            "server": "jiaotang-kb",
            "setup_tool": "jiaotang_kb_setup",
            "binding_authorization": "separate_portal_third_step",
            "write_user_config": (
                "workbuddy_5_3_literal_placeholder_fallback_only"
            ),
            "write_global_mcp_config": False,
            "write_project_mcp_config": False,
        }
        compatibility = authorized_protocol.json()["installation"][
            "workbuddy_5_3_compatibility"
        ]
        assert "${CODEBUDDY_PLUGIN_ROOT}" in compatibility["trigger"]
        assert compatibility["scope"] == "user_mcp_jiaotang_kb_entry_only"
        assert compatibility["preserve_other_servers"] is True
        assert compatibility["modify_signed_plugin_files"] is False
        existing_install_policy = authorized_protocol.json()["installation"][
            "existing_install_policy"
        ]
        assert "持久共创研究院市场目录" in (
            existing_install_policy["same_package_sha256"]
        )
        assert "不得只凭 enabled 状态跳过" in (
            existing_install_policy["same_package_sha256"]
        )
        cleanup = authorized_protocol.json()["installation"]["cleanup"]
        assert cleanup["allowed"] == [
            "downloaded_zip",
            "unregistered_staging_directory",
        ]
        assert "registered_persistent_marketplace" in cleanup["preserve"]
        assert cleanup["requires_runtime_connection_check"] is True
        steps = authorized_protocol.json()["installation"]["steps"]
        assert any("plugins/marketplaces/gongchuang-research-institute" in step for step in steps)
        assert any("不得直接从临时下载目录" in step for step in steps)
        assert any("不得删除已注册的持久共创研究院市场" in step for step in steps)
        publisher_trust = authorized_protocol.json()["integrity"]["publisher_trust"]
        assert publisher_trust["fingerprint"] == (
            "SHA256:+BLR7x5xFci+u1Ue3KoFs9jFzzS+ebNk46JlfDUoEJI"
        )
        assert publisher_trust["package_embedded_public_key_must_match"] is True
        assert publisher_trust["package_self_report_is_not_sufficient"] is True
        safe_extract = authorized_protocol.json()["integrity"]["safe_extract"]
        assert safe_extract["execute_archive_content"] is False
        assert safe_extract["reject_parent_traversal"] is True
        assert safe_extract["reject_symbolic_links"] is True
        workbuddy_instruction = authorized_protocol.json()["completion"][
            "result_handling"
        ]["workbuddy_instruction"]
        assert "`jiaotang_kb_setup`" in workbuddy_instruction
        assert "`knowledge_search`" in workbuddy_instruction
        assert "`knowledge_service_status`" in workbuddy_instruction
        assert (
            authorized_protocol.json()["installation"]["plugin_download_url"]
            == scoped_download_url
        )
        assert "bootstrap_url" not in authorized_protocol.json()["installation"]
        anonymous_client = TestClient(module.app)
        authorized_download = anonymous_client.get(
            f"/v1/agent-install/{enrollment_code}/workbuddy/download"
        )
        anonymous_client.close()
        assert authorized_download.status_code == 200
        assert authorized_download.headers["content-type"] == "application/zip"
        assert authorized_download.content == workbuddy_package.read_bytes()
        assert authorized_download.headers["x-jiaotang-package-sha256"] == (
            hashlib.sha256(authorized_download.content).hexdigest()
        )
        assert authorized_protocol.json()["integrity"][
            "plugin_package_sha256"
        ] == hashlib.sha256(authorized_download.content).hexdigest()

        installer = client.get("/install/jiaotang-agent.mjs")
        assert installer.status_code == 200
        assert "activation_required" in installer.text
        assert "WorkBuddy 左侧「连接器」" in installer.text
        installer_path = tmp_path / "jiaotang-agent.mjs"
        installer_path.write_text(installer.text, encoding="utf-8")
        failed_install = subprocess.run(
            ["node", str(installer_path), "install"],
            capture_output=True,
            check=False,
            text=True,
        )
        assert failed_install.returncode == 1
        failed_result = json.loads(failed_install.stdout)
        assert failed_result["schema"] == "jiaotang-agent-result/v1"
        assert failed_result["ok"] is False
        assert failed_result["status"] == "failed"
        assert failed_result["error_stage"] == "validation"
        assert failed_result["user_message"].startswith("安装失败：")
        assert failed_result["next_action"]
        manifest = client.get(f"/v1/agent-bootstrap/{enrollment_code}")
        assert manifest.status_code == 200
        assert manifest.json()["result_url"].endswith(
            f"/v1/agent-install-result/{enrollment_code}"
        )
        assert manifest.json()["supported_platforms"] == ["darwin", "win32"]
        assert re.fullmatch(r"[a-f0-9]{64}", manifest.json()["installer_sha256"])
        assert {"workbuddy"} <= set(
            manifest.json()["supported_hosts"]
        )
        assert "commands" not in manifest.json()
        assert manifest.json()["workbuddy_plugin"]["dynamic_command"] is False
        assert (
            manifest.json()["workbuddy_plugin"]["download_url"]
            == scoped_download_url
        )
        assert manifest.json()["workbuddy_plugin"]["mcp_manifest"] == ".mcp.json"
        assert manifest.json()["workbuddy_plugin"]["setup_tool"] == (
            "jiaotang_kb_setup"
        )
        assert manifest.json()["workbuddy_plugin"]["configuration_transport"] == (
            "local_mcp_tool_argument"
        )
        assert manifest.json()["workbuddy_plugin"]["configuration_key"] == "bootstrap_url"
        assert manifest.json()["workbuddy_plugin"]["configuration_sensitive"] is True
        connector_sha256 = manifest.json()["workbuddy_plugin"]["connector_sha256"]
        assert re.fullmatch(r"[a-f0-9]{64}", connector_sha256)
        assert connector_sha256 == hashlib.sha256(connector.read_bytes()).hexdigest()

        failed_report = client.post(
            f"/v1/agent-install-result/{enrollment_code}",
            json={
                "schema": "jiaotang-agent-result/v1",
                "ok": False,
                "status": "failed",
                "error_stage": "installer_download",
                "user_message": "安装失败：下载超时",
                "next_action": "请检查网络后重试。",
            },
        )
        assert failed_report.status_code == 200
        with closing(module.database()) as connection:
            stored_failure = connection.execute(
                """
                SELECT result_status,result_error_stage,result_user_message
                FROM agent_enrollment_codes WHERE code_hash=?
                """,
                (module.token_hash(enrollment_code),),
            ).fetchone()
        assert stored_failure["result_status"] == "failed"
        assert stored_failure["result_error_stage"] == "installer_download"
        assert stored_failure["result_user_message"] == "安装失败：下载超时"

        private_key = Ed25519PrivateKey.generate()
        public_key = base64url_encode(
            private_key.public_key().public_bytes(
                Encoding.DER, PublicFormat.SubjectPublicKeyInfo
            )
        )
        registration = {
            "device_id": TEST_DEVICE_ID,
            "device_name": TEST_DEVICE_NAME,
            "platform": "darwin",
            "agent_host": "workbuddy",
            "public_key": public_key,
        }
        proof = private_key.sign(
            enrollment_canonical_value(
                enrollment_code=enrollment_code,
                **registration,
            )
        )
        registration["proof"] = base64url_encode(proof)
        enrolled = client.post(
            f"/v1/agent-bootstrap/{enrollment_code}/register",
            json=registration,
        )
        assert enrolled.status_code == 200
        old_token = enrolled.json()["token"]
        incomplete_skills_page = client.get("/skills")
        assert incomplete_skills_page.status_code == 200
        assert "撤销未完成登记" in incomplete_skills_page.text

        assert client.get(f"/v1/agent-bootstrap/{enrollment_code}").status_code == 200
        assert client.get(f"/v1/agent-install/{enrollment_code}").status_code == 200

        retry_private_key = Ed25519PrivateKey.generate()
        retry_public_key = base64url_encode(
            retry_private_key.public_key().public_bytes(
                Encoding.DER, PublicFormat.SubjectPublicKeyInfo
            )
        )
        retry_registration = {
            **{key: value for key, value in registration.items() if key not in {"public_key", "proof"}},
            "public_key": retry_public_key,
        }
        retry_registration["proof"] = base64url_encode(
            retry_private_key.sign(
                enrollment_canonical_value(
                    enrollment_code=enrollment_code,
                    **{key: value for key, value in retry_registration.items() if key != "proof"},
                )
            )
        )
        retried = client.post(
            f"/v1/agent-bootstrap/{enrollment_code}/register",
            json=retry_registration,
        )
        assert retried.status_code == 409
        assert "已经登记到另一组设备密钥" in retried.json()["detail"]
        idempotent = client.post(
            f"/v1/agent-bootstrap/{enrollment_code}/register",
            json=registration,
        )
        assert idempotent.status_code == 200
        assert idempotent.json()["idempotent"] is True
        assert idempotent.json()["token"] == old_token
        token = old_token
        key_id = enrolled.json()["key_id"]

        unsigned = client.get("/v1/me", headers=api_headers(token))
        assert unsigned.status_code == 428

        credential_saved = client.post(
            "/v1/device-installation/credential-saved",
            headers=signed_api_headers(
                module,
                token,
                private_key,
                key_id,
                method="POST",
                request_target="/v1/device-installation/credential-saved",
            ),
        )
        assert credential_saved.status_code == 200
        assert credential_saved.json()["stages"]["registration"]["completed"]
        assert credential_saved.json()["stages"]["credential_saved"]["completed"]
        assert credential_saved.json()["stages"]["first_signature"]["completed"]
        assert not credential_saved.json()["stages"]["mcp_connection"]["completed"]

        installation_status = client.get(
            "/v1/device-installation/status",
            headers=signed_api_headers(
                module,
                token,
                private_key,
                key_id,
                method="GET",
                request_target="/v1/device-installation/status",
            ),
        )
        assert installation_status.status_code == 200
        assert not installation_status.json()["configured"]

        nonce = base64url_encode(uuid.uuid4().bytes)
        signed_headers = signed_api_headers(
            module,
            token,
            private_key,
            key_id,
            method="GET",
            request_target="/v1/me",
            nonce=nonce,
        )
        signed = client.get("/v1/me", headers=signed_headers)
        assert signed.status_code == 200
        assert signed.json()["username"] == "member"
        replay = client.get("/v1/me", headers=signed_headers)
        assert replay.status_code == 409

        wrong_key = Ed25519PrivateKey.generate()
        wrong_signature = signed_api_headers(
            module,
            token,
            wrong_key,
            key_id,
            method="GET",
            request_target="/v1/me",
        )
        assert client.get("/v1/me", headers=wrong_signature).status_code == 403

        access = client.get("/access")
        assert "安装未完成" in access.text
        assert "登记成功" in access.text
        assert "凭据保存" in access.text
        assert "首次验签" in access.text
        assert "MCP连接" in access.text
        assert "workbuddy" in access.text

        mcp_body = json.dumps(
            {"jsonrpc": "2.0", "id": 7, "method": "ping", "params": {}},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        mcp_connected = client.post(
            "/mcp/",
            headers={
                **signed_api_headers(
                    module,
                    token,
                    private_key,
                    key_id,
                    method="POST",
                    request_target="/mcp/",
                    body=mcp_body,
                ),
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            content=mcp_body,
        )
        assert mcp_connected.status_code == 200
        completed_report = client.post(
            f"/v1/agent-install-result/{enrollment_code}",
            json={
                "schema": "jiaotang-agent-result/v1",
                "ok": True,
                "status": "configured",
                "user_message": "配置成功",
                "next_action": None,
                "host": "codex",
                "platform": "darwin-arm64",
                "activation_required": False,
            },
        )
        assert completed_report.status_code == 200
        with closing(module.database()) as connection:
            stored_success = connection.execute(
                """
                SELECT result_ok,result_status,result_error_stage,result_host
                FROM agent_enrollment_codes WHERE code_hash=?
                """,
                (module.token_hash(enrollment_code),),
            ).fetchone()
        assert stored_success["result_ok"] == 1
        assert stored_success["result_status"] == "configured"
        assert stored_success["result_error_stage"] is None
        assert stored_success["result_host"] == "codex"
        completed_access = client.get("/access")
        assert "安装成功" in completed_access.text
        consumed_manifest = client.get(f"/v1/agent-bootstrap/{enrollment_code}")
        assert consumed_manifest.status_code == 410
        assert "已经使用" in consumed_manifest.json()["detail"]
        consumed_protocol = client.get(f"/v1/agent-install/{enrollment_code}")
        assert consumed_protocol.status_code == 410
        assert "已经使用" in consumed_protocol.json()["detail"]
        consumed_registration = client.post(
            f"/v1/agent-bootstrap/{enrollment_code}/register",
            json=registration,
        )
        assert consumed_registration.status_code == 410
        assert "已经使用" in consumed_registration.json()["detail"]

        replaced = client.post(
            "/device-binding/replace",
            data={"csrf_token": user["csrf_token"]},
        )
        assert replaced.status_code == 200
        assert "旧设备、公钥和访问凭据已失效" in replaced.text
        assert client.get("/v1/me", headers=signed_api_headers(
            module,
            token,
            private_key,
            key_id,
            method="GET",
            request_target="/v1/me",
        )).status_code == 401

        renewed = client.post(
            "/agent-bootstrap-codes",
            data={"csrf_token": user["csrf_token"]},
        )
        assert renewed.status_code == 200
        assert "安装说明" in renewed.json()["prompt"]
        assert "不再返回或要求执行任何动态命令" not in renewed.json()["prompt"]
        assert "不包含动态命令字段" in renewed.json()["prompt"]
        renewed_code = re.search(
            r"http://testserver/v1/agent-install/(jbe_[A-Za-z0-9_-]+)",
            renewed.json()["prompt"],
        ).group(1)
        with closing(module.database()) as connection:
            connection.execute(
                "UPDATE agent_enrollment_codes SET expires_at=? WHERE code_hash=?",
                (
                    module.isoformat(module.utc_now() - timedelta(seconds=1)),
                    module.token_hash(renewed_code),
                ),
            )
            connection.commit()
        expired_manifest = client.get(f"/v1/agent-bootstrap/{renewed_code}")
        assert expired_manifest.status_code == 410
        assert "已经过期" in expired_manifest.json()["detail"]
        expired_protocol = client.get(f"/v1/agent-install/{renewed_code}")
        assert expired_protocol.status_code == 410
        assert "已经过期" in expired_protocol.json()["detail"]
        expired_registration_payload = {
            key: value for key, value in registration.items() if key != "proof"
        }
        expired_registration_payload["proof"] = base64url_encode(
            private_key.sign(
                enrollment_canonical_value(
                    enrollment_code=renewed_code,
                    **expired_registration_payload,
                )
            )
        )
        expired_registration = client.post(
            f"/v1/agent-bootstrap/{renewed_code}/register",
            json=expired_registration_payload,
        )
        assert expired_registration.status_code == 410
        assert "已经过期" in expired_registration.json()["detail"]


def test_transactional_device_registration_activates_only_after_saved_credential_proof(
    tmp_path,
):
    module = load_app(tmp_path)
    enrollment_code = "jbe_transactional-test-0001"
    now = module.isoformat(module.utc_now())
    expires_at = module.isoformat(module.utc_now() + timedelta(minutes=30))
    with closing(module.database()) as connection:
        user_id = int(
            connection.execute(
                """
                INSERT INTO users(username,real_name,password_hash,created_at)
                VALUES (?,?,?,?)
                """,
                (
                    "member",
                    "王小明",
                    module.password_hasher.hash("member-password-123"),
                    now,
                ),
            ).lastrowid
        )
        connection.execute(
            """
            INSERT INTO registration_authorizations(
                real_name,identity_code,status,user_id,created_at,registered_at
            ) VALUES (?,?,'registered',?,?,?)
            """,
            ("王小明", "0826", user_id, now, now),
        )
        connection.execute(
            """
            INSERT INTO agent_enrollment_codes(
                user_id,code_hash,created_at,expires_at,confirmed_at,
                binding_authorized_at
            ) VALUES (?,?,?,?,?,?)
            """,
            (
                user_id,
                module.token_hash(enrollment_code),
                now,
                expires_at,
                now,
                now,
            ),
        )
        connection.commit()

    private_key = Ed25519PrivateKey.generate()
    public_key = base64url_encode(
        private_key.public_key().public_bytes(
            Encoding.DER,
            PublicFormat.SubjectPublicKeyInfo,
        )
    )
    registration = {
        "device_id": TEST_DEVICE_ID,
        "device_name": TEST_DEVICE_NAME,
        "platform": "win32-x64",
        "agent_host": "workbuddy",
        "public_key": public_key,
        "transaction_mode": "credential_activation_v1",
    }
    registration["proof"] = base64url_encode(
        private_key.sign(
            enrollment_canonical_value(
                enrollment_code=enrollment_code,
                **registration,
            )
        )
    )

    with TestClient(module.app) as client:
        prepared = client.post(
            f"/v1/agent-bootstrap/{enrollment_code}/register",
            json=registration,
        )
        assert prepared.status_code == 200
        assert prepared.json()["status"] == "prepared"
        assert prepared.json()["idempotent"] is False
        assert prepared.json()["activation_url"].endswith(
            f"/v1/agent-bootstrap/{enrollment_code}/activate"
        )
        token = prepared.json()["token"]
        key_id = prepared.json()["key_id"]

        with closing(module.database()) as connection:
            assert connection.execute("SELECT COUNT(*) FROM device_tokens").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM device_bindings").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM device_keys").fetchone()[0] == 0
            intent = connection.execute(
                """
                SELECT activated_at FROM device_registration_intents
                WHERE user_id=?
                """,
                (user_id,),
            ).fetchone()
            enrollment = connection.execute(
                """
                SELECT registered_at FROM agent_enrollment_codes
                WHERE user_id=?
                """,
                (user_id,),
            ).fetchone()
        assert intent is not None
        assert intent["activated_at"] is None
        assert enrollment["registered_at"] is None
        assert client.get(
            "/v1/me",
            headers=signed_api_headers(
                module,
                token,
                private_key,
                key_id,
                method="GET",
                request_target="/v1/me",
            ),
        ).status_code == 401

        invalid_activation = client.post(
            f"/v1/agent-bootstrap/{enrollment_code}/activate",
            json={
                "device_id": TEST_DEVICE_ID,
                "key_id": key_id,
                "token": token,
                "proof": base64url_encode(Ed25519PrivateKey.generate().sign(b"invalid")),
            },
        )
        assert invalid_activation.status_code == 403
        with closing(module.database()) as connection:
            assert connection.execute("SELECT COUNT(*) FROM device_tokens").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM device_bindings").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM device_keys").fetchone()[0] == 0

        activation_proof = base64url_encode(
            private_key.sign(
                activation_canonical_value(
                    enrollment_code=enrollment_code,
                    device_id=TEST_DEVICE_ID,
                    key_id=key_id,
                    token_fingerprint=module.token_hash(token),
                )
            )
        )
        activation_payload = {
            "device_id": TEST_DEVICE_ID,
            "key_id": key_id,
            "token": token,
            "proof": activation_proof,
        }
        activated = client.post(
            f"/v1/agent-bootstrap/{enrollment_code}/activate",
            json=activation_payload,
        )
        assert activated.status_code == 200
        assert activated.json()["status"] == "activated"
        assert activated.json()["idempotent"] is False
        idempotent = client.post(
            f"/v1/agent-bootstrap/{enrollment_code}/activate",
            json=activation_payload,
        )
        assert idempotent.status_code == 200
        assert idempotent.json()["idempotent"] is True

        status_response = client.get(
            "/v1/device-installation/status",
            headers=signed_api_headers(
                module,
                token,
                private_key,
                key_id,
                method="GET",
                request_target="/v1/device-installation/status",
            ),
        )
        assert status_response.status_code == 200
        stages = status_response.json()["stages"]
        assert stages["registration"]["completed"]
        assert stages["credential_saved"]["completed"]
        assert stages["first_signature"]["completed"]
        assert not stages["mcp_connection"]["completed"]

    with closing(module.database()) as connection:
        assert connection.execute("SELECT COUNT(*) FROM device_tokens").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM device_bindings").fetchone()[0] == 1
        key = connection.execute(
            """
            SELECT credential_saved_at,first_verified_at
            FROM device_keys WHERE user_id=?
            """,
            (user_id,),
        ).fetchone()
        enrollment = connection.execute(
            """
            SELECT registered_at,registered_key_id
            FROM agent_enrollment_codes WHERE user_id=?
            """,
            (user_id,),
        ).fetchone()
    assert key["credential_saved_at"]
    assert key["first_verified_at"]
    assert enrollment["registered_at"]
    assert enrollment["registered_key_id"] == key_id


@pytest.mark.skip(reason="V1.4.5 一键安装不再进入设备登记流程")
def test_legacy_device_registration_is_blocked_after_transactional_release(
    tmp_path,
    monkeypatch,
):
    module = load_app(tmp_path)
    monkeypatch.setattr(
        module,
        "latest_skill_artifact",
        lambda target: (
            {"version": "1.3.1.4", "target": "workbuddy"}
            if target == "workbuddy"
            else None
        ),
    )
    monkeypatch.setattr(
        module,
        "workbuddy_artifact_has_signed_root_mcp",
        lambda artifact: bool(artifact),
    )
    private_key = Ed25519PrivateKey.generate()
    public_key = base64url_encode(
        private_key.public_key().public_bytes(
            Encoding.DER,
            PublicFormat.SubjectPublicKeyInfo,
        )
    )
    registration = {
        "device_id": TEST_DEVICE_ID,
        "device_name": TEST_DEVICE_NAME,
        "platform": "win32-x64",
        "agent_host": "workbuddy",
        "public_key": public_key,
    }
    registration["proof"] = base64url_encode(
        private_key.sign(
            enrollment_canonical_value(
                enrollment_code="jbe_legacy-block-test",
                **registration,
            )
        )
    )
    with TestClient(module.app) as client:
        response = client.post(
            "/v1/agent-bootstrap/jbe_legacy-block-test/register",
            json=registration,
        )
    assert response.status_code == 426
    assert response.headers["upgrade"] == "jiaotang-registration-transaction-v1"
    assert "V1.3.1.4" in response.json()["detail"]
    with closing(module.database()) as connection:
        assert connection.execute("SELECT COUNT(*) FROM device_tokens").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM device_bindings").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM device_keys").fetchone()[0] == 0


def test_skills_diagnostics_uses_current_platform_pair_and_redacts_secrets(
    tmp_path,
    monkeypatch,
):
    module = load_app(tmp_path)
    packages = {
        "macos": tmp_path / "workbuddy-macos-diagnostics.zip",
        "windows": tmp_path / "workbuddy-windows-diagnostics.zip",
    }
    packages["macos"].write_bytes(b"diagnostic-package-macos")
    packages["windows"].write_bytes(b"diagnostic-package-windows")
    package_sha256 = {
        target: hashlib.sha256(path.read_bytes()).hexdigest()
        for target, path in packages.items()
    }
    now = module.isoformat(module.utc_now())
    expires_at = module.isoformat(module.utc_now() + timedelta(minutes=30))
    with closing(module.database()) as connection:
        user_id = int(
            connection.execute(
                """
                INSERT INTO users(username,real_name,password_hash,created_at)
                VALUES (?,?,?,?)
                """,
                (
                    "member",
                    "王小明",
                    module.password_hasher.hash("member-password-123"),
                    now,
                ),
            ).lastrowid
        )
        connection.execute(
            """
            INSERT INTO registration_authorizations(
                real_name,identity_code,status,user_id,created_at,registered_at
            ) VALUES (?,?,'registered',?,?,?)
            """,
            ("王小明", "0826", user_id, now, now),
        )
        enrollment_id = int(
            connection.execute(
                """
                INSERT INTO agent_enrollment_codes(
                    user_id,code_hash,created_at,expires_at,confirmed_at,
                    binding_authorized_at
                ) VALUES (?,?,?,?,?,?)
                """,
                (
                    user_id,
                    module.token_hash("jbe_supersecret-code"),
                    now,
                    expires_at,
                    now,
                    now,
                ),
            ).lastrowid
        )
        connection.execute(
            """
            INSERT INTO device_registration_intents(
                enrollment_id,user_id,device_id_hash,device_id_prefix,
                device_name,key_id,public_key,platform,agent_host,
                token_prefix,token_hash,token_seed,created_at,expires_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                enrollment_id,
                user_id,
                hashlib.sha256(TEST_DEVICE_ID.encode()).hexdigest(),
                TEST_DEVICE_ID[:12],
                TEST_DEVICE_NAME,
                "jdk_012345678901234567890123",
                "PUBLIC-SENSITIVE",
                "win32-x64",
                "workbuddy",
                "jtk_secret",
                module.token_hash("jtk_supersecret-token"),
                "SEED-SENSITIVE",
                now,
                expires_at,
            ),
        )
        connection.commit()

    monkeypatch.setattr(
        module,
        "latest_skill_artifact",
        lambda target: {
            "file_path": str(packages[target]),
            "file_name": packages[target].name,
            "sha256": package_sha256[target],
            "target": target,
            "version": "1.6.3",
        }
        if target in packages
        else None,
    )
    monkeypatch.setattr(
        module,
        "validate_workbuddy_artifact_for_diagnostics",
        lambda artifact: {
            "status": "verified",
            "publisher_fingerprint": (
                "SHA256:+BLR7x5xFci+u1Ue3KoFs9jFzzS+ebNk46JlfDUoEJI"
            ),
            "signature_namespace": "codex-workbuddy-plugin-manifest",
            "verified_files": 319 if artifact["target"] == "macos" else 317,
            "archive_entries": 319 if artifact["target"] == "macos" else 317,
            "mcp_configuration_mode": "user_remote_streamable_http",
            "hook_mode": "behavior_only_fail_open",
        },
    )

    with TestClient(module.app) as client:
        login = client.post(
            "/login",
            data={"username": "member", "password": "member-password-123"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)
        page = client.get("/skills/diagnostics")
        assert page.status_code == 200
        assert "WorkBuddy 一键诊断" in page.text
        assert package_sha256["macos"] in page.text
        assert package_sha256["windows"] in page.text
        assert "WorkBuddy V1.6.3" in page.text
        assert "Ed25519 双端签名有效" in page.text
        assert "636 个文件已核验" in page.text
        assert "SHA256:+BLR7x5xFci+u1Ue3KoFs9jFzzS+ebNk46JlfDUoEJI" in page.text
        assert "安装包边界" in page.text
        assert "运行时完成标准" in page.text
        assert "knowledge_service_status" in page.text
        assert "四阶段连接状态" not in page.text
        assert "设备登记 URL" not in page.text
        for sensitive in (
            "jbe_supersecret-code",
            "jtk_supersecret-token",
            "PUBLIC-SENSITIVE",
            "SEED-SENSITIVE",
        ):
            assert sensitive not in page.text
        assert page.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize(
    ("fault", "expected_status", "expected_detail"),
    (
        ("missing", "unavailable", "未同时就绪"),
        ("version", "invalid", "双端版本不一致"),
        ("fingerprint", "invalid", "公钥指纹不一致"),
        ("invalid", "invalid", "至少一个平台验签或安装边界未通过"),
    ),
)
def test_agent_diagnostics_fails_closed_for_platform_pair_drift(
    tmp_path,
    monkeypatch,
    fault,
    expected_status,
    expected_detail,
):
    module = load_app(tmp_path)
    packages = {
        "macos": tmp_path / "macos.zip",
        "windows": tmp_path / "windows.zip",
    }
    for target, path in packages.items():
        path.write_bytes(f"{target}-package".encode())

    def artifact(target):
        if target not in packages:
            raise AssertionError("不得回退到旧workbuddy单包")
        if fault == "missing" and target == "windows":
            return None
        path = packages[target]
        return {
            "file_path": str(path),
            "file_name": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "target": target,
            "version": "1.6.2" if fault == "version" and target == "windows" else "1.6.3",
        }

    def validation(candidate):
        target = candidate["target"]
        if fault == "invalid" and target == "windows":
            raise ValueError("fixture signature failure")
        fingerprint = "SHA256:current-publisher"
        if fault == "fingerprint" and target == "windows":
            fingerprint = "SHA256:different-publisher"
        return {
            "status": "verified",
            "publisher_fingerprint": fingerprint,
            "signature_namespace": "codex-workbuddy-plugin-manifest",
            "verified_files": 2,
            "archive_entries": 2,
            "mcp_configuration_mode": "user_remote_streamable_http",
            "hook_mode": "behavior_only_fail_open",
        }

    monkeypatch.setattr(module, "latest_skill_artifact", artifact)
    monkeypatch.setattr(
        module,
        "validate_workbuddy_artifact_for_diagnostics",
        validation,
    )
    payload = module.agent_diagnostics_payload(None, 1)
    assert payload["signature"]["status"] == expected_status
    assert expected_detail in payload["signature"]["detail"]
    assert payload["signature"]["verified_files"] == 0


def test_current_workbuddy_upgrade_channel_uses_platform_artifact(monkeypatch, tmp_path):
    module = load_app(tmp_path)
    monkeypatch.setattr(
        module,
        "latest_workbuddy_artifact",
        lambda: {
            "version": "1.6.3",
            "installable": True,
            "platform_artifacts": {
                "macos": {"sha256": "a" * 64},
                "windows": {"sha256": "b" * 64},
            },
        },
    )
    assert module.current_workbuddy_upgrade_channel("win32-x64") == {
        "version": "1.6.3",
        "installable": True,
        "target": "windows",
        "sha256": "b" * 64,
    }
    assert module.current_workbuddy_upgrade_channel("darwin-arm64") == {
        "version": "1.6.3",
        "installable": True,
        "target": "macos",
        "sha256": "a" * 64,
    }
    assert module.current_workbuddy_upgrade_channel("unknown-agent") == {
        "version": "1.6.3",
        "installable": False,
        "target": "",
        "sha256": "",
    }


def test_current_workbuddy_upgrade_channel_does_not_cross_platform_versions(
    monkeypatch,
    tmp_path,
):
    module = load_app(tmp_path)
    monkeypatch.setattr(
        module,
        "latest_workbuddy_artifact",
        lambda: {
            "version": "1.6.4",
            "installable": True,
            "platform_artifacts": {
                "macos": {"version": "1.6.3", "sha256": "a" * 64},
                "windows": {"version": "1.6.4", "sha256": "b" * 64},
            },
        },
    )
    assert module.current_workbuddy_upgrade_channel("darwin-arm64")["version"] == (
        "1.6.3"
    )
    assert module.current_workbuddy_upgrade_channel("windows-x64")["version"] == (
        "1.6.4"
    )


@pytest.mark.skip(reason="V1.4.5 通过插件与 MCP 配置备份恢复，不再使用 bootstrap")
def test_bootstrap_recovers_unverified_partial_installation(tmp_path, monkeypatch):
    module = load_app(tmp_path)
    workbuddy_package = tmp_path / "workbuddy-recovery-fixture.zip"
    workbuddy_package.write_bytes(b"signed-workbuddy-recovery-fixture")
    monkeypatch.setattr(
        module,
        "latest_skill_artifact",
        lambda target: (
            {
                "file_path": str(workbuddy_package),
                "file_name": workbuddy_package.name,
                "sha256": hashlib.sha256(workbuddy_package.read_bytes()).hexdigest(),
                "target": "workbuddy",
                "version": "",
            }
            if target == "workbuddy"
            else None
        ),
    )
    monkeypatch.setattr(
        module,
        "workbuddy_artifact_has_signed_root_mcp",
        lambda artifact: bool(artifact),
    )
    password = "member-password-123"
    with closing(module.database()) as connection:
        connection.execute(
            """
            INSERT INTO users(username,real_name,password_hash,created_at)
            VALUES (?,?,?,?)
            """,
            (
                "member",
                "王小明",
                module.password_hasher.hash(password),
                module.isoformat(module.utc_now()),
            ),
        )
        user_id = int(
            connection.execute(
                "SELECT id FROM users WHERE username='member'"
            ).fetchone()[0]
        )
        connection.commit()
    provision_signed_device(module, user_id, agent_host="workbuddy")

    with TestClient(module.app) as client:
        login = client.post(
            "/login",
            data={"username": "member", "password": password},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)
        user = module.session_user(login.cookies[module.SESSION_COOKIE])[0]
        partial_access = client.get("/access")
        assert "安装未完成" in partial_access.text
        assert "登记成功" in partial_access.text
        assert "等待凭据库确认" in partial_access.text
        assert "等待签名请求" in partial_access.text
        assert "等待服务器确认" in partial_access.text
        assert "自动清理本次半成品绑定" in partial_access.text
        recovered = client.post(
            "/agent-bootstrap-codes",
            data={"csrf_token": user["csrf_token"]},
        )
        assert recovered.status_code == 200
        assert recovered.json()["expires_in_seconds"] == 60 * 60
        enrollment_code = recovered.json()["review_code"]
        with closing(module.database()) as connection:
            binding_before_confirmation = connection.execute(
                "SELECT revoked_at FROM device_bindings WHERE user_id=?",
                (user_id,),
            ).fetchone()
            key_before_confirmation = connection.execute(
                "SELECT revoked_at FROM device_keys WHERE user_id=?",
                (user_id,),
            ).fetchone()
        assert binding_before_confirmation["revoked_at"] is None
        assert key_before_confirmation["revoked_at"] is None

        confirmed = client.post(
            "/agent-bootstrap-codes/confirm",
            data={
                "csrf_token": user["csrf_token"],
                "enrollment_code": enrollment_code,
            },
        )
        assert confirmed.status_code == 200

    with closing(module.database()) as connection:
        binding = connection.execute(
            "SELECT revoked_at,revoked_reason FROM device_bindings WHERE user_id=?",
            (user_id,),
        ).fetchone()
        key = connection.execute(
            "SELECT revoked_at,revoked_reason FROM device_keys WHERE user_id=?",
            (user_id,),
        ).fetchone()
        active_codes = connection.execute(
            """
            SELECT COUNT(*) FROM agent_enrollment_codes
            WHERE user_id=? AND consumed_at IS NULL
            """,
            (user_id,),
        ).fetchone()[0]
    assert binding["revoked_at"]
    assert binding["revoked_reason"] == "confirmed_installation_retry"
    assert key["revoked_at"]
    assert key["revoked_reason"] == "confirmed_installation_retry"
    assert active_codes == 1


def test_init_database_reopens_latest_incomplete_enrollment(tmp_path):
    module = load_app(tmp_path)
    now = module.isoformat(module.utc_now())
    expires_at = module.isoformat(module.utc_now() + timedelta(minutes=30))
    with closing(module.database()) as connection:
        user_id = int(
            connection.execute(
                """
                INSERT INTO users(username,password_hash,created_at)
                VALUES (?,?,?)
                """,
                ("member", module.password_hasher.hash("member-password-123"), now),
            ).lastrowid
        )
        connection.execute(
            """
            INSERT INTO agent_enrollment_codes(
                user_id,code_hash,created_at,expires_at,consumed_at,consumed_ip
            ) VALUES (?,?,?,?,?,?)
            """,
            (
                user_id,
                module.token_hash("jbe_legacy-incomplete"),
                now,
                expires_at,
                now,
                "test",
            ),
        )
        connection.commit()
    _, key_id = provision_signed_device(module, user_id)

    module.init_database()

    with closing(module.database()) as connection:
        enrollment = connection.execute(
            """
            SELECT registered_at,registered_key_id,registered_ip,consumed_at,consumed_ip
            FROM agent_enrollment_codes WHERE user_id=?
            """,
            (user_id,),
        ).fetchone()
    assert enrollment["registered_at"] == now
    assert enrollment["registered_key_id"] == key_id
    assert enrollment["registered_ip"] == "test"
    assert enrollment["consumed_at"] is None
    assert enrollment["consumed_ip"] == ""


def test_latest_skill_release_metadata_and_download(tmp_path, monkeypatch):
    module = load_app(tmp_path)
    allow_test_release_artifacts(monkeypatch, module)
    package = tmp_path / "project-assistant-skills.zip"
    package.write_bytes(b"test-skill-package")
    historical_package = tmp_path / "project-assistant-skills-v1.0.zip"
    historical_package.write_bytes(b"historical-skill-package")
    digest = module.hashlib.sha256(package.read_bytes()).hexdigest()
    historical_digest = module.hashlib.sha256(historical_package.read_bytes()).hexdigest()
    with closing(module.database()) as connection:
        connection.execute(
            "INSERT INTO users(username, password_hash, is_admin, created_at) VALUES (?, ?, 1, ?)",
            ("member", module.password_hasher.hash("member-password-123"), module.isoformat(module.utc_now())),
        )
        user_id = connection.execute("SELECT id FROM users WHERE username = 'member'").fetchone()[0]
        token_seed = "test-release-token-seed"
        raw_token = module.user_access_token(user_id, token_seed)
        connection.execute(
            """
            INSERT INTO device_tokens(user_id, label, token_prefix, token_hash, token_seed, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user_id, "test", raw_token[:12], module.token_hash(raw_token), token_seed,
                module.isoformat(module.utc_now()),
            ),
        )
        connection.execute(
            """
            INSERT INTO skill_releases(version, file_name, file_path, sha256, release_notes, published_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "1.0",
                historical_package.name,
                str(historical_package),
                historical_digest,
                "历史版本",
                module.isoformat(module.utc_now() - timedelta(days=1)),
            ),
        )
        connection.execute(
            """
            INSERT INTO skill_releases(version, file_name, file_path, sha256, release_notes, published_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "1.1.0",
                package.name,
                str(package),
                digest,
                "测试版本",
                module.isoformat(module.utc_now()),
            ),
        )
        connection.commit()
    headers = api_headers(raw_token)
    with TestClient(module.app) as client:
        latest = client.get("/v1/skills/latest", headers=headers)
        assert latest.status_code == 200
        assert latest.json()["version"] == "1.1.0"
        assert latest.json()["sha256"] == digest
        download = client.get("/v1/skills/latest/download", headers=headers)
        assert download.status_code == 200
        assert download.content == b"test-skill-package"
        login = client.post(
            "/login",
            data={"username": "member", "password": "member-password-123"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)
        skills_page = client.get("/skills")
        assert skills_page.status_code == 200
        assert "企业全生命周期助手 V1.0" in skills_page.text
        assert "下载 V1.0 通用包" not in skills_page.text
        with closing(module.database()) as connection:
            historical_id = connection.execute(
                "SELECT id FROM skill_releases WHERE version='1.0'"
            ).fetchone()[0]
        historical_download = client.get(f"/skills/releases/{historical_id}/download")
        assert historical_download.status_code == 200
        assert historical_download.content == b"historical-skill-package"


def test_workbuddy_downloads_show_platforms_without_confirmation_status(
    tmp_path,
    monkeypatch,
):
    module = load_app(tmp_path)
    allow_test_release_artifacts(monkeypatch, module)
    monkeypatch.setattr(
        module,
        "workbuddy_artifact_is_simple_remote_mcp",
        lambda artifact: bool(artifact),
    )
    macos_package = module.SKILL_RELEASE_DIR / "共创研究院企业全生命周期助手-V1.2-WorkBuddy-macOS.zip"
    windows_package = module.SKILL_RELEASE_DIR / "共创研究院企业全生命周期助手-V1.2-WorkBuddy-Windows.zip"
    macos_package.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(macos_package, "w") as archive:
        archive.writestr("jiaotang/.codebuddy-plugin/marketplace.json", "{}")
        archive.writestr("jiaotang/plugins/plugin/.codebuddy-plugin/plugin.json", "{}")
        archive.writestr("jiaotang/plugins/plugin/hooks/workbuddy-hook.sh", "#!/bin/sh\n")
    with zipfile.ZipFile(windows_package, "w") as archive:
        archive.writestr("jiaotang/.codebuddy-plugin/marketplace.json", "{}")
        archive.writestr("jiaotang/plugins/plugin/.codebuddy-plugin/plugin.json", "{}")
        archive.writestr("jiaotang/plugins/plugin/hooks/workbuddy-hook.cmd", "@echo off\r\n")
    generic = tmp_path / "generic.zip"
    generic.write_bytes(b"generic")
    with closing(module.database()) as connection:
        connection.execute(
            "INSERT INTO users(username,password_hash,is_admin,created_at) VALUES (?,?,1,?)",
            (
                "member",
                module.password_hasher.hash("member-password-123"),
                module.isoformat(module.utc_now()),
            ),
        )
        release_cursor = connection.execute(
            """
            INSERT INTO skill_releases(version,file_name,file_path,sha256,release_notes,published_at)
            VALUES (?,?,?,?,?,?)
            """,
            (
                "1.2",
                generic.name,
                str(generic),
                hashlib.sha256(generic.read_bytes()).hexdigest(),
                "V1.2",
                module.isoformat(module.utc_now()),
            ),
        )
        connection.executemany(
            """
            INSERT INTO skill_release_artifacts(
                release_id,target,file_name,file_path,sha256
            ) VALUES (?,?,?,?,?)
            """,
            [
                (
                    release_cursor.lastrowid,
                    "macos",
                    macos_package.name,
                    str(macos_package),
                    hashlib.sha256(macos_package.read_bytes()).hexdigest(),
                ),
                (
                    release_cursor.lastrowid,
                    "windows",
                    windows_package.name,
                    str(windows_package),
                    hashlib.sha256(windows_package.read_bytes()).hexdigest(),
                ),
            ],
        )
        connection.commit()

    with TestClient(module.app) as client:
        login = client.post(
            "/login",
            data={"username": "member", "password": "member-password-123"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)
        page = client.get("/skills")
        assert "macOS" in page.text
        assert "Windows" in page.text
        assert "macOS 与 Windows 使用两个独立签名插件市场 ZIP" in page.text
        assert "固定三产物" in page.text
        assert "其他宿主不再规划或展示平台专用版本" in page.text
        assert "平台增强版 · TRAE" not in page.text
        assert "平台插件版 · Kimi Code" not in page.text
        assert "等待人工反馈" not in page.text
        assert "人工反馈" not in page.text
        assert "自动实机证据" not in page.text
        assert "GitHub Job" not in page.text
        assert "OIDC 签名证明" not in page.text
        macos_download = client.get("/skills/latest/workbuddy/macos/download")
        windows_download = client.get("/skills/latest/workbuddy/windows/download")
        assert macos_download.status_code == 200
        assert windows_download.status_code == 200
        assert macos_download.content == macos_package.read_bytes()
        assert windows_download.content == windows_package.read_bytes()
        assert macos_download.content != windows_download.content
        assert client.get("/skills/latest/workbuddy/download").status_code == 409


def test_legacy_platform_artifacts_do_not_feed_unified_workbuddy_channel(
    tmp_path,
    monkeypatch,
):
    module = load_app(tmp_path)
    allow_test_release_artifacts(monkeypatch, module)
    generic = tmp_path / "generic-v1.3.1.zip"
    generic.write_bytes(b"generic-v1.3.1")
    macos = tmp_path / "workbuddy-macos-v1.3.1.zip"
    windows = tmp_path / "workbuddy-windows-v1.3.1.1.zip"
    with zipfile.ZipFile(macos, "w") as archive:
        archive.writestr("jiaotang/.codebuddy-plugin/marketplace.json", "{}")
        archive.writestr("jiaotang/plugins/plugin/.codebuddy-plugin/plugin.json", "{}")
    with zipfile.ZipFile(windows, "w") as archive:
        archive.writestr("jiaotang/.codebuddy-plugin/marketplace.json", "{}")
        archive.writestr("jiaotang/plugins/plugin/.codebuddy-plugin/plugin.json", "{}")
    with closing(module.database()) as connection:
        user_cursor = connection.execute(
            "INSERT INTO users(username,password_hash,is_admin,created_at) VALUES (?,?,1,?)",
            (
                "member",
                module.password_hasher.hash("member-password-123"),
                module.isoformat(module.utc_now()),
            ),
        )
        token_seed = "legacy-platform-channel-token"
        raw_token = module.user_access_token(user_cursor.lastrowid, token_seed)
        connection.execute(
            """
            INSERT INTO device_tokens(
                user_id,label,token_prefix,token_hash,token_seed,created_at
            ) VALUES (?,?,?,?,?,?)
            """,
            (
                user_cursor.lastrowid,
                "legacy-platform-client",
                raw_token[:12],
                module.token_hash(raw_token),
                token_seed,
                module.isoformat(module.utc_now()),
            ),
        )
        old_cursor = connection.execute(
            """
            INSERT INTO skill_releases(
                version,file_name,file_path,sha256,release_notes,published_at
            ) VALUES (?,?,?,?,?,?)
            """,
            (
                "1.3.1",
                generic.name,
                str(generic),
                hashlib.sha256(generic.read_bytes()).hexdigest(),
                "V1.3.1",
                module.isoformat(module.utc_now() - timedelta(days=1)),
            ),
        )
        new_cursor = connection.execute(
            """
            INSERT INTO skill_releases(
                version,file_name,file_path,sha256,release_notes,published_at
            ) VALUES (?,?,?,?,?,?)
            """,
            (
                "1.3.1.1",
                windows.name,
                str(windows),
                hashlib.sha256(windows.read_bytes()).hexdigest(),
                "Windows hotfix",
                module.isoformat(module.utc_now()),
            ),
        )
        windows_release_id = new_cursor.lastrowid
        connection.executemany(
            """
            INSERT INTO skill_release_artifacts(
                release_id,target,file_name,file_path,sha256
            ) VALUES (?,?,?,?,?)
            """,
            [
                (
                    old_cursor.lastrowid,
                    "generic",
                    generic.name,
                    str(generic),
                    hashlib.sha256(generic.read_bytes()).hexdigest(),
                ),
                (
                    old_cursor.lastrowid,
                    "macos",
                    macos.name,
                    str(macos),
                    hashlib.sha256(macos.read_bytes()).hexdigest(),
                ),
                (
                    new_cursor.lastrowid,
                    "windows",
                    windows.name,
                    str(windows),
                    hashlib.sha256(windows.read_bytes()).hexdigest(),
                ),
            ],
        )
        connection.commit()

    with TestClient(module.app) as client:
        login = client.post(
            "/login",
            data={"username": "member", "password": "member-password-123"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)
        web_channels = client.get("/v1/web/skills/channels")
        assert web_channels.status_code == 200
        web_artifacts = {
            item["id"]: item for item in web_channels.json()["channels"]
        }
        assert web_artifacts["generic"]["download_url"] == "/skills/latest/download"
        assert set(web_artifacts) == {"generic", "macos", "windows"}
        assert web_artifacts["macos"]["available"] is False
        assert web_artifacts["windows"]["available"] is False
        assert client.get("/skills/latest/download").content == generic.read_bytes()
        for path in (
            "/skills/latest/workbuddy/macos/download",
            "/skills/latest/workbuddy/windows/download",
        ):
            assert client.get(path).status_code == 404
        assert client.get("/skills/latest/workbuddy/download").status_code == 409
        historical = client.get(
            f"/skills/releases/{windows_release_id}/workbuddy/download"
        )
        assert historical.status_code == 200
        assert historical.content == windows.read_bytes()
        page = client.get("/skills")
        assert page.status_code == 200
        assert "打开双端管理器" not in page.text
        assert "固定三产物" in page.text
        assert "平台增强版 · TRAE" not in page.text
        assert "平台增强版 · Qoder" not in page.text
        assert "平台增强版 · 通义灵码" not in page.text
        assert "平台插件版 · Kimi Code" not in page.text
        assert "平台增强版 · Cherry Studio" not in page.text
        assert (
            'class="skill-platform-card is-workbuddy" data-platform-version=""'
            in page.text
        )
        assert "当前版本未包含" in page.text
        assert "下载 WorkBuddy 包" not in page.text
        assert "下载 macOS 包" not in page.text
        assert "下载 Windows 包" not in page.text
        assert client.get("/v1/skills/channels").status_code == 401
        channels = client.get(
            "/v1/skills/channels",
            headers=api_headers(raw_token),
        )
        assert channels.status_code == 200
        assert channels.json()["schema"] == "jiaotang-skill-channels/v1"
        artifacts = {item["id"]: item for item in channels.json()["channels"]}
        assert artifacts["generic"]["version"] == "1.3.1"
        assert set(artifacts) == {"generic", "macos", "windows"}
        assert artifacts["macos"]["available"] is False
        assert artifacts["windows"]["available"] is False


def test_workbuddy_distribution_revision_uses_public_intro_without_rewriting_audit_notes(
    tmp_path,
):
    module = load_app(tmp_path)
    package = tmp_path / "workbuddy-universal.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("jiaotang/.codebuddy-plugin/marketplace.json", "{}")
        archive.writestr(
            "jiaotang/plugins/plugin/.codebuddy-plugin/plugin.json",
            "{}",
        )
    with closing(module.database()) as connection:
        connection.execute(
            "INSERT INTO users(username,password_hash,is_admin,created_at) VALUES (?,?,1,?)",
            (
                "member",
                module.password_hasher.hash("member-password-123"),
                module.isoformat(module.utc_now()),
            ),
        )
        release_cursor = connection.execute(
            """
            INSERT INTO skill_releases(
                version,file_name,file_path,sha256,release_notes,published_at
            ) VALUES (?,?,?,?,?,?)
            """,
            (
                "1.3.1.2",
                "historical-windows.zip",
                "/retained/historical-windows.zip",
                "historical",
                "初始 Windows 历史说明",
                module.isoformat(module.utc_now() - timedelta(days=1)),
            ),
        )
        connection.execute(
            """
            INSERT INTO skill_release_artifacts(
                release_id,target,file_name,file_path,sha256
            ) VALUES (?,?,?,?,?)
            """,
            (
                release_cursor.lastrowid,
                "workbuddy",
                package.name,
                str(package),
                hashlib.sha256(package.read_bytes()).hexdigest(),
            ),
        )
        now = module.isoformat(module.utc_now())
        connection.execute(
            """
            INSERT INTO skill_release_artifact_stages(
                version,target,status,file_path,sha256,release_notes,
                git_commit,github_url,staged_at,promoted_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "1.3.1.2",
                "workbuddy",
                "published",
                str(package),
                hashlib.sha256(package.read_bytes()).hexdigest(),
                "跨平台分发修订：移除外层固定安装器。",
                "abc123",
                "https://github.example/workbuddy-universal-v1.3.1.2-r1",
                now,
                now,
            ),
        )
        connection.commit()

    with TestClient(module.app) as client:
        login = client.post(
            "/login",
            data={"username": "member", "password": "member-password-123"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)
        page = client.get("/skills")
        assert page.status_code == 200
        assert "查看 WorkBuddy 分发修订说明" in page.text
        assert "跨平台分发修订：移除外层固定安装器。" in page.text
        assert "查看不可变发行记录" in page.text
        assert "一、本版本新增功能" in page.text
        assert "初始 Windows 历史说明" not in page.text

        with closing(module.database()) as connection:
            stored_notes = connection.execute(
                "SELECT release_notes FROM skill_releases WHERE version='1.3.1.2'"
            ).fetchone()["release_notes"]
        assert stored_notes == "初始 Windows 历史说明"


@pytest.mark.parametrize(
    "stage_status",
    ["releasing", "staged-awaiting-acceptance"],
)
def test_skills_page_shows_releasing_stage_without_replacing_latest(
    tmp_path,
    monkeypatch,
    stage_status,
):
    module = load_app(tmp_path)
    allow_test_release_artifacts(monkeypatch, module)
    generic = tmp_path / "generic-v1.3.zip"
    generic.write_bytes(b"published-generic")
    staged_generic = tmp_path / "staged-generic-v1.4.zip"
    staged_workbuddy = tmp_path / "staged-workbuddy-v1.4.zip"
    staged_generic.write_bytes(b"staged-generic")
    staged_workbuddy.write_bytes(b"staged-workbuddy")
    now = module.isoformat(module.utc_now())
    with closing(module.database()) as connection:
        connection.execute(
            "INSERT INTO users(username,password_hash,is_admin,created_at) VALUES (?,?,1,?)",
            (
                "member",
                module.password_hasher.hash("member-password-123"),
                now,
            ),
        )
        connection.execute(
            """
            INSERT INTO skill_releases(version,file_name,file_path,sha256,release_notes,published_at)
            VALUES (?,?,?,?,?,?)
            """,
            (
                "1.3",
                generic.name,
                str(generic),
                hashlib.sha256(generic.read_bytes()).hexdigest(),
                "V1.3 current",
                now,
            ),
        )
        connection.execute(
            """
            INSERT INTO skill_release_stages(
                version,status,generic_path,generic_sha256,
                workbuddy_path,workbuddy_sha256,release_notes,
                git_commit,github_url,staged_at,promoted_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,NULL)
            """,
            (
                "1.4",
                stage_status,
                str(staged_generic),
                hashlib.sha256(staged_generic.read_bytes()).hexdigest(),
                str(staged_workbuddy),
                hashlib.sha256(staged_workbuddy.read_bytes()).hexdigest(),
                "V1.4 staged",
                "abc123",
                "https://github.example/releases/V1.4",
                now,
            ),
        )
        connection.commit()

    with TestClient(module.app) as client:
        login = client.post(
            "/login",
            data={"username": "member", "password": "member-password-123"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)
        page = client.get("/skills")
        assert page.status_code == 200
        assert f'data-release-stage="{stage_status}"' in page.text
        assert "正式发布中" in page.text
        assert "企业全生命周期助手 V1.4" in page.text
        assert "等待主人确认正式发布" in page.text
        assert "企业全生命周期助手 V1.3" in page.text
        current_download = client.get("/skills/latest/download")
        assert current_download.status_code == 200
        assert current_download.content == generic.read_bytes()


def test_selective_macos_release_preserves_only_historical_client_downloads(
    tmp_path,
    monkeypatch,
):
    module = load_app(tmp_path)
    allow_test_release_artifacts(monkeypatch, module)
    old_generic = tmp_path / "generic-v1.3.1.zip"
    new_macos = tmp_path / "macos-v1.3.1.1.zip"
    old_generic.write_bytes(b"legacy-generic")
    with zipfile.ZipFile(new_macos, "w") as archive:
        archive.writestr("jiaotang/.codebuddy-plugin/marketplace.json", "{}")
        archive.writestr("jiaotang/plugins/plugin/.codebuddy-plugin/plugin.json", "{}")
    module.SKILL_RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    old_workbuddy = (
        module.SKILL_RELEASE_DIR
        / "共创研究院企业全生命周期助手-V1.3.1-WorkBuddy.zip"
    )
    with zipfile.ZipFile(old_workbuddy, "w") as archive:
        archive.writestr("jiaotang/.codebuddy-plugin/marketplace.json", "{}")
        archive.writestr("jiaotang/plugins/plugin/.codebuddy-plugin/plugin.json", "{}")
    with closing(module.database()) as connection:
        connection.execute(
            "INSERT INTO users(username,password_hash,is_admin,created_at) VALUES (?,?,1,?)",
            (
                "member",
                module.password_hasher.hash("member-password-123"),
                module.isoformat(module.utc_now()),
            ),
        )
        old_cursor = connection.execute(
            """
            INSERT INTO skill_releases(
                version,file_name,file_path,sha256,release_notes,published_at
            ) VALUES (?,?,?,?,?,?)
            """,
            (
                "1.3.1",
                old_generic.name,
                str(old_generic),
                hashlib.sha256(old_generic.read_bytes()).hexdigest(),
                "V1.3.1",
                module.isoformat(module.utc_now() - timedelta(days=1)),
            ),
        )
        old_release_id = old_cursor.lastrowid
        new_cursor = connection.execute(
            """
            INSERT INTO skill_releases(
                version,file_name,file_path,sha256,release_notes,published_at
            ) VALUES (?,?,?,?,?,?)
            """,
            (
                "1.3.1.1",
                new_macos.name,
                str(new_macos),
                hashlib.sha256(new_macos.read_bytes()).hexdigest(),
                "macOS MCP hotfix",
                module.isoformat(module.utc_now()),
            ),
        )
        new_release_id = new_cursor.lastrowid
        connection.execute(
            """
            INSERT INTO skill_release_artifacts(
                release_id,target,file_name,file_path,sha256
            ) VALUES (?,?,?,?,?)
            """,
            (
                new_cursor.lastrowid,
                "macos",
                new_macos.name,
                str(new_macos),
                hashlib.sha256(new_macos.read_bytes()).hexdigest(),
            ),
        )
        connection.commit()

    with TestClient(module.app) as client:
        login = client.post(
            "/login",
            data={"username": "member", "password": "member-password-123"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)
        assert client.get("/skills/latest/download").content == old_generic.read_bytes()
        for path in (
            "/skills/latest/workbuddy/macos/download",
            "/skills/latest/workbuddy/windows/download",
        ):
            assert client.get(path).status_code == 404
        assert client.get("/skills/latest/workbuddy/download").status_code == 409
        old_historical = client.get(
            f"/skills/releases/{old_release_id}/workbuddy/download"
        )
        assert old_historical.status_code == 404
        macos_historical = client.get(
            f"/skills/releases/{new_release_id}/workbuddy/download"
        )
        assert macos_historical.status_code == 200
        assert macos_historical.content == new_macos.read_bytes()


def test_release_announcement_appears_once_after_publish(tmp_path):
    module = load_app(tmp_path)
    with TestClient(module.app) as client:
        client.post(
            "/setup",
            data={"setup_key": "setup-secret", "username": "owner", "password": "correct-horse-battery"},
        )
        login = client.post(
            "/login",
            data={"username": "owner", "password": "correct-horse-battery"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)
        user = module.session_user(login.cookies[module.SESSION_COOKIE])[0]
        with closing(module.database()) as connection:
            release_id = connection.execute(
                """
                INSERT INTO skill_releases(version,file_name,file_path,sha256,release_notes,published_at)
                VALUES ('1.0','skills-v1.0.zip','/tmp/skills-v1.0.zip','digest','首版',?)
                """,
                (module.isoformat(module.utc_now()),),
            ).lastrowid
            connection.execute(
                """
                INSERT INTO release_announcements(release_id,title,body,quick_phrases,status,updated_at,published_at)
                VALUES (?,?,?,?,'published',?,?)
                """,
                (
                    release_id,
                    "欢迎使用企业全生命周期助手 V1.0",
                    "## 首次使用",
                    json.dumps(["帮我分析企业"], ensure_ascii=False),
                    module.isoformat(module.utc_now()),
                    module.isoformat(module.utc_now()),
                ),
            )
            connection.commit()
        portal = client.get("/portal")
        assert "欢迎使用企业全生命周期助手 V1.0" in portal.text
        assert "data-release-dialog" in portal.text
        assert '<dialog class="release-dialog" open' not in portal.text
        acknowledged = client.post(
            f"/releases/{release_id}/acknowledge",
            data={"csrf_token": user["csrf_token"]},
            follow_redirects=False,
        )
        assert acknowledged.status_code == 303
        assert "欢迎使用企业全生命周期助手 V1.0" not in client.get("/portal").text


def test_admin_incremental_index_release_and_rollback(tmp_path, monkeypatch):
    module = load_app(tmp_path)
    allow_test_release_artifacts(monkeypatch, module)
    with closing(module.database()) as connection:
        connection.execute(
            "INSERT INTO users(username, password_hash, is_admin, created_at) VALUES (?, ?, 1, ?)",
            ("owner", module.password_hasher.hash("owner-password-123"), module.isoformat(module.utc_now())),
        )
        user_id = connection.execute("SELECT id FROM users WHERE username = 'owner'").fetchone()[0]
        token_seed = "test-admin-token-seed"
        raw_token = module.user_access_token(user_id, token_seed)
        connection.execute(
            """
            INSERT INTO device_tokens(user_id, label, token_prefix, token_hash, token_seed, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user_id, "admin-test", raw_token[:12], module.token_hash(raw_token), token_seed,
                module.isoformat(module.utc_now()),
            ),
        )
        connection.commit()
    headers = api_headers(raw_token)
    with TestClient(module.app) as client:
        login = client.post(
            "/login",
            data={"username": "owner", "password": "owner-password-123"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)
        user = module.session_user(login.cookies[module.SESSION_COOKIE])[0]
        update = client.post(
            "/admin/knowledge-updates",
            data={
                "document_role": "10_政策与通知",
                "csrf_token": user["csrf_token"],
            },
            files={
                "knowledge_file": (
                    "新增政策.md",
                    (
                        "增量测试政策要求企业建立独立研发机构并持续保持研发投入，"
                        "配备稳定研发人员、研发场地和成果转化机制，形成完整技术创新体系。"
                    ).encode(),
                    "text/markdown",
                )
            },
            follow_redirects=False,
        )
        assert update.status_code == 303
        with closing(module.database()) as connection:
            job = connection.execute(
                "SELECT id, status, snapshot_path FROM knowledge_update_jobs ORDER BY id DESC LIMIT 1"
            ).fetchone()
        assert job["status"] == "indexed"
        assert module.Path(job["snapshot_path"]).is_file()
        sync_request = json.loads(module.OSS_SYNC_REQUEST_PATH.read_text(encoding="utf-8"))
        assert sync_request["reason"] == f"knowledge-upload-indexed:{job['id']}"
        search = client.post(
            "/v1/search",
            headers=headers,
            json={"query": "增量测试政策", "limit": 5},
        )
        assert search.status_code == 200
        assert any(item["title"] == "新增政策.md" for item in search.json()["results"])

        archive = complete_skill_release_fixture(module.SKILL_SOURCE_DIR)
        release = client.post(
            "/admin/skill-releases",
            data={
                "version": "1.2.0",
                "release_notes": "新增测试技能",
                "csrf_token": user["csrf_token"],
            },
            files={"skill_package": ("skills-1.2.0.zip", archive, "application/zip")},
            follow_redirects=False,
        )
        assert release.status_code == 303
        latest = client.get("/v1/skills/latest", headers=headers)
        assert latest.json()["version"] == "1.2.0"
        web_download = client.get("/skills/latest/download")
        assert web_download.status_code == 200

        rollback = client.post(
            f"/admin/knowledge-updates/{job['id']}/rollback",
            data={"csrf_token": user["csrf_token"]},
            follow_redirects=False,
        )
        assert rollback.status_code == 303
        sync_request = json.loads(module.OSS_SYNC_REQUEST_PATH.read_text(encoding="utf-8"))
        assert sync_request["reason"] == f"knowledge-upload-rollback:{job['id']}"
        after_rollback = client.post(
            "/v1/search",
            headers=headers,
            json={"query": "增量测试政策", "limit": 5},
        )
        assert after_rollback.status_code == 200
        assert after_rollback.json()["results"] == []


def test_extraction_cache_retries_non_success_statuses():
    assert cache_status_reusable("indexed")
    assert not cache_status_reusable("ocr_required")
    assert not cache_status_reusable("convert_required")
    assert not cache_status_reusable("error:ModuleNotFoundError")


def test_mcp_search_uses_personal_bearer_token(tmp_path):
    module = load_app(tmp_path)
    with closing(sqlite3.connect(module.CONTENT_DATABASE_PATH)) as connection:
        connection.executescript(
            """
            CREATE TABLE national_small_giant_master(
                id INTEGER PRIMARY KEY,
                enterprise_name TEXT,normalized_name TEXT,unified_social_credit_code TEXT,qice_eid TEXT,
                region TEXT,city TEXT,county TEXT,recognition_year INTEGER,batch TEXT,status TEXT,
                official_url TEXT,official_url_role TEXT,official_fragment_key TEXT,verification_status TEXT,
                sequence_no TEXT,platform_year_raw TEXT,former_names_json TEXT,
                source_documents_json TEXT,source_paths_json TEXT
            );
            INSERT INTO national_small_giant_master VALUES(
                1,'杭州MCP权威测试公司','','','','浙江省','杭州市','余杭区',2024,'第六批','认定',
                'https://example.gov.cn/list','official_batch_notice','',
                'official_local_fragment_match','','','[]','[1]','["官方名单.pdf"]'
            );
            """
        )
        connection.commit()
    with closing(module.database()) as connection:
        connection.execute(
            "INSERT INTO users(username, password_hash, created_at) VALUES (?, ?, ?)",
            ("member", module.password_hasher.hash("member-password-123"), module.isoformat(module.utc_now())),
        )
        user_id = connection.execute("SELECT id FROM users WHERE username = 'member'").fetchone()[0]
        token_seed = "test-mcp-token-seed"
        raw_token = module.user_access_token(user_id, token_seed)
        connection.execute(
            """
            INSERT INTO device_tokens(user_id, label, token_prefix, token_hash, token_seed, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user_id, "王小明", raw_token[:12], module.token_hash(raw_token), token_seed,
                module.isoformat(module.utc_now()),
            ),
        )
        connection.execute(
            """
            INSERT INTO registration_authorizations(
                real_name,identity_code,status,user_id,created_at,registered_at
            ) VALUES (?,?, 'registered', ?, ?, ?)
            """,
            (
                "王小明",
                "0826",
                user_id,
                module.isoformat(module.utc_now()),
                module.isoformat(module.utc_now()),
            ),
        )
        connection.commit()
    private_key, key_id = provision_signed_device(module, user_id)

    def mcp_request(client, payload):
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = {
            **api_headers(raw_token),
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        return client.post("/mcp/", headers=headers, content=body)

    with TestClient(module.app) as client:
        assert client.post(
            "/mcp/",
            headers={"Accept": "application/json, text/event-stream"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        ).status_code == 401
        head_headers = {
            **api_headers(raw_token),
            "Accept": "application/json, text/event-stream",
        }
        assert client.head("/mcp/", headers=head_headers).status_code == 405
        ping = mcp_request(
            client,
            {"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}},
        )
        assert ping.status_code == 200
        tool_list = mcp_request(
            client,
            {"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}},
        )
        assert tool_list.status_code == 200
        tool_names = {
            item["name"] for item in tool_list.json()["result"]["tools"]
        }
        assert "authoritative_list_search" in tool_names
        assert "three_first_analysis" in tool_names
        assert "recognition_search" in tool_names
        assert "enterprise_lifecycle_decision" in tool_names
        assert "three_first_directory_diff" not in tool_names
        assert "three_first_product_match" not in tool_names
        response = mcp_request(
            client,
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "knowledge_search",
                    "arguments": {"query": "小巨人", "limit": 3},
                },
            },
        )
        assert response.status_code == 200
        first_result = response.json()["result"]["structuredContent"]["results"][0]
        assert "小巨人" in first_result["title"]
        assert "source_layer" not in first_result
        document = mcp_request(
            client,
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "knowledge_document",
                    "arguments": {"document_id": first_result["document_id"]},
                },
            },
        )
        assert document.status_code == 200
        authoritative = mcp_request(
            client,
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {
                    "name": "authoritative_list_search",
                    "arguments": {
                        "list_type": "national_small_giant",
                        "year": 2024,
                        "batch": "第六批",
                        "region": "杭州市",
                        "limit": 1,
                    },
                },
            },
        )
        assert authoritative.status_code == 200
        authoritative_payload = authoritative.json()["result"]["structuredContent"]
        assert authoritative_payload["total"] == 1
        assert authoritative_payload["summary"]["official_match_count"] == 1
        assert authoritative_payload["pagination"]["is_truncated"] is False
    with closing(module.database()) as connection:
        usage_rows = connection.execute(
            """
            SELECT endpoint,activity_type,activity_name,counts_toward_usage
            FROM api_usage ORDER BY id
            """
        ).fetchall()
        installation = connection.execute(
            """
            SELECT first_verified_at,mcp_connected_at
            FROM device_keys WHERE user_id=? AND key_id=?
            """,
            (user_id, key_id),
        ).fetchone()
    assert installation["first_verified_at"] is None
    assert installation["mcp_connected_at"] is None
    assert [row["activity_type"] for row in usage_rows] == [
        "mcp_connection",
        "mcp_connection",
        "mcp_tools_list",
        "mcp_search",
        "mcp_document",
        "mcp_search",
    ]
    assert [row["activity_name"] for row in usage_rows] == [
        "MCP连接检测",
        "MCP连接检测",
        "工具列表",
        "实际检索",
        "文档读取",
        "实际检索",
    ]
    assert [row["counts_toward_usage"] for row in usage_rows] == [0, 0, 0, 1, 1, 1]


def test_mcp_middleware_forwards_disconnect_after_replaying_body(tmp_path, monkeypatch):
    module = load_app(tmp_path)
    request_body = b'{"jsonrpc":"2.0","id":1,"method":"ping"}'
    received_messages = []
    upstream_messages = iter(
        [
            {"type": "http.request", "body": request_body, "more_body": False},
            {"type": "http.disconnect"},
        ]
    )

    async def receive():
        return next(upstream_messages)

    async def send(message):
        del message

    async def downstream(scope, downstream_receive, downstream_send):
        del scope, downstream_send
        received_messages.append(await downstream_receive())
        received_messages.append(await downstream_receive())

    monkeypatch.setattr(
        module,
        "authenticate_api_token",
        lambda *args, **kwargs: {"id": 1, "device_token_id": 1},
    )
    monkeypatch.setattr(module, "record_api_usage", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "mark_mcp_connected", lambda *args, **kwargs: None)

    middleware = module.MCPBearerMiddleware(downstream)
    asyncio.run(
        middleware(
            {
                "type": "http",
                "method": "POST",
                "path": "/mcp/",
                "query_string": b"",
                "headers": [],
                "client": ("127.0.0.1", 12345),
            },
            receive,
            send,
        )
    )

    assert received_messages == [
        {"type": "http.request", "body": request_body, "more_body": False},
        {"type": "http.disconnect"},
    ]


def test_admin_all_calls_shows_records_first_and_supports_pagination(tmp_path):
    module = load_app(tmp_path)
    now = module.isoformat(module.utc_now())
    with closing(module.database()) as connection:
        user_id = connection.execute(
            "INSERT INTO users(username, password_hash, real_name, is_admin, created_at) VALUES (?, ?, ?, 1, ?)",
            ("owner", module.password_hasher.hash("owner-password-123"), "管理员", now),
        ).lastrowid
        token_id = connection.execute(
            """
            INSERT INTO device_tokens(user_id,label,token_prefix,token_hash,token_seed,created_at)
            VALUES (?,?,?,?,?,?)
            """,
            (user_id, "管理员", "jtk_test", "test-token-hash", "test-seed", now),
        ).lastrowid
        connection.executemany(
            """
            INSERT INTO api_usage(
                user_id,device_token_id,endpoint,method,activity_type,
                activity_name,counts_toward_usage,called_at
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            [
                (user_id, token_id, f"/v1/search/{index}", "POST", "rest_api", "REST检索", 1, now)
                for index in range(55)
            ],
        )
        mcp_rows = []
        for activity_type, activity_name, count in (
            ("mcp_connection", "MCP连接检测", 2),
            ("mcp_tools_list", "工具列表", 3),
            ("mcp_search", "实际检索", 4),
            ("mcp_document", "文档读取", 5),
        ):
            mcp_rows.extend(
                (
                    user_id,
                    token_id,
                    "/mcp/",
                    "POST",
                    activity_type,
                    activity_name,
                    0,
                    now,
                )
                for index in range(count)
            )
        connection.executemany(
            """
            INSERT INTO api_usage(
                user_id,device_token_id,endpoint,method,activity_type,
                activity_name,counts_toward_usage,called_at
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            mcp_rows,
        )
        connection.commit()
    with TestClient(module.app) as client:
        login = client.post(
            "/login",
            data={"username": "owner", "password": "owner-password-123"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)
        first_page = client.get("/admin/health/calls")
        assert first_page.status_code == 200
        assert first_page.text.index("全部调用明细") < first_page.text.index("24小时业务调用")
        assert "按用户账号合并多台电脑" in first_page.text
        assert "</td><td>55</td><td>55</td><td>55</td><td>55</td><td>2</td><td>3</td><td>4</td><td>5</td>" in first_page.text
        assert "test-token-hash" not in first_page.text
        assert "第 1/2 页 · 共 69 条" in first_page.text
        assert "/v1/search/54" in first_page.text
        assert 'aria-current="page">1</a>' in first_page.text
        second_page = client.get("/admin/health/calls?page=2")
        assert "第 2/2 页 · 共 69 条" in second_page.text
        assert "/v1/search/0" in second_page.text


def test_admin_can_view_edit_and_rollback_knowledge(tmp_path):
    module = load_app(tmp_path)
    with closing(module.database()) as connection:
        connection.execute(
            "INSERT INTO users(username, password_hash, is_admin, created_at) VALUES (?, ?, 1, ?)",
            ("owner", module.password_hasher.hash("owner-password-123"), module.isoformat(module.utc_now())),
        )
        connection.commit()
    with TestClient(module.app) as client:
        login = client.post(
            "/login",
            data={"username": "owner", "password": "owner-password-123"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)
        user = module.session_user(login.cookies[module.SESSION_COOKIE])[0]
        portal = client.get("/portal")
        health_portal = client.get("/admin/operations")
        assert "/admin/health/index" in health_portal.text
        assert "/admin/health/oss" in health_portal.text
        assert "/admin/health/snapshot" not in health_portal.text
        assert "/admin/health/deploy-gate" in health_portal.text
        assert "/admin/knowledge" in portal.text
        health = client.get("/admin/health/index")
        assert health.status_code == 200
        assert "全文资料" in health.text
        deploy_gate_health = client.get("/admin/health/deploy-gate")
        assert deploy_gate_health.status_code == 200
        assert "部署签名覆盖" in deploy_gate_health.text
        assert "套件内容完整性" in deploy_gate_health.text
        access_health = client.get("/admin/health/access")
        assert access_health.status_code == 200
        assert "具体用户" in access_health.text
        assert "owner" in access_health.text
        calls_health = client.get("/admin/health/calls")
        assert calls_health.status_code == 200
        assert "/admin/health/calls?activity=mcp_tools_list" in calls_health.text
        tool_list_health = client.get("/admin/health/calls?activity=mcp_tools_list")
        assert tool_list_health.status_code == 200
        assert "客户端读取当前MCP提供的工具清单" in tool_list_health.text
        assert "查看全部调用" in tool_list_health.text
        knowledge = client.get("/admin/knowledge?query=小巨人")
        assert knowledge.status_code == 200
        assert "小巨人测试资料" in knowledge.text
        fuzzy_knowledge = client.get("/admin/knowledge?query=2025小巨人")
        assert fuzzy_knowledge.status_code == 200
        assert "2025年浙江省专精特新小巨人申报通知" in fuzzy_knowledge.text
        assert "2025年浙江省第六批专精特新小巨人认定名单" in fuzzy_knowledge.text
        assert "第 1/1 页 · 每页30份" in knowledge.text
        assert 'aria-current="page">1</a>' in knowledge.text
        ordered_knowledge = client.get("/admin/knowledge")
        assert ordered_knowledge.text.index("0001") < ordered_knowledge.text.index("0002")
        assert "编号升序" in ordered_knowledge.text
        assert "移入回收站" in ordered_knowledge.text
        assert "2026-07-18T00:00:00+00:00" not in ordered_knowledge.text
        assert "2026-07-18 08:00:00" in ordered_knowledge.text
        access_portal = client.get("/access")
        assert "www.tianyancha.com/ai" in access_portal.text
        assert "agent.qcc.com/invitation?code=3ZRZPHF7Q5MH4" in access_portal.text
        assert "docs.cloud.google.com/bigquery/docs/use-bigquery-mcp" in access_portal.text
        assert "aiqice.cn" not in access_portal.text
        assert "pss-system.cponline.cnipa.gov.cn" not in access_portal.text
        assert "epo.org/en/searching-for-patents" not in portal.text
        assert "DeepSeek开放平台" not in portal.text
        assert client.get("/mcp").status_code == 401
        edit = client.post(
            "/admin/knowledge/1",
            data={
                "title": "小巨人修订资料",
                "content": "修订后的研究院申报条件和研发机构要求",
                "source": "管理员修订测试",
                "document_role": "20_项目规则与指南",
                "csrf_token": user["csrf_token"],
            },
            follow_redirects=False,
        )
        assert edit.status_code == 303
        assert module.get_knowledge_document(1)["title"] == "小巨人修订资料"
        assert module.search_knowledge("研究院")["results"][0]["document_id"] == 1
        with closing(module.database()) as connection:
            revision = connection.execute(
                "SELECT id, snapshot_path FROM knowledge_document_revisions ORDER BY id DESC LIMIT 1"
            ).fetchone()
        assert module.Path(revision["snapshot_path"]).is_file()
        rollback = client.post(
            f"/admin/knowledge-revisions/{revision['id']}/rollback",
            data={"csrf_token": user["csrf_token"]},
            follow_redirects=False,
        )
        assert rollback.status_code == 303
        assert module.get_knowledge_document(1)["title"] == "小巨人测试资料"
        trash_confirm = client.get("/admin/knowledge/1/trash")
        assert trash_confirm.status_code == 200
        assert "不会永久删除原文件" in trash_confirm.text
        move_to_trash = client.post(
            "/admin/knowledge/1/trash",
            data={"csrf_token": user["csrf_token"]},
            follow_redirects=False,
        )
        assert move_to_trash.status_code == 303
        assert move_to_trash.headers["location"] == "/admin/knowledge-trash"
        assert module.search_knowledge("产业链关键环节")["results"] == []
        trash_page = client.get("/admin/knowledge-trash")
        assert trash_page.status_code == 200
        assert "小巨人测试资料" in trash_page.text
        with closing(module.database()) as connection:
            trash_id = connection.execute(
                "SELECT id FROM knowledge_document_trash WHERE document_id = 1"
            ).fetchone()["id"]
        restore = client.post(
            f"/admin/knowledge-trash/{trash_id}/restore",
            data={"csrf_token": user["csrf_token"]},
            follow_redirects=False,
        )
        assert restore.status_code == 303
        restored = module.search_knowledge("产业链关键环节")["results"]
        assert restored[0]["document_id"] == 1


def test_pagination_window_has_numbers_and_ellipses(tmp_path):
    module = load_app(tmp_path)
    assert module.pagination_window(1, 1) == [1]
    assert module.pagination_window(6, 12) == [1, None, 4, 5, 6, 7, 8, None, 12]


def test_login_rate_limit_is_ip_scoped_and_proxy_headers_are_fail_closed(tmp_path):
    module = load_app(tmp_path)
    now = module.isoformat(module.utc_now())
    with closing(module.database()) as connection:
        connection.execute(
            """
            INSERT INTO users(username,password_hash,is_admin,created_at)
            VALUES (?,?,1,?)
            """,
            ("owner", module.password_hasher.hash("owner-password-123"), now),
        )
        connection.executemany(
            """
            INSERT INTO auth_attempts(
                action,username,client_ip,succeeded,attempted_at
            ) VALUES ('login',?,?,0,?)
            """,
            [
                ("owner", "198.51.100.24", now)
                for _ in range(10)
            ],
        )
        connection.commit()
        assert module.auth_attempts_blocked(
            connection,
            "login",
            "unrelated-account",
            "198.51.100.24",
            10,
        )
        assert not module.auth_attempts_blocked(
            connection,
            "login",
            "owner",
            "203.0.113.25",
            10,
        )

    with TestClient(module.app) as client:
        login = client.post(
            "/login",
            data={"username": "owner", "password": "owner-password-123"},
            follow_redirects=False,
        )
    assert login.status_code == 303
    assert module.client_ip_from_peer(
        "203.0.113.25",
        "10.0.0.8",
    ) == "203.0.113.25"
    assert module.client_ip_from_peer(
        "127.0.0.1",
        "198.51.100.24",
    ) == "198.51.100.24"


def test_registration_invite_reissue_expiry_entropy_and_one_use(tmp_path):
    module = load_app(tmp_path)
    now = module.isoformat(module.utc_now())
    with closing(module.database()) as connection:
        connection.execute(
            """
            INSERT INTO users(username,password_hash,is_admin,created_at)
            VALUES (?,?,1,?)
            """,
            ("owner", module.password_hasher.hash("owner-password-123"), now),
        )
        authorization_id = int(
            connection.execute(
                """
                INSERT INTO registration_authorizations(
                    real_name,identity_code,status,created_at
                ) VALUES (?,?,'pending',?)
                """,
                ("王小明", "0826", now),
            ).lastrowid
        )
        first = issue_test_invitation(module, connection, authorization_id)
        second = issue_test_invitation(module, connection, authorization_id)
        connection.commit()

    first_parts = first.split(".")
    second_parts = second.split(".")
    assert len(first_parts) == len(second_parts) == 3
    assert len(second_parts[1]) >= 40
    assert len(second_parts[2]) >= 40
    assert first != second
    assert module.registration_authorization_from_invite(first) is None
    assert module.registration_authorization_from_invite(second) is not None

    with closing(module.database()) as connection:
        connection.execute(
            "UPDATE registration_authorizations SET invite_expires_at=? WHERE id=?",
            (
                module.isoformat(module.utc_now() - timedelta(seconds=1)),
                authorization_id,
            ),
        )
        connection.commit()
    assert module.registration_authorization_from_invite(second) is None

    with closing(module.database()) as connection:
        third = module.registration_invite_token(
            module.issue_registration_invite(
                connection,
                authorization_id,
                issued_by=None,
            )
        )
        connection.commit()

    registration = {
        "invite_token": third,
        "username": "member-invited",
        "real_name": "伪造姓名",
        "identity_code": "9999",
        "company_name": "共创集团",
        "password": "member-password-123",
        "confirm_password": "member-password-123",
    }
    with TestClient(module.app) as client:
        accepted = client.post(
            "/register",
            data=registration,
            follow_redirects=False,
        )
        replay = client.post(
            "/register",
            data={**registration, "username": "member-replay"},
            follow_redirects=False,
        )
    assert accepted.status_code == 303
    assert replay.status_code == 403
    assert "无效、已过期或已使用" in replay.text


def test_user_ai_network_guards_reject_private_redirect_large_and_concurrent(
    tmp_path,
    monkeypatch,
):
    module = load_app(tmp_path)

    monkeypatch.setattr(
        module.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (
                module.socket.AF_INET,
                module.socket.SOCK_STREAM,
                module.socket.IPPROTO_TCP,
                "",
                ("127.0.0.1", 443),
            )
        ],
    )
    with pytest.raises(ValueError, match="本机、内网或保留地址"):
        module.public_model_addresses("model.example.com")

    class OversizedResponse:
        def read(self, size):
            return b"x" * size

    with pytest.raises(ValueError, match="超过允许大小"):
        module.read_bounded_response(OversizedResponse(), limit=32)

    class RedirectResponseFixture:
        status = 302

        def read(self, size):
            return b""

    class RedirectingConnection:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return RedirectResponseFixture()

        def close(self):
            pass

    monkeypatch.setattr(
        module,
        "public_model_addresses",
        lambda hostname, port=443: ("8.8.8.8",),
    )
    monkeypatch.setattr(module, "PinnedHTTPSConnection", RedirectingConnection)
    with pytest.raises(ValueError, match="不允许HTTP重定向"):
        module.request_user_assistant_model(
            b"{}",
            {
                "api_base": "https://model.example.com",
                "api_key": "secret",
                "model": "chat",
                "user_id": 1,
            },
        )

    monkeypatch.setattr(module, "USER_AI_GLOBAL_SEMAPHORE", module.threading.BoundedSemaphore(2))
    monkeypatch.setattr(module, "USER_AI_PER_USER_CONCURRENCY", 1)
    monkeypatch.setattr(module, "USER_AI_USER_SEMAPHORES", {})
    with module.user_ai_request_slot(7):
        with pytest.raises(module.HTTPException) as limited:
            with module.user_ai_request_slot(7):
                pass
    assert limited.value.status_code == 429
    assert "当前账号已有" in limited.value.detail


def test_security_headers_storage_cache_robots_health_and_404_contract(tmp_path):
    module = load_app(tmp_path)
    template_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((module.BASE_DIR / "templates").glob("*.html"))
    )
    portal_script = (module.BASE_DIR / "static" / "portal.js").read_text(
        encoding="utf-8"
    )
    assert re.search(r"\s(?:on[a-z]+|style)\s*=", template_source, re.I) is None
    assert ".style." not in portal_script
    assert "USER_API_SESSION_STORAGE_KEY" in portal_script
    assert "sessionStorage.setItem(USER_API_SESSION_STORAGE_KEY" in portal_script
    assert "sessionStorage.removeItem(USER_API_SESSION_STORAGE_KEY" in portal_script
    assert "localStorage.setItem(USER_API_SESSION_STORAGE_KEY" not in portal_script
    assert "localStorage.getItem(USER_API_SESSION_STORAGE_KEY" not in portal_script
    assert "data-clear-sensitive-storage-on-load" in template_source
    assert template_source.count("data-clear-sensitive-storage") >= 4

    with TestClient(module.app) as client:
        demo = client.get("/demo")
        csp = demo.headers["content-security-policy"]
        assert "script-src 'self'" in csp
        assert "script-src-attr 'none'" in csp
        assert "style-src 'self'" in csp
        assert "style-src-attr 'none'" in csp
        assert "'unsafe-inline'" not in csp
        assert demo.headers["cache-control"] == "public, max-age=300"
        assert demo.headers["x-robots-tag"] == "index, follow"

        digest = hashlib.sha256(
            (module.BASE_DIR / "static" / "portal.js").read_bytes()
        ).hexdigest()[:16]
        versioned_static = client.get(f"/static/portal.js?v={digest}")
        unversioned_static = client.get("/static/portal.js")
        assert versioned_static.headers["cache-control"] == (
            "public, max-age=31536000, immutable"
        )
        assert unversioned_static.headers["cache-control"] == (
            "public, max-age=300, must-revalidate"
        )

        robots = client.get("/robots.txt")
        assert "Allow: /demo" in robots.text
        assert "Allow: /guide" not in robots.text
        assert "Disallow: /" in robots.text
        assert robots.headers["cache-control"] == "public, max-age=3600"

        live = client.get("/livez")
        ready = client.get("/readyz")
        build = client.get("/build")
        assert live.status_code == 200
        assert ready.status_code == 200
        assert build.status_code == 200
        assert build.headers["server-timing"].startswith("app;dur=")
        assert set(build.json()) >= {
            "schema",
            "commit",
            "deployment_id",
            "dependency_lock_sha256",
            "dependency_build_lock_sha256",
            "wheelhouse_install_lock_sha256",
            "wheelhouse_manifest_sha256",
            "wheelhouse_content_identity_sha256",
            "dependency_identity_sha256",
            "dependency_release_record_sha256",
            "private_overlay_identity_sha256",
            "candidate_version",
            "published_generic_version",
            "published_workbuddy_version",
            "workbuddy_installable",
        }

        html_missing = client.get("/missing-page")
        api_missing = client.get("/v1/missing-page")
        assert html_missing.status_code == 404
        assert "不在当前档案中" in html_missing.text
        assert html_missing.headers["cache-control"] == "private, no-store"
        assert api_missing.status_code == 404
        assert api_missing.json() == {"detail": "资源不存在"}
        assert api_missing.headers["cache-control"] == "no-store"


def test_privacy_worker_redacts_expired_question_without_new_request(
    tmp_path,
    monkeypatch,
):
    module = load_app(tmp_path)
    old_started_at = module.isoformat(
        module.utc_now()
        - timedelta(hours=module.ASSISTANT_QUESTION_RETENTION_HOURS + 1)
    )
    with closing(module.database()) as connection:
        user_id = int(
            connection.execute(
                """
                INSERT INTO users(username,password_hash,created_at)
                VALUES (?,?,?)
                """,
                (
                    "member",
                    module.password_hasher.hash("member-password-123"),
                    module.isoformat(module.utc_now()),
                ),
            ).lastrowid
        )
        usage_id = int(
            connection.execute(
                """
                INSERT INTO assistant_usage(
                    user_id,question,status,started_at,question_fingerprint
                ) VALUES (?,?,?,?,?)
                """,
                (
                    user_id,
                    "这是一条等待定时清理的原始问题",
                    "completed",
                    old_started_at,
                    module.assistant_question_fingerprint(
                        "这是一条等待定时清理的原始问题"
                    ),
                ),
            ).lastrowid
        )
        connection.commit()
    monkeypatch.setattr(module, "ASSISTANT_REDACTION_INTERVAL_SECONDS", 0.01)

    async def exercise_worker():
        stop_event = module.asyncio.Event()
        task = module.asyncio.create_task(
            module.assistant_question_redaction_worker(stop_event)
        )
        for _ in range(50):
            await module.asyncio.sleep(0.01)
            with closing(module.database()) as connection:
                row = connection.execute(
                    """
                    SELECT question,question_redacted_at
                    FROM assistant_usage WHERE id=?
                    """,
                    (usage_id,),
                ).fetchone()
            if row["question_redacted_at"]:
                break
        stop_event.set()
        await task
        return row

    redacted = module.asyncio.run(exercise_worker())
    assert redacted["question"] == "[已按隐私策略清理]"
    assert redacted["question_redacted_at"]
    privacy_status = json.loads(
        module.ASSISTANT_PRIVACY_STATUS_PATH.read_text(encoding="utf-8")
    )
    assert privacy_status["status"] == "正常"
    assert privacy_status["redacted_rows"] == 1


def test_unsafe_published_workbuddy_is_visible_but_not_installable(
    tmp_path,
    monkeypatch,
):
    module = load_app(tmp_path)
    generic = tmp_path / "generic-v1.4.1.zip"
    workbuddy = tmp_path / "workbuddy-v1.4.1.zip"
    generic.write_bytes(b"generic-v1.4.1")
    with zipfile.ZipFile(workbuddy, "w") as archive:
        archive.writestr(
            "jiaotang/.codebuddy-plugin/marketplace.json",
            "{}",
        )
        archive.writestr(
            "jiaotang/plugins/jiaotang-workbuddy-skills/"
            ".codebuddy-plugin/plugin.json",
            "{}",
        )
    now = module.isoformat(module.utc_now())
    with closing(module.database()) as connection:
        connection.execute(
            """
            INSERT INTO users(username,password_hash,is_admin,created_at)
            VALUES (?,?,1,?)
            """,
            ("owner", module.password_hasher.hash("owner-password-123"), now),
        )
        release_id = int(
            connection.execute(
                """
                INSERT INTO skill_releases(
                    version,file_name,file_path,sha256,release_notes,published_at
                ) VALUES (?,?,?,?,?,?)
                """,
                (
                    "1.4.1",
                    generic.name,
                    str(generic),
                    hashlib.sha256(generic.read_bytes()).hexdigest(),
                    "已发布但 WorkBuddy 安全能力不足",
                    now,
                ),
            ).lastrowid
        )
        connection.executemany(
            """
            INSERT INTO skill_release_artifacts(
                release_id,target,file_name,file_path,sha256
            ) VALUES (?,?,?,?,?)
            """,
            [
                (
                    release_id,
                    "generic",
                    generic.name,
                    str(generic),
                    hashlib.sha256(generic.read_bytes()).hexdigest(),
                ),
                (
                    release_id,
                    "workbuddy",
                    workbuddy.name,
                    str(workbuddy),
                    hashlib.sha256(workbuddy.read_bytes()).hexdigest(),
                ),
            ],
        )
        connection.commit()

    def selective_validation(artifact, *, target, require_signature):
        if target == "generic":
            return {"status": "verified", "signed_format": True}
        raise ValueError("missing signed root .mcp.json")

    monkeypatch.setattr(
        module,
        "validate_release_artifact_for_serving",
        selective_validation,
    )
    with TestClient(module.app) as client:
        login = client.post(
            "/login",
            data={"username": "owner", "password": "owner-password-123"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)
        skills = client.get("/skills")
        access = client.get("/access")
        blocked_download = client.get("/skills/latest/workbuddy/download")
        generic_download = client.get("/skills/latest/download")

    assert "已暂停新安装" in skills.text
    assert "等待安全正式版" in skills.text
    assert "data-manual-package-download" not in skills.text
    assert "data-copy-agent-bootstrap" not in access.text
    assert blocked_download.status_code == 409
    assert generic_download.status_code == 200
    assert generic_download.content == generic.read_bytes()


def test_operational_health_staleness_and_provenance_are_visible(tmp_path):
    module = load_app(tmp_path)
    now = module.isoformat(module.utc_now())
    stale = module.isoformat(module.utc_now() - timedelta(hours=3))
    module.HEALTH_STATUS_PATH.write_text(
        json.dumps(
            {
                "status": "正常",
                "checked_at": stale,
                "errors": ["数据库探测失败"],
                "warnings": ["证书将在30天内到期"],
                "failed_units": ["jiaotang-kb-index-refresh.service"],
                "current_release_id": "release-current",
                "previous_release_id": "release-previous",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    module.ASSISTANT_PRIVACY_STATUS_PATH.write_text(
        json.dumps({"status": "正常", "checked_at": now}),
        encoding="utf-8",
    )
    module.BACKUP_STATUS_PATH.write_text(
        json.dumps(
            {
                "status": "正常",
                "completed_at": now,
                "offsite_mode": "oss",
                "offsite_status": "verified",
                "artifacts": [
                    {
                        "label": "数据库",
                        "artifact": "knowledge.db.zst",
                        "size": 1024,
                        "sha256": "a" * 64,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    module.OSS_INDEX_CACHE_STATUS_PATH.write_text(
        json.dumps(
            {
                "status": "正常",
                "checked_at": now,
                "current_release_id": "oss-current",
                "previous_release_id": "oss-previous",
                "generation_consistent": False,
                "pointer_sha256": "b" * 64,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    with closing(module.database()) as connection:
        connection.execute(
            """
            INSERT INTO users(username,password_hash,is_admin,created_at)
            VALUES (?,?,1,?)
            """,
            ("owner", module.password_hasher.hash("owner-password-123"), now),
        )
        connection.commit()

    with TestClient(module.app) as client:
        login = client.post(
            "/login",
            data={"username": "owner", "password": "owner-password-123"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)
        portal = client.get("/portal")
        runtime = client.get("/admin/health/runtime")
        backup = client.get("/admin/health/backup")
        oss = client.get("/admin/health/oss")

    assert 'href="/admin/health/runtime" class="is-alert"' in portal.text
    assert 'href="/admin/health/oss" class="is-alert"' in portal.text
    assert "/admin/health/snapshot" not in portal.text
    assert "状态过期" in runtime.text
    assert "数据库探测失败" in runtime.text
    assert "jiaotang-kb-index-refresh.service" in runtime.text
    assert "release-current" in runtime.text
    assert "release-previous" in runtime.text
    assert "knowledge.db.zst" in backup.text
    assert "oss" in backup.text
    assert "verified" in backup.text
    assert "oss-current" in oss.text
    assert "oss-previous" in oss.text
    assert "指针 SHA-256" in oss.text
    assert "否" in oss.text


def test_release_validation_uses_content_identity_and_snapshot_streaming(
    tmp_path,
    monkeypatch,
):
    module = load_app(tmp_path)
    legacy = tmp_path / "legacy.zip"
    with zipfile.ZipFile(legacy, "w") as archive:
        archive.writestr("legacy/readme.txt", "legacy release")
    legacy_artifact = {
        "version": "1.0",
        "file_name": legacy.name,
        "file_path": str(legacy),
        "sha256": hashlib.sha256(legacy.read_bytes()).hexdigest(),
    }
    first = module.validate_release_artifact_for_serving(
        legacy_artifact,
        target="generic",
        require_signature=False,
    )
    assert first["status"] == "legacy_sha256_verified"
    original_stat = legacy.stat()
    tampered = bytearray(legacy.read_bytes())
    tampered[len(tampered) // 2] ^= 1
    legacy.write_bytes(tampered)
    os.utime(
        legacy,
        ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
    )
    assert legacy.stat().st_size == original_stat.st_size
    assert legacy.stat().st_mtime_ns == original_stat.st_mtime_ns
    with pytest.raises(ValueError, match="SHA-256"):
        module.validate_release_artifact_for_serving(
            legacy_artifact,
            target="generic",
            require_signature=False,
        )

    package = tmp_path / "current.zip"
    original_content = b"validated-content-addressed-release"
    replacement_content = b"path-was-replaced-after-validation"
    package.write_bytes(original_content)
    artifact_sha256 = hashlib.sha256(original_content).hexdigest()
    now = module.isoformat(module.utc_now())
    with closing(module.database()) as connection:
        connection.execute(
            """
            INSERT INTO users(username,password_hash,is_admin,created_at)
            VALUES (?,?,1,?)
            """,
            ("owner", module.password_hasher.hash("owner-password-123"), now),
        )
        connection.execute(
            """
            INSERT INTO skill_releases(
                version,file_name,file_path,sha256,release_notes,published_at
            ) VALUES (?,?,?,?,?,?)
            """,
            (
                "1.2.0",
                package.name,
                str(package),
                artifact_sha256,
                "snapshot regression",
                now,
            ),
        )
        connection.commit()

    def validate_then_replace(artifact, *, target, require_signature):
        package.write_bytes(replacement_content)
        return {"status": "verified", "signed_format": True}

    monkeypatch.setattr(
        module,
        "validate_release_artifact_for_serving",
        validate_then_replace,
    )
    with TestClient(module.app) as client:
        login = client.post(
            "/login",
            data={"username": "owner", "password": "owner-password-123"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)
        changed_before_snapshot = client.get("/skills/latest/download")
        assert changed_before_snapshot.status_code == 503

        package.write_bytes(original_content)
        monkeypatch.setattr(
            module,
            "validate_release_artifact_for_serving",
            lambda artifact, *, target, require_signature: {
                "status": "verified",
                "signed_format": True,
            },
        )
        original_snapshot = module.snapshot_release_artifact

        def snapshot_then_replace(artifact):
            snapshot = original_snapshot(artifact)
            package.write_bytes(replacement_content)
            return snapshot

        monkeypatch.setattr(
            module,
            "snapshot_release_artifact",
            snapshot_then_replace,
        )
        stable_download = client.get("/skills/latest/download")
    assert stable_download.status_code == 200
    assert stable_download.content == original_content
    assert package.read_bytes() == replacement_content


def test_release_display_validation_cache_rechecks_changed_file(
    tmp_path,
    monkeypatch,
):
    module = load_app(tmp_path)
    package = tmp_path / "display-cache.zip"
    package.write_bytes(b"immutable-display-artifact")
    expected_sha256 = hashlib.sha256(package.read_bytes()).hexdigest()
    artifact = {
        "version": "1.5.0",
        "file_path": str(package),
        "sha256": expected_sha256,
    }
    calls = []

    def validate(candidate, *, target, require_signature):
        calls.append((target, require_signature))
        actual = hashlib.sha256(package.read_bytes()).hexdigest()
        if actual != candidate["sha256"]:
            raise ValueError("SHA-256 mismatch")
        return {"status": "verified", "signed_format": True}

    monkeypatch.setattr(module, "validate_release_artifact_for_serving", validate)
    module.validate_release_artifact_for_display_cached.cache_clear()
    assert module.release_artifact_is_servable(
        artifact,
        target="generic",
        require_signature=True,
    )
    assert module.release_artifact_is_servable(
        artifact,
        target="generic",
        require_signature=True,
    )
    assert calls == [("generic", True)]

    original_stat = package.stat()
    changed = bytearray(package.read_bytes())
    changed[0] ^= 1
    package.write_bytes(changed)
    os.utime(package, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    assert package.stat().st_size == original_stat.st_size
    assert package.stat().st_mtime_ns == original_stat.st_mtime_ns
    assert not module.release_artifact_is_servable(
        artifact,
        target="generic",
        require_signature=True,
    )
    assert calls == [("generic", True), ("generic", True)]


@pytest.mark.parametrize(
    ("username", "password", "is_admin"),
    (
        ("owner", "owner-password-123", 1),
        ("member", "member-password-123", 0),
    ),
)
def test_portal_displays_latest_and_full_public_release_history_for_all_roles(
    tmp_path,
    monkeypatch,
    username,
    password,
    is_admin,
):
    module = load_app(tmp_path)
    module.FIRST_PUBLIC_SKILL_VERSION = "1.5.0"
    allow_test_release_artifacts(monkeypatch, module)
    now = module.utc_now()
    with closing(module.database()) as connection:
        connection.execute(
            "INSERT INTO users(username,password_hash,is_admin,created_at) VALUES (?,?,?,?)",
            (
                username,
                module.password_hasher.hash(password),
                is_admin,
                module.isoformat(now),
            ),
        )
        if not is_admin:
            member_id = connection.execute(
                "SELECT id FROM users WHERE username=?",
                (username,),
            ).fetchone()["id"]
            connection.execute(
                """
                INSERT INTO registration_authorizations(
                    real_name,identity_code,status,user_id,created_at,registered_at
                ) VALUES (?,?,'registered',?,?,?)
                """,
                ("普通成员", "1550", member_id, module.isoformat(now), module.isoformat(now)),
            )
        for offset, version in enumerate(("1.5.0", "1.5.1", "1.5.2")):
            package = tmp_path / f"skills-{version}.zip"
            package.write_bytes(f"skills-{version}".encode())
            connection.execute(
                """
                INSERT INTO skill_releases(
                    version,file_name,file_path,sha256,release_notes,published_at
                ) VALUES (?,?,?,?,?,?)
                """,
                (
                    version,
                    package.name,
                    str(package),
                    hashlib.sha256(package.read_bytes()).hexdigest(),
                    f"release {version}",
                    module.isoformat(now + timedelta(minutes=offset)),
                ),
            )
        connection.commit()

    with TestClient(module.app) as client:
        login = client.post(
            "/login",
            data={"username": username, "password": password},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)
        page = client.get("/skills")

        assert page.status_code == 200
        assert "共创研究院企业全生命周期助手 V1.5.2" in page.text
        assert "共创研究院企业全生命周期助手 V1.5.1" in page.text
        assert "共创研究院企业全生命周期助手 V1.5.0" in page.text
        assert "一、本版本新增功能" in page.text
        assert "49 项 Skill 划分为主业务" in page.text
        assert "release 1.5.1" not in page.text
        assert "历史记录只读" in page.text
        assert "共创研究院企业全生命周期助手 V1.4.9" not in page.text


def test_admin_invalid_signature_upload_keeps_previous_latest(
    tmp_path,
    monkeypatch,
):
    module = load_app(tmp_path)
    old_package = tmp_path / "generic-v1.1.0.zip"
    old_package.write_bytes(b"previous-verified-release")
    old_sha256 = hashlib.sha256(old_package.read_bytes()).hexdigest()
    now = module.isoformat(module.utc_now())
    with closing(module.database()) as connection:
        connection.execute(
            """
            INSERT INTO users(username,password_hash,is_admin,created_at)
            VALUES (?,?,1,?)
            """,
            ("owner", module.password_hasher.hash("owner-password-123"), now),
        )
        connection.execute(
            """
            INSERT INTO skill_releases(
                version,file_name,file_path,sha256,release_notes,published_at
            ) VALUES (?,?,?,?,?,?)
            """,
            (
                "1.1.0",
                old_package.name,
                str(old_package),
                old_sha256,
                "previous release",
                now,
            ),
        )
        connection.commit()

    production_validation = module.validate_release_artifact_for_serving

    def validate_old_fixture_only(artifact, *, target, require_signature):
        if artifact is not None and str(artifact["version"]) == "1.1.0":
            return {"status": "verified", "signed_format": True}
        return production_validation(
            artifact,
            target=target,
            require_signature=require_signature,
        )

    monkeypatch.setattr(
        module,
        "validate_release_artifact_for_serving",
        validate_old_fixture_only,
    )
    invalid_package = invalidly_signed_complete_skill_release_fixture(
        module.SKILL_SOURCE_DIR,
        version="1.2.0",
    )
    with TestClient(module.app) as client:
        login = client.post(
            "/login",
            data={"username": "owner", "password": "owner-password-123"},
            follow_redirects=False,
        )
        client.cookies.update(login.cookies)
        user = module.session_user(
            login.cookies[module.SESSION_COOKIE]
        )[0]
        rejected = client.post(
            "/admin/skill-releases",
            data={
                "version": "1.2.0",
                "release_notes": "must be rejected",
                "csrf_token": user["csrf_token"],
            },
            files={
                "skill_package": (
                    "generic-v1.2.0.zip",
                    invalid_package,
                    "application/zip",
                )
            },
            follow_redirects=False,
        )
        current_download = client.get("/skills/latest/download")

    assert rejected.status_code == 400
    assert "Skills 发布包校验失败" in rejected.text
    with closing(module.database()) as connection:
        versions = [
            row["version"]
            for row in connection.execute(
                "SELECT version FROM skill_releases ORDER BY id"
            ).fetchall()
        ]
    assert versions == ["1.1.0"]
    assert current_download.status_code == 200
    assert current_download.content == old_package.read_bytes()
    rejected_files = list((module.SKILL_RELEASE_DIR / "rejected").glob("*.zip"))
    assert len(rejected_files) == 1
