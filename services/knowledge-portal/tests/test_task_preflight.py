from __future__ import annotations

import pytest

from app.task_preflight import assess_task_preflight


def scoring_requirements() -> list[dict[str, object]]:
    return [
        {
            "key": "project_level",
            "label": "项目层级",
            "dimension": "task_type",
            "impact": "high",
            "resolution": "ask-user",
            "allowed_values": ["省级专精特新", "专精特新小巨人"],
            "reason": "项目层级决定政策门槛和评分标准",
        },
        {
            "key": "application_type",
            "label": "申请类型",
            "dimension": "policy_context",
            "impact": "high",
            "resolution": "ask-user",
            "allowed_values": ["新申报", "复核"],
            "reason": "2026年新申报与复核可能适用不同规则",
        },
        {
            "key": "policy_version",
            "label": "现行政策版本",
            "dimension": "policy_context",
            "impact": "high",
            "resolution": "discover",
            "reason": "必须先核验本地规则包和官方来源",
        },
        {
            "key": "standard_input",
            "label": "标准财务底表",
            "dimension": "source_data",
            "impact": "high",
            "resolution": "ask-user",
            "reason": "完整评分不得用缺失数据补造",
        },
        {
            "key": "output_format",
            "label": "输出格式",
            "dimension": "output_contract",
            "impact": "low",
            "resolution": "assume",
            "default": "Excel",
        },
    ]


def test_discoverable_gaps_are_resolved_before_asking_user():
    result = assess_task_preflight(
        objective="完成专精特新申报前评分",
        requirements=scoring_requirements(),
        supplied={},
    )

    assert result["status"] == "needs-discovery"
    assert result["can_start_substantive_work"] is False
    assert [item["key"] for item in result["discover_first"]] == [
        "policy_version"
    ]
    assert result["blocking_question"] is None


def test_high_impact_gaps_collapse_into_one_minimal_question():
    result = assess_task_preflight(
        objective="完成专精特新申报前评分",
        requirements=scoring_requirements(),
        supplied={"policy_version": "2026.1"},
    )

    assert result["status"] == "needs-user-input"
    assert result["can_start_substantive_work"] is False
    assert [item["key"] for item in result["high_impact_gaps"]] == [
        "project_level",
        "application_type",
        "standard_input",
    ]
    assert result["blocking_question"].count("请主人一次确认") == 1
    assert "项目层级" in result["blocking_question"]
    assert "申请类型" in result["blocking_question"]


def test_low_impact_gap_uses_explicit_default_and_proceeds():
    result = assess_task_preflight(
        objective="完成专精特新申报前评分",
        requirements=scoring_requirements(),
        supplied={
            "project_level": "省级专精特新",
            "application_type": "新申报",
            "policy_version": "2026.1",
            "standard_input": "企业三年财务底表.xlsx",
        },
    )

    assert result["status"] == "ready-with-assumptions"
    assert result["can_start_substantive_work"] is True
    assert result["resolved"]["output_format"] == "Excel"
    assert result["blocking_question"] is None


def test_high_impact_field_cannot_be_silently_assumed():
    with pytest.raises(ValueError, match="不得静默假设"):
        assess_task_preflight(
            objective="示例",
            requirements=[
                {
                    "key": "project_level",
                    "label": "项目层级",
                    "dimension": "task_type",
                    "impact": "high",
                    "resolution": "assume",
                    "default": "省级专精特新",
                }
            ],
            supplied={},
        )
