package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strings"
)

const runtimeVersion = "1.6.6"

type options struct {
	command         string
	pluginRoot      string
	session         string
	skill           string
	skillDir        string
	rootSource      string
	platformAdapter string
}

func main() {
	if len(os.Args) == 2 && (os.Args[1] == "version" || os.Args[1] == "--version") {
		writeJSON(map[string]any{"version": runtimeVersion, "runtime_os": runtime.GOOS, "runtime_arch": runtime.GOARCH})
		return
	}
	opts, err := parseOptions(os.Args[1:])
	if err != nil {
		writeHook(map[string]any{"hook_runtime_ok": false, "error_code": "INVALID_ARGUMENTS", "delivery_check_ok": nil, "systemMessage": err.Error()})
		return
	}
	if runtime.GOOS != "windows" {
		writeHook(map[string]any{"hook_runtime_ok": false, "error_code": "NON_WINDOWS_RUNTIME", "delivery_check_ok": nil})
		return
	}
	root, err := canonicalWindowsPath(opts.pluginRoot)
	if err != nil || root == "" {
		writeHook(map[string]any{"hook_runtime_ok": false, "error_code": "PLUGIN_ROOT_UNAVAILABLE", "delivery_check_ok": nil})
		return
	}
	opts.pluginRoot = root
	if opts.rootSource == "auto" || opts.rootSource == "" {
		opts.rootSource = inferRootSource(root)
	}
	dataRoot, err := dataDirectory()
	if err != nil {
		writeHook(map[string]any{"hook_runtime_ok": false, "error_code": "STATE_DIRECTORY_UNAVAILABLE", "delivery_check_ok": nil})
		return
	}
	var code int
	switch opts.command {
	case "session-start":
		code = sessionStartEvent(dataRoot, opts)
	case "prompt":
		code = promptEvent(dataRoot, opts)
	case "activate":
		code = activateEvent(dataRoot, opts)
	case "stop":
		code = stopEvent(dataRoot, opts)
	default:
		writeHook(map[string]any{"hook_runtime_ok": false, "error_code": "INVALID_HOOK_EVENT", "delivery_check_ok": nil})
	}
	if code != 0 {
		os.Exit(code)
	}
}

func parseOptions(args []string) (options, error) {
	if len(args) == 0 {
		return options{}, fmt.Errorf("missing command")
	}
	opts := options{command: strings.TrimSpace(args[0]), rootSource: "auto", platformAdapter: "workbuddy-windows-exe"}
	for index := 1; index < len(args); index++ {
		if index+1 >= len(args) {
			return options{}, fmt.Errorf("missing value for %s", args[index])
		}
		value := args[index+1]
		switch args[index] {
		case "--plugin-root":
			opts.pluginRoot = value
		case "--session":
			opts.session = value
		case "--skill":
			opts.skill = value
		case "--skill-dir":
			opts.skillDir = value
		case "--root-source":
			opts.rootSource = value
		case "--platform-adapter":
			opts.platformAdapter = value
		default:
			return options{}, fmt.Errorf("unknown option %s", args[index])
		}
		index++
	}
	if opts.pluginRoot == "" {
		opts.pluginRoot = os.Getenv("CODEBUDDY_PLUGIN_ROOT")
	}
	return opts, nil
}

func canonicalWindowsPath(value string) (string, error) {
	value = strings.Trim(strings.TrimSpace(value), `"`)
	if strings.HasPrefix(value, "${") || value == "" {
		return "", fmt.Errorf("placeholder or empty path")
	}
	if len(value) >= 3 && value[0] == '/' && value[2] == '/' && ((value[1] >= 'a' && value[1] <= 'z') || (value[1] >= 'A' && value[1] <= 'Z')) {
		value = strings.ToUpper(value[1:2]) + `:\` + filepath.FromSlash(value[3:])
	}
	value = filepath.Clean(value)
	info, err := os.Stat(value)
	if err != nil || !info.IsDir() {
		return "", fmt.Errorf("plugin root not accessible")
	}
	manifest := filepath.Join(value, ".codebuddy-plugin", "plugin.json")
	if info, err = os.Stat(manifest); err != nil || info.IsDir() {
		return "", fmt.Errorf("plugin manifest unavailable")
	}
	return value, nil
}

func inferRootSource(root string) string {
	normalized := strings.ToLower(filepath.ToSlash(root))
	switch {
	case strings.Contains(normalized, "/.workbuddy/plugins/marketplaces/jiaotang/"):
		return "workbuddy-marketplace"
	case strings.Contains(normalized, "/.codebuddy/plugins/marketplaces/jiaotang/"):
		return "codebuddy-marketplace"
	default:
		return "env-plugin-root"
	}
}

func dataDirectory() (string, error) {
	// WorkBuddy injects CODEBUDDY_PLUGIN_DATA only for lifecycle command Hooks.
	// Inline Skill activation commands do not inherit that variable. Using it
	// here therefore splits a single turn across two state roots: prompt/Stop
	// state under the host plugin directory and activation state under the
	// stable user state directory. Keep every Windows entry point on one root.
	configured := strings.TrimSpace(os.Getenv("JIAOTANG_BEHAVIOR_STATE_ROOT"))
	if configured != "" && !strings.HasPrefix(configured, "${") {
		root, err := canonicalDataPath(configured)
		if err == nil {
			if err = os.MkdirAll(filepath.Join(root, "sessions"), 0o700); err != nil {
				return "", err
			}
			return root, nil
		}
	}
	profile := strings.TrimSpace(os.Getenv("USERPROFILE"))
	if profile == "" {
		var err error
		profile, err = os.UserHomeDir()
		if err != nil {
			return "", err
		}
	}
	root := filepath.Join(profile, ".workbuddy", "state", "jiaotang-behavior")
	if err := os.MkdirAll(filepath.Join(root, "sessions"), 0o700); err != nil {
		return "", err
	}
	return root, nil
}

func canonicalDataPath(value string) (string, error) {
	value = strings.Trim(strings.TrimSpace(value), `"`)
	if len(value) >= 3 && value[0] == '/' && value[2] == '/' {
		value = strings.ToUpper(value[1:2]) + `:\` + filepath.FromSlash(value[3:])
	}
	if value == "" {
		return "", fmt.Errorf("empty path")
	}
	return filepath.Clean(value), nil
}

func writeHook(values map[string]any) {
	payload := map[string]any{"continue": true, "suppressOutput": true}
	for key, value := range values {
		payload[key] = value
	}
	writeJSON(payload)
}

func writeJSON(value any) {
	encoder := json.NewEncoder(os.Stdout)
	encoder.SetEscapeHTML(false)
	if err := encoder.Encode(value); err != nil {
		os.Exit(0)
	}
}
