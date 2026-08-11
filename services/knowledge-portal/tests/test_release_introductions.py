from __future__ import annotations

import json
import re
from pathlib import Path

from app.release_introductions import (
    DEFAULT_CATALOG_PATH,
    release_function_introduction,
    release_introduction_versions,
)


EXPECTED_RELEASES = (
    "1.0",
    "1.1",
    "1.2",
    "1.3",
    "1.3.1",
    "1.3.1.1",
    "1.3.1.2",
    "1.3.1.3",
    "1.3.1.4",
    "1.3.1.5",
    "1.3.1.6",
    "1.4.0",
    "1.4.1",
    "1.4.3",
    "1.4.4",
    "1.4.5",
    "1.4.6",
    "1.4.7",
    "1.4.8",
    "1.4.9",
    "1.5.0",
    "1.5.1",
    "1.5.2",
    "1.5.4",
    "1.5.5",
    "1.5.6",
    "1.5.7",
    "1.5.8",
    "1.5.9",
    "1.6.0",
    "1.6.1",
    "1.6.2",
    "1.6.3",
)


def test_release_introduction_catalog_covers_github_product_history():
    assert release_introduction_versions() == EXPECTED_RELEASES
    payload = json.loads(DEFAULT_CATALOG_PATH.read_text(encoding="utf-8"))
    assert payload["schema"] == "gongchuang-release-function-introductions/v1"


def test_every_release_uses_the_two_section_function_structure():
    for version in EXPECTED_RELEASES:
        introduction = release_function_introduction(version)
        assert introduction.startswith(
            f"# 共创研究院企业全生命周期助手 V{version} 功能简介\n"
        )
        assert introduction.count("## 一、本版本新增功能") == 1
        assert introduction.count("## 二、原有核心功能") == 1
        assert "正式发布命令" not in introduction
        assert "回滚命令" not in introduction


def test_public_introductions_only_keep_the_mcp_compatibility_name_exception():
    combined = "\n".join(
        release_function_introduction(version)
        for version in EXPECTED_RELEASES
    )
    scrubbed = combined.replace("mcpServers.jiaotang-kb", "").replace(
        "`jiaotang-kb`",
        "",
    )
    assert not re.search(r"jiaotang|焦糖", scrubbed, re.IGNORECASE)


def test_v163_matches_the_owner_confirmed_function_summary():
    introduction = release_function_introduction("V1.6.3")
    for text in (
        "新增 Word 模板原样填充功能",
        "增加模板保真校验和逐页视觉检查",
        "完善企业数字身份证",
        "优化小巨人、专精特新、三首等名单检索",
        "一键安装 49 项 Skills",
        "企业分析报告 A/B/C 版本和金税四期分析报告",
        "Word、Excel、PowerPoint、PDF 等常用交付格式",
    ):
        assert text in introduction


def test_unknown_release_falls_back_without_rewriting_history():
    assert release_function_introduction("9.9.9", "legacy body") == "legacy body"
