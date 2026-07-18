import importlib
import io
import os
import sqlite3
import zipfile
from contextlib import closing
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from scripts.build_knowledge_content_index import cache_status_reusable


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
                updated_at TEXT NOT NULL
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
        connection.execute("INSERT INTO documents_fts(documents_fts) VALUES ('rebuild')")
        connection.execute("INSERT INTO documents_fts_trigram(documents_fts_trigram) VALUES ('rebuild')")
        connection.commit()


def load_app(tmp_path):
    os.environ["JIAOTANG_DATA_DIR"] = str(tmp_path)
    os.environ["JIAOTANG_INDEX_DIR"] = str(tmp_path / "knowledge-index")
    os.environ["JIAOTANG_SETUP_KEY"] = "setup-secret"
    os.environ["JIAOTANG_SECURE_COOKIES"] = "false"
    os.environ.pop("JIAOTANG_AI_API_BASE", None)
    os.environ.pop("JIAOTANG_AI_API_KEY", None)
    os.environ.pop("JIAOTANG_AI_MODEL", None)
    create_test_content_index(tmp_path / "knowledge-index" / "knowledge_content.sqlite3")
    import app.main

    module = importlib.reload(app.main)
    module.init_database()
    return module


def test_public_user_guide(tmp_path):
    module = load_app(tmp_path)
    with TestClient(module.app) as client:
        guide = client.get("/guide")
        assert guide.status_code == 200
        assert "项目申报助手用户使用手册" in guide.text
        assert "下载与安装" in guide.text
        assert "53项 Skills 能力导航" not in guide.text
        assert "2.1.5版本" not in guide.text

        client.post(
            "/setup",
            data={"setup_key": "setup-secret", "username": "owner", "password": "correct-horse-battery"},
        )
        login = client.get("/login")
        assert login.status_code == 200
        assert 'href="/guide"' in login.text


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
        assert "退出当前账号并切换用户" in portal.text
        assert "first-run-configuration" in portal.text
        assert "驾驶舱智能看板" in portal.text
        assert "免费知识检索" in portal.text
        user = module.session_user(response.cookies[module.SESSION_COOKIE])[0]

        assistant = client.post(
            "/assistant/answer",
            data={"question": "小巨人", "csrf_token": user["csrf_token"]},
        )
        assert assistant.status_code == 200
        assert assistant.json()["mode"] == "knowledge-search"
        assert assistant.json()["sources"][0]["title"] == "小巨人测试资料"

        token_page = client.post(
            "/device-tokens",
            data={
                "real_name": "王小明",
                "company_name": "共创集团",
                "csrf_token": user["csrf_token"],
            },
        )
        assert token_page.status_code == 200
        assert "复制 API + MCP 接入配置" in token_page.text
        assert "JIAOTANG_KB_MCP_URL=http://testserver/mcp/" in token_page.text
        assert "仅复制个人 Token" in token_page.text
        with closing(module.database()) as connection:
            assert connection.execute("SELECT label FROM device_tokens").fetchone()["label"] == "王小明"
        marker = "jtk_"
        token = marker + token_page.text.split(marker, 1)[1].split("<", 1)[0]

        me = client.get("/v1/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        assert me.json() == {"username": "owner", "access": "unified"}

        search = client.post(
            "/v1/search",
            headers={"Authorization": f"Bearer {token}"},
            json={"query": "小巨人", "limit": 5},
        )
        assert search.status_code == 200
        assert search.json()["results"][0]["title"] == "小巨人测试资料"
        document_id = search.json()["results"][0]["document_id"]
        document = client.get(
            f"/v1/documents/{document_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert document.status_code == 200
        assert document.json()["content"] == "产业链关键环节与工业六基匹配"

        usage = client.get("/v1/usage", headers={"Authorization": f"Bearer {token}"})
        assert usage.status_code == 200
        assert usage.json()["total_calls"] >= 4
        assert any(item["endpoint"] == "/v1/search" for item in usage.json()["by_endpoint"])

        latest = client.get("/v1/skills/latest", headers={"Authorization": f"Bearer {token}"})
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
        connection.commit()
    with TestClient(module.app) as client:
        response = client.post(
            "/register",
            data={
                "username": "王小明",
                "company_name": "共创集团",
                "password": "member-password-123",
                "confirm_password": "member-password-123",
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
        connection.commit()
    with TestClient(module.app) as client:
        rejected = client.post(
            "/register",
            data={
                "username": "member-one",
                "company_name": "错误公司",
                "password": "member-password-123",
                "confirm_password": "member-password-123",
            },
        )
        assert rejected.status_code == 403
        created = client.post(
            "/register",
            data={
                "username": "member-one",
                "company_name": "共创集团",
                "password": "member-password-123",
                "confirm_password": "member-password-123",
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


def test_api_rejects_missing_token(tmp_path):
    module = load_app(tmp_path)
    with TestClient(module.app) as client:
        response = client.get("/v1/me")
        assert response.status_code == 401


def test_latest_skill_release_metadata_and_download(tmp_path):
    module = load_app(tmp_path)
    package = tmp_path / "project-assistant-skills.zip"
    package.write_bytes(b"test-skill-package")
    digest = module.hashlib.sha256(package.read_bytes()).hexdigest()
    with closing(module.database()) as connection:
        connection.execute(
            "INSERT INTO users(username, password_hash, created_at) VALUES (?, ?, ?)",
            ("member", module.password_hasher.hash("member-password-123"), module.isoformat(module.utc_now())),
        )
        user_id = connection.execute("SELECT id FROM users WHERE username = 'member'").fetchone()[0]
        raw_token = "jtk_test-token"
        connection.execute(
            """
            INSERT INTO device_tokens(user_id, label, token_prefix, token_hash, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, "test", "jtk_test", module.token_hash(raw_token), module.isoformat(module.utc_now())),
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
    headers = {"Authorization": f"Bearer {raw_token}"}
    with TestClient(module.app) as client:
        latest = client.get("/v1/skills/latest", headers=headers)
        assert latest.status_code == 200
        assert latest.json()["version"] == "1.1.0"
        assert latest.json()["sha256"] == digest
        download = client.get("/v1/skills/latest/download", headers=headers)
        assert download.status_code == 200
        assert download.content == b"test-skill-package"


def test_admin_incremental_index_release_and_rollback(tmp_path):
    module = load_app(tmp_path)
    raw_token = "jtk_admin-test-token"
    with closing(module.database()) as connection:
        connection.execute(
            "INSERT INTO users(username, password_hash, is_admin, created_at) VALUES (?, ?, 1, ?)",
            ("owner", module.password_hasher.hash("owner-password-123"), module.isoformat(module.utc_now())),
        )
        user_id = connection.execute("SELECT id FROM users WHERE username = 'owner'").fetchone()[0]
        connection.execute(
            """
            INSERT INTO device_tokens(user_id, label, token_prefix, token_hash, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, "admin-test", "jtk_admin", module.token_hash(raw_token), module.isoformat(module.utc_now())),
        )
        connection.commit()
    headers = {"Authorization": f"Bearer {raw_token}"}
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
        search = client.post(
            "/v1/search",
            headers=headers,
            json={"query": "增量测试政策", "limit": 5},
        )
        assert search.status_code == 200
        assert any(item["title"] == "新增政策.md" for item in search.json()["results"])

        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as package:
            package.writestr("skills/sample-skill/SKILL.md", "---\nname: sample-skill\n---\n")
        release = client.post(
            "/admin/skill-releases",
            data={
                "version": "1.2.0",
                "release_notes": "新增测试技能",
                "csrf_token": user["csrf_token"],
            },
            files={"skill_package": ("skills-1.2.0.zip", archive.getvalue(), "application/zip")},
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
    raw_token = "jtk_mcp-test-token"
    with closing(module.database()) as connection:
        connection.execute(
            "INSERT INTO users(username, password_hash, created_at) VALUES (?, ?, ?)",
            ("member", module.password_hasher.hash("member-password-123"), module.isoformat(module.utc_now())),
        )
        user_id = connection.execute("SELECT id FROM users WHERE username = 'member'").fetchone()[0]
        connection.execute(
            """
            INSERT INTO device_tokens(user_id, label, token_prefix, token_hash, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, "王小明", "jtk_mcp", module.token_hash(raw_token), module.isoformat(module.utc_now())),
        )
        connection.commit()
    headers = {
        "Authorization": f"Bearer {raw_token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    with TestClient(module.app) as client:
        assert client.post(
            "/mcp/",
            headers={"Accept": "application/json, text/event-stream"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        ).status_code == 401
        response = client.post(
            "/mcp/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "knowledge_search",
                    "arguments": {"query": "小巨人", "limit": 3},
                },
            },
        )
        assert response.status_code == 200
        assert response.json()["result"]["structuredContent"]["results"][0]["document_id"] == 1
    with closing(module.database()) as connection:
        usage = connection.execute(
            "SELECT endpoint FROM api_usage ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert usage["endpoint"] == "/mcp"


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
        assert "/admin/health/index" in portal.text
        assert "/admin/knowledge" in portal.text
        health = client.get("/admin/health/index")
        assert health.status_code == 200
        assert "全文资料" in health.text
        access_health = client.get("/admin/health/access")
        assert access_health.status_code == 200
        assert "具体用户" in access_health.text
        assert "owner" in access_health.text
        knowledge = client.get("/admin/knowledge?query=小巨人")
        assert knowledge.status_code == 200
        assert "小巨人测试资料" in knowledge.text
        assert "第 1/1 页 · 每页30份" in knowledge.text
        assert 'aria-current="page">1</a>' in knowledge.text
        ordered_knowledge = client.get("/admin/knowledge")
        assert ordered_knowledge.text.index("0001") < ordered_knowledge.text.index("0002")
        assert "编号升序" in ordered_knowledge.text
        assert "移入回收站" in ordered_knowledge.text
        assert "agent.qcc.com/invitation?code=3ZRZPHF7Q5MH4" in portal.text
        assert "docs.cloud.google.com/bigquery/docs/use-bigquery-mcp" in portal.text
        assert "aiqice.cn" not in portal.text
        assert "pss-system.cponline.cnipa.gov.cn" not in portal.text
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
