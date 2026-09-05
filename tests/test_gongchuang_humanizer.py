from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "gongchuang-humanizer-zh"


def test_rewrite_audit_preserves_locked_numbers_and_acronyms() -> None:
    process = subprocess.run(
        [
            sys.executable,
            str(SKILL / "scripts" / "audit_rewrite.py"),
            "--source-text",
            "企业2025年营收3000万元，MES覆盖率80%。",
            "--rewrite-text",
            "2025年，企业营收3000万元，MES覆盖率为80%。",
            "--max-chars",
            "80",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    payload = json.loads(process.stdout)
    assert process.returncode == 0
    assert payload["numbers"]["missing_from_rewrite"] == []
    assert payload["numbers"]["added_in_rewrite"] == []
    assert payload["acronyms"]["missing_from_rewrite"] == []
    assert payload["format"]["over_max_chars"] is False


def test_rewrite_audit_reports_added_fact_like_number() -> None:
    process = subprocess.run(
        [
            sys.executable,
            str(SKILL / "scripts" / "audit_rewrite.py"),
            "--source-text",
            "企业主营工业视觉检测设备。",
            "--rewrite-text",
            "企业主营工业视觉检测设备，市场占有率达到20%。",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    payload = json.loads(process.stdout)
    assert process.returncode == 0
    assert payload["numbers"]["added_in_rewrite"] == ["20%"]


def test_rewrite_audit_detects_model_changes_next_to_chinese() -> None:
    process = subprocess.run(
        [sys.executable, str(SKILL / "scripts" / "audit_rewrite.py"),
         "--source-text", "整机X1通过MES调度，沿用GC-QA品牌。",
         "--rewrite-text", "整机X2通过ERP调度，沿用GC-QA品牌。"],
        capture_output=True, text=True, check=False,
    )
    payload = json.loads(process.stdout)
    assert process.returncode == 0
    assert payload["acronyms"]["missing_from_rewrite"] == ["MES", "X1"]
    assert payload["acronyms"]["added_in_rewrite"] == ["ERP", "X2"]


def test_rewrite_audit_ignores_chinese_spacing_but_keeps_ascii_word_boundaries() -> None:
    process = subprocess.run(
        [sys.executable, str(SKILL / "scripts" / "audit_rewrite.py"),
         "--source-text", "整机X1使用MES，GC-QA品牌。",
         "--rewrite-text", "整机 X1 使用 MES，GC-QA 品牌。变量 someX9value 不是型号。"],
        capture_output=True, text=True, check=False,
    )
    payload = json.loads(process.stdout)
    assert process.returncode == 0
    assert payload["acronyms"]["missing_from_rewrite"] == []
    assert payload["acronyms"]["added_in_rewrite"] == []


def test_feedback_defaults_to_user_data_directory(tmp_path: Path) -> None:
    data_root = tmp_path / "profiles"
    env = os.environ.copy()
    env["GONGCHUANG_SKILL_DATA_DIR"] = str(data_root)
    process = subprocess.run(
        [
            sys.executable,
            str(SKILL / "scripts" / "record_feedback.py"),
            "--case-id",
            "case-1",
            "--domain",
            "政府申报",
            "--source-sha256",
            "a" * 64,
            "--candidate",
            "原稿:60",
            "--candidate",
            "改写稿:90",
            "--winner",
            "改写稿",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    output = data_root / "gongchuang-humanizer-zh" / "evolution-feedback.jsonl"
    assert process.returncode == 0, process.stdout + process.stderr
    assert output.is_file()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["raw_text_stored"] is False
    assert payload["source_sha256"] == "a" * 64
