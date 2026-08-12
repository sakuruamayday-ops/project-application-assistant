from __future__ import annotations

import importlib.util
import json
from argparse import Namespace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "industry-positioning" / "scripts" / "technical_product_revenue_matrix.py"
SPEC = importlib.util.spec_from_file_location("technical_product_revenue_matrix", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def sample_master() -> dict:
    return {
        "schema_version": "1.0",
        "company": {"name": "示例制造企业有限公司", "as_of_date": "2026-08-12"},
        "technologies": [
            {
                "id": "tech-1",
                "internal_version": "M-A",
                "carrier_type": "material",
                "public_name": "耐介质功能基材",
                "technical_goal": "提高阻隔与韧性",
                "public_route": "相容增强与多层协同",
                "public_window": "企业已公开区间",
                "development_status": "mass_production",
                "sources": [{"document": "技术说明", "locator": "技术章节"}],
                "confidential_boundary": ["不披露精确配方比例"],
            }
        ],
        "products": [
            {
                "id": "prod-1",
                "name": "耐介质包装容器",
                "product_type": "terminal_product",
                "sales_status": "sold",
                "sources": [{"document": "产品说明", "locator": "产品结构"}],
            }
        ],
        "technology_product_links": [
            {
                "technology_id": "tech-1",
                "product_id": "prod-1",
                "relation": "embedded",
                "stable_use": True,
                "performance_contributions": [{"metric": "阻隔性能", "value": "申请书原值"}],
                "source": {"document": "技术说明", "locator": "产品应用"},
            }
        ],
        "commercialization": [
            {
                "product_id": "prod-1",
                "year": "2025",
                "amount": "申请书原值",
                "unit": "万元",
                "basis": "terminal_sales",
                "source": {"document": "申请书", "locator": "经济指标"},
            }
        ],
        "intellectual_property_links": [],
        "project_overrides": {},
    }


def test_master_matrix_validates_and_generates_all_project_views(tmp_path: Path) -> None:
    master = sample_master()
    assert MODULE.validate_master(master) == []
    source = tmp_path / "enterprise_master.json"
    output = tmp_path / "generated"
    MODULE.write_json(source, master)
    result = MODULE.build_command(
        Namespace(input=str(source), output_dir=str(output), projects="all")
    )
    assert result == 0
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["project_views"]) == 11
    assert (output / "enterprise_master_matrix.md").is_file()


def test_master_matrix_rejects_confidential_and_internal_transfer_fields() -> None:
    master = sample_master()
    master["technologies"][0]["exact_formula"] = "不应进入公开母矩阵"
    master["commercialization"][0]["basis"] = "internal_transfer"
    issues = MODULE.validate_master(master)
    assert any("敏感字段" in issue for issue in issues)
    assert any("内部转移收入" in issue for issue in issues)
