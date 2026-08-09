package main

import (
	"bufio"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"time"
)

const maxHookInput = 16 * 1024 * 1024
const sessionStartTranscriptTTL = 2 * time.Minute
const promptEventDedupTTL = 5 * time.Second
const currentTurnTTL = 15 * time.Minute
const activationTranscriptAmbiguityWindow = 2 * time.Second

var userQueryPattern = regexp.MustCompile(`(?s)<user_query>(.*?)</user_query>`)
var nonHostSessionPrefixes = []string{"dry-run-", "fixture-", "local-self-check-", "test-"}

func readPayload() (map[string]any, error) {
	data, err := io.ReadAll(io.LimitReader(bufio.NewReader(os.Stdin), maxHookInput+1))
	if err != nil {
		return nil, err
	}
	if len(data) > maxHookInput {
		return nil, fmt.Errorf("stdin too large")
	}
	payload := map[string]any{}
	if len(strings.TrimSpace(string(data))) == 0 {
		return payload, nil
	}
	if err := json.Unmarshal(data, &payload); err != nil {
		return nil, err
	}
	return payload, nil
}

func promptEvent(root string, opts options) int {
	payload, err := readPayload()
	prompt := promptFromPayload(payload)
	if err != nil || strings.TrimSpace(prompt) == "" {
		writeHook(map[string]any{"hook_runtime_ok": false, "error_code": "PROMPT_CONTEXT_UNAVAILABLE", "delivery_check_ok": nil, "state_origin": "unavailable", "prompt_context_ok": false, "root_source": opts.rootSource, "platform_adapter": opts.platformAdapter})
		return 0
	}
	return recordPromptContext(root, opts, payload, prompt, "user_prompt_submit", "UserPromptSubmit", true)
}

func sessionStartEvent(root string, opts options) int {
	payload, err := readPayload()
	if err != nil {
		writeHook(map[string]any{"hook_runtime_ok": false, "error_code": "HOOK_INPUT_INVALID", "delivery_check_ok": nil, "state_origin": "unavailable", "prompt_context_ok": false, "root_source": opts.rootSource, "platform_adapter": opts.platformAdapter})
		return 0
	}
	prompt, eventID, errorCode := promptFromSessionTranscriptDetails(payload)
	if strings.TrimSpace(prompt) == "" {
		writeHook(map[string]any{"hook_runtime_ok": false, "error_code": errorCode, "delivery_check_ok": nil, "state_origin": "unavailable", "prompt_context_ok": false, "prompt_hook_observable": false, "root_source": opts.rootSource, "platform_adapter": opts.platformAdapter})
		return 0
	}
	payload["prompt_event_id"] = eventID
	return recordPromptContext(root, opts, payload, prompt, "session_start_recovery", "SessionStart", true)
}

func promptFromPayload(payload map[string]any) string {
	for _, key := range []string{"user_prompt", "prompt"} {
		if value := strings.TrimSpace(toString(payload[key])); value != "" {
			return value
		}
	}
	return ""
}

func promptFromSessionTranscript(payload map[string]any) (string, string) {
	prompt, _, errorCode := promptFromSessionTranscriptDetails(payload)
	return prompt, errorCode
}

func promptFromSessionTranscriptDetails(payload map[string]any) (string, string, string) {
	sessionID := strings.TrimSpace(toString(payload["session_id"]))
	if sessionID == "" || strings.HasPrefix(sessionID, "${") {
		return "", "", "SESSION_START_SESSION_UNAVAILABLE"
	}
	loweredSession := strings.ToLower(sessionID)
	for _, prefix := range nonHostSessionPrefixes {
		if strings.HasPrefix(loweredSession, prefix) {
			return "", "", "SESSION_START_SESSION_REJECTED"
		}
	}
	transcriptValue := strings.TrimSpace(toString(payload["transcript_path"]))
	if transcriptValue == "" || strings.HasPrefix(transcriptValue, "${") {
		return "", "", "SESSION_START_TRANSCRIPT_UNAVAILABLE"
	}
	transcript, err := filepath.Abs(filepath.Clean(transcriptValue))
	if err != nil {
		return "", "", "SESSION_START_TRANSCRIPT_UNAVAILABLE"
	}
	if resolved, resolveErr := filepath.EvalSymlinks(transcript); resolveErr == nil {
		transcript = resolved
	}
	profile := strings.TrimSpace(os.Getenv("USERPROFILE"))
	if profile == "" {
		profile, err = os.UserHomeDir()
		if err != nil {
			return "", "", "SESSION_START_TRANSCRIPT_UNAVAILABLE"
		}
	}
	allowedRoots := []string{
		filepath.Join(profile, ".workbuddy", "projects"),
		filepath.Join(profile, ".codebuddy", "projects"),
	}
	trusted := false
	for _, allowedRoot := range allowedRoots {
		if pathIsWithin(transcript, allowedRoot) {
			trusted = true
			break
		}
	}
	if strings.ToLower(filepath.Ext(transcript)) != ".jsonl" || strings.TrimSuffix(filepath.Base(transcript), filepath.Ext(transcript)) != sessionID || !trusted {
		return "", "", "SESSION_START_TRANSCRIPT_REJECTED"
	}
	info, err := os.Stat(transcript)
	if err != nil || info.IsDir() {
		return "", "", "SESSION_START_TRANSCRIPT_UNAVAILABLE"
	}
	age := time.Since(info.ModTime())
	if age < 0 || age > sessionStartTranscriptTTL {
		return "", "", "SESSION_START_TRANSCRIPT_STALE"
	}
	return promptFromTranscriptFile(transcript, sessionID)
}

func promptFromTranscriptFile(transcript, sessionID string) (string, string, string) {
	stream, err := os.Open(transcript)
	if err != nil {
		return "", "", "SESSION_START_TRANSCRIPT_UNAVAILABLE"
	}
	defer stream.Close()
	scanner := bufio.NewScanner(stream)
	scanner.Buffer(make([]byte, 64*1024), maxHookInput)
	candidate := ""
	eventID := ""
	lineNumber := 0
	for scanner.Scan() {
		lineNumber++
		if strings.TrimSpace(scanner.Text()) == "" {
			continue
		}
		item := map[string]any{}
		if json.Unmarshal(scanner.Bytes(), &item) != nil {
			return "", "", "SESSION_START_TRANSCRIPT_INVALID"
		}
		if toString(item["type"]) != "message" || toString(item["role"]) != "user" || toString(item["sessionId"]) != sessionID {
			continue
		}
		text := messageText(item["content"])
		matches := userQueryPattern.FindAllStringSubmatch(text, -1)
		if len(matches) > 0 {
			value := strings.TrimSpace(matches[len(matches)-1][1])
			if value != "" {
				candidate = value
				eventID = hashText(fmt.Sprintf("%s:%d:%s", sessionID, lineNumber, scanner.Text()))
			}
		}
	}
	if scanner.Err() != nil {
		return "", "", "SESSION_START_TRANSCRIPT_INVALID"
	}
	if candidate == "" {
		return "", "", "SESSION_START_PROMPT_UNAVAILABLE"
	}
	return candidate, eventID, ""
}

type transcriptCandidate struct {
	path    string
	session string
	prompt  string
	eventID string
	modTime time.Time
}

func encodedProjectDirectory(cwd string) string {
	normalized := filepath.ToSlash(filepath.Clean(cwd))
	if len(normalized) >= 3 && normalized[1] == ':' && normalized[2] == '/' {
		normalized = strings.ToLower(normalized[:1]) + normalized[2:]
	}
	normalized = strings.Trim(normalized, "/")
	return strings.NewReplacer("/", "-", ":", "-").Replace(normalized)
}

func recentTranscriptCandidates(projectRoot string) []transcriptCandidate {
	paths, _ := filepath.Glob(filepath.Join(projectRoot, "*.jsonl"))
	result := make([]transcriptCandidate, 0, len(paths))
	for _, path := range paths {
		info, err := os.Stat(path)
		if err != nil || info.IsDir() {
			continue
		}
		age := time.Since(info.ModTime())
		if age < 0 || age > sessionStartTranscriptTTL {
			continue
		}
		sessionID := strings.TrimSuffix(filepath.Base(path), filepath.Ext(path))
		lowered := strings.ToLower(sessionID)
		rejected := sessionID == ""
		for _, prefix := range nonHostSessionPrefixes {
			rejected = rejected || strings.HasPrefix(lowered, prefix)
		}
		if rejected {
			continue
		}
		prompt, eventID, errorCode := promptFromTranscriptFile(path, sessionID)
		if errorCode == "" {
			result = append(result, transcriptCandidate{path: path, session: sessionID, prompt: prompt, eventID: eventID, modTime: info.ModTime()})
		}
	}
	sort.Slice(result, func(i, j int) bool { return result[i].modTime.After(result[j].modTime) })
	return result
}

func transcriptCandidateForSession(session string, ttl time.Duration) (transcriptCandidate, bool) {
	session = strings.TrimSpace(session)
	if session == "" || filepath.Base(session) != session {
		return transcriptCandidate{}, false
	}
	lowered := strings.ToLower(session)
	for _, prefix := range nonHostSessionPrefixes {
		if strings.HasPrefix(lowered, prefix) {
			return transcriptCandidate{}, false
		}
	}
	profile := strings.TrimSpace(os.Getenv("USERPROFILE"))
	if profile == "" {
		var err error
		profile, err = os.UserHomeDir()
		if err != nil {
			return transcriptCandidate{}, false
		}
	}
	candidates := []transcriptCandidate{}
	for _, base := range []string{filepath.Join(profile, ".workbuddy", "projects"), filepath.Join(profile, ".codebuddy", "projects")} {
		projects, _ := filepath.Glob(filepath.Join(base, "*"))
		for _, project := range projects {
			path := filepath.Join(project, session+".jsonl")
			info, err := os.Stat(path)
			if err != nil || info.IsDir() {
				continue
			}
			age := time.Since(info.ModTime())
			if age < 0 || age > ttl {
				continue
			}
			prompt, eventID, errorCode := promptFromTranscriptFile(path, session)
			if errorCode == "" {
				candidates = append(candidates, transcriptCandidate{path: path, session: session, prompt: prompt, eventID: eventID, modTime: info.ModTime()})
			}
		}
	}
	if len(candidates) == 0 {
		return transcriptCandidate{}, false
	}
	sort.Slice(candidates, func(i, j int) bool { return candidates[i].modTime.After(candidates[j].modTime) })
	return candidates[0], true
}

func recoverPromptForActivation() (map[string]any, string, string) {
	profile := strings.TrimSpace(os.Getenv("USERPROFILE"))
	if profile == "" {
		var err error
		profile, err = os.UserHomeDir()
		if err != nil {
			return nil, "", "ACTIVATION_TRANSCRIPT_UNAVAILABLE"
		}
	}
	cwd, err := os.Getwd()
	if err == nil {
		projectKey := encodedProjectDirectory(cwd)
		for _, base := range []string{filepath.Join(profile, ".workbuddy", "projects"), filepath.Join(profile, ".codebuddy", "projects")} {
			candidates := recentTranscriptCandidates(filepath.Join(base, projectKey))
			if len(candidates) > 0 {
				item := candidates[0]
				return map[string]any{"session_id": item.session, "transcript_path": item.path, "prompt_event_id": item.eventID}, item.prompt, ""
			}
		}
	}
	all := []transcriptCandidate{}
	for _, base := range []string{filepath.Join(profile, ".workbuddy", "projects"), filepath.Join(profile, ".codebuddy", "projects")} {
		projects, _ := filepath.Glob(filepath.Join(base, "*"))
		for _, project := range projects {
			all = append(all, recentTranscriptCandidates(project)...)
		}
	}
	sort.Slice(all, func(i, j int) bool { return all[i].modTime.After(all[j].modTime) })
	if len(all) == 0 {
		return nil, "", "ACTIVATION_TRANSCRIPT_UNAVAILABLE"
	}
	if len(all) > 1 && all[0].modTime.Sub(all[1].modTime) < activationTranscriptAmbiguityWindow {
		return nil, "", "ACTIVATION_TRANSCRIPT_AMBIGUOUS"
	}
	item := all[0]
	return map[string]any{"session_id": item.session, "transcript_path": item.path, "prompt_event_id": item.eventID}, item.prompt, ""
}

func pathIsWithin(path, root string) bool {
	absoluteRoot, err := filepath.Abs(filepath.Clean(root))
	if err != nil {
		return false
	}
	if resolved, resolveErr := filepath.EvalSymlinks(absoluteRoot); resolveErr == nil {
		absoluteRoot = resolved
	}
	relative, err := filepath.Rel(absoluteRoot, path)
	if err != nil {
		return false
	}
	return relative != ".." && !strings.HasPrefix(relative, ".."+string(os.PathSeparator)) && !filepath.IsAbs(relative)
}

func recentSamePrompt(state behaviorState, session any, promptHash, promptEventID string) bool {
	if state.TurnID == "" || state.Status != "pending" || !state.PromptContextOK || state.PromptSHA256 != promptHash || fmt.Sprint(state.SessionID) != fmt.Sprint(session) {
		return false
	}
	if promptEventID != "" && state.PromptEventID == promptEventID {
		return true
	}
	submitted, err := time.Parse(time.RFC3339, state.SubmittedAt)
	if err != nil {
		return false
	}
	age := time.Since(submitted)
	return age >= 0 && age <= promptEventDedupTTL
}

func recordPromptContext(root string, opts options, payload map[string]any, prompt, stateOrigin, hookEventName string, emitReceipt bool) int {
	session := payload["session_id"]
	statePath, lockPath := statePaths(root, session)
	contract := loadContract(opts.pluginRoot)
	currentSignals := promptSignalSet(prompt, contract)
	var state behaviorState
	reused := false
	err := withStateLock(lockPath, func() error {
		var previous behaviorState
		_ = readJSON(statePath, &previous)
		promptHash := hashText(prompt)
		promptEventID := strings.TrimSpace(toString(payload["prompt_event_id"]))
		if recentSamePrompt(previous, session, promptHash, promptEventID) {
			state = previous
			reused = true
			if stateOrigin == "user_prompt_submit" && state.StateOrigin == "session_start_recovery" {
				state.StateOrigin = "user_prompt_submit"
				state.RootSource = opts.rootSource
				state.PlatformAdapter = opts.platformAdapter
				if err := atomicJSON(statePath, state); err != nil {
					return err
				}
			}
			return atomicJSON(filepath.Join(root, "current-turn.json"), map[string]any{"session_id": session, "turn_id": state.TurnID, "updated_at": nowISO(), "state_origin": state.StateOrigin, "platform_adapter": state.PlatformAdapter})
		}
		previous = continuationBaseState(root, previous, prompt, payload)
		if previous.TurnID == "" && continuationRequested(prompt, payload) {
			currentTurn := map[string]any{}
			_ = readJSON(filepath.Join(root, "current-turn.json"), &currentTurn)
			priorSession := currentTurn["session_id"]
			if priorSession != nil && fmt.Sprint(priorSession) != fmt.Sprint(session) {
				priorStatePath, _ := statePaths(root, priorSession)
				var candidate behaviorState
				_ = readJSON(priorStatePath, &candidate)
				if candidate.Status == "blocked" {
					previous = candidate
				}
			}
		}
		continued := previous.Status == "blocked" && continuationRequested(prompt, payload)
		signals := currentSignals
		active := []activeSkill{}
		var blockedCode any
		var continuedTurn any
		if continued {
			signals = mergeSignals(previous.PromptSignals, currentSignals)
			active = append(active, previous.ActiveSkills...)
			blockedCode = previous.DeliveryReceipt["error_code"]
			continuedTurn = previous.TurnID
		}
		state = behaviorState{SchemaVersion: 4, SessionID: session, TurnID: randomTurnID(), StateOrigin: stateOrigin, PromptContextOK: true, PromptSHA256: promptHash, PromptEventID: promptEventID, PromptSignals: signals, ActiveSkills: active, Status: "pending", SubmittedAt: nowISO(), RootSource: opts.rootSource, PlatformAdapter: opts.platformAdapter, IntentRuleVersion: intentRuleVersion, PreviousDeliveryBlocked: continued, BlockedErrorCode: blockedCode, ContinuedFromTurnID: continuedTurn}
		if err := atomicJSON(statePath, state); err != nil {
			return err
		}
		return atomicJSON(filepath.Join(root, "current-turn.json"), map[string]any{"session_id": session, "turn_id": state.TurnID, "updated_at": state.SubmittedAt, "state_origin": state.StateOrigin, "platform_adapter": state.PlatformAdapter})
	})
	if err != nil {
		writeHook(map[string]any{"hook_runtime_ok": false, "error_code": "STATE_PERSISTENCE_FAILED", "delivery_check_ok": nil, "prompt_context_ok": false})
		return 0
	}
	context := "焦糖行为约束已启用：命中正式业务 Skill 时，交付前执行必要章节与结论检查。"
	if state.PreviousDeliveryBlocked {
		context = "上轮正式交付仍被门禁阻断；继续任务必须补齐缺失的主业务Skill或交付要求。"
	} else if state.StateOrigin == "session_start_recovery" {
		context = "WorkBuddy 冷启动首轮提示已从同一会话转录恢复；命中正式业务 Skill 时，交付前执行必要章节与结论检查。"
	}
	promptObservable := state.StateOrigin == "user_prompt_submit"
	promptSource := "session_transcript"
	if promptObservable {
		promptSource = "hook_payload"
	}
	if emitReceipt {
		writeHook(map[string]any{"hook_runtime_ok": true, "error_code": nil, "turn_id": state.TurnID, "state_origin": state.StateOrigin, "prompt_context_ok": true, "prompt_sha256_present": true, "prompt_hook_observable": promptObservable, "prompt_context_source": promptSource, "prompt_event_reused": reused, "root_source": state.RootSource, "platform_adapter": state.PlatformAdapter, "formal_business_delivery": state.PromptSignals.FormalBusinessDelivery, "business_domain": state.PromptSignals.BusinessDomain, "intent_rule_version": intentRuleVersion, "previous_delivery_blocked": state.PreviousDeliveryBlocked, "blocked_error_code": state.BlockedErrorCode, "continued_from_turn_id": state.ContinuedFromTurnID, "hookSpecificOutput": map[string]any{"hookEventName": hookEventName, "additionalContext": context}})
	}
	return 0
}

func promptContextOrigin(origin string) bool {
	return origin == "user_prompt_submit" || origin == "session_start_recovery" || origin == "skill_activation_recovery"
}

func currentTurnSession(root string) any {
	current := map[string]any{}
	_ = readJSON(filepath.Join(root, "current-turn.json"), &current)
	session := current["session_id"]
	turnID := strings.TrimSpace(toString(current["turn_id"]))
	updatedAt, err := time.Parse(time.RFC3339, strings.TrimSpace(toString(current["updated_at"])))
	if session == nil || strings.TrimSpace(fmt.Sprint(session)) == "" || turnID == "" || err != nil {
		return "anonymous"
	}
	age := time.Since(updatedAt)
	if age < 0 || age > currentTurnTTL {
		return "anonymous"
	}
	statePath, _ := statePaths(root, session)
	var state behaviorState
	_ = readJSON(statePath, &state)
	if state.TurnID != turnID || state.Status != "pending" || !state.PromptContextOK || !promptContextOrigin(state.StateOrigin) {
		return "anonymous"
	}
	return session
}

func activateEvent(root string, opts options) int {
	if !validSkillName(opts.skill) {
		writeHook(map[string]any{"activation_ok": false, "error_code": "INVALID_SKILL_NAME", "skill": opts.skill, "root_source": opts.rootSource})
		return 0
	}
	skillsRoot := filepath.Join(opts.pluginRoot, "skills")
	resolved := filepath.Join(skillsRoot, opts.skill)
	if info, err := os.Stat(filepath.Join(resolved, "SKILL.md")); err != nil || info.IsDir() {
		writeHook(map[string]any{"activation_ok": false, "error_code": "SKILL_DIRECTORY_UNAVAILABLE", "skill": opts.skill, "root_source": opts.rootSource})
		return 0
	}
	session := any(strings.TrimSpace(opts.session))
	if session == "" || strings.HasPrefix(fmt.Sprint(session), "${") {
		payload, prompt, _ := recoverPromptForActivation()
		if strings.TrimSpace(prompt) != "" {
			_ = recordPromptContext(root, opts, payload, prompt, "skill_activation_recovery", "SkillActivation", false)
			session = payload["session_id"]
		} else {
			session = currentTurnSession(root)
		}
	}
	statePath, lockPath := statePaths(root, session)
	contract := loadContract(opts.pluginRoot)
	var state behaviorState
	err := withStateLock(lockPath, func() error {
		_ = readJSON(statePath, &state)
		if state.Status == "completed" || (!promptContextOrigin(state.StateOrigin) && state.StateOrigin != "activation_fallback") || state.TurnID == "" {
			state = behaviorState{SchemaVersion: 4, SessionID: session, TurnID: randomTurnID(), StateOrigin: "activation_fallback", PromptContextOK: false, PromptSignals: promptSignals{SkillApplicability: map[string]bool{}}, ActiveSkills: []activeSkill{}, Status: "pending", PlatformAdapter: opts.platformAdapter, RootSource: opts.rootSource, IntentRuleVersion: intentRuleVersion}
		}
		found := false
		for _, item := range state.ActiveSkills {
			if item.Skill == opts.skill {
				found = true
			}
		}
		if !found {
			state.ActiveSkills = append(state.ActiveSkills, activeSkill{Skill: opts.skill, RuleVersion: toString(contract.Raw["rule_version"]), TurnID: state.TurnID, ActivatedAt: nowISO()})
		}
		state.ActivatedAt = nowISO()
		return atomicJSON(statePath, state)
	})
	if err != nil {
		writeHook(map[string]any{"activation_ok": false, "error_code": "ACTIVATION_NOT_PERSISTED", "skill": opts.skill, "root_source": opts.rootSource})
		return 0
	}
	names := skillNames(state.ActiveSkills)
	promptObservable := state.StateOrigin == "user_prompt_submit"
	promptSource := "unavailable"
	if promptObservable {
		promptSource = "hook_payload"
	} else if state.StateOrigin == "session_start_recovery" || state.StateOrigin == "skill_activation_recovery" {
		promptSource = "session_transcript"
	}
	writeHook(map[string]any{"activation_ok": true, "hook_runtime_ok": state.PromptContextOK, "error_code": func() any {
		if state.PromptContextOK {
			return nil
		}
		return "PROMPT_CONTEXT_UNAVAILABLE"
	}(), "skill": opts.skill, "turn_id": state.TurnID, "state_origin": state.StateOrigin, "prompt_context_ok": state.PromptContextOK, "prompt_sha256_present": state.PromptSHA256 != "", "prompt_hook_observable": promptObservable, "prompt_context_source": promptSource, "root_source": opts.rootSource, "platform_adapter": state.PlatformAdapter, "state_persisted": true, "active_skills_after": names, "active_skill_count": len(names)})
	return 0
}

func validSkillName(value string) bool {
	if value == "" || len(value) > 63 {
		return false
	}
	for _, char := range value {
		if !((char >= 'a' && char <= 'z') || (char >= '0' && char <= '9') || char == '-') {
			return false
		}
	}
	return true
}

func freshPendingStopState(root string, session any) bool {
	statePath, _ := statePaths(root, session)
	var state behaviorState
	if readJSON(statePath, &state) != nil || state.Status != "pending" || !state.PromptContextOK || !promptContextOrigin(state.StateOrigin) {
		return false
	}
	timestamp := state.ActivatedAt
	if timestamp == "" {
		timestamp = state.SubmittedAt
	}
	updatedAt, err := time.Parse(time.RFC3339, timestamp)
	if err != nil {
		return false
	}
	age := time.Since(updatedAt)
	return age >= 0 && age <= currentTurnTTL
}

func recoveredStopSession(root string, payload map[string]any) (any, string, bool) {
	// The activation fallback and Stop hook can receive different host session
	// identifiers even though they belong to the same WorkBuddy turn.  Only
	// trust the transcript bound to the atomically published current turn and
	// only while that turn itself is still fresh.  Stop may run more than two
	// minutes after activation while the report and validator receipt are being
	// generated, so it must not reuse the shorter activation-recovery window.
	// This prevents an unrelated recent transcript from overriding a valid
	// Stop payload, while still allowing a duplicate Stop to return the already
	// completed receipt.
	current := map[string]any{}
	if readJSON(filepath.Join(root, "current-turn.json"), &current) != nil {
		return nil, "", false
	}
	recoveredSession := strings.TrimSpace(toString(current["session_id"]))
	if recoveredSession == "" {
		return nil, "", false
	}
	updatedAt, err := time.Parse(time.RFC3339, strings.TrimSpace(toString(current["updated_at"])))
	if err != nil {
		return nil, "", false
	}
	age := time.Since(updatedAt)
	if age < 0 || age > currentTurnTTL {
		return nil, "", false
	}
	statePath, _ := statePaths(root, recoveredSession)
	var state behaviorState
	if readJSON(statePath, &state) != nil || state.TurnID != strings.TrimSpace(toString(current["turn_id"])) || (state.Status != "pending" && state.Status != "completed") || !state.PromptContextOK || !promptContextOrigin(state.StateOrigin) {
		return nil, "", false
	}
	payloadSession := payload["session_id"]
	if fmt.Sprint(payloadSession) == fmt.Sprint(recoveredSession) {
		return recoveredSession, "stop_payload", true
	}
	// A fresh, prompt-grounded pending payload can belong to another live
	// WorkBuddy window. Preserve that explicit session instead of allowing the
	// process-wide current-turn pointer to steal a concurrent Stop event.
	if freshPendingStopState(root, payloadSession) {
		return nil, "", false
	}

	// The current-turn/state pair is the durable activation receipt. WorkBuddy
	// may rotate, rewrite, or move the JSONL transcript before Stop runs, so a
	// transcript re-read is useful corroboration but cannot be a prerequisite
	// for using a newer pending turn over an old blocked host payload.
	source := "current_turn_state"
	transcript, ok := transcriptCandidateForSession(recoveredSession, currentTurnTTL)
	if ok && state.PromptSHA256 == hashText(transcript.prompt) && (transcript.eventID == "" || state.PromptEventID == transcript.eventID) {
		source = "session_transcript_current_turn"
	}
	return recoveredSession, source, true
}

func stopStateSession(root string, payload map[string]any) (any, string, bool) {
	payloadSession := payload["session_id"]
	if recoveredSession, source, ok := recoveredStopSession(root, payload); ok {
		matched := fmt.Sprint(recoveredSession) == fmt.Sprint(payloadSession)
		return recoveredSession, source, matched
	}
	return payloadSession, "stop_payload", true
}

func stopEvent(root string, opts options) int {
	payload, err := readPayload()
	if err != nil {
		writeHook(map[string]any{"hook_runtime_ok": false, "error_code": "HOOK_INPUT_INVALID", "delivery_check_ok": nil})
		return 0
	}
	stopSession, stopStateSource, payloadSessionMatched := stopStateSession(root, payload)
	statePath, lockPath := statePaths(root, stopSession)
	returnCode := 0
	err = withStateLock(lockPath, func() error {
		var state behaviorState
		if err := readJSON(statePath, &state); err != nil || state.TurnID == "" {
			writeHook(map[string]any{"hook_runtime_ok": false, "error_code": "PROMPT_CONTEXT_UNAVAILABLE", "delivery_check_ok": nil, "state_origin": "unavailable", "prompt_context_ok": false, "root_source": opts.rootSource, "platform_adapter": opts.platformAdapter})
			return nil
		}
		if state.Status == "completed" {
			writeHook(state.DeliveryReceipt)
			return nil
		}
		if !promptContextOrigin(state.StateOrigin) || !state.PromptContextOK {
			receipt := map[string]any{"hook_runtime_ok": false, "error_code": "PROMPT_CONTEXT_UNAVAILABLE", "delivery_check_ok": nil, "state_origin": state.StateOrigin, "prompt_context_ok": false, "turn_id": state.TurnID, "root_source": opts.rootSource, "platform_adapter": state.PlatformAdapter, "stop_state_source": stopStateSource, "stop_payload_session_matched": payloadSessionMatched}
			state.Status, state.CompletedAt, state.DeliveryReceipt = "completed", nowISO(), receipt
			if err := atomicJSON(statePath, state); err != nil {
				return err
			}
			writeHook(receipt)
			return nil
		}
		receipt, missing := auditDelivery(root, state.TurnID, assistantText(payload), state.ActiveSkills, loadContract(opts.pluginRoot), state.PromptSignals)
		receipt["hook_runtime_ok"] = true
		receipt["stop_event_seen"] = true
		receipt["state_origin"] = state.StateOrigin
		receipt["prompt_context_ok"] = true
		receipt["turn_id"] = state.TurnID
		receipt["root_source"] = state.RootSource
		receipt["platform_adapter"] = state.PlatformAdapter
		receipt["formal_business_delivery"] = state.PromptSignals.FormalBusinessDelivery
		receipt["business_domain"] = state.PromptSignals.BusinessDomain
		receipt["intent_rule_version"] = state.IntentRuleVersion
		receipt["previous_delivery_blocked"] = state.PreviousDeliveryBlocked
		receipt["blocked_error_code"] = state.BlockedErrorCode
		receipt["continued_from_turn_id"] = state.ContinuedFromTurnID
		receipt["stop_state_source"] = stopStateSource
		receipt["stop_payload_session_matched"] = payloadSessionMatched
		state.DeliveryReceipt = receipt
		if len(missing) > 0 {
			state.Status, state.PreviousDeliveryBlocked, state.BlockedErrorCode, state.CheckedAt = "blocked", true, receipt["error_code"], nowISO()
			if err := atomicJSON(statePath, state); err != nil {
				return err
			}
			_ = atomicJSON(lastBlockedPath(root), state)
			output := map[string]any{"continue": false, "reason": "交付检查未通过，请补全后再结束：" + strings.Join(missing, "；"), "suppressOutput": false}
			for key, value := range receipt {
				output[key] = value
			}
			writeJSON(output)
			returnCode = 2
			return nil
		}
		state.Status, state.CompletedAt = "completed", nowISO()
		if err := atomicJSON(statePath, state); err != nil {
			return err
		}
		if state.PreviousDeliveryBlocked {
			_ = atomicJSON(lastBlockedPath(root), map[string]any{"schema_version": state.SchemaVersion, "status": "resolved", "resolved_at": state.CompletedAt, "continued_from_turn_id": state.ContinuedFromTurnID})
		}
		writeHook(receipt)
		return nil
	})
	if err != nil {
		writeHook(map[string]any{"hook_runtime_ok": false, "error_code": "HOOK_RUNTIME_ERROR", "delivery_check_ok": nil, "systemMessage": err.Error()})
		return 0
	}
	return returnCode
}

func assistantText(payload map[string]any) string {
	for _, key := range []string{"last_assistant_message", "assistant_response", "response"} {
		if text := messageText(payload[key]); strings.TrimSpace(text) != "" {
			return text
		}
	}
	return ""
}

func messageText(value any) string {
	switch item := value.(type) {
	case string:
		return item
	case []any:
		parts := make([]string, 0, len(item))
		for _, child := range item {
			parts = append(parts, messageText(child))
		}
		return strings.Join(parts, "\n")
	case map[string]any:
		if content := messageText(item["content"]); content != "" {
			return content
		}
		return messageText(item["text"])
	default:
		return ""
	}
}

func loadValidatorReceipts(root, turnID, validatorID string) []map[string]any {
	receipts := []map[string]any{}
	turnID = strings.TrimSpace(turnID)
	if turnID == "" {
		return receipts
	}
	receiptDir := filepath.Join(root, "validator-receipts", turnID)
	entries, err := os.ReadDir(receiptDir)
	if err != nil {
		return receipts
	}
	for _, entry := range entries {
		if entry.IsDir() || !strings.HasSuffix(strings.ToLower(entry.Name()), ".json") {
			continue
		}
		path := filepath.Join(receiptDir, entry.Name())
		data, err := os.ReadFile(path)
		if err != nil {
			continue
		}
		payload := map[string]any{}
		if json.Unmarshal(data, &payload) != nil || toString(payload["status"]) != "pass" || toString(payload["turn_id"]) != turnID || toString(payload["validator_id"]) != validatorID {
			continue
		}
		artifact, ok := payload["artifact"].(map[string]any)
		if !ok {
			continue
		}
		artifactPath := strings.TrimSpace(toString(artifact["path"]))
		expectedHash := strings.ToLower(strings.TrimSpace(toString(artifact["sha256"])))
		artifactData, err := os.ReadFile(artifactPath)
		if err != nil || len(expectedHash) != 64 {
			continue
		}
		actualHash := fmt.Sprintf("%x", sha256.Sum256(artifactData))
		if actualHash != expectedHash {
			continue
		}
		payload["receipt_path"] = path
		receipts = append(receipts, payload)
	}
	return receipts
}

func auditDelivery(root, turnID, answer string, active []activeSkill, contract deliveryContract, signals promptSignals) (map[string]any, []string) {
	roles := activeRoles(active, contract)
	missing, missingIDs, passedIDs, applied := []string{}, []string{}, []string{}, []string{}
	if len(contract.Raw) > 0 && signals.FormalBusinessDelivery && signals.BusinessDomain && len(roles["primary_business"]) == 0 {
		missing = append(missing, "NO_PRIMARY_BUSINESS_SKILL：正式业务交付未激活主业务Skill；辅助Skill和质量闸门不能替代主业务Skill")
		missingIDs = append(missingIDs, "routing.primary_business_skill")
	}
	validatorReceipts := []map[string]any{}
	grounded, groundedConfigured := contract.Raw["grounded_delivery"].(map[string]any)
	if groundedConfigured && len(grounded) > 0 && signals.FormalBusinessDelivery && signals.BusinessDomain {
		contractID := toString(grounded["contract_id"])
		if contractID == "" {
			contractID = "grounded-evidence/v1"
		}
		applied = append(applied, contractID)
		qualityGate := toString(grounded["quality_gate_skill"])
		if qualityGate == "" {
			qualityGate = "evidence-ledger"
		}
		activeNames := map[string]bool{}
		for _, item := range active {
			activeNames[item.Skill] = true
		}
		if activeNames[qualityGate] {
			passedIDs = append(passedIDs, "grounded.quality_gate")
		} else {
			missing = append(missing, "Grounded交付缺少质量闸门Skill:"+qualityGate)
			missingIDs = append(missingIDs, "grounded.quality_gate")
		}
		validatorID := toString(grounded["validator_id"])
		if validatorID == "" {
			validatorID = "grounded-delivery/v1"
		}
		validatorReceipts = loadValidatorReceipts(root, turnID, validatorID)
		if len(validatorReceipts) > 0 {
			passedIDs = append(passedIDs, "grounded.artifact.report")
		} else {
			missing = append(missing, "Grounded交付缺少当前turn的report文件校验回执")
			missingIDs = append(missingIDs, "grounded.artifact.report")
		}
	}
	// File/template content is intentionally not a Stop hard gate. The host
	// does not reliably provide all created files in the Stop payload, so the
	// Hook only enforces primary-business routing. Deterministic artifact
	// validators remain owned by the corresponding Skill or server generator.
	errorCode := any(nil)
	if len(missing) > 0 {
		errorCode = "DELIVERY_REQUIREMENTS_MISSING"
	}
	if containsExact(missingIDs, "routing.primary_business_skill") {
		errorCode = "NO_PRIMARY_BUSINESS_SKILL"
	}
	receipt := map[string]any{"delivery_check_ok": len(missing) == 0, "error_code": errorCode, "primary_business_skills": roles["primary_business"], "supporting_business_skills": roles["supporting_business"], "quality_gate_skills": roles["quality_gate"], "infrastructure_skills": roles["infrastructure"], "unclassified_skills": roles["unclassified"], "applied_contracts": applied, "passed_requirement_ids": passedIDs, "accepted_na_items": []string{}, "missing_requirement_ids": missingIDs, "validator_receipts": validatorReceipts}
	return receipt, missing
}

func anyActive(active map[string]bool, names ...string) bool {
	for _, name := range names {
		if active[name] {
			return true
		}
	}
	return false
}

func containsCompletedMarker(text string, markers []string) bool {
	for _, marker := range markers {
		start := 0
		for {
			index := strings.Index(text[start:], marker)
			if index < 0 {
				break
			}
			index += start
			clauseStart := -1
			for _, separator := range []string{"。", "！", "？", "；", ";", "\n"} {
				if location := strings.LastIndex(text[:index], separator); location > clauseStart {
					clauseStart = location
				}
			}
			prefix := []rune(text[clauseStart+1 : index])
			if len(prefix) > 18 {
				prefix = prefix[len(prefix)-18:]
			}
			negative := containsAny(string(prefix), []string{"N/A", "n/a", "不适用", "未生成", "未执行", "未运行", "未完成", "未取得", "未通过", "尚未", "没有", "缺少", "不能满足", "无法确认"})
			if !negative {
				return true
			}
			start = index + len(marker)
		}
	}
	return false
}
