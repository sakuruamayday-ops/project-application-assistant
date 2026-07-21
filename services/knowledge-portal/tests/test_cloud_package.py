from scripts.build_cloud_knowledge_package import source_scope_rejection
from scripts.build_cloud_upload_allowlist import HIGH_RISK_PATTERNS, has_ocr_sidecar
from scripts.import_all_lists_and_case_words import is_case_word
from scripts.import_remaining_knowledge import exclusion_reason
from scripts.import_second_pass_knowledge import basic_rejection, classify_value
from pathlib import Path


def record(path: str, role: str) -> dict[str, object]:
    return {"relative_path": path, "document_role": role}


def test_public_policy_requires_verified_title_signal() -> None:
    item = record("技术中心/公共资料/企业专利情况.xlsx", "10_政策与通知")
    assert source_scope_rejection(item, "public_core") == "public_policy_title_not_verified"


def test_customer_specific_path_is_rejected() -> None:
    item = record("技术中心/某客户/答辩/申报通知.pdf", "10_政策与通知")
    assert source_scope_rejection(item, "public_core") == "non_public_or_case_path"


def test_official_public_list_is_allowed() -> None:
    item = record("名单库/2026年专精特新中小企业认定名单.pdf", "50_名单与对标")
    assert source_scope_rejection(item, "public_core") is None


def test_credit_code_is_not_treated_as_bank_account_without_context() -> None:
    digits = "913301001234567890"
    assert not HIGH_RISK_PATTERNS["bank_account_context"].search(digits)
    assert HIGH_RISK_PATTERNS["bank_account_context"].search(f"银行账号：{digits}")


def test_private_key_is_blocked() -> None:
    assert HIGH_RISK_PATTERNS["private_key"].search("-----BEGIN PRIVATE KEY-----")


def test_pdf_ocr_sidecar_is_detected() -> None:
    paths = {"50_名单与对标/名单.pdf", "50_名单与对标/名单.md"}
    assert has_ocr_sidecar("50_名单与对标/名单.pdf", paths)


def test_case_word_selection_includes_application_and_plan() -> None:
    assert is_case_word("高新/某企业申请书.docx", ".docx")
    assert is_case_word("研究院/企业研究院建设方案.doc", ".doc")


def test_case_word_selection_excludes_science_space_and_contracts() -> None:
    assert not is_case_word("科创空间/项目申请书.docx", ".docx")
    assert not is_case_word("高新/申请书配套销售合同.docx", ".docx")


def test_remaining_import_excludes_requested_file_types() -> None:
    assert exclusion_reason(Path("客户/发明专利说明书.pdf")) == "excluded_patent"
    assert exclusion_reason(Path("客户/企业标准/Q-001.pdf")) == "excluded_enterprise_standard"
    assert exclusion_reason(Path("客户/高新技术企业证书.pdf")) == "excluded_certificate"
    assert exclusion_reason(Path("客户/2025年度审计报告.pdf")) == "excluded_audit_report"
    assert exclusion_reason(Path("客户/员工社保清单.xlsx")) == "excluded_social_security"
    assert exclusion_reason(Path("客户/照片.png")) == "excluded_image"
    assert exclusion_reason(Path("客户/材料.zip")) == "excluded_archive"


def test_remaining_import_keeps_policy_and_guidance_documents() -> None:
    assert exclusion_reason(Path("政策/专精特新中小企业标准.pdf")) is None
    assert exclusion_reason(Path("政策/人力资源和社保厅申报通知.pdf")) is None
    assert exclusion_reason(Path("指南/审计报告复核要点.pdf")) is None


def test_second_pass_excludes_audit_and_certificates() -> None:
    assert basic_rejection(Path("客户/2025年度审计报告.pdf")) == "excluded_sensitive_evidence"
    assert basic_rejection(Path("客户/发明专利证书.pdf")) == "excluded_sensitive_evidence"


def test_second_pass_routes_ip_disclosure_templates() -> None:
    assert classify_value(Path("专利/技术交底书-机械类.docx"), "70_知识产权", "专利") == (
        "70_知识产权方法",
        "专利",
    )
