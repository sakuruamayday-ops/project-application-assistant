from datetime import date

from app.policy_retrieval import select_policy_evidence


def test_direct_official_page_wins_even_when_search_index_missed():
    result = select_policy_evidence(
        [
            {
                "title": "2026年度高新技术企业申报认定通知",
                "year": 2026,
                "source_url": (
                    "https://jxt.zj.gov.cn/col/col1229886900/art/2026/"
                    "art_7ecbc859150f48e499725022aeb5880c.html"
                ),
                "source_role": "issuing-authority-original",
                "retrieval_channel": "direct-url",
                "verification_status": "official-page-verified",
                "quoted_claims": ["eligibility_threshold"],
            },
            {
                "title": "2025年度通知",
                "year": 2025,
                "source_url": "https://jxt.zj.gov.cn/art/2025/example.html",
                "source_role": "issuing-authority-original",
                "retrieval_channel": "department-site-search",
            },
        ],
        target_year=2026,
        requested_claims=["application_deadline", "eligibility_threshold"],
        as_of=date(2026, 7, 30),
    )

    assert result["status"] == "official-original"
    assert result["selected_documents"][0]["year"] == 2026
    assert result["prohibited_claims"] == []


def test_subordinate_official_citation_only_allows_explicitly_quoted_claims():
    result = select_policy_evidence(
        [
            {
                "year": 2026,
                "source_url": "https://kjj.hangzhou.gov.cn/art/example.html",
                "source_role": "subordinate-official-citation",
                "retrieval_channel": "subordinate-official-search",
                "quoted_claims": ["application_deadline", "eligible_cohort"],
            }
        ],
        target_year=2026,
        requested_claims=[
            "application_deadline",
            "eligible_cohort",
            "application_materials",
        ],
    )

    assert result["status"] == "official-citation-fallback"
    assert result["prohibited_claims"] == ["application_materials"]
    assert result["formal_annual_conclusion_allowed"] is False


def test_management_measure_fallback_never_reuses_old_annual_deadline():
    result = select_policy_evidence(
        [
            {
                "year": 2016,
                "source_url": "https://www.most.gov.cn/policy/management.html",
                "source_role": "management-basis",
                "retrieval_channel": "latest-notice-citation",
                "policy_status": "current",
            },
            {
                "year": 2025,
                "source_url": "https://jxt.zj.gov.cn/art/2025/notice.html",
                "source_role": "issuing-authority-original",
                "retrieval_channel": "department-site-search",
            },
        ],
        target_year=2026,
        requested_claims=[
            "eligibility_threshold",
            "preparation_direction",
            "application_deadline",
        ],
    )

    assert result["status"] == "management-baseline-only"
    assert result["allowed_claims"] == [
        "eligibility_threshold",
        "evaluation_method",
        "preparation_direction",
        "validity_period",
    ]
    assert result["prohibited_claims"] == ["application_deadline"]
    assert result["formal_annual_conclusion_allowed"] is False
