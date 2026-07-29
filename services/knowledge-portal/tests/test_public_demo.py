from fastapi.testclient import TestClient

from test_portal import load_app


def test_public_demo_requires_no_registration_or_session(tmp_path):
    module = load_app(tmp_path)

    with TestClient(module.app) as client:
        response = client.get("/demo")

    assert response.status_code == 200
    assert "企业全生命周期助手" in response.text
    assert "无需注册" in response.text
    assert "示例数据" in response.text
    assert 'href="/login"' in response.text
    assert "jtk_" not in response.text
    assert "/v1/search" not in response.text
    assert "冀ICP备2026028214号-1" in response.text
    assert 'href="https://beian.miit.gov.cn/"' in response.text
    assert response.headers["cache-control"] == "public, max-age=300"


def test_login_links_to_public_demo(tmp_path):
    module = load_app(tmp_path)
    module.init_database()
    with module.database() as connection:
        connection.execute(
            """
            INSERT INTO users(username,password_hash,is_admin,active,created_at)
            VALUES (?,?,?,?,?)
            """,
            ("admin", module.password_hasher.hash("password123"), 1, 1, module.isoformat(module.utc_now())),
        )
        connection.commit()

    with TestClient(module.app) as client:
        response = client.get("/login")

    assert response.status_code == 200
    assert 'href="/demo"' in response.text
    assert "冀ICP备2026028214号-1" in response.text
    assert 'href="https://beian.miit.gov.cn/"' in response.text
