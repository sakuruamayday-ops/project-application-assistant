from pathlib import Path

from scripts.import_shichen_curated import rejection_reason


def test_rejects_customer_specific_and_system_files():
    assert rejection_reason(Path("某企业/2025年度审计报告.pdf")) == "sensitive_or_customer_specific"
    assert rejection_reason(Path("某目录/._政策通知.pdf")) == "system_or_temporary"
    assert rejection_reason(Path("某目录/客户材料.zip")) == "unsupported_or_archive"


def test_allows_public_policy_and_blank_template():
    assert rejection_reason(Path("政策/浙江省企业技术中心管理办法.pdf")) is None
    assert rejection_reason(Path("模板/专精特新申请书空白模板.docx")) is None
