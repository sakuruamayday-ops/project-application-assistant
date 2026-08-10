package main

import (
	"path/filepath"
	"testing"
)

func TestFormalDeliveryIntentBaseline(t *testing.T) {
	contract := deliveryContract{Raw: map[string]any{"formal_business_delivery_markers": []any{"形成报告"}}}
	cases := []struct {
		prompt string
		want   bool
	}{
		{"现在生成政府项目可行性报告", true},
		{"不要生成报告，只解释申报条件", false},
		{"以后确认后再生成报告", false},
		{"生成报告是什么意思", false},
		{"不要生成报告，只解释申报条件。结束后记录 Stop Hook 回执。", false},
		{"我问的是“生成报告”是什么意思，以后确认后再做。", false},
		{"禁止调用MCP、读取文件、生成测试报告", false},
		{"本轮不形成材料，资料齐全后再生成", false},
		{"请记录报告门禁测试结果", false},
		{"不要只解释，但现在直接生成报告", true},
		{"整理 TC-15 技术验收事实汇总，说明政府项目报告门禁结果。", false},
		{"请生成 V1.5.8 插件测试报告，覆盖政府项目报告门禁。", false},
		{"执行 V1.5.8-RC2 Windows 提示词语义测试3。请整理一段 TC-15 插件技术验收事实汇总。这是插件技术验收，不是企业分析、政府项目咨询或客户正式报告。本轮只能加载 consistency-check，不得加载主业务 Skill。原样输出 Hook JSON，用不超过五行输出技术事实汇总，不得生成政府项目可行性报告。", false},
		{"整理插件验收结论，禁止生成政府项目可行性报告。", false},
		{"现在生成测试项目政府项目可行性报告。", true},
		{"给我一份政府项目可行性报告。", true},
	}
	for _, item := range cases {
		if got := formalDeliveryIntent(item.prompt, contract); got != item.want {
			t.Fatalf("%q got %v want %v", item.prompt, got, item.want)
		}
	}
}

func TestSignalMergeKeepsBlockedTaskOnlyWhenRequested(t *testing.T) {
	previous := promptSignals{FormalBusinessDelivery: true, BusinessDomain: true, SkillApplicability: map[string]bool{"project-feasibility": true}}
	current := promptSignals{SkillApplicability: map[string]bool{}}
	merged := mergeSignals(previous, current)
	if !merged.FormalBusinessDelivery || !merged.BusinessDomain || !merged.SkillApplicability["project-feasibility"] {
		t.Fatal("signals not merged")
	}
}

func TestExplicitContinuationRecoversDurableBlockedSnapshot(t *testing.T) {
	root := t.TempDir()
	blocked := behaviorState{
		SchemaVersion:           4,
		SessionID:               "prior-session",
		TurnID:                  "blocked-turn",
		Status:                  "blocked",
		CheckedAt:               nowISO(),
		PreviousDeliveryBlocked: true,
		BlockedErrorCode:        "NO_PRIMARY_BUSINESS_SKILL",
	}
	if err := atomicJSON(lastBlockedPath(root), blocked); err != nil {
		t.Fatal(err)
	}
	current := behaviorState{SessionID: "automatic-host-turn", TurnID: "automatic-turn", Status: "completed"}
	prompt := "继续完成上一轮未完成的任务。不要加载任何新Skill，也不要补救，直接结束。"
	got := continuationBaseState(root, current, prompt, map[string]any{})
	if got.TurnID != "blocked-turn" || got.Status != "blocked" {
		t.Fatalf("durable blocked state not recovered: %#v", got)
	}
	if filepath.Base(lastBlockedPath(root)) != "last-blocked.json" {
		t.Fatal("unexpected blocked snapshot path")
	}
}
