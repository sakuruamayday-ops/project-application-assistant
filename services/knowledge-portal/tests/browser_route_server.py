#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import sys
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
    uvicorn.run(portal.app, host="127.0.0.1", port=int(os.environ["JIAOTANG_BROWSER_TEST_PORT"]))


if __name__ == "__main__":
    main()
