package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
)

const intentRuleVersion = "7-delivery-action-scoped-negation"

// Commas and ideographic enumeration commas stay inside one scope.  A prompt
// such as "禁止调用 MCP、读取文件、生成测试报告" is one negative request,
// not three independent clauses.  Only sentence boundaries and explicit
// turn/reset conjunctions end the current intent scope.
var clauseSeparator = regexp.MustCompile(`(?:但是|而是|然后|但)|[。；！？;!?\n]+`)
var negatedDeliveryAction = regexp.MustCompile(`(?:不要|不用|无需|暂不|先不|不得|禁止|别|不)(?:再)?\s*(?:生成|撰写|出具|形成|输出|制作|整理成)`)
var negatedNonDelivery = regexp.MustCompile(`(?:不要|别|不能|不应|无需)(?:再)?\s*(?:只|仅|仅仅)?\s*(?:解释|回答|说明|查询)`)
var quotedOrCode = regexp.MustCompile("(?s)```.*?```|`[^`]*`|“[^”]*”|‘[^’]*’|「[^」]*」|『[^』]*』|\\\"[^\\\"]*\\\"|'[^']*'")

var continuationExact = []string{"继续", "请继续", "继续任务", "继续完成", "继续完成任务", "继续完成未完成任务", "继续完成未完成的任务"}
var continuationPrefixes = []string{"继续完成", "继续刚才", "继续上个", "继续上一", "接着完成", "接着刚才", "请继续完成"}
var formalNegations = []string{"不要生成报告", "不生成报告", "不用生成报告", "无需生成报告", "不要形成正式材料", "不形成正式材料"}
var deliveryActions = []string{"生成", "撰写", "出具", "形成", "输出", "制作", "整理成", "起草", "编制", "做一份"}
var deliveryArtifacts = []string{"报告", "申请书", "申报材料", "正式材料", "正式稿", "提交稿", "交付文件", "word", "pdf", "excel", "标准草案", "正式标准"}
var deliveryReferences = []string{"文件", "简版", "完整版", "正式版", "终稿"}
var currentExecutionMarkers = []string{"直接", "现在", "立即", "马上", "立刻"}
var deferredMarkers = []string{"如果", "假如", "以后", "将来", "到时候", "确认后", "等我确认", "下一步再"}
var discussionMarkers = []string{"是什么意思", "怎么理解", "是指什么", "是否意味着", "需要准备哪些", "要准备哪些", "需要什么材料"}
var nonDeliveryRequests = []string{"只解释", "仅解释", "只回答", "仅查询", "只查询", "只列材料清单", "只列清单"}
var technicalContextMarkers = []string{"Hook", "hook", "插件", "黑箱", "验收", "execution-ledger", "测试汇总", "事实汇总", "运行日志", "技术报告"}
var businessArtifactMarkers = []string{"政府项目报告", "政府项目可行性报告", "可行性报告", "申报报告", "企业分析报告", "财税报告", "税务报告", "专利报告", "申请书", "申报材料", "标准草案", "正式标准"}
var negativeScopeMarkers = []string{"不要", "不用", "无需", "暂不", "先不", "不得", "禁止", "别", "不应", "不能"}

func leadingNegativeOwnsDelivery(clause string) bool {
	firstAction := -1
	for _, action := range deliveryActions {
		if index := strings.Index(clause, action); index >= 0 && (firstAction < 0 || index < firstAction) {
			firstAction = index
		}
	}
	if firstAction < 0 {
		return false
	}
	firstNegative := -1
	for _, marker := range negativeScopeMarkers {
		if index := strings.Index(clause, marker); index >= 0 && (firstNegative < 0 || index < firstNegative) {
			firstNegative = index
		}
	}
	return firstNegative >= 0 && firstNegative < firstAction
}

type deliveryContract struct {
	Raw map[string]any
}

func loadContract(pluginRoot string) deliveryContract {
	for _, path := range []string{filepath.Join(pluginRoot, "delivery-contracts.json"), filepath.Join(pluginRoot, "skills", "delivery-contracts.json")} {
		data, err := os.ReadFile(path)
		if err != nil {
			continue
		}
		var raw map[string]any
		if json.Unmarshal(data, &raw) == nil {
			return deliveryContract{Raw: raw}
		}
	}
	return deliveryContract{Raw: map[string]any{}}
}

func (contract deliveryContract) strings(key string) []string {
	return anyStrings(contract.Raw[key])
}

func anyStrings(value any) []string {
	items, ok := value.([]any)
	if !ok {
		return nil
	}
	result := make([]string, 0, len(items))
	for _, item := range items {
		text := strings.TrimSpace(toString(item))
		if text != "" {
			result = append(result, text)
		}
	}
	return result
}

func toString(value any) string {
	if value == nil {
		return ""
	}
	if text, ok := value.(string); ok {
		return text
	}
	return ""
}

func containsAny(text string, markers []string) bool {
	for _, marker := range markers {
		if marker != "" && strings.Contains(text, marker) {
			return true
		}
	}
	return false
}

func promptSignalSet(prompt string, contract deliveryContract) promptSignals {
	applicability := map[string]bool{}
	if skills, ok := contract.Raw["skills"].(map[string]any); ok {
		for skill, raw := range skills {
			if spec, ok := raw.(map[string]any); ok {
				applicability[skill] = containsAny(prompt, anyStrings(spec["applies_when_prompt_contains"]))
			}
		}
	}
	return promptSignals{
		ComplexTask:            containsAny(prompt, contract.strings("complex_task_markers")),
		PolicyTask:             containsAny(prompt, contract.strings("policy_task_markers")),
		PeerTask:               containsAny(prompt, contract.strings("peer_task_markers")),
		FormalBusinessDelivery: formalDeliveryIntent(prompt, contract),
		BusinessDomain:         containsAny(prompt, contract.strings("business_domain_markers")),
		SkillApplicability:     applicability,
	}
}

func formalDeliveryIntent(prompt string, contract deliveryContract) bool {
	prompt = quotedOrCode.ReplaceAllString(prompt, "")
	decisionSet := false
	decision := false
	artifactContext := false
	deferredContext := false
	for _, clause := range clauseSeparator.Split(prompt, -1) {
		clause = strings.TrimSpace(clause)
		if clause == "" {
			continue
		}
		folded := strings.ToLower(clause)
		hasArtifact := containsAny(folded, deliveryArtifacts)
		hasReference := containsAny(folded, deliveryReferences)
		hasAction := containsAny(clause, deliveryActions)
		direct := containsAny(clause, currentExecutionMarkers)
		technicalContext := containsAny(clause, technicalContextMarkers)
		businessArtifact := containsAny(clause, businessArtifactMarkers)
		technicalReport := containsAny(clause, []string{"插件测试报告", "报告门禁", "技术验收", "Hook JSON"})
		// A leading or otherwise unbroken negative marker owns the complete
		// enumeration until an explicit reset conjunction.  This prevents
		// later actions in the same sentence from escaping the negation scope.
		if containsAny(clause, nonDeliveryRequests) && !negatedNonDelivery.MatchString(clause) {
			decisionSet, decision = true, false
			artifactContext = artifactContext || hasArtifact
			continue
		}
		negated := leadingNegativeOwnsDelivery(clause) || negatedDeliveryAction.MatchString(clause) || containsAny(clause, formalNegations)
		if negated && (hasArtifact || hasAction || artifactContext) {
			decisionSet, decision = true, false
			artifactContext = artifactContext || hasArtifact
			continue
		}
		discussion := containsAny(clause, discussionMarkers)
		deferred := containsAny(clause, deferredMarkers)
		effectiveDeferred := deferred || deferredContext
		if discussion || (effectiveDeferred && !direct) {
			artifactContext = artifactContext || hasArtifact
			deferredContext = deferred && !(hasAction || hasArtifact)
			continue
		}
		if technicalContext && (!businessArtifact || technicalReport) {
			artifactContext = artifactContext || hasArtifact
			continue
		}
		referentialArtifact := hasReference && artifactContext
		requestedArtifact := (strings.Contains(clause, "给我") || strings.Contains(clause, "我要")) && (hasArtifact || referentialArtifact)
		if requestedArtifact || (hasAction && (hasArtifact || referentialArtifact)) {
			decisionSet, decision = true, true
		}
		artifactContext = artifactContext || hasArtifact
		deferredContext = false
	}
	return decisionSet && decision
}

func continuationRequested(prompt string, payload map[string]any) bool {
	for _, key := range []string{"continuation", "is_continuation", "resume_previous", "automatic_retry"} {
		if value, ok := payload[key].(bool); ok && value {
			return true
		}
	}
	source := strings.ToLower(toString(payload["source"]))
	if source == "" {
		source = strings.ToLower(toString(payload["trigger"]))
	}
	for _, candidate := range []string{"auto-continue", "auto_continue", "automatic-retry", "automatic_retry", "resume-previous", "resume_previous"} {
		if source == candidate {
			return true
		}
	}
	normalized := strings.NewReplacer(" ", "", "\t", "", "\n", "", "，", "", "。", "", "；", "", "！", "", "？", "", ",", "", ".", "", "!", "", "?", "", ";", "", "：", "", ":", "").Replace(prompt)
	if normalized == "" || len([]rune(normalized)) > 48 {
		return false
	}
	if containsExact(continuationExact, normalized) {
		return true
	}
	for _, prefix := range continuationPrefixes {
		if strings.HasPrefix(normalized, prefix) {
			return true
		}
	}
	return false
}

func continuationBaseState(root string, current behaviorState, prompt string, payload map[string]any) behaviorState {
	if !continuationRequested(prompt, payload) || current.Status == "blocked" {
		return current
	}
	if candidate := recentBlockedState(root); candidate.Status == "blocked" {
		return candidate
	}
	return current
}

func containsExact(values []string, target string) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
}

func mergeSignals(previous, current promptSignals) promptSignals {
	merged := current
	merged.ComplexTask = previous.ComplexTask || current.ComplexTask
	merged.PolicyTask = previous.PolicyTask || current.PolicyTask
	merged.PeerTask = previous.PeerTask || current.PeerTask
	merged.FormalBusinessDelivery = previous.FormalBusinessDelivery || current.FormalBusinessDelivery
	merged.BusinessDomain = previous.BusinessDomain || current.BusinessDomain
	if merged.SkillApplicability == nil {
		merged.SkillApplicability = map[string]bool{}
	}
	for key, value := range previous.SkillApplicability {
		merged.SkillApplicability[key] = value || merged.SkillApplicability[key]
	}
	return merged
}

func activeRoles(active []activeSkill, contract deliveryContract) map[string][]string {
	result := map[string][]string{"primary_business": {}, "supporting_business": {}, "quality_gate": {}, "infrastructure": {}, "unclassified": {}}
	definitions, _ := contract.Raw["skill_roles"].(map[string]any)
	for _, name := range skillNames(active) {
		role := ""
		if definition, ok := definitions[name].(map[string]any); ok {
			role = toString(definition["role"])
		} else {
			role = toString(definitions[name])
		}
		if _, ok := result[role]; !ok {
			role = "unclassified"
		}
		result[role] = append(result[role], name)
	}
	for _, values := range result {
		sort.Strings(values)
	}
	return result
}
