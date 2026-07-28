#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import hashlib
import os
import sqlite3
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import uvicorn


ROOT = Path(__file__).resolve().parent.parent
TEST_MODULE_PATH = ROOT / "tests" / "test_portal.py"
sys.path.insert(0, str(ROOT))


def main() -> None:
    data_dir = Path(os.environ["JIAOTANG_BROWSER_TEST_DATA"])
    os.environ.update(
        {
            "JIAOTANG_DATA_DIR": str(data_dir),
            "JIAOTANG_INDEX_DIR": str(data_dir / "knowledge-index"),
            "JIAOTANG_SETUP_KEY": "browser-route-setup",
            "JIAOTANG_TOKEN_DERIVATION_SECRET": "browser-route-test-secret",
            "JIAOTANG_SECURE_COOKIES": "false",
            "JIAOTANG_PUBLIC_HOST": "127.0.0.1",
        }
    )
    spec = importlib.util.spec_from_file_location("portal_test_helpers", TEST_MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载浏览器测试辅助模块")
    helpers = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = helpers
    spec.loader.exec_module(helpers)
    helpers.create_test_content_index(data_dir / "knowledge-index" / "knowledge_content.sqlite3")

    from app import main as portal

    portal.init_database()
    if os.environ.get("JIAOTANG_BROWSER_TEST_SKILL_RELEASE_FIXTURE") == "1":
        release_dir = data_dir / "skill-releases"
        release_dir.mkdir(parents=True, exist_ok=True)
        generic = release_dir / "企业全生命周期助手-V1.2.zip"
        generic.write_bytes(b"browser-release-fixture")
        workbuddy = release_dir / "企业全生命周期助手-V1.2-WorkBuddy.zip"
        with zipfile.ZipFile(workbuddy, "w") as archive:
            archive.writestr("jiaotang/.codebuddy-plugin/marketplace.json", "{}")
            archive.writestr("jiaotang/plugins/plugin/.codebuddy-plugin/plugin.json", "{}")
        with sqlite3.connect(data_dir / "knowledge.db") as connection:
            release_cursor = connection.execute(
                """
                INSERT INTO skill_releases(
                    version,file_name,file_path,sha256,release_notes,published_at
                ) VALUES (?,?,?,?,?,?)
                """,
                (
                    "1.2",
                    generic.name,
                    str(generic),
                    hashlib.sha256(generic.read_bytes()).hexdigest(),
                    "## 浏览器回归版本\n\n验证 macOS 与 Windows 下载呈现。",
                    datetime.now(timezone.utc).isoformat(),
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
                    workbuddy.name,
                    str(workbuddy),
                    hashlib.sha256(workbuddy.read_bytes()).hexdigest(),
                ),
            )
            connection.commit()
    uvicorn.run(portal.app, host="127.0.0.1", port=int(os.environ["JIAOTANG_BROWSER_TEST_PORT"]))


if __name__ == "__main__":
    main()
