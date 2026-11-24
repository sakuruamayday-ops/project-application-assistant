#!/usr/bin/env python3
"""End-to-end verification tests for the WorkBuddy High-Tech + SME commercial pilot split."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt

REPO_ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build_workbuddy_single.py"
BLACKBOARD_SCRIPT = REPO_ROOT / "skills" / "_runtime" / "workbuddy-core" / "facts_blackboard.py"


def _run(*cmd: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-B", *cmd],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


class WorkBuddyPilotSplitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._build_tmp = tempfile.TemporaryDirectory(prefix="wb-build-")
        cls.build_out = Path(cls._build_tmp.name)
        proc = _run(str(BUILD_SCRIPT), "--output", str(cls.build_out))
        if proc.returncode != 0:
            raise AssertionError(f"build_workbuddy_single.py failed:\n{proc.stderr}\n{proc.stdout}")
        cls.build_summary = json.loads(proc.stdout)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._build_tmp.cleanup()

    def test_build_passes_strict_isolation_and_zero_leaks(self) -> None:
        self.assertEqual(self.build_summary["status"], "pass")
        self.assertEqual(self.build_summary["built_count"], 4)
        self.assertEqual(self.build_summary["errors"], [])

    def test_blackboard_prevents_multi_company_cross_contamination_and_reconciles(self) -> None:
        sys.path.insert(0, str(BLACKBOARD_SCRIPT.parent))
        import facts_blackboard as fb  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            # Save Hangzhou Zhouji Food blackboard with AI design target.
            bb_a = fb.empty_blackboard("杭州洲际食品有限公司", "91330100MA27AAAA11")
            bb_a["lockedProduct"] = {
                "rawAnchor": "蛋挞皮",
                "formalDeclarationName": "基于精准粉质调控及急冻锁鲜工艺的冷冻蛋挞皮",
                "businessType": "product_or_material_maker",
                "sixBasesAlignment": "细分特色食品先进工艺",
                "unpatentedProcessTags": ["精准粉质调控", "急冻锁鲜工艺"],
                "revision": 1,
            }
            bb_a["estimatedMetrics"] = [
                {
                    "moduleId": "H07",
                    "metricName": "预热腔温度",
                    "suggestedValue": "60—90℃",
                    "snippet": "预热腔温度设计控制目标为60—90℃",
                    "origin": "ai_design_target",
                },
                {
                    "moduleId": "H07",
                    "metricName": "饼坯厚度公差",
                    "suggestedValue": "±1.5mm",
                    "snippet": "批产饼坯直径与厚度公差设计控制目标控制在±1.5mm以内",
                    "origin": "ai_design_target",
                },
            ]
            fb.save_blackboard(ws, bb_a, strict=True)

            # Reading for Company B (Zhejiang Shenxin) in the SAME workspace must NOT leak Company A!
            loaded_b, _ = fb.load_blackboard(ws, "浙江申新新材料包装有限公司", "91330400MA28BBBB22")
            self.assertIsNone(loaded_b)

            # Reading for Company A returns exact blackboard.
            loaded_a, _ = fb.load_blackboard(ws, "杭州洲际食品有限公司", "91330100MA27AAAA11")
            self.assertIsNotNone(loaded_a)
            assert loaded_a is not None
            self.assertEqual(loaded_a["lockedProduct"]["rawAnchor"], "蛋挞皮")

            # Reconcile: user replaced temperature with measured 72℃, left ±1.5mm unedited.
            reconciled = fb.reconcile_text_against_estimates(
                loaded_a,
                "预热腔温度实测为72℃（厂内温控记录）；批产饼坯直径与厚度公差设计控制目标控制在±1.5 mm以内。",
            )
            self.assertEqual(reconciled["resolved_count"], 1)
            self.assertEqual(reconciled["pending_count"], 1)
            self.assertEqual(reconciled["pending_estimates"][0]["metricName"], "饼坯厚度公差")

    def test_bare_metal_free_hightech_zip_runs_with_null_coverage(self) -> None:
        zip_path = self.build_out / "zips" / "free-checkup_高新技术企业申报体检.zip"
        with tempfile.TemporaryDirectory() as isolated:
            iso = Path(isolated)
            with ZipFile(zip_path) as zf:
                zf.extractall(iso)
            # Ensure zero commercial masters exist in extracted free skill.
            self.assertEqual(list(iso.rglob("*.docx")), [])
            self.assertEqual(list(iso.rglob("*.xlsx")), [])

            # Run light runtime probe & compare_scenarios with coverage: null (previously crashed exit 2!).
            probe = _run(str(iso / "scripts" / "workbuddy_light_runtime.py"))
            self.assertEqual(probe.returncode, 0, probe.stderr)

            payload = {
                "scenarios": [
                    {
                        "name": "2026窗口",
                        "revenue": [1000, 1200, 1500],
                        "net_assets": [500, 600, 750],
                        "material_coverage": {"qualification": "partial", "growth": "complete"},
                        "scores": {"ip": {"coverage": None}},
                    }
                ]
            }
            inp = iso / "input.json"
            inp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            proc = _run(str(iso / "scripts" / "compare_scenarios.py"), str(inp), cwd=iso)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads(proc.stdout)
            self.assertEqual(out["scenarios"][0]["growth"]["revenue"]["percentage"], "22.50%")
            self.assertIsNone(out["scenarios"][0]["coverage"]["ip"])

    def test_bare_metal_free_sme_zip_runs_and_has_no_persona_leak(self) -> None:
        zip_path = self.build_out / "zips" / "free-checkup_专精特新申报体检.zip"
        with tempfile.TemporaryDirectory() as isolated:
            iso = Path(isolated)
            with ZipFile(zip_path) as zf:
                zf.extractall(iso)
            self.assertEqual(list(iso.rglob("*.docx")), [])

            # Missing args prompt must NOT leak "主人".
            blocked = _run(str(iso / "scripts" / "preflight.py"), "--task-type", "quality-preassessment", cwd=iso)
            self.assertEqual(blocked.returncode, 2)
            self.assertNotIn("主人", blocked.stdout)

            # Ready run for Zhejiang provincial SME.
            ok = _run(
                str(iso / "scripts" / "preflight.py"),
                "--task-type", "quality-preassessment",
                "--project-level", "省级专精特新中小企业",
                "--application-type", "新申报",
                cwd=iso,
            )
            self.assertEqual(ok.returncode, 0, ok.stderr)
            self.assertEqual(json.loads(ok.stdout)["selected_policy"]["quality_score_threshold"], 50)

    def test_bare_metal_paid_hightech_zip_cover_aliases_strict_mode_and_v12_audit(self) -> None:
        zip_path = self.build_out / "zips" / "paid-mcp-engine_高新技术企业申请书撰写.zip"
        with tempfile.TemporaryDirectory() as isolated:
            iso = Path(isolated)
            with ZipFile(zip_path) as zf:
                zf.extractall(iso)

            # 1. Test cover aliases ("所在地区", "公司名称") + lossless fill + vendored validate_docx_text_only.
            template = iso / "assets" / "高新技术企业认定申请书空白模板.docx"
            out_docx = iso / "filled.docx"
            spec_path = iso / "spec.json"
            spec_path.write_text(
                json.dumps(
                    {
                        "cover": {"公司名称": "杭州洲际食品有限公司", "所在地区": "浙江省杭州市"},
                        "registration": {"企业名称": "杭州洲际食品有限公司"},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            fill_proc = _run(
                str(iso / "scripts" / "fill_application_fields.py"),
                str(template), str(spec_path), str(out_docx), "--strict",
                cwd=iso,
            )
            self.assertEqual(fill_proc.returncode, 0, fill_proc.stdout + fill_proc.stderr)
            fill_res = json.loads(fill_proc.stdout)
            self.assertEqual(fill_res["status"], "passed")

            fidelity = _run(
                str(iso / "scripts" / "validate_docx_text_only.py"),
                str(template), str(out_docx), "--allow-empty-cell-text",
                cwd=iso,
            )
            self.assertEqual(fidelity.returncode, 0, fidelity.stdout + fidelity.stderr)

            # 2. Strict mode must fail (exit 2) when an unknown field is passed, while default exits 0.
            bad_spec = iso / "bad_spec.json"
            bad_spec.write_text(json.dumps({"cover": {"不存在的封面格": "X"}}, ensure_ascii=False), encoding="utf-8")
            strict_bad = _run(
                str(iso / "scripts" / "fill_application_fields.py"),
                str(template), str(bad_spec), str(iso / "bad_strict.docx"), "--strict",
                cwd=iso,
            )
            self.assertEqual(strict_bad.returncode, 2)
            tolerant_bad = _run(
                str(iso / "scripts" / "fill_application_fields.py"),
                str(template), str(bad_spec), str(iso / "bad_tol.docx"),
                cwd=iso,
            )
            self.assertEqual(tolerant_bad.returncode, 0)
            self.assertEqual(json.loads(tolerant_bad.stdout)["status"], "partial")

            # 3. Audit v1.2 engineering design target phrasing + mm/RH/± units + 400-char incl. domain + blackboard reconcile.
            doc = Document()
            field = "先进制造与自动化／先进制造技术／食品加工装备／连续化预热定型"
            doc.add_paragraph("研发活动编号：RD01")
            tbl = doc.add_table(rows=0, cols=2)
            for k, v in (
                ("研发活动名称", "冷冻面坯连续化预热定型设备研发"),
                ("技术领域", field),
                (
                    "核心技术及创新点（限400字）",
                    "\n".join(
                        (
                            f"所属技术领域：{field}。",
                            "核心技术：",
                            "1、分区温湿联动预热技术：采用多温区PID加热与补湿联动。预热腔温度设计控制目标为60—90℃，相对湿度55%—75% RH。",
                            "2、伺服同步成型技术：采用双轴伺服驱动与快换模腔。饼坯厚度公差设计控制目标控制在±1.5 mm以内。",
                            "创新点：",
                            "1、将单温区烘烤改为分区温湿闭环控制，按批次抽检水分均匀性。",
                            "2、将固定模腔改为快换双轴同步结构，按同工况测算厚度偏差。",
                        )
                    ),
                ),
                (
                    "取得的阶段性成果（限400字）",
                    "1、项目于2025年完成样机试制。\n2、形成工艺规程与装配图纸。\n3、申报筛粉与成型相关专利2件。\n4、已用于蛋挞皮产线试生产。",
                ),
            ):
                row = tbl.add_row()
                row.cells[0].text = k
                row.cells[1].text = v
            for p in list(doc.paragraphs) + [p for t in doc.tables for r in t.rows for c in r.cells for p in c.paragraphs]:
                for run in p.runs:
                    run.font.name = "宋体"
                    run.font.size = Pt(12)
                    run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
            v12_docx = iso / "zhouji_v12.docx"
            doc.save(v12_docx)

            bb_file = iso / "zhouji.facts.json"
            bb_file.write_text(
                json.dumps(
                    {
                        "company_name": "杭州洲际食品有限公司",
                        "estimatedMetrics": [
                            {"metricName": "预热腔温度", "suggestedValue": "60—90℃", "origin": "ai_design_target"},
                            {"metricName": "速冻中心温度", "suggestedValue": "-18℃", "origin": "ai_design_target"},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            audit_proc = _run(
                str(iso / "scripts" / "audit_application_docx.py"),
                str(v12_docx),
                "--include-domain-in-limit",
                "--blackboard", str(bb_file),
                "--strict",
                cwd=iso,
            )
            self.assertEqual(audit_proc.returncode, 0, audit_proc.stdout + audit_proc.stderr)
            audit = json.loads(audit_proc.stdout)
            self.assertEqual(audit["rd_core_issue_count"], 0)
            self.assertLessEqual(audit["rd_core_innovation"]["RD01"]["total_length"], 400)
            self.assertEqual(audit["estimated_metrics_reconciliation"]["pending_count"], 1)
            self.assertEqual(audit["estimated_metrics_reconciliation"]["resolved_count"], 1)

    def test_bare_metal_paid_sme_zip_validates_v12_ai_meta_for_zhouji_and_shenxin(self) -> None:
        zip_path = self.build_out / "zips" / "paid-mcp-engine_专精特新撰写与培育方案.zip"
        with tempfile.TemporaryDirectory() as isolated:
            iso = Path(isolated)
            with ZipFile(zip_path) as zf:
                zf.extractall(iso)

            help_proc = _run(str(iso / "scripts" / "validate_sme_assessment.py"), "--help", cwd=iso)
            self.assertEqual(help_proc.returncode, 0)

            zhouji = {
                "application_context": {
                    "project_level": "省级专精特新中小企业",
                    "region": "浙江省杭州市",
                    "year": 2026,
                    "application_type": "新申报",
                    "form_version": "2026-v1",
                    "version_status": "confirmed",
                    "policy_status": "current",
                },
                "overall_conclusion": "conditional",
                "four_judgments": {
                    k: {"decision": "retain-after-evidence", "evidence_state": "claimed", "object": "冷冻蛋挞皮", "reason": "工艺升维待补发明专利", "actions": ["按Q2补强发明专利"]}
                    for k in ("leading_product", "bottleneck", "gap_filling", "import_substitution")
                },
                "hard_gates": [],
                "evaluation": {"quality_score": {"status": "pending-platform-evaluation", "value": None}},
                "evidence_gaps": [],
                "risks": [],
                "actions": [],
                "ai_meta": {
                    "lockedProduct": {
                        "rawAnchor": "蛋挞皮",
                        "formalDeclarationName": "基于精准粉质调控及急冻锁鲜工艺的冷冻蛋挞皮",
                        "businessType": "product_or_material_maker",
                        "unpatentedProcessTags": ["精准粉质调控", "急冻锁鲜工艺"],
                    },
                    "patentTierReport": {
                        "direct_support": [],
                        "production_support": [{"patentId": "CN-DEMO-1", "title": "一种筛粉机"}],
                        "weak_or_unrelated": [],
                    },
                    "estimatedMetrics": [
                        {"moduleId": "02", "metricName": "急冻中心温度", "suggestedValue": "-18℃以下", "origin": "ai_design_target"}
                    ],
                },
            }
            jpath = iso / "zhouji_sme.json"
            jpath.write_text(json.dumps(zhouji, ensure_ascii=False), encoding="utf-8")
            proc = _run(str(iso / "scripts" / "validate_sme_assessment.py"), str(jpath), "--strict", cwd=iso)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            res = json.loads(proc.stdout)
            self.assertEqual(res["status"], "pass")
            self.assertTrue(any("direct_support" in w for w in res["warnings"]))


if __name__ == "__main__":
    unittest.main()
