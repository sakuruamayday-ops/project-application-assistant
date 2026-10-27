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
    assert "操作名前缀只表示代码归属" in guidance
    assert "不以先加载所属业务技能为执行前提" in guidance
    assert "不等待业务画像、专业预校验或正式状态回执" in guidance
    assert "不编造来源或结论" in guidance
    assert "后台上传失败不阻断本地文件交付" in guidance
    manifest = json.loads((SKILLS / "suite-manifest.json").read_text())
    contract = manifest["release"]["installation"]["verification"]
    assert "不以所属业务技能预加载" in contract
    assert "固定操作先加载所属技能" not in contract
