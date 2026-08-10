package main

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

const blockedContinuationTTL = 30 * time.Minute

type activeSkill struct {
	Skill       string `json:"skill"`
	RuleVersion string `json:"rule_version"`
	TurnID      string `json:"turn_id"`
	ActivatedAt string `json:"activated_at"`
}

type promptSignals struct {
	ComplexTask            bool            `json:"complex_task"`
	PolicyTask             bool            `json:"policy_task"`
	PeerTask               bool            `json:"peer_task"`
	FormalBusinessDelivery bool            `json:"formal_business_delivery"`
	BusinessDomain         bool            `json:"business_domain"`
	SkillApplicability     map[string]bool `json:"skill_applicability"`
}

type behaviorState struct {
	SchemaVersion           int            `json:"schema_version"`
	SessionID               any            `json:"session_id"`
	TurnID                  string         `json:"turn_id"`
	StateOrigin             string         `json:"state_origin"`
	PromptContextOK         bool           `json:"prompt_context_ok"`
	PromptSHA256            string         `json:"prompt_sha256"`
	PromptEventID           string         `json:"prompt_event_id,omitempty"`
	PromptSignals           promptSignals  `json:"prompt_signals"`
	ActiveSkills            []activeSkill  `json:"active_skills"`
	Status                  string         `json:"status"`
	SubmittedAt             string         `json:"submitted_at,omitempty"`
	ActivatedAt             string         `json:"activated_at,omitempty"`
	CompletedAt             string         `json:"completed_at,omitempty"`
	CheckedAt               string         `json:"checked_at,omitempty"`
	RootSource              string         `json:"root_source"`
	PlatformAdapter         string         `json:"platform_adapter"`
	IntentRuleVersion       string         `json:"intent_rule_version"`
	PreviousDeliveryBlocked bool           `json:"previous_delivery_blocked"`
	BlockedErrorCode        any            `json:"blocked_error_code"`
	ContinuedFromTurnID     any            `json:"continued_from_turn_id"`
	DeliveryReceipt         map[string]any `json:"delivery_receipt,omitempty"`
}

func nowISO() string { return time.Now().Format(time.RFC3339) }

func randomTurnID() string {
	buffer := make([]byte, 10)
	if _, err := rand.Read(buffer); err == nil {
		return hex.EncodeToString(buffer)
	}
	return fmt.Sprintf("%x", time.Now().UnixNano())
}

func hashText(value string) string {
	digest := sha256.Sum256([]byte(value))
	return hex.EncodeToString(digest[:])
}

func sessionKey(value any) string {
	text := fmt.Sprint(value)
	if strings.TrimSpace(text) == "" || text == "<nil>" {
		text = "anonymous"
	}
	return hashText(text)[:24]
}

func statePaths(root string, session any) (string, string) {
	key := sessionKey(session)
	return filepath.Join(root, "sessions", key+".json"), filepath.Join(root, "sessions", key+".lock")
}

func lastBlockedPath(root string) string {
	return filepath.Join(root, "last-blocked.json")
}

func recentBlockedState(root string) behaviorState {
	var candidate behaviorState
	_ = readJSON(lastBlockedPath(root), &candidate)
	if candidate.Status != "blocked" {
		return behaviorState{}
	}
	timestamp := candidate.CheckedAt
	if timestamp == "" {
		timestamp = candidate.SubmittedAt
	}
	checkedAt, err := time.Parse(time.RFC3339, timestamp)
	if err != nil {
		return behaviorState{}
	}
	age := time.Since(checkedAt)
	if age < 0 || age > blockedContinuationTTL {
		return behaviorState{}
	}
	return candidate
}

func readJSON(path string, target any) error {
	data, err := os.ReadFile(path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return nil
		}
		return err
	}
	if len(data) == 0 {
		return nil
	}
	return json.Unmarshal(data, target)
}

func atomicJSON(path string, value any) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	data, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return err
	}
	data = append(data, '\n')
	temporary, err := os.CreateTemp(filepath.Dir(path), filepath.Base(path)+".*.tmp")
	if err != nil {
		return err
	}
	name := temporary.Name()
	defer os.Remove(name)
	if err = temporary.Chmod(0o600); err == nil {
		_, err = temporary.Write(data)
	}
	if closeErr := temporary.Close(); err == nil {
		err = closeErr
	}
	if err != nil {
		return err
	}
	if err = os.Rename(name, path); err == nil {
		return nil
	}
	_ = os.Remove(path)
	return os.Rename(name, path)
}

func withStateLock(lockPath string, action func() error) error {
	if err := os.MkdirAll(filepath.Dir(lockPath), 0o700); err != nil {
		return err
	}
	deadline := time.Now().Add(4 * time.Second)
	for {
		file, err := os.OpenFile(lockPath, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
		if err == nil {
			_, _ = file.WriteString(fmt.Sprintf("%d\n", os.Getpid()))
			_ = file.Close()
			defer os.Remove(lockPath)
			return action()
		}
		if !errors.Is(err, os.ErrExist) {
			return err
		}
		if info, statErr := os.Stat(lockPath); statErr == nil && time.Since(info.ModTime()) > 30*time.Second {
			_ = os.Remove(lockPath)
			continue
		}
		if time.Now().After(deadline) {
			return fmt.Errorf("state lock timeout")
		}
		time.Sleep(25 * time.Millisecond)
	}
}

func skillNames(active []activeSkill) []string {
	seen := map[string]bool{}
	for _, item := range active {
		if item.Skill != "" {
			seen[item.Skill] = true
		}
	}
	result := make([]string, 0, len(seen))
	for name := range seen {
		result = append(result, name)
	}
	sort.Strings(result)
	return result
}
