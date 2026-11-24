#!/usr/bin/env python3
"""Full 32-skill bare-metal standalone ZIP verification suite for WorkBuddy."""

from __future__ import annotations

import json
import py_compile
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

REPO_ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build_workbuddy_single.py"
MANIFEST = REPO_ROOT / "config" / "workbuddy-bundles.json"


def _run(*cmd: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-B", *cmd],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


class WorkBuddyAll32BundlesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="wb-all32-")
        cls.out = Path(cls._tmp.name)
        proc = _run(str(BUILD_SCRIPT), "--manifest", str(MANIFEST), "--output", str(cls.out))
        if proc.returncode != 0:
            raise AssertionError(f"32-skill build failed:\n{proc.stderr}\n{proc.stdout}")
        cls.summary = json.loads(proc.stdout)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_all_32_zips_bare_metal_isolation_compile_and_runtime_probe(self) -> None:
        self.assertEqual(self.summary["built_count"], 32)
        self.assertEqual(self.summary["errors"], [])

        for bundle in self.summary["bundles"]:
            display = bundle["displayName"]
            tier = bundle["tier"]
            zip_path = Path(bundle["zip"])
            self.assertTrue(zip_path.is_file(), f"Missing ZIP for {display}")

            with self.subTest(skill=display, tier=tier):
                with tempfile.TemporaryDirectory() as iso_tmp:
                    iso = Path(iso_tmp)
                    with ZipFile(zip_path) as zf:
                        zf.extractall(iso)

                    # 1. Exactly one SKILL.md at root & native WorkBuddy _skillhub_meta.json
                    self.assertEqual(list(iso.rglob("SKILL.md")), [iso / "SKILL.md"])
                    meta = json.loads((iso / "_skillhub_meta.json").read_text(encoding="utf-8"))
                    for required_key in ("name", "skillId", "skillName", "version", "description_zh", "examples_zh"):
                        self.assertIn(required_key, meta)
                    self.assertEqual(len(meta["examples_zh"]), 3)

                    # 2. Commercial master isolation for free tiers
                    if tier in {"free-checkup", "free-data-mcp"}:
                        self.assertEqual(list(iso.rglob("*.docx")), [])
                        self.assertEqual(list(iso.rglob("*.xlsx")), [])
                        self.assertEqual(list(iso.rglob("*.doc")), [])

                    # 3. Every vendored Python file compiles cleanly
                    py_files = list(iso.rglob("*.py"))
                    self.assertTrue(py_files, f"{display} should contain light runtime & blackboard scripts")
                    for py_file in py_files:
                        py_compile.compile(str(py_file), doraise=True)

                    # 4. Light runtime & blackboard execute cleanly inside isolated folder
                    r_probe = _run(str(iso / "scripts" / "workbuddy_light_runtime.py"), cwd=iso)
                    self.assertEqual(r_probe.returncode, 0, r_probe.stderr)
                    b_probe = _run(str(iso / "scripts" / "facts_blackboard.py"), "--help", cwd=iso)
                    self.assertEqual(b_probe.returncode, 0, b_probe.stderr)

    def test_consistency_check_free_zip_blackboard_reconciliation(self) -> None:
        zip_path = self.out / "zips" / "free-checkup_申报材料交叉核对.zip"
        with tempfile.TemporaryDirectory() as iso_tmp:
            iso = Path(iso_tmp)
            with ZipFile(zip_path) as zf:
                zf.extractall(iso)
            txt = iso / "draft.txt"
            txt.write_text("预热腔温度实测为75℃，饼坯厚度公差设计控制目标为±1.5mm。", encoding="utf-8")
            bb = iso / "bb.json"
            bb.write_text(
                json.dumps(
                    {
                        "company_name": "杭州洲际食品有限公司",
                        "estimatedMetrics": [
                            {"metricName": "预热腔温度", "suggestedValue": "60—90℃", "origin": "ai_design_target"},
                            {"metricName": "厚度公差", "suggestedValue": "±1.5mm", "origin": "ai_design_target"},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            proc = _run(str(iso / "scripts" / "scan_formal_material.py"), str(txt), "--blackboard", str(bb), cwd=iso)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            res = json.loads(proc.stdout)
            self.assertEqual(res["estimated_metrics_reconciliation"]["resolved_count"], 1)
            self.assertEqual(res["estimated_metrics_reconciliation"]["pending_count"], 1)

    def test_feasibility_help_and_standard_drafting_false_positive_fix(self) -> None:
        feas_zip = self.out / "zips" / "paid-mcp-engine_项目申报可行性评估.zip"
        with tempfile.TemporaryDirectory() as iso_tmp:
            iso = Path(iso_tmp)
            with ZipFile(feas_zip) as zf:
                zf.extractall(iso)
            proc = _run(str(iso / "scripts" / "validate_feasibility_assessment.py"), "--help", cwd=iso)
            self.assertEqual(proc.returncode, 0, proc.stderr)

        std_zip = self.out / "zips" / "paid-mcp-engine_技术标准起草与审查.zip"
        with tempfile.TemporaryDirectory() as iso_tmp:
            iso = Path(iso_tmp)
            with ZipFile(std_zip) as zf:
                zf.extractall(iso)
            draft = iso / "std.md"
            draft.write_text(
                "# 前言\n本文件起草。\n"
                "# 范围\n本文件规定了冷链食品成型设备的校区应用场景与响应要求，数据来源【合成】。\n"
                "# 规范性引用文件\n本文件没有规范性引用文件。\n"
                "# 术语和定义\n本文件没有需要界定的术语和定义。\n"
                "# 技术要求\n设备温控偏差应≤±2℃。\n"
                "# 试验方法\n采用校准温度计测量。\n",
                encoding="utf-8",
            )
            proc = _run(str(iso / "scripts" / "audit_standard_draft.py"), str(draft), cwd=iso)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("要求型条款数：1", proc.stdout)


if __name__ == "__main__":
    unittest.main()
