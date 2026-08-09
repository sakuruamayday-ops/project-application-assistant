package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

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
