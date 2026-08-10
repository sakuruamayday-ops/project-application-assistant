package main

import (
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func groundedTestContract() deliveryContract {
	return deliveryContract{Raw: map[string]any{
		"skill_roles": map[string]any{
			"industrialization-projects": map[string]any{"role": "primary_business"},
			"evidence-ledger":            map[string]any{"role": "quality_gate"},
		},
		"grounded_delivery": map[string]any{
			"contract_id":        "grounded-evidence/v1",
			"quality_gate_skill": "evidence-ledger",
			"validator_id":       "grounded-delivery/v1",
		},
	}}
}

func writeGroundedTestReceipt(t *testing.T, root, turnID, artifactPath, artifactHash string) string {
	t.Helper()
	receiptDir := filepath.Join(root, "validator-receipts", turnID)
	if err := os.MkdirAll(receiptDir, 0o700); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(receiptDir, "grounded-delivery-v1-test.json")
	payload := map[string]any{
		"validator_id": "grounded-delivery/v1",
		"status":       "pass",
		"turn_id":      turnID,
		"artifact": map[string]any{
			"path":   artifactPath,
			"sha256": artifactHash,
		},
	}
	if err := atomicJSON(path, payload); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestGroundedDeliveryUsesActivePrimarySkillWhenPromptDomainSignalMissing(t *testing.T) {
	root := t.TempDir()
	turnID := "turn-primary-domain-fallback"
	artifactPath := filepath.Join(t.TempDir(), "report.docx")
	artifactData := []byte("validated artifact")
	if err := os.WriteFile(artifactPath, artifactData, 0o600); err != nil {
		t.Fatal(err)
	}
	artifactHash := fmt.Sprintf("%x", sha256.Sum256(artifactData))
	active := []activeSkill{
		{Skill: "industrialization-projects", TurnID: turnID},
		{Skill: "evidence-ledger", TurnID: turnID},
	}
	signals := promptSignals{FormalBusinessDelivery: true, BusinessDomain: false}

	missingReceipt, missing := auditDelivery(root, turnID, "", active, groundedTestContract(), signals)
	if len(missing) != 1 || !containsExact(missingReceipt["missing_requirement_ids"].([]string), "grounded.artifact.report") {
		t.Fatalf("missing receipt did not fail closed: receipt=%#v missing=%#v", missingReceipt, missing)
	}
	if missingReceipt["effective_business_domain"] != true || missingReceipt["business_domain_source"] != "active_primary_business_skill" {
		t.Fatalf("primary skill did not establish effective business domain: %#v", missingReceipt)
	}

	writeGroundedTestReceipt(t, root, turnID, artifactPath, artifactHash)
	receipt, missing := auditDelivery(root, turnID, "", active, groundedTestContract(), signals)
	if len(missing) != 0 || receipt["delivery_check_ok"] != true {
		t.Fatalf("valid current-turn receipt was not consumed: receipt=%#v missing=%#v", receipt, missing)
	}
	if !containsExact(receipt["passed_requirement_ids"].([]string), "grounded.artifact.report") {
		t.Fatalf("artifact requirement not passed: %#v", receipt)
	}
	if got := receipt["validator_receipts"].([]map[string]any); len(got) != 1 {
		t.Fatalf("validator receipt not recorded: %#v", got)
	}
}

func TestGroundedDeliveryRejectsWrongTurnAndChangedArtifact(t *testing.T) {
	root := t.TempDir()
	turnID := "turn-current"
	artifactPath := filepath.Join(t.TempDir(), "report.docx")
	artifactData := []byte("artifact version one")
	if err := os.WriteFile(artifactPath, artifactData, 0o600); err != nil {
		t.Fatal(err)
	}
	artifactHash := fmt.Sprintf("%x", sha256.Sum256(artifactData))
	active := []activeSkill{
		{Skill: "industrialization-projects", TurnID: turnID},
		{Skill: "evidence-ledger", TurnID: turnID},
	}
	signals := promptSignals{FormalBusinessDelivery: true, BusinessDomain: false}

	writeGroundedTestReceipt(t, root, "turn-stale", artifactPath, artifactHash)
	receipt, _ := auditDelivery(root, turnID, "", active, groundedTestContract(), signals)
	if receipt["delivery_check_ok"] != false {
		t.Fatalf("wrong-turn receipt was accepted: %#v", receipt)
	}

	writeGroundedTestReceipt(t, root, turnID, artifactPath, artifactHash)
	if err := os.WriteFile(artifactPath, []byte("artifact version two"), 0o600); err != nil {
		t.Fatal(err)
	}
	receipt, _ = auditDelivery(root, turnID, "", active, groundedTestContract(), signals)
	if receipt["delivery_check_ok"] != false {
		t.Fatalf("changed artifact was accepted: %#v", receipt)
	}
}

func addTestSkill(t *testing.T, pluginRoot, skill string) {
	t.Helper()
	root := filepath.Join(pluginRoot, "skills", skill)
	if err := os.MkdirAll(root, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "SKILL.md"), []byte("---\nname: "+skill+"\ndescription: test\n---\n"), 0o600); err != nil {
		t.Fatal(err)
	}
}

func writeTestTranscript(t *testing.T, profile, session string, prompts ...string) string {
	t.Helper()
	root := filepath.Join(profile, ".workbuddy", "projects", "workspace")
	if err := os.MkdirAll(root, 0o700); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(root, session+".jsonl")
	stream, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	encoder := json.NewEncoder(stream)
	for _, prompt := range prompts {
		if err := encoder.Encode(map[string]any{
			"type":      "message",
			"role":      "user",
			"sessionId": session,
			"content":   "<user_query>" + prompt + "</user_query>",
		}); err != nil {
			stream.Close()
			t.Fatal(err)
		}
	}
	if err := stream.Close(); err != nil {
		t.Fatal(err)
	}
	return path
}

func testOptions(pluginRoot string) options {
	return options{
		pluginRoot:      pluginRoot,
		rootSource:      "workbuddy-marketplace",
		platformAdapter: "workbuddy-windows-exe",
	}
}

func TestSessionStartRecoveryRebuildsTurnAndClearsPriorSkills(t *testing.T) {
	profile := t.TempDir()
	t.Setenv("USERPROFILE", profile)
	pluginRoot := filepath.Join(t.TempDir(), "plugin")
	addTestSkill(t, pluginRoot, "local-knowledge-retrieval")
	addTestSkill(t, pluginRoot, "industrialization-projects")
	stateRoot := filepath.Join(t.TempDir(), "state")
	session := "real-windows-session"
	opts := testOptions(pluginRoot)

	transcript := writeTestTranscript(t, profile, session, "第一轮状态检查")
	payload := map[string]any{"session_id": session, "transcript_path": transcript}
	firstPrompt, errorCode := promptFromSessionTranscript(payload)
	if errorCode != "" || firstPrompt != "第一轮状态检查" {
		t.Fatalf("unexpected recovery: prompt=%q error=%q", firstPrompt, errorCode)
	}
	recordPromptContext(stateRoot, opts, payload, firstPrompt, "session_start_recovery", "SessionStart", false)
	opts.session, opts.skill = session, "local-knowledge-retrieval"
	activateEvent(stateRoot, opts)
	statePath, _ := statePaths(stateRoot, session)
	var first behaviorState
	if err := readJSON(statePath, &first); err != nil {
		t.Fatal(err)
	}

	transcript = writeTestTranscript(t, profile, session, "智能水表主题反查")
	payload["transcript_path"] = transcript
	secondPrompt, errorCode := promptFromSessionTranscript(payload)
	if errorCode != "" || secondPrompt != "智能水表主题反查" {
		t.Fatalf("unexpected recovery: prompt=%q error=%q", secondPrompt, errorCode)
	}
	recordPromptContext(stateRoot, opts, payload, secondPrompt, "session_start_recovery", "SessionStart", false)
	opts.skill = "industrialization-projects"
	activateEvent(stateRoot, opts)
	var second behaviorState
	if err := readJSON(statePath, &second); err != nil {
		t.Fatal(err)
	}
	if first.TurnID == second.TurnID {
		t.Fatalf("turn id reused across prompts: %s", second.TurnID)
	}
	if len(second.ActiveSkills) != 1 || second.ActiveSkills[0].Skill != "industrialization-projects" {
		t.Fatalf("prior skill leaked into new turn: %#v", second.ActiveSkills)
	}
	if second.StateOrigin != "session_start_recovery" || !second.PromptContextOK {
		t.Fatalf("unexpected recovered state: %#v", second)
	}
}

func TestPromptHookUpgradesSameRecoveredPromptWithoutNewTurn(t *testing.T) {
	pluginRoot := filepath.Join(t.TempDir(), "plugin")
	stateRoot := filepath.Join(t.TempDir(), "state")
	session := "real-upgrade-session"
	opts := testOptions(pluginRoot)
	payload := map[string]any{"session_id": session}

	recordPromptContext(stateRoot, opts, payload, "同一条提示", "session_start_recovery", "SessionStart", false)
	statePath, _ := statePaths(stateRoot, session)
	var recovered behaviorState
	if err := readJSON(statePath, &recovered); err != nil {
		t.Fatal(err)
	}
	recordPromptContext(stateRoot, opts, payload, "同一条提示", "user_prompt_submit", "UserPromptSubmit", false)
	var upgraded behaviorState
	if err := readJSON(statePath, &upgraded); err != nil {
		t.Fatal(err)
	}
	if recovered.TurnID != upgraded.TurnID {
		t.Fatalf("same prompt created duplicate turns: %s != %s", recovered.TurnID, upgraded.TurnID)
	}
	if upgraded.StateOrigin != "user_prompt_submit" {
		t.Fatalf("prompt origin was not upgraded: %s", upgraded.StateOrigin)
	}
}

func writeProjectTranscript(t *testing.T, profile, cwd, session string, prompts ...string) string {
	t.Helper()
	root := filepath.Join(profile, ".workbuddy", "projects", encodedProjectDirectory(cwd))
	if err := os.MkdirAll(root, 0o700); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(root, session+".jsonl")
	stream, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	encoder := json.NewEncoder(stream)
	for _, prompt := range prompts {
		if err := encoder.Encode(map[string]any{
			"type":      "message",
			"role":      "user",
			"sessionId": session,
			"content":   "<user_query>" + prompt + "</user_query>",
		}); err != nil {
			stream.Close()
			t.Fatal(err)
		}
	}
	if err := stream.Close(); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestActivationRecoversCurrentProjectTranscriptAndIsolatesTurns(t *testing.T) {
	profile := t.TempDir()
	t.Setenv("USERPROFILE", profile)
	workspace := filepath.Join(t.TempDir(), "current-workspace")
	if err := os.MkdirAll(workspace, 0o700); err != nil {
		t.Fatal(err)
	}
	previousCWD, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Chdir(workspace); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.Chdir(previousCWD) })

	pluginRoot := filepath.Join(t.TempDir(), "plugin")
	addTestSkill(t, pluginRoot, "local-knowledge-retrieval")
	addTestSkill(t, pluginRoot, "industrialization-projects")
	stateRoot := filepath.Join(t.TempDir(), "state")
	session := "windows-real-session"
	writeProjectTranscript(t, profile, workspace, session, "第一轮状态检查")

	opts := testOptions(pluginRoot)
	opts.skill = "local-knowledge-retrieval"
	activateEvent(stateRoot, opts)
	statePath, _ := statePaths(stateRoot, session)
	var first behaviorState
	if err := readJSON(statePath, &first); err != nil {
		t.Fatal(err)
	}
	if first.StateOrigin != "skill_activation_recovery" || !first.PromptContextOK || first.PromptEventID == "" {
		t.Fatalf("activation did not recover prompt context: %#v", first)
	}
	if len(first.ActiveSkills) != 1 || first.ActiveSkills[0].Skill != "local-knowledge-retrieval" {
		t.Fatalf("unexpected first activation: %#v", first.ActiveSkills)
	}

	writeProjectTranscript(t, profile, workspace, session, "第一轮状态检查", "智能水表主题反查")
	opts.skill = "industrialization-projects"
	activateEvent(stateRoot, opts)
	var second behaviorState
	if err := readJSON(statePath, &second); err != nil {
		t.Fatal(err)
	}
	if first.TurnID == second.TurnID {
		t.Fatalf("new transcript event reused stale turn: %s", second.TurnID)
	}
	if len(second.ActiveSkills) != 1 || second.ActiveSkills[0].Skill != "industrialization-projects" {
		t.Fatalf("prior turn skill leaked: %#v", second.ActiveSkills)
	}
}

func TestActivationRecoveryReusesSameTranscriptEventAcrossSkills(t *testing.T) {
	profile := t.TempDir()
	t.Setenv("USERPROFILE", profile)
	workspace := filepath.Join(t.TempDir(), "current-workspace")
	if err := os.MkdirAll(workspace, 0o700); err != nil {
		t.Fatal(err)
	}
	previousCWD, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Chdir(workspace); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.Chdir(previousCWD) })

	pluginRoot := filepath.Join(t.TempDir(), "plugin")
	addTestSkill(t, pluginRoot, "local-knowledge-retrieval")
	addTestSkill(t, pluginRoot, "industrialization-projects")
	stateRoot := filepath.Join(t.TempDir(), "state")
	session := "windows-shared-turn"
	writeProjectTranscript(t, profile, workspace, session, "组合任务")

	opts := testOptions(pluginRoot)
	opts.skill = "local-knowledge-retrieval"
	activateEvent(stateRoot, opts)
	statePath, _ := statePaths(stateRoot, session)
	var first behaviorState
	if err := readJSON(statePath, &first); err != nil {
		t.Fatal(err)
	}
	opts.skill = "industrialization-projects"
	activateEvent(stateRoot, opts)
	var second behaviorState
	if err := readJSON(statePath, &second); err != nil {
		t.Fatal(err)
	}
	if first.TurnID != second.TurnID {
		t.Fatalf("same transcript event created duplicate turns: %s != %s", first.TurnID, second.TurnID)
	}
	if got := skillNames(second.ActiveSkills); len(got) != 2 || got[0] != "industrialization-projects" || got[1] != "local-knowledge-retrieval" {
		t.Fatalf("same-turn skills did not accumulate: %#v", got)
	}
}

func TestStopUsesCurrentTranscriptTurnWhenPayloadSessionDiffers(t *testing.T) {
	profile := t.TempDir()
	t.Setenv("USERPROFILE", profile)
	workspace := filepath.Join(t.TempDir(), "current-workspace")
	if err := os.MkdirAll(workspace, 0o700); err != nil {
		t.Fatal(err)
	}
	previousCWD, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Chdir(workspace); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.Chdir(previousCWD) })

	pluginRoot := filepath.Join(t.TempDir(), "plugin")
	addTestSkill(t, pluginRoot, "project-feasibility")
	addTestSkill(t, pluginRoot, "evidence-ledger")
	stateRoot := filepath.Join(t.TempDir(), "state")
	transcriptSession := "transcript-session"
	writeProjectTranscript(t, profile, workspace, transcriptSession, "继续完成测试可行性报告")

	opts := testOptions(pluginRoot)
	opts.skill = "project-feasibility"
	activateEvent(stateRoot, opts)
	opts.skill = "evidence-ledger"
	activateEvent(stateRoot, opts)

	wrongSession := "stop-payload-session"
	wrongPath, _ := statePaths(stateRoot, wrongSession)
	if err := atomicJSON(wrongPath, behaviorState{
		SchemaVersion:   4,
		SessionID:       wrongSession,
		TurnID:          "stale-stop-turn",
		StateOrigin:     "session_start_recovery",
		PromptContextOK: true,
		PromptSHA256:    hashText("TC06 stale turn"),
		PromptSignals: promptSignals{
			FormalBusinessDelivery: true,
			BusinessDomain:         true,
			SkillApplicability:     map[string]bool{},
		},
		ActiveSkills: []activeSkill{},
		Status:       "blocked",
		SubmittedAt:  time.Now().Add(-time.Hour).Format(time.RFC3339),
	}); err != nil {
		t.Fatal(err)
	}

	resolved, source, matched := stopStateSession(stateRoot, map[string]any{"session_id": wrongSession})
	if fmt.Sprint(resolved) != transcriptSession {
		t.Fatalf("Stop kept stale payload session: got %v want %s", resolved, transcriptSession)
	}
	if source != "session_transcript_current_turn" || matched {
		t.Fatalf("unexpected Stop resolution metadata: source=%s matched=%v", source, matched)
	}
	resolvedPath, _ := statePaths(stateRoot, resolved)
	var resolvedState behaviorState
	if err := readJSON(resolvedPath, &resolvedState); err != nil {
		t.Fatal(err)
	}
	if got := skillNames(resolvedState.ActiveSkills); len(got) != 2 || got[0] != "evidence-ledger" || got[1] != "project-feasibility" {
		t.Fatalf("Stop did not resolve the active current turn: %#v", got)
	}
}

func TestStopUsesCurrentTurnTranscriptAfterActivationRecoveryWindow(t *testing.T) {
	profile := t.TempDir()
	t.Setenv("USERPROFILE", profile)
	workspace := filepath.Join(t.TempDir(), "current-workspace")
	if err := os.MkdirAll(workspace, 0o700); err != nil {
		t.Fatal(err)
	}
	previousCWD, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Chdir(workspace); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.Chdir(previousCWD) })

	pluginRoot := filepath.Join(t.TempDir(), "plugin")
	addTestSkill(t, pluginRoot, "project-feasibility")
	stateRoot := filepath.Join(t.TempDir(), "state")
	transcriptSession := "transcript-session"
	transcriptPath := writeProjectTranscript(t, profile, workspace, transcriptSession, "继续完成测试可行性报告")

	opts := testOptions(pluginRoot)
	opts.skill = "project-feasibility"
	activateEvent(stateRoot, opts)

	// A real grounded report can take longer than the two-minute activation
	// recovery window.  The current turn remains valid for fifteen minutes and
	// must stay bound to its own transcript even if another transcript is newer.
	older := time.Now().Add(-3 * time.Minute)
	if err := os.Chtimes(transcriptPath, older, older); err != nil {
		t.Fatal(err)
	}
	otherWorkspace := filepath.Join(t.TempDir(), "other-workspace")
	if err := os.MkdirAll(otherWorkspace, 0o700); err != nil {
		t.Fatal(err)
	}
	writeProjectTranscript(t, profile, otherWorkspace, "unrelated-session", "无关的新会话")

	wrongSession := "stale-stop-payload-session"
	resolved, source, matched := stopStateSession(stateRoot, map[string]any{"session_id": wrongSession})
	if fmt.Sprint(resolved) != transcriptSession {
		t.Fatalf("Stop kept stale payload session after activation window: got %v want %s", resolved, transcriptSession)
	}
	if source != "session_transcript_current_turn" || matched {
		t.Fatalf("unexpected Stop resolution metadata: source=%s matched=%v", source, matched)
	}
}

func TestStopUsesCurrentTurnStateWhenTranscriptUnavailable(t *testing.T) {
	profile := t.TempDir()
	t.Setenv("USERPROFILE", profile)
	workspace := filepath.Join(t.TempDir(), "current-workspace")
	if err := os.MkdirAll(workspace, 0o700); err != nil {
		t.Fatal(err)
	}
	previousCWD, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Chdir(workspace); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.Chdir(previousCWD) })

	pluginRoot := filepath.Join(t.TempDir(), "plugin")
	addTestSkill(t, pluginRoot, "project-feasibility")
	stateRoot := filepath.Join(t.TempDir(), "state")
	transcriptSession := "transcript-session"
	transcriptPath := writeProjectTranscript(t, profile, workspace, transcriptSession, "继续完成测试可行性报告")

	opts := testOptions(pluginRoot)
	opts.skill = "project-feasibility"
	activateEvent(stateRoot, opts)
	if err := os.Remove(transcriptPath); err != nil {
		t.Fatal(err)
	}

	resolved, source, matched := stopStateSession(stateRoot, map[string]any{"session_id": "old-blocked-host-session"})
	if fmt.Sprint(resolved) != transcriptSession {
		t.Fatalf("Stop did not use durable current-turn state: got %v want %s", resolved, transcriptSession)
	}
	if source != "current_turn_state" || matched {
		t.Fatalf("unexpected state-only Stop resolution metadata: source=%s matched=%v", source, matched)
	}
}

func TestStopPreservesFreshConcurrentPayloadSession(t *testing.T) {
	profile := t.TempDir()
	t.Setenv("USERPROFILE", profile)
	workspace := filepath.Join(t.TempDir(), "current-workspace")
	if err := os.MkdirAll(workspace, 0o700); err != nil {
		t.Fatal(err)
	}
	previousCWD, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Chdir(workspace); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.Chdir(previousCWD) })

	pluginRoot := filepath.Join(t.TempDir(), "plugin")
	addTestSkill(t, pluginRoot, "project-feasibility")
	stateRoot := filepath.Join(t.TempDir(), "state")
	writeProjectTranscript(t, profile, workspace, "current-session", "当前窗口任务")

	opts := testOptions(pluginRoot)
	opts.skill = "project-feasibility"
	activateEvent(stateRoot, opts)

	concurrentSession := "concurrent-session"
	concurrentPath, _ := statePaths(stateRoot, concurrentSession)
	if err := atomicJSON(concurrentPath, behaviorState{
		SchemaVersion:   4,
		SessionID:       concurrentSession,
		TurnID:          "concurrent-turn",
		StateOrigin:     "session_start_recovery",
		PromptContextOK: true,
		PromptSHA256:    hashText("并发窗口任务"),
		PromptSignals: promptSignals{
			FormalBusinessDelivery: true,
			BusinessDomain:         true,
			SkillApplicability:     map[string]bool{},
		},
		ActiveSkills: []activeSkill{{Skill: "project-feasibility", TurnID: "concurrent-turn", ActivatedAt: nowISO()}},
		Status:       "pending",
		SubmittedAt:  nowISO(),
		ActivatedAt:  nowISO(),
	}); err != nil {
		t.Fatal(err)
	}

	resolved, source, matched := stopStateSession(stateRoot, map[string]any{"session_id": concurrentSession})
	if fmt.Sprint(resolved) != concurrentSession || source != "stop_payload" || !matched {
		t.Fatalf("fresh concurrent Stop payload was overridden: resolved=%v source=%s matched=%v", resolved, source, matched)
	}
}
