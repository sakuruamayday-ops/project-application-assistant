from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_active_installation_docs_exclude_legacy_flow() -> None:
    paths = (
        ROOT / "docs/config/local-knowledge.md",
        ROOT / "docs/user-guide/企业全生命周期助手用户使用手册.md",
        ROOT / "services/knowledge-portal/README.md",
        ROOT / "services/knowledge-portal/templates/agent_diagnostics.html",
        ROOT / "services/knowledge-portal/templates/portal.html",
        ROOT / "services/knowledge-portal/templates/skill_center.html",
    )
    forbidden = (
        "jiaotang_kb_setup",
        "第三步 · 执行 bootstrap",
        "设备签名验证",
        "设备公钥登记",
        "签名插件根目录 `.mcp.json`",
    )
    for path in paths:
        text = path.read_text(encoding="utf-8")
        hits = [marker for marker in forbidden if marker in text]
        assert not hits, f"{path.relative_to(ROOT)} 仍包含旧安装机制：{hits}"


def test_word_manual_excludes_legacy_flow() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/update_user_manual_template.py"),
            "--check",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
