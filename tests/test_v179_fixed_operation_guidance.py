"""Model-visible document instructions must match direct signed operation execution."""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"


@pytest.mark.parametrize("operation_id", [
    "evidence-ledger.create-docx",
    "evidence-ledger.create-docx-from-file",
    "evidence-ledger.apply-office-branding-gold",
])
def test_document_catalog_does_not_require_business_receipts(operation_id):
    manifest = json.loads((SKILLS / "client-runtime-operations.json").read_text())
    operation = next(item for item in manifest["operations"] if item["id"] == operation_id)
    description = operation["description"]
    for stale in ["已通过 chat 预校验", "保留原画像和校验", "首次artifact校验前", "先加载所属技能"]:
        assert stale not in description
    assert operation["sandbox_mode"] == "workspace-write"
    assert operation["network"] == "none"
    assert (SKILLS / operation["script"]).is_file()
    assert operation["stdout_json_schema_version"]


def test_shared_guidance_separates_code_ownership_from_skill_loading():
    guidance = (SKILLS / "_runtime/task-execution.md").read_text()
    assert "前缀表示代码归属" in guidance
    assert "客户端工具目录已登记操作可直接使用" in guidance
    assert "先生成并交付可用产物" in guidance
    assert "资料缺失时继续生成可用稿" in guidance
    assert "登录、隔离、密钥、验签和回滚" in guidance
    manifest = json.loads((SKILLS / "suite-manifest.json").read_text())
    contract = manifest["release"]["installation"]["verification"]
    assert "签名与逐文件完整性一致" in contract
    assert "技能按任务需要读取" in contract
    assert "真实文件生成后直接交付" in contract
