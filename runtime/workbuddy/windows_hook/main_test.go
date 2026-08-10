package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestDataDirectoryIgnoresHostPluginData(t *testing.T) {
	profile := t.TempDir()
	t.Setenv("USERPROFILE", profile)
	t.Setenv("CODEBUDDY_PLUGIN_DATA", filepath.Join(t.TempDir(), "host-plugin-data"))
	t.Setenv("GONGCHUANG_BEHAVIOR_STATE_ROOT", "")

	root, err := dataDirectory()
	if err != nil {
		t.Fatalf("dataDirectory returned error: %v", err)
	}
	want := filepath.Join(profile, ".workbuddy", "state", "gongchuang-behavior")
	if root != want {
		t.Fatalf("dataDirectory=%q want stable root %q", root, want)
	}
	if info, statErr := os.Stat(filepath.Join(root, "sessions")); statErr != nil || !info.IsDir() {
		t.Fatalf("sessions directory unavailable: %v", statErr)
	}
}

func TestDataDirectoryHonorsExplicitBehaviorStateRoot(t *testing.T) {
	configured := filepath.Join(t.TempDir(), "shared-behavior-state")
	t.Setenv("USERPROFILE", t.TempDir())
	t.Setenv("CODEBUDDY_PLUGIN_DATA", filepath.Join(t.TempDir(), "host-plugin-data"))
	t.Setenv("GONGCHUANG_BEHAVIOR_STATE_ROOT", configured)

	root, err := dataDirectory()
	if err != nil {
		t.Fatalf("dataDirectory returned error: %v", err)
	}
	if root != configured {
		t.Fatalf("dataDirectory=%q want explicit root %q", root, configured)
	}
	if info, statErr := os.Stat(filepath.Join(root, "sessions")); statErr != nil || !info.IsDir() {
		t.Fatalf("sessions directory unavailable: %v", statErr)
	}
}
