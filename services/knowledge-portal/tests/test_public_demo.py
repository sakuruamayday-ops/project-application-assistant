import hashlib

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
    assert ">50</dt><dd>顶层 Skills" in response.text
    assert ">49</dt><dd>顶层 Skills" not in response.text
    assert 'href="/login"' in response.text
    assert "jtk_" not in response.text
    assert "/v1/search" not in response.text
    assert "冀ICP备2026028214号-1" in response.text
    assert 'href="https://beian.miit.gov.cn/"' in response.text
    assert "浙公网安备33011002020199号" in response.text
    assert 'href="https://beian.mps.gov.cn/#/query/webSearch?code=33011002020199"' in response.text
    assert 'src="/static/ghs.png"' in response.text
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
    assert "浙公网安备33011002020199号" in response.text
    assert 'href="https://beian.mps.gov.cn/#/query/webSearch?code=33011002020199"' in response.text
    assert 'src="/static/ghs.png"' in response.text


def test_public_security_filing_icon_is_served_locally(tmp_path):
    module = load_app(tmp_path)

    with TestClient(module.app) as client:
        response = client.get("/static/ghs.png")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert hashlib.sha256(response.content).hexdigest() == (
        "a20583c81805fe64f7fa210851ce29754af9d25fd6aa5a3225a9557529602513"
    )
