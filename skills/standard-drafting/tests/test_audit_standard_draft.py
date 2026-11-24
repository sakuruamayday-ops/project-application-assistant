import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from audit_standard_draft import audit


def draft(scope, extra=""):
    return f"# 验证规范\n## 1 范围\n{scope}\n## 2 规范性引用文件\n无。\n{extra}"


@pytest.mark.parametrize(("scope", "expected"), [
    ("本文件适用于本系统的应用场景。", []),
    ("本文件规定响应时间。", []),
    ("本文件界定人员适应期。", []),
    ("验收示例使用【合成】编号。", []),
    ("企业名称为 XXX。", ["placeholder"]),
])
def test_words_and_placeholders(scope, expected):
    report = audit(draft(scope))
    assert report["requirement_clause_count"] == 0
    assert [item["code"] for item in report["findings"]] == expected


def test_requirements_in_scope_and_core_clauses_keep_being_checked():
    assert [item["code"] for item in audit(draft("平台应保存日志。"))["findings"]] == ["requirement-in-scope"]
    body = """## 3 要求
### 3.1 日志
空调应记录报警。平台不应删除日志。
注：本文示例中说明平台应删除重复日志。
## 附录 A（资料性）
### A.1 样例
平台应关闭服务。
"""
    report = audit(draft("本文件规定日志范围。", body))
    assert report["requirement_clause_count"] == 2
    assert [item["code"] for item in report["findings"]] == ["missing-verification"]
    complete = audit(draft("本文件规定日志范围。", "## 验证方法\n核对日志。\n" + body))
    assert complete["requirement_clause_count"] == 2
    assert complete["findings"] == []
