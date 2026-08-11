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
            "JIAOTANG_FIRST_PUBLIC_SKILL_VERSION": "1.0",
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
        generic = release_dir / "共创研究院企业全生命周期助手-V1.2.zip"
        generic.write_bytes(b"browser-release-fixture")
        historical_generics = []
        for version in ("1.1", "1.0"):
            archive_path = release_dir / f"共创研究院企业全生命周期助手-V{version}.zip"
            archive_path.write_bytes(f"browser-release-fixture-{version}".encode())
            historical_generics.append((version, archive_path))
        workbuddy = release_dir / "共创研究院企业全生命周期助手-V1.2-WorkBuddy.zip"
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
            for target in ("workbuddy", "macos", "windows"):
                connection.execute(
                    """
                    INSERT INTO skill_release_artifacts(
                        release_id,target,file_name,file_path,sha256
                    ) VALUES (?,?,?,?,?)
                    """,
                    (
                        release_cursor.lastrowid,
                        target,
                        workbuddy.name,
                        str(workbuddy),
                        hashlib.sha256(workbuddy.read_bytes()).hexdigest(),
                    ),
                )
            for offset, (version, archive_path) in enumerate(historical_generics, start=1):
                connection.execute(
                    """
                    INSERT INTO skill_releases(
                        version,file_name,file_path,sha256,release_notes,published_at
                    ) VALUES (?,?,?,?,?,datetime('now', ?))
                    """,
                    (
                        version,
                        archive_path.name,
                        str(archive_path),
                        hashlib.sha256(archive_path.read_bytes()).hexdigest(),
                        f"## 历史版本 {version}\n\n验证历史版本折叠。",
                        f"-{offset} day",
                    ),
                )
            connection.commit()
        # This fixture exercises presentation and interaction only. The tiny
        # synthetic archives intentionally omit the production publisher
        # signature tree, so keep signature validation covered by pytest and
        # expose these fixture artifacts as installable inside this isolated
        # browser-test process.
        portal.release_artifact_is_servable = (
            lambda artifact, *, target, require_signature: artifact is not None
        )
        portal.workbuddy_artifact_is_simple_remote_mcp = (
            lambda artifact: artifact is not None
        )
    uvicorn.run(portal.app, host="127.0.0.1", port=int(os.environ["JIAOTANG_BROWSER_TEST_PORT"]))


if __name__ == "__main__":
    main()
