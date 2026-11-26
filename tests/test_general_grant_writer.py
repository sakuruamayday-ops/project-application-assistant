from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI = REPO_ROOT / "skills" / "general-grant-writer" / "scripts" / "validate_grant_deliverable.py"


def _run_track(tmp_path: Path, track: str, payload: dict, extra: list[str] | None = None) -> tuple[int, dict]:
    fp = tmp_path / f"{track}_{abs(hash(json.dumps(payload, sort_keys=True))) % 100000}.json"
    fp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    cmd = [sys.executable, str(CLI), "--track", track, "--input", str(fp)] + (extra or [])
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    return p.returncode, json.loads(p.stdout)


def test_all_10_tracks_positive_and_negative_probes(tmp_path: Path):
    # 1. institute (169号文 + patent 5th digit)
    rc, out = _run_track(
        tmp_path, "institute",
        {
            "tier": "provincial_key_institute",
            "latest_revenue": 10000,
            "latest_rd_expense": 150,
            "rd_staff_count": 20,
            "rd_equipment_original_value": 300,
            "rd_venue_area_m2": 400,
            "patents": [{"patent_no": "ZL202320123456.7", "type": "发明专利", "filing_date": "2023-05-01"}],
        },
    )
    assert rc == 2 and len(out["errors"]) >= 3

    rc_ok, _ = _run_track(
        tmp_path, "institute",
        {
            "tier": "provincial_institute",
            "latest_revenue": 15000,
            "latest_rd_expense": 600,
            "rd_staff_count": 35,
            "rd_equipment_original_value": 650,
            "rd_venue_area_m2": 800,
            "patents": [{"patent_no": "ZL202310123456.1", "type": "发明专利", "filing_date": "2023-05-01"}],
        },
    )
    assert rc_ok == 0

    # 2. three-first (all-conclusion locator + timeline inversion)
    rc, out = _run_track(
        tmp_path, "three-first",
        {
            "conclusion": "conditional",
            "evidences": [{"name": "检测报告", "locator": ""}],
            "design_start_date": "2025-06-01",
            "prototype_date": "2025-01-01",
            "test_report_date": "2024-12-01",
        },
    )
    assert rc == 2 and any("locator" in e for e in out["errors"]) and any("倒挂" in e for e in out["errors"])

    # 3. subsidy (5-10% retention money PASSES; 0-yuan row BLOCKED)
    rc_ret, out_ret = _run_track(
        tmp_path, "subsidy",
        {
            "construction_start": "2025-01-01",
            "construction_end": "2026-12-31",
            "investments": [
                {
                    "asset_name": "高速精密涂布机",
                    "contract_amount": 500,
                    "invoice_amount": 500,
                    "paid_amount": 475,
                    "retention_ratio": 0.05,
                    "invoice_no": "INV-2025-001",
                    "asset_card_no": "FA-001",
                    "invoice_date": "2025-08-15",
                }
            ],
        },
    )
    assert rc_ret == 0 and out_ret["eligible_investment_total"] == 475.0

    rc_zero, _ = _run_track(
        tmp_path, "subsidy",
        {
            "investments": [
                {"asset_name": "虚假占位设备", "contract_amount": 0, "invoice_amount": 0, "paid_amount": 0}
            ]
        },
    )
    assert rc_zero == 2

    # 4. digitalization (L4 without MES/networking >= 80% BLOCKED)
    rc_dig, _ = _run_track(
        tmp_path, "digitalization",
        {
            "claimed_level": "L4",
            "equipment_networking_rate_pct": 45,
            "deployed_systems": ["ERP"],
            "seven_dimensions": {"人员": 3, "技术": 2},
        },
    )
    assert rc_dig == 2

    # 5. green (% unit PASSES; blank value BLOCKED)
    rc_g_ok, _ = _run_track(
        tmp_path, "green",
        {
            "major_env_or_safety_incident_3y": False,
            "metrics": [
                {"name": "绿色物料使用率", "value": 85.4, "unit": "%"},
                {"name": "单位产值综合能耗", "value": 0.042, "unit": "tce/万元"},
            ],
        },
    )
    assert rc_g_ok == 0

    rc_g_bad, _ = _run_track(
        tmp_path, "green",
        {"metrics": [{"name": "固废利用率", "value": "", "unit": "%"}]},
    )
    assert rc_g_bad == 2

    # 6. agriculture
    rc_ag, _ = _run_track(tmp_path, "agriculture", {"food_safety_incident_3y": True, "agro_processing_revenue_pct": 55})
    assert rc_ag == 2

    # 7. talent (age/return/social security/postdoc)
    rc_tal, out_tal = _run_track(
        tmp_path, "talent",
        {
            "birth_date": "1970-01-01",
            "max_age_limit": 45,
            "return_date": "2015-01-01",
            "max_return_years": 3,
            "social_security_months": 2,
            "min_social_security_months": 6,
            "postdoc_entry_date": "2024-06-01",
            "postdoc_exit_date": "2024-01-01",
            "founder_equity_pct": 10,
            "min_equity_pct": 30,
        },
    )
    assert rc_tal == 2 and len(out_tal["errors"]) == 5

    # 8. trade (negative amount + bad FX math BLOCKED)
    rc_tr, _ = _run_track(
        tmp_path, "trade",
        {
            "records": [
                {"fx_amount": 10000, "fx_rate": 7.2, "rmb_amount": 85000, "customs_no": "C001"},
                {"fx_amount": -500, "fx_rate": 7.2, "rmb_amount": -3600, "customs_no": ""},
            ]
        },
    )
    assert rc_tr == 2

    # 9. ip-project
    rc_ip, _ = _run_track(
        tmp_path, "ip-project",
        {"min_invention_patents": 2, "patents": [{"patent_no": "ZL202310123456.1", "type": "发明专利", "filing_date": "2023-05-01"}]},
    )
    assert rc_ip == 2

    # 10. feasibility (dropped condition & 客户填写 BLOCKED)
    rc_feas, out_feas = _run_track(
        tmp_path, "feasibility",
        {
            "target_period": "客户填写",
            "template_requirements": ["注册成立满一年", "研发费用占比达标"],
            "conditions": [{"match": "根本不存在的条款"}],
        },
    )
    assert rc_feas == 2 and len(out_feas["errors"]) >= 4
