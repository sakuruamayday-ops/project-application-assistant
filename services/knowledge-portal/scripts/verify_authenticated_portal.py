#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import HTTPCookieProcessor, Request, build_opener


SESSION_COOKIE = "jiaotang_session"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="验证生产登录态 Skills 页面")
    parser.add_argument("--base-url", default="http://127.0.0.1:8100")
    parser.add_argument("--database", type=Path)
    return parser.parse_args()


def require_order(text: str, labels: list[tuple[str, str]]) -> None:
    positions = []
    for label, marker in labels:
        position = text.find(marker)
        if position < 0:
            raise AssertionError(f"页面缺少结构：{label}")
        positions.append((label, position))
    if positions != sorted(positions, key=lambda item: item[1]):
        raise AssertionError("页面结构顺序错误：" + " → ".join(label for label, _ in positions))


def validate_portal_html(html: str) -> str:
    require_order(
        html,
        [
            ("留言反馈", 'data-section-link="feedback"'),
            ("Skills 中心", 'data-section-link="skills"'),
        ],
    )
    require_order(
        html,
        [
            ("Skills 总览", 'class="skill-hero"'),
            ("Skills 页签", 'class="skill-section-tabs"'),
            ("连续技能目录", 'class="skill-catalog-shell"'),
            ("清单底部返回区", 'class="skill-catalog-footer"'),
        ],
    )
    for marker in (
        'class="skill-group-switcher"',
        'class="skill-catalog-controls"',
        'data-skill-back-to-list',
    ):
        if marker not in html:
            raise AssertionError(f"页面缺少 Skills 交互结构：{marker}")
    match = re.search(r'<link[^>]+href="([^"]*app\.css\?v=[^"]+)"', html)
    if not match:
        raise AssertionError("页面未加载带版本号的 app.css")
    return match.group(1)


def css_rule(css: str, selector: str) -> str:
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    if not match:
        raise AssertionError(f"样式表缺少规则：{selector}")
    return match.group(1)


def validate_stylesheet(css: str) -> None:
    for selector in (".skill-section-tabs", ".skill-group-switcher", ".skill-catalog-controls"):
        if "position:sticky" not in css_rule(css, selector).replace(" ", ""):
            raise AssertionError(f"{selector} 未启用吸顶")
    back_rule = css_rule(css, ".skill-back-to-list").replace(" ", "")
    if "position:fixed" in back_rule:
        raise AssertionError("返回清单顶部按钮仍在悬浮覆盖内容")


def insert_temporary_session(database: Path) -> tuple[str, str]:
    raw_token = "portal-gate-" + secrets.token_urlsafe(32)
    hashed = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc)
    with sqlite3.connect(database) as connection:
        admin = connection.execute(
            "SELECT id FROM users WHERE active=1 AND is_admin=1 ORDER BY id LIMIT 1"
        ).fetchone()
        if admin is None:
            raise RuntimeError("生产数据库没有可用于验收的有效管理员")
        connection.execute(
            """
            INSERT INTO sessions(token_hash,user_id,csrf_token,expires_at,created_at)
            VALUES (?,?,?,?,?)
            """,
            (
                hashed,
                int(admin[0]),
                secrets.token_urlsafe(24),
                (now + timedelta(minutes=5)).isoformat(),
                now.isoformat(),
            ),
        )
        connection.commit()
    return raw_token, hashed


def remove_temporary_session(database: Path, hashed: str) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM sessions WHERE token_hash=?", (hashed,))
        connection.commit()


def fetch_text(opener, url: str, cookie: str | None = None) -> str:
    headers = {"User-Agent": "JiaotangProductionPortalGate/1.0"}
    if cookie:
        headers["Cookie"] = f"{SESSION_COOKIE}={cookie}"
    with opener.open(Request(url, headers=headers), timeout=20) as response:
        if response.status != 200:
            raise AssertionError(f"页面返回状态异常：{response.status} {url}")
        return response.read().decode("utf-8")


def main() -> int:
    args = parse_args()
    database = args.database or Path(
        os.environ.get("JIAOTANG_DATA_DIR", "/var/lib/jiaotang-kb")
    ) / "knowledge.db"
    raw_token, hashed = insert_temporary_session(database)
    try:
        opener = build_opener(HTTPCookieProcessor(CookieJar()))
        skills_url = urljoin(args.base_url.rstrip("/") + "/", "skills")
        html = fetch_text(opener, skills_url, raw_token)
        stylesheet_path = validate_portal_html(html)
        css = fetch_text(opener, urljoin(skills_url, stylesheet_path))
        validate_stylesheet(css)
    finally:
        remove_temporary_session(database, hashed)
    print(
        json.dumps(
            {
                "status": "pass",
                "page": "/skills",
                "authenticated": True,
                "checks": [
                    "sidebar-order",
                    "skills-dom-order",
                    "versioned-stylesheet",
                    "sticky-navigation",
                    "non-floating-back-button",
                ],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
