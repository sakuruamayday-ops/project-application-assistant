from scripts.build_policy_version_links import (
    detect_policy_status,
    extract_dates,
    extract_lifecycle_evidence,
    is_policy_candidate,
    normalize_policy_title,
    title_similarity,
)


def test_normalize_policy_title_removes_year_and_version_noise():
    assert normalize_policy_title("2025年度浙江省专精特新中小企业认定管理办法（修订版）.pdf") == normalize_policy_title(
        "浙江省专精特新中小企业认定管理办法2024年版.pdf"
    )


def test_detect_policy_status():
    assert detect_policy_status("本办法自发布之日起废止") == "invalid"
    assert detect_policy_status("公开征求意见稿") == "draft"
    assert detect_policy_status("本办法试行") == "trial"


def test_extract_dates_and_similarity():
    assert extract_dates("发布于2026年7月16日，2026-07-17实施") == ["2026-07-16", "2026-07-17"]
    assert title_similarity("浙江省专精特新中小企业认定管理办法", "浙江省专精特新中小企业管理办法") >= 0.9


def test_extract_lifecycle_evidence_from_original_text():
    evidence = extract_lifecycle_evidence(
        "本办法自2026年8月1日起施行。《浙江省旧项目管理办法》同时废止。"
    )
    assert evidence["self_invalid"] is False
    assert evidence["evidence_types"] == ["explicit_supersedes"]
    assert evidence["supersedes_titles"] == ["浙江省旧项目管理办法"]
    assert "同时废止" in evidence["evidence_quote"]


def test_extract_self_invalid_evidence_from_original_text():
    evidence = extract_lifecycle_evidence("本办法自2025年12月31日起停止执行。")
    assert evidence["self_invalid"] is True
    assert evidence["evidence_types"] == ["self_invalid"]


def test_old_policy_repeal_does_not_invalidate_current_policy():
    evidence = extract_lifecycle_evidence(
        "本意见自发布之日起实施，原《杭州市旧管理办法》同时废止。"
    )
    assert evidence["self_invalid"] is False
    assert evidence["evidence_types"] == ["explicit_supersedes"]


def test_effective_date_reference_does_not_invalidate_current_policy():
    evidence = extract_lifecycle_evidence("杭政办函〔2024〕40号）自本方案施行之日起同时废止。")
    assert evidence["self_invalid"] is False


def test_policy_candidate_uses_filename_not_parent_directory():
    item = {
        "name": "某企业实用新型专利证书.pdf",
        "relative_path": "职称办法及材料/专利证书/某企业实用新型专利证书.pdf",
        "document_role": "60_模板培训",
    }
    assert not is_policy_candidate(item)
