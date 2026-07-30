from __future__ import annotations

import pytest

from app.task_preflight import (
    assess_conversation_continuity,
    assess_task_preflight,
)


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


def conversation_state() -> dict[str, object]:
    return {
        "current_topic": "讨论会话防遗漏机制",
        "objective": "避免遗忘既有决定和未决事项",
        "confirmed_facts": ["任务前置复盘已经生效"],
        "confirmed_decisions": ["普通闲聊不永久归档"],
        "rejected_options": ["每轮机械输出完整会议纪要"],
        "open_loops": ["WorkBuddy签名包尚未发布"],
        "constraints": ["只有重要决定经确认后才持久保存"],
        "assumptions": ["当前只修改源码，不部署生产"],
        "next_actions": ["加入会话连续性门禁"],
    }


def test_conversation_without_signal_continues_silently():
    result = assess_conversation_continuity(state=conversation_state())

    assert result["status"] == "silent"
    assert result["reminder_required"] is False
    assert result["checkpoint_required"] is False
    assert result["can_form_dependent_conclusion"] is True


def test_reintroduced_rejected_option_triggers_visible_reminder():
    result = assess_conversation_continuity(
        state=conversation_state(),
        signals=[
            {
                "type": "rejected-option-reintroduced",
                "summary": "当前建议重新采用了已否决的逐轮完整纪要",
                "impact": "low",
            }
        ],
    )

    assert result["status"] == "reminder"
    assert result["reminder"].startswith("连续性提醒：")
    assert result["requires_user_resolution"] is False
    assert result["next_action"] == "remind-and-continue"


def test_high_impact_conflict_blocks_dependent_conclusion_once():
    result = assess_conversation_continuity(
        state=conversation_state(),
        signals=[
            {
                "type": "decision-conflict",
                "summary": "是否静默归档与既有隐私决定冲突",
                "impact": "high",
            },
            {
                "type": "constraint-omission",
                "summary": "当前方案遗漏了主人确认门禁",
                "impact": "high",
            },
        ],
    )

    assert result["requires_user_resolution"] is True
    assert result["can_form_dependent_conclusion"] is False
    assert result["blocking_question"].count("请主人一次确认") == 1
    assert "既有隐私决定冲突" in result["blocking_question"]


def test_topic_switch_with_open_loops_emits_four_field_checkpoint():
    result = assess_conversation_continuity(
        state=conversation_state(),
        signals=[
            {
                "type": "topic-shift-with-open-loops",
                "summary": "切换话题前仍有WorkBuddy发布事项未闭环",
                "impact": "low",
            }
        ],
    )

    assert result["status"] == "reminder-and-checkpoint"
    assert result["checkpoint_required"] is True
    assert result["checkpoint_reasons"] == ["topic-switch"]
    assert list(result["checkpoint"]) == [
        "已确认",
        "尚未确认",
        "关键限制",
        "下一步",
    ]
    assert "已否决：每轮机械输出完整会议纪要" in result["checkpoint"][
        "关键限制"
    ]


def test_three_open_loops_trigger_checkpoint_without_visible_reminder():
    state = conversation_state()
    state["open_loops"] = ["事项一", "事项二", "事项三"]
    result = assess_conversation_continuity(state=state)

    assert result["status"] == "checkpoint"
    assert result["reminder_required"] is False
    assert result["checkpoint_reasons"] == ["open-loop-threshold"]


def test_durable_memory_requires_confirmation_and_sensitive_text_is_blocked():
    result = assess_conversation_continuity(
        state=conversation_state(),
        persistence_candidates=[
            {
                "summary": "主人确认会话连续性为长期规则",
                "scope": "durable",
                "kind": "decision",
            },
            {
                "summary": "客户原始聊天记录",
                "scope": "durable",
                "sensitive": True,
            },
            {
                "summary": "临时脑暴想法",
                "scope": "session",
            },
        ],
    )

    assert result["persistence_action"] == "ask-before-persisting"
    assert [item["summary"] for item in result["durable_candidates"]] == [
        "主人确认会话连续性为长期规则"
    ]
    assert [
        item["summary"] for item in result["blocked_sensitive_candidates"]
    ] == ["客户原始聊天记录"]
