const USER_API_SESSION_STORAGE_KEY = "jiaotang-user-model-api";
if (document.querySelector("[data-clear-sensitive-storage-on-load]")) {
  try {
    sessionStorage.removeItem(USER_API_SESSION_STORAGE_KEY);
  } catch {
    // Storage can be unavailable in hardened browser profiles.
  }
}
try {
  document.documentElement.dataset.pageDirection =
    sessionStorage.getItem("jiaotang-page-direction") || "next";
  sessionStorage.removeItem("jiaotang-page-direction");
} catch {
  document.documentElement.dataset.pageDirection = "next";
}

const RISK_CONTROL_SELECTOR = ".text-danger,.text-button.danger,.button.danger,.button.danger-outline,.account-logout-button";
const RISK_SUBMIT_SELECTOR = "button[type='submit'].text-danger,button[type='submit'].text-button.danger,button[type='submit'].button.danger";
const RISK_CONFIRMATIONS = {
  confirm: "这是需要明确确认的风险操作。确认继续？",
  verify: "这是最高等级风险操作。请确认核验信息无误后继续。",
};

// 全站框体流光清单。装饰层自动使用组件未占用的伪元素，避免覆盖原有圆弧、图标和状态标记。
const FLOW_FRAME_SELECTOR = [
  ".auth-shell",
  ".remember-option",
  ".invite-confirmation",
  ".side-nav a.active",
  ".service-state",
  ".account-chip",
  ".account-menu-link",
  ".account-menu-panel",
  ".hero-banner",
  ".hero-command",
  ".button:not(.danger):not(.danger-outline):not(.disabled):not(:disabled):not([aria-disabled='true'])",
  ".metrics",
  ".metrics > a",
  ".panel",
  ".download-card",
  ".cockpit-radar",
  ".assistant-console",
  ".health-grid > a",
  ".detail-grid article",
  ".detail-card-link",
  ".deployment-gate-boundary article",
  ".secret-config-card",
  ".empty-token-state",
  ".table-wrap",
  ".credential-batch-bar",
  ".quick-prompts button",
  ".assistant-progress",
  ".assistant-result",
  ".external-link-grid a",
  ".notice",
  ".token-reveal",
  ".upload-field",
  ".release-modal-card",
  ".preference-status-grid article",
  ".preference-checks label",
  ".page-continuation-link",
  ".endpoint-list > div",
  ".agent-connection-summary",
  ".manual-agent-config",
  ".installation-stage-list li",
  ".feedback-item",
  ".preview-summary-grid article",
  ".preview-commit-bar",
  ".record-summary",
  ".alert-item",
  ".manual-hero",
  ".manual-content",
  ".user-model-config",
  ".calibration-metrics article",
  ".calibration-tabs",
  ".calibration-workspace",
  ".calibration-card",
  ".candidate-comparison",
  ".calibration-form",
  ".policy-facts",
  ".cluster-members",
  ".calibration-empty",
  ".algorithm-stat-card",
  ".algorithm-detail-metrics",
  ".algorithm-chip-list span",
  ".algorithm-routing-notice",
  ".skill-center",
  ".skill-section-tabs",
  ".skill-section-tabs button",
  ".skill-catalog-shell",
  ".skill-group-button",
  ".skill-hero",
  ".skill-metrics div",
  ".skill-filter-bar",
  ".skill-status-filters button",
  ".skill-catalog-table",
  ".skill-download-content",
  ".skill-install-plan",
  ".skill-install-status",
  ".skill-install-result",
  ".skill-install-safety",
  ".skill-detail-dialog",
  ".skill-detail-pane.manual-content",
  ".diagnostics-summary article",
  "[role='dialog']",
].join(",");

const FLOW_FOCUS_SELECTOR = [
  'input:not([type]):not([name="confirmation"])',
  'input:is([type="text"], [type="search"], [type="password"], [type="email"], [type="url"], [type="number"], [type="tel"]):not([name="confirmation"])',
  'textarea:not([name="confirmation"])',
  "select",
].join(",");

const syncFlowDocumentVisibility = () => {
  document.documentElement.classList.toggle(
    "is-atelier-flow-document-visible",
    document.visibilityState === "visible",
  );
};

syncFlowDocumentVisibility();
document.addEventListener("visibilitychange", syncFlowDocumentVisibility, true);
window.addEventListener("pageshow", syncFlowDocumentVisibility);

const flowFrameVisibility = "IntersectionObserver" in window
  ? new IntersectionObserver((entries) => {
    entries.forEach((entry) => entry.target.classList.toggle("is-atelier-flow-visible", entry.isIntersecting));
  }, {rootMargin: "0px", threshold: .01})
  : null;

const observeFlowVisibility = (element) => {
  if (!(element instanceof HTMLElement)) return;
  if (flowFrameVisibility) flowFrameVisibility.observe(element);
  else element.classList.add("is-atelier-flow-visible");
};

const pseudoSlotIsFree = (element, slot) => {
  const content = getComputedStyle(element, slot).content;
  return content === "none" || content === "normal" || content === "";
};

const isVisibleRoundedFrame = (element) => {
  if (!(element instanceof HTMLElement)) return false;
  if (element.matches("input, textarea, select, option, progress, meter")) return false;
  if (element.matches(RISK_CONTROL_SELECTOR) || element.closest("[data-risk-level]") === element) return false;
  const rect = element.getBoundingClientRect();
  if (rect.width < 38 || rect.height < 28) return false;
  const style = getComputedStyle(element);
  const radii = [
    style.borderTopLeftRadius,
    style.borderTopRightRadius,
    style.borderBottomRightRadius,
    style.borderBottomLeftRadius,
  ].map((value) => Number.parseFloat(value) || 0);
  if (Math.max(...radii) < 2) return false;
  const sides = ["Top", "Right", "Bottom", "Left"];
  const hasVisibleBorder = sides.some((side) => {
    const width = Number.parseFloat(style[`border${side}Width`]) || 0;
    const borderStyle = style[`border${side}Style`];
    const color = style[`border${side}Color`].replaceAll(" ", "").toLowerCase();
    const transparent = color === "transparent" || /rgba\([^)]*,0(?:\.0+)?\)$/.test(color);
    return width > 0 && borderStyle !== "none" && borderStyle !== "hidden" && !transparent;
  });
  if (!hasVisibleBorder) return false;
  const looksCircular = Math.abs(rect.width - rect.height) < 4
    && Math.max(...radii) >= Math.min(rect.width, rect.height) * .4;
  return !looksCircular;
};

const decorateFlowFrame = (element) => {
  if (!(element instanceof HTMLElement) || element.dataset.atelierFlowFrame) return;
  const slot = pseudoSlotIsFree(element, "::before")
    ? "before"
    : (pseudoSlotIsFree(element, "::after") ? "after" : "unavailable");
  element.dataset.atelierFlowFrame = slot;
  if (slot === "unavailable") return;
  if (getComputedStyle(element).position === "static") element.classList.add("atelier-flow-needs-position");
  observeFlowVisibility(element);
};

const installFlowFrames = (root = document) => {
  if (root instanceof Element && (root.matches(FLOW_FRAME_SELECTOR) || isVisibleRoundedFrame(root))) {
    decorateFlowFrame(root);
  }
  const candidates = new Set(root.querySelectorAll?.(FLOW_FRAME_SELECTOR) || []);
  root.querySelectorAll?.("[class]").forEach((element) => {
    if (isVisibleRoundedFrame(element)) candidates.add(element);
  });
  candidates.forEach(decorateFlowFrame);
  if (root instanceof Element && root.matches(FLOW_FOCUS_SELECTOR)) observeFlowVisibility(root);
  root.querySelectorAll?.(FLOW_FOCUS_SELECTOR).forEach(observeFlowVisibility);
};

installFlowFrames();
new MutationObserver((records) => {
  records.forEach((record) => record.addedNodes.forEach((node) => {
    if (node instanceof Element) installFlowFrames(node);
  }));
}).observe(document.body, {childList: true, subtree: true});

const FLOW_FRAME_RUNTIME_SELECTOR = '[data-atelier-flow-frame="before"],[data-atelier-flow-frame="after"]';
let hoveredFlowFrame = null;
let focusedFlowFrame = null;

const closestFlowFrame = (target) => (
  target instanceof Element && !target.matches("input,textarea,select")
    ? target.closest(FLOW_FRAME_RUNTIME_SELECTOR)
    : null
);

const setHoveredFlowFrame = (nextFrame, pointerActive) => {
  document.documentElement.classList.toggle("is-atelier-flow-pointer-active", pointerActive);
  if (hoveredFlowFrame === nextFrame) return;
  hoveredFlowFrame?.classList.remove("is-atelier-flow-hovered");
  hoveredFlowFrame = nextFrame;
  hoveredFlowFrame?.classList.add("is-atelier-flow-hovered");
};

const setFocusedFlowFrame = (nextFrame) => {
  if (focusedFlowFrame === nextFrame) return;
  focusedFlowFrame?.classList.remove("is-atelier-flow-focused");
  focusedFlowFrame = nextFrame;
  focusedFlowFrame?.classList.add("is-atelier-flow-focused");
};

const syncPointerFlowFrame = (event) => {
  setHoveredFlowFrame(closestFlowFrame(event.target), true);
};

document.addEventListener("pointerover", syncPointerFlowFrame, true);
document.addEventListener("pointermove", syncPointerFlowFrame, true);
document.addEventListener("pointerout", (event) => {
  if (event.relatedTarget === null) setHoveredFlowFrame(null, false);
}, true);
window.addEventListener("blur", () => setHoveredFlowFrame(null, false));
document.addEventListener("keydown", (event) => {
  if (["Tab", "ArrowUp", "ArrowRight", "ArrowDown", "ArrowLeft"].includes(event.key)) {
    setHoveredFlowFrame(null, false);
  }
}, true);
document.addEventListener("focusin", (event) => setFocusedFlowFrame(closestFlowFrame(event.target)), true);
document.addEventListener("focusout", (event) => setFocusedFlowFrame(closestFlowFrame(event.relatedTarget)), true);

const riskLevelForControl = (control) => {
  const form = control.closest("form");
  if (form?.querySelector("input[name='confirmation']") || form?.action.includes("/purge")) return "verify";
  if (form?.dataset.confirm || control.matches(RISK_SUBMIT_SELECTOR)) return "confirm";
  return "caution";
};

document.querySelectorAll(RISK_CONTROL_SELECTOR).forEach((control) => {
  const level = control.dataset.riskLevel || riskLevelForControl(control);
  control.dataset.riskLevel = level;
  control.closest("form")?.setAttribute("data-risk-level", level);
});

document.addEventListener("submit", (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement)) return;
  const riskControl = form.querySelector(RISK_SUBMIT_SELECTOR);
  const riskLevel = form.dataset.riskLevel || (riskControl ? riskLevelForControl(riskControl) : "");
  const confirmation = form.dataset.confirm || RISK_CONFIRMATIONS[riskLevel];
  if (confirmation && !window.confirm(confirmation)) {
    event.preventDefault();
    event.stopImmediatePropagation();
    return;
  }
  if (form.dataset.clearSensitiveStorage !== undefined) {
    try {
      sessionStorage.removeItem(USER_API_SESSION_STORAGE_KEY);
    } catch {
      // Storage can be unavailable in hardened browser profiles.
    }
  }
}, true);

document.querySelectorAll("[data-credential-batch]").forEach((form) => {
  const credentialChecks = [...form.querySelectorAll("[data-credential-select]")];
  const selectAll = form.querySelector("[data-credential-select-all]");
  const selection = form.querySelector("[data-credential-selection]");
  const batchSubmit = form.querySelector("[data-credential-batch-submit]");
  const updateSelection = () => {
    const checkedCount = credentialChecks.filter((control) => control.checked).length;
    if (selection) selection.textContent = checkedCount ? `已选择 ${checkedCount} 条` : "尚未选择";
    if (batchSubmit) batchSubmit.disabled = checkedCount === 0;
    if (selectAll) {
      selectAll.checked = credentialChecks.length > 0 && checkedCount === credentialChecks.length;
      selectAll.indeterminate = checkedCount > 0 && checkedCount < credentialChecks.length;
    }
  };
  selectAll?.addEventListener("change", () => {
    credentialChecks.forEach((control) => {
      control.checked = selectAll.checked;
    });
    updateSelection();
  });
  credentialChecks.forEach((control) => control.addEventListener("change", updateSelection));
  updateSelection();
});

function renderAssistantAnswer(container, value) {
  container.replaceChildren();
  const urlPattern = /(https:\/\/[^\s]+)/g;
  value.split(urlPattern).forEach((part) => {
    if (part.startsWith("https://")) {
      const link = document.createElement("a");
      link.href = part;
      link.textContent = part;
      link.target = "_blank";
      link.rel = "noopener";
      container.appendChild(link);
    } else {
      container.appendChild(document.createTextNode(part));
    }
  });
}

async function copyToClipboard(value) {
  if (navigator.clipboard?.writeText && window.isSecureContext) {
    await navigator.clipboard.writeText(value);
    return;
  }
  const temporary = document.createElement("textarea");
  temporary.value = value;
  temporary.setAttribute("readonly", "");
  temporary.className = "clipboard-fallback";
  document.body.appendChild(temporary);
  temporary.select();
  const copied = document.execCommand("copy");
  temporary.remove();
  if (!copied) throw new Error("浏览器未允许复制，请刷新页面后重试。");
}

function appendAssistantProgress(list, payload) {
  list.querySelector("li.is-active")?.classList.replace("is-active", "is-complete");
  const item = document.createElement("li");
  item.className = "is-active";
  const title = document.createElement("strong");
  title.textContent = payload.message;
  item.appendChild(title);
  const details = payload.details || {};
  const fragments = [];
  if (Array.isArray(details.skills)) fragments.push(`Skills：${details.skills.join("、")}`);
  if (details.query) fragments.push(`检索：${String(details.query).slice(0, 80)}`);
  if (details.document_id) fragments.push(`文档：#${details.document_id}`);
  if (details.skill_name) fragments.push(`Skill：${details.skill_name}`);
  if (details.tool) fragments.push(`工具：${details.tool}`);
  if (details.reason) fragments.push(`原因码：${details.reason}`);
  if (details.sources !== undefined) fragments.push(`来源：${details.sources}份`);
  if (details.new_sources !== undefined) fragments.push(`新增来源：${details.new_sources}份`);
  if (details.round) fragments.push(`轮次：${details.round}`);
  if (fragments.length) {
    const note = document.createElement("small");
    note.textContent = fragments.join(" · ");
    item.appendChild(note);
  }
  list.appendChild(item);
  item.scrollIntoView({block: "nearest", behavior: "smooth"});
}

function renderAssistantResult(payload, elements) {
  renderAssistantAnswer(elements.answer, payload.answer);
  elements.mode.textContent = {
    "language-model": "大模型 + Skills",
    "usage-guide": "平台使用指南",
    "knowledge-search": "知识库检索",
  }[payload.mode] || payload.mode;
  elements.skills.replaceChildren();
  (payload.skills || []).forEach((skill) => {
    const chip = document.createElement("span");
    chip.textContent = skill;
    elements.skills.appendChild(chip);
  });
  elements.sources.replaceChildren();
  (payload.sources || []).forEach((item) => {
    const row = document.createElement(item.url ? "a" : "span");
    const title = document.createElement("strong");
    title.textContent = item.document_id ? `#${item.document_id} ${item.title}` : `联网来源 · ${item.title}`;
    row.appendChild(title);
    if (item.url) {
      row.href = item.url;
      row.target = "_blank";
      row.rel = "noopener noreferrer";
    }
    elements.sources.appendChild(row);
  });
  if (payload.quota) {
    if (payload.quota.unlimited) {
      elements.quota.textContent = "管理员不限次数";
    } else {
      elements.quota.textContent = payload.quota.counted
        ? `今日剩余 ${payload.quota.remaining}/${payload.quota.limit}`
        : `自带 API · 不计次数 · 免费额度仍剩 ${payload.quota.remaining}/${payload.quota.limit}`;
    }
  }
  elements.progressList.querySelector("li.is-active")?.classList.replace("is-active", "is-complete");
  elements.result.hidden = false;
}

const releaseDialog = document.querySelector("[data-release-dialog]");
const releaseDialogForm = releaseDialog?.querySelector("form");
const dismissReleaseDialog = () => {
  if (!releaseDialog) return;
  releaseDialog.classList.add("is-dismissing");
  window.setTimeout(() => releaseDialog.close(), 180);
};
if (releaseDialog) {
  window.requestAnimationFrame(() => {
    window.requestAnimationFrame(() => {
      releaseDialog.showModal();
      releaseDialog.classList.add("is-ready");
    });
  });
  releaseDialogForm?.addEventListener("submit", dismissReleaseDialog);
}

const knowledgeDeviceStorageKey = "jiaotang-kb-device-id";
const createKnowledgeDeviceId = () => {
  if (window.crypto?.randomUUID) return `device:${window.crypto.randomUUID()}`;
  const random = new Uint8Array(18);
  window.crypto?.getRandomValues?.(random);
  const suffix = Array.from(random, (value) => value.toString(16).padStart(2, "0")).join("");
  return `device:${suffix || `${Date.now()}-${Math.random().toString(36).slice(2)}`}`;
};
const knowledgeDeviceId = (() => {
  try {
    const existing = window.localStorage.getItem(knowledgeDeviceStorageKey);
    if (existing) return existing;
    const generated = createKnowledgeDeviceId();
    window.localStorage.setItem(knowledgeDeviceStorageKey, generated);
    return generated;
  } catch {
    return createKnowledgeDeviceId();
  }
})();
const knowledgeDeviceName =
  navigator.userAgentData?.platform || navigator.platform || "浏览器配置设备";
document.querySelectorAll("[data-device-id-display]").forEach((element) => {
  element.textContent = knowledgeDeviceId;
});

const renderAgentInstallStatus = (payload) => {
  if (!payload?.connection) return;
  document.querySelectorAll("[data-agent-install-status]").forEach((statusPanel) => {
    statusPanel.classList.remove("is-waiting", "is-verified", "is-connected", "is-recently_active");
    statusPanel.classList.add(`is-${payload.connection.state || "waiting"}`);
    const label = statusPanel.querySelector("[data-agent-connection-label]");
    const detail = statusPanel.querySelector("[data-agent-connection-detail]");
    if (label) label.textContent = payload.connection.label || "等待 MCP 连接";
    if (detail) detail.textContent = payload.connection.detail || "等待 WorkBuddy 完成验收";
  });
};

const watchAgentInstallStatus = (card) => {
  const statusUrl = card?.dataset.installStatusUrl;
  if (!statusUrl || card.dataset.installPolling === "true") return;
  card.dataset.installPolling = "true";
  let attempts = 0;
  const poll = async () => {
    attempts += 1;
    try {
      const response = await fetch(statusUrl, {headers: {Accept: "application/json"}, cache: "no-store"});
      if (response.ok) {
        const payload = await response.json();
        renderAgentInstallStatus(payload);
        if (payload.configured || payload.result?.result_status === "failed") {
          card.dataset.installPolling = "false";
          return;
        }
      }
    } catch {
      // A temporary polling failure does not invalidate the one-time installation plan.
    }
    if (attempts < 120) window.setTimeout(poll, 5000);
    else card.dataset.installPolling = "false";
  };
  poll();
};

const watchAgentUpgradeStatus = (card) => {
  const statusUrl = card?.dataset.installStatusUrl;
  if (!statusUrl || card.dataset.upgradePolling === "true") return;
  card.dataset.upgradePolling = "true";
  let attempts = 0;
  const poll = async () => {
    attempts += 1;
    try {
      const response = await fetch(statusUrl, {headers: {Accept: "application/json"}, cache: "no-store"});
      if (response.ok) {
        const payload = await response.json();
        renderAgentInstallStatus(payload);
        if (
          payload.result?.operation === "upgrade"
          && ["upgraded", "failed"].includes(payload.result?.result_status)
        ) {
          card.dataset.upgradePolling = "false";
          return;
        }
      }
    } catch {
      // A temporary polling failure does not invalidate the pinned upgrade plan.
    }
    if (attempts < 120) window.setTimeout(poll, 5000);
    else card.dataset.upgradePolling = "false";
  };
  poll();
};

const loadAgentInstallReview = async (card, {copyPrompt = false, platform = ""} = {}) => {
  if (!["macos", "windows"].includes(platform)) throw new Error("请选择 macOS 版或 Windows 版。");
  const form = new URLSearchParams();
  form.set("csrf_token", card?.dataset.csrfToken || "");
  form.set("platform", platform);
  const response = await fetch("/agent-bootstrap-codes", {
    method: "POST",
    headers: {"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
    body: form,
  });
  const payload = await response.json();
  if (!response.ok || payload.phase !== "install_ready" || !payload.prompt) {
    throw new Error(payload.detail || "无法生成完整安装指令");
  }
  if (copyPrompt) await copyToClipboard(payload.prompt);
  return payload;
};

const loadAgentUpgradeReview = async (card, {copyPrompt = false} = {}) => {
  const form = new URLSearchParams();
  form.set("csrf_token", card?.dataset.csrfToken || "");
  const response = await fetch("/agent-upgrade-codes", {
    method: "POST",
    headers: {"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
    body: form,
  });
  const payload = await response.json();
  if (!response.ok || payload.phase !== "review" || !payload.prompt || !payload.review_code || !payload.review_url) {
    throw new Error(payload.detail || "无法生成升级审查");
  }
  card.dataset.agentUpgradeCode = payload.review_code;
  card.dataset.agentUpgradeUrl = payload.review_url;
  if (copyPrompt) await copyToClipboard(payload.prompt);
  card.querySelector("[data-confirm-agent-upgrade]")?.removeAttribute("hidden");
  return payload;
};

const confirmAgentUpgrade = async (card) => {
  const upgradeCode = card?.dataset.agentUpgradeCode || "";
  if (!upgradeCode) throw new Error("请先生成并审查升级计划。");
  const form = new URLSearchParams();
  form.set("csrf_token", card?.dataset.csrfToken || "");
  form.set("upgrade_code", upgradeCode);
  const response = await fetch("/agent-upgrade-codes/confirm", {
    method: "POST",
    headers: {"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
    body: form,
  });
  const payload = await response.json();
  if (!response.ok || payload.phase !== "upgrade_authorized" || !payload.prompt) {
    throw new Error(payload.detail || "无法确认升级");
  }
  return payload;
};

document.addEventListener("click", async (event) => {
  const agentUpgradeButton = event.target.closest("[data-copy-agent-upgrade]");
  if (agentUpgradeButton) {
    const card = agentUpgradeButton.closest("[data-agent-upgrade]");
    const status = card?.querySelector("[data-agent-upgrade-status]");
    const originalMarkup = agentUpgradeButton.innerHTML;
    agentUpgradeButton.disabled = true;
    agentUpgradeButton.classList.add("is-loading");
    status?.classList.remove("is-error");
    agentUpgradeButton.innerHTML = "<span>正在锁定升级版本…</span><small>请稍候</small>";
    try {
      await loadAgentUpgradeReview(card, {copyPrompt: true});
      agentUpgradeButton.classList.remove("is-loading");
      agentUpgradeButton.classList.add("copy-success");
      agentUpgradeButton.innerHTML = "<span>升级审查已复制</span><small>回到本页确认后再升级</small>";
      if (status) status.textContent = "请把审查计划粘贴给当前设备的同一个 Agent；核对目标版本、签名、身份复用和回滚步骤后再确认。";
      window.setTimeout(() => {
        agentUpgradeButton.innerHTML = originalMarkup;
        agentUpgradeButton.classList.remove("copy-success");
        agentUpgradeButton.disabled = false;
      }, 4000);
    } catch (error) {
      agentUpgradeButton.innerHTML = originalMarkup;
      agentUpgradeButton.disabled = false;
      agentUpgradeButton.classList.remove("is-loading");
      if (status) {
        status.classList.add("is-error");
        status.textContent = error.message || "生成升级审查失败。";
      }
    }
    return;
  }
  const confirmUpgradeButton = event.target.closest("[data-confirm-agent-upgrade]");
  if (confirmUpgradeButton) {
    const card = confirmUpgradeButton.closest("[data-agent-upgrade]");
    const status = card?.querySelector("[data-agent-upgrade-status]");
    const installCard = card?.closest("[data-agent-bootstrap]");
    confirmUpgradeButton.disabled = true;
    status?.classList.remove("is-error");
    try {
      const payload = await confirmAgentUpgrade(card);
      await copyToClipboard(payload.prompt);
      confirmUpgradeButton.innerHTML = "<span>升级确认已复制</span><small>发送给同一个 Agent</small>";
      if (status) status.textContent = "请粘贴给审查升级计划的同一个 Agent；门户只接受目标版本和目标哈希完全一致的回传。";
      watchAgentUpgradeStatus(installCard);
    } catch (error) {
      if (status) {
        status.classList.add("is-error");
        status.textContent = error.message || "确认升级失败。";
      }
    } finally {
      confirmUpgradeButton.disabled = false;
    }
    return;
  }
  const agentBootstrapButton = event.target.closest("[data-copy-agent-bootstrap]");
  if (agentBootstrapButton) {
    const card = agentBootstrapButton.closest("[data-agent-bootstrap]");
    const status = card?.querySelector("[data-agent-copy-status]");
    const platform = agentBootstrapButton.dataset.agentPlatform || "";
    const platformLabel = platform === "macos" ? "macOS" : platform === "windows" ? "Windows" : "";
    const installButtons = Array.from(card?.querySelectorAll("[data-copy-agent-bootstrap]") || []);
    const originalMarkup = agentBootstrapButton.innerHTML;
    installButtons.forEach((button) => { button.disabled = true; });
    agentBootstrapButton.classList.add("is-loading");
    status?.classList.remove("is-error");
    agentBootstrapButton.innerHTML = `<span>正在生成 ${platformLabel} 配置…</span><small>请稍候</small>`;
    try {
      const payload = await loadAgentInstallReview(card, {copyPrompt: true, platform});
      agentBootstrapButton.classList.remove("is-loading");
      agentBootstrapButton.innerHTML = `<span>${platformLabel} 指令已复制</span><small>粘贴到 WorkBuddy 执行</small>`;
      agentBootstrapButton.classList.add("copy-success");
      if (status) status.textContent = `请粘贴到 ${platformLabel} 版 WorkBuddy；安装、远程 MCP 合并、一次重载和验收会在同一轮完成。`;
      watchAgentInstallStatus(card);
      window.setTimeout(() => {
        agentBootstrapButton.innerHTML = originalMarkup;
        agentBootstrapButton.classList.remove("copy-success");
        installButtons.forEach((button) => { button.disabled = false; });
      }, 4000);
    } catch (error) {
      agentBootstrapButton.innerHTML = originalMarkup;
      installButtons.forEach((button) => { button.disabled = false; });
      agentBootstrapButton.classList.remove("is-loading");
      if (status) {
        status.classList.add("is-error");
        status.textContent = error.message || "生成失败，请稍后重试。";
      }
    }
    return;
  }
  const secretToggle = event.target.closest("[data-toggle-secret]");
  if (secretToggle) {
    const group = secretToggle.dataset.toggleSecret;
    const displays = document.querySelectorAll(`[data-secret-display="${group}"]`);
    const shouldReveal = secretToggle.getAttribute("aria-pressed") !== "true";
    document.querySelectorAll(`[data-toggle-secret="${group}"]`).forEach((toggle) => {
      toggle.setAttribute("aria-pressed", String(shouldReveal));
      toggle.textContent = shouldReveal ? "隐藏" : "显示";
    });
    displays.forEach((display) => {
      display.textContent = shouldReveal ? display.dataset.secretValue : "••••••••••••••••••••";
      display.classList.toggle("is-revealed", shouldReveal);
    });
    return;
  }
  const questionButton = event.target.closest("[data-question]");
  if (questionButton) {
    const question = document.querySelector('#assistant-form textarea[name="question"]');
    const cockpitPage = document.querySelector(".portal-page.page-cockpit");
    const releaseForm = questionButton.closest(".release-modal-card");
    if (question && cockpitPage) {
      question.value = questionButton.dataset.question;
      document.querySelector("#assistant-form")?.requestSubmit();
    } else if (releaseForm) {
      sessionStorage.setItem("jiaotang-cockpit-question", questionButton.dataset.question);
      dismissReleaseDialog();
      await fetch(releaseForm.action, {method: "POST", body: new FormData(releaseForm)});
      sessionStorage.setItem("jiaotang-page-direction", "next");
      window.location.href = "/cockpit";
    } else {
      sessionStorage.setItem("jiaotang-cockpit-question", questionButton.dataset.question);
      window.location.href = "/cockpit";
    }
    return;
  }
  const button = event.target.closest(
    "[data-copy-target], [data-copy-config], [data-copy-value], [data-copy-device-id]"
  );
  if (!button) return;

  let value = "";
  if (button.dataset.copyDeviceId !== undefined) {
    value = knowledgeDeviceId;
  } else if (button.dataset.copyValue !== undefined) {
    value = button.dataset.copyValue;
  } else if (button.dataset.copyConfig !== undefined) {
    value = `JIAOTANG_KB_BASE_URL=${window.location.origin}\nJIAOTANG_KB_API_BASE_URL=${window.location.origin}/v1\nJIAOTANG_KB_ENDPOINT=${window.location.origin}\nJIAOTANG_KB_MCP_URL=${window.location.origin}/mcp/\nJIAOTANG_KB_DEVICE_ID=${knowledgeDeviceId}\nJIAOTANG_KB_DEVICE_NAME=${knowledgeDeviceName}\nJIAOTANG_KB_TOKEN=${button.dataset.token}`;
  } else {
    const target = document.querySelector(button.dataset.copyTarget);
    value = target?.textContent?.trim() || "";
  }
  if (!value) return;

  try {
    await copyToClipboard(value);
    const original = button.textContent;
    button.textContent = "已复制";
    button.classList.add("copy-success");
    window.setTimeout(() => {
      button.textContent = original;
      button.classList.remove("copy-success");
    }, 1800);
  } catch {
    window.prompt("请复制以下内容", value);
  }
});

const pendingCockpitQuestion = sessionStorage.getItem("jiaotang-cockpit-question");
const cockpitQuestion = document.querySelector('.page-cockpit #assistant-form textarea[name="question"]');
if (pendingCockpitQuestion && cockpitQuestion) {
  cockpitQuestion.value = pendingCockpitQuestion;
  sessionStorage.removeItem("jiaotang-cockpit-question");
  cockpitQuestion.focus();
}

document.querySelector("#assistant-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const submit = form.querySelector('button[type="submit"]');
  const result = document.querySelector("#assistant-result");
  const answer = document.querySelector("#assistant-answer");
  const mode = document.querySelector("#assistant-result-mode");
  const skills = document.querySelector("#assistant-skills");
  const sources = document.querySelector("#assistant-sources");
  const quota = document.querySelector("#assistant-quota");
  const progress = document.querySelector("#assistant-progress");
  const progressList = document.querySelector("#assistant-progress-list");
  const elements = {answer, mode, skills, sources, quota, progressList, result};
  submit.disabled = true;
  submit.textContent = "推导中…";
  result.hidden = true;
  progress.hidden = false;
  progressList.replaceChildren();
  try {
    const body = new FormData(form);
    if (!document.querySelector("#user-api-enabled")?.checked) {
      body.delete("user_api_base");
      body.delete("user_api_key");
      body.delete("user_api_model");
    }
    const response = await fetch("/assistant/answer", {method: "POST", body});
    if (!response.ok) {
      const payload = await response.json();
      throw new Error(payload.detail || "答疑失败");
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const {value, done} = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), {stream: !done});
      const blocks = buffer.split("\n\n");
      buffer = blocks.pop() || "";
      for (const block of blocks) {
        if (!block.trim()) continue;
        let eventName = "message";
        const dataLines = [];
        block.split("\n").forEach((line) => {
          if (line.startsWith("event:")) eventName = line.slice(6).trim();
          if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
        });
        if (!dataLines.length) continue;
        const payload = JSON.parse(dataLines.join("\n"));
        if (eventName === "progress") appendAssistantProgress(progressList, payload);
        if (eventName === "result") renderAssistantResult(payload, elements);
        if (eventName === "error") throw new Error(payload.detail || "答疑失败");
      }
      if (done) break;
    }
  } catch (error) {
    answer.textContent = error.message;
    mode.textContent = "需要检查";
    skills.replaceChildren();
    sources.replaceChildren();
    result.hidden = false;
  } finally {
    submit.disabled = false;
    submit.textContent = "开始答疑";
  }
});

const userApiForm = document.querySelector("#assistant-form");
if (userApiForm) {
  const apiBase = userApiForm.querySelector('[name="user_api_base"]');
  const apiKey = userApiForm.querySelector('[name="user_api_key"]');
  const apiModel = userApiForm.querySelector('[name="user_api_model"]');
  const enabled = document.querySelector("#user-api-enabled");
  try {
    const saved = JSON.parse(sessionStorage.getItem(USER_API_SESSION_STORAGE_KEY) || "null");
    if (saved) {
      apiBase.value = saved.apiBase || "";
      apiKey.value = saved.apiKey || "";
      apiModel.value = saved.apiModel || "";
      enabled.checked = Boolean(saved.enabled);
    }
  } catch {
    sessionStorage.removeItem(USER_API_SESSION_STORAGE_KEY);
  }
  document.querySelector("#save-user-api")?.addEventListener("click", () => {
    sessionStorage.setItem(USER_API_SESSION_STORAGE_KEY, JSON.stringify({
      apiBase: apiBase.value.trim(),
      apiKey: apiKey.value.trim(),
      apiModel: apiModel.value.trim(),
      enabled: enabled.checked,
    }));
    const button = document.querySelector("#save-user-api");
    button.textContent = "已保存";
    window.setTimeout(() => { button.textContent = "保存到本标签页会话"; }, 1500);
  });
  document.querySelector("#clear-user-api")?.addEventListener("click", () => {
    sessionStorage.removeItem(USER_API_SESSION_STORAGE_KEY);
    apiBase.value = "";
    apiKey.value = "";
    apiModel.value = "";
    enabled.checked = false;
  });
}

const ROUTE_SECTIONS = {
  "/portal": "overview",
  "/cockpit": "cockpit",
  "/algorithms": "algorithms",
  "/access": "api-access",
  "/skills": "skills",
  "/feedback": "feedback",
  "/admin/operations": "health-admin",
  "/admin/knowledge-update": "knowledge-admin",
  "/admin/releases": "skill-admin",
  "/admin/members": "members",
};

const singlePage = document.querySelector(".single-page");
const sectionLinks = [...document.querySelectorAll("[data-section-link]")];
const portalMobileQuery = window.matchMedia("(max-width: 760px)");
const activateSectionLink = (sectionId) => {
  sectionLinks.forEach((link) => {
    link.classList.toggle("active", link.dataset.sectionLink === sectionId);
  });
};
const scrollToPortalSection = (section, behavior) => {
  const instant = behavior === "instant";
  if (instant) document.documentElement.classList.add("is-instant-scroll");
  if (portalMobileQuery.matches) {
    const sidebar = document.querySelector(".sidebar");
    const stickyOffset = (sidebar?.getBoundingClientRect().height || 0) + 12;
    const targetTop = window.scrollY + section.getBoundingClientRect().top - stickyOffset;
    window.scrollTo({top: Math.max(0, targetTop), behavior: instant ? "auto" : behavior});
    window.setTimeout(() => {
      const currentSidebarBottom = sidebar?.getBoundingClientRect().bottom || 0;
      const currentSectionTop = section.getBoundingClientRect().top;
      const desiredTop = currentSidebarBottom + 12;
      if (Math.abs(currentSectionTop - desiredTop) > 2) {
        window.scrollBy({top: currentSectionTop - desiredTop, behavior: "auto"});
      }
    }, instant ? 160 : 520);
  } else {
    section.scrollIntoView({behavior: instant ? "auto" : behavior, block: "start"});
  }
  if (instant) {
    window.requestAnimationFrame(() => {
      document.documentElement.classList.remove("is-instant-scroll");
    });
  }
};
const initialRouteId = window.location.hash.slice(1) || ROUTE_SECTIONS[window.location.pathname];
const initialSectionId = initialRouteId?.startsWith("skills-") ? "skills" : initialRouteId;
const initialSection = initialSectionId ? document.getElementById(initialSectionId) : null;
let initialRouteAnchorLocked = Boolean(singlePage && initialSection);
if (singlePage && initialSection) {
  window.requestAnimationFrame(() => {
    const isDefaultOverview = window.location.pathname === "/portal" && !window.location.hash;
    if (!isDefaultOverview) {
      scrollToPortalSection(initialSection, "instant");
    }
    activateSectionLink(initialSectionId);
    if (!window.location.hash) {
      history.replaceState(null, "", `/portal#${initialSectionId}`);
    }
    window.setTimeout(() => {
      activateSectionLink(initialSectionId);
      initialRouteAnchorLocked = false;
      updateActiveSectionLink();
    }, 120);
  });
}

document.querySelectorAll("a.page-transition-link").forEach((link) => {
  link.addEventListener("click", (event) => {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const targetUrl = new URL(link.href, window.location.origin);
    const sectionId = targetUrl.hash.slice(1) || ROUTE_SECTIONS[targetUrl.pathname];
    const section = sectionId ? document.getElementById(sectionId) : null;
    if (singlePage && section) {
      event.preventDefault();
      scrollToPortalSection(section, "smooth");
      activateSectionLink(sectionId);
      history.replaceState(null, "", `/portal#${sectionId}`);
      return;
    }
    event.preventDefault();
    sessionStorage.setItem("jiaotang-page-direction", "next");
    document.body.classList.add("is-page-leaving");
    window.setTimeout(() => {
      window.location.href = link.href;
    }, 360);
  });
});

document.querySelector(".single-page")?.addEventListener("click", (event) => {
  const link = event.target.closest("a[href]");
  if (!link || link.classList.contains("page-transition-link")) return;
  if (link.hasAttribute("data-force-navigation")) return;
  const targetUrl = new URL(link.href, window.location.origin);
  if (targetUrl.origin !== window.location.origin) return;
  const sectionId = targetUrl.hash.slice(1) || ROUTE_SECTIONS[targetUrl.pathname];
  const section = sectionId ? document.getElementById(sectionId) : null;
  if (!section) return;
  event.preventDefault();
  scrollToPortalSection(section, "smooth");
  activateSectionLink(sectionId);
  history.replaceState(null, "", `/portal#${sectionId}`);
});

const observedSections = sectionLinks
  .map((link) => document.getElementById(link.dataset.sectionLink))
  .filter(Boolean);
let sectionActivationFrame = 0;
function updateActiveSectionLink() {
  sectionActivationFrame = 0;
  if (initialRouteAnchorLocked || !observedSections.length) return;
  const sidebarHeight = portalMobileQuery.matches
    ? document.querySelector(".sidebar")?.getBoundingClientRect().height || 0
    : 0;
  const viewportAnchor = portalMobileQuery.matches
    ? Math.min(window.innerHeight - 1, sidebarHeight + 88)
    : Math.min(window.innerHeight * .36, 340);
  const containing = observedSections.find((section) => {
    const rect = section.getBoundingClientRect();
    return rect.top <= viewportAnchor && rect.bottom > viewportAnchor;
  });
  const activeSection = containing || observedSections
    .map((section) => ({section, distance: Math.abs(section.getBoundingClientRect().top - viewportAnchor)}))
    .sort((left, right) => left.distance - right.distance)[0]?.section;
  if (activeSection) activateSectionLink(activeSection.id);
}
const scheduleSectionActivation = () => {
  if (sectionActivationFrame) return;
  sectionActivationFrame = window.requestAnimationFrame(updateActiveSectionLink);
};
if (sectionLinks.length && observedSections.length) {
  window.addEventListener("scroll", scheduleSectionActivation, {passive: true});
  window.addEventListener("resize", scheduleSectionActivation, {passive: true});
  scheduleSectionActivation();
}

// 滚轮/触摸/方向键自动翻页已移除：滚动到边界即跳页容易误触。
// 翻页改为页面底部显式的「上一页 / 下一页」链接（portal.html 的 .page-continuation）。

const skillCenter = document.querySelector("[data-skill-center]");
if (skillCenter) {
  const search = skillCenter.querySelector("[data-skill-search]");
  const rows = [...skillCenter.querySelectorAll("[data-skill-row]")];
  const groupButtons = [...skillCenter.querySelectorAll("[data-skill-group]")];
  const groupRail = skillCenter.querySelector("[data-skill-group-rail]");
  const statusButtons = [...skillCenter.querySelectorAll("[data-skill-status]")];
  const sectionTabs = [...skillCenter.querySelectorAll("[data-skill-section-tab]")];
  const sectionPanes = [...skillCenter.querySelectorAll("[data-skill-section-pane]")];
  const resultCount = skillCenter.querySelector("[data-skill-result-count]");
  const currentGroup = skillCenter.querySelector("[data-skill-current-group]");
  const emptyState = skillCenter.querySelector("[data-skill-empty]");
  const catalogShell = skillCenter.querySelector(".skill-catalog-shell");
  const backToList = skillCenter.querySelector("[data-skill-back-to-list]");
  const dialog = skillCenter.querySelector("[data-skill-dialog]");
  const loading = dialog?.querySelector("[data-skill-detail-loading]");
  const content = dialog?.querySelector("[data-skill-detail-content]");
  let activeGroup = "all";
  let activeStatus = "all";

  const bindTabKeyboard = (tabs, activate) => {
    tabs.forEach((tab, index) => {
      tab.addEventListener("keydown", (event) => {
        let nextIndex = null;
        if (event.key === "ArrowRight") nextIndex = (index + 1) % tabs.length;
        if (event.key === "ArrowLeft") nextIndex = (index - 1 + tabs.length) % tabs.length;
        if (event.key === "Home") nextIndex = 0;
        if (event.key === "End") nextIndex = tabs.length - 1;
        if (nextIndex === null) return;
        event.preventDefault();
        tabs[nextIndex].focus();
        activate(tabs[nextIndex]);
      });
    });
  };

  const showSkillSection = (name, {updateHash = true} = {}) => {
    sectionTabs.forEach((tab) => {
      const active = tab.dataset.skillSectionTab === name;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
    });
    sectionPanes.forEach((pane) => {
      const active = pane.dataset.skillSectionPane === name;
      pane.classList.toggle("is-active", active);
      pane.hidden = !active;
    });
    if (updateHash) history.replaceState(null, "", `/portal#skills-${name}`);
    if (name === "install") {
      const installCard = skillCenter.querySelector("[data-install-status-url]");
      if (installCard) watchAgentInstallStatus(installCard);
    }
  };

  sectionTabs.forEach((tab) => tab.addEventListener("click", () => {
    showSkillSection(tab.dataset.skillSectionTab);
  }));
  bindTabKeyboard(sectionTabs, (tab) => showSkillSection(tab.dataset.skillSectionTab));
  skillCenter.querySelectorAll("[data-skill-tab-target]").forEach((button) => {
    button.addEventListener("click", () => {
      showSkillSection(button.dataset.skillTabTarget);
      skillCenter.querySelector(".skill-section-tabs")?.scrollIntoView({behavior: "smooth", block: "start"});
    });
  });
  const requestedSkillPane = window.location.hash.match(/^#skills-(catalog|downloads|install)$/)?.[1];
  if (requestedSkillPane) showSkillSection(requestedSkillPane, {updateHash: false});

  const applySkillFilters = () => {
    const query = search.value.trim().toLocaleLowerCase("zh-CN");
    let visible = 0;
    rows.forEach((row) => {
      const matchesQuery = !query || row.dataset.skillSearchValue.toLocaleLowerCase("zh-CN").includes(query);
      const matchesGroup = activeGroup === "all" || row.dataset.skillGroupValue === activeGroup;
      const matchesStatus = activeStatus === "all" || row.dataset.skillStatusValue === activeStatus;
      row.hidden = !(matchesQuery && matchesGroup && matchesStatus);
      if (!row.hidden) visible += 1;
    });
    resultCount.textContent = `${visible} / ${rows.length}`;
    const activeGroupButton = groupButtons.find((button) => button.dataset.skillGroup === activeGroup);
    if (currentGroup && activeGroupButton) {
      currentGroup.textContent = activeGroupButton.dataset.skillGroupLabel || activeGroupButton.textContent.trim();
    }
    emptyState.hidden = visible !== 0;
  };

  const selectFilter = (buttons, selected) => {
    buttons.forEach((button) => {
      const active = button === selected;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    });
  };

  groupButtons.forEach((button) => button.addEventListener("click", () => {
    activeGroup = button.dataset.skillGroup;
    selectFilter(groupButtons, button);
    applySkillFilters();
    if (groupRail) {
      const railRect = groupRail.getBoundingClientRect();
      const buttonRect = button.getBoundingClientRect();
      const centeredTarget = groupRail.scrollLeft
        + buttonRect.left
        - railRect.left
        - (groupRail.clientWidth - buttonRect.width) / 2;
      const maximumScroll = Math.max(0, groupRail.scrollWidth - groupRail.clientWidth);
      groupRail.scrollTo({
        left: Math.max(0, Math.min(centeredTarget, maximumScroll)),
        behavior: "auto",
      });
    }
  }));
  statusButtons.forEach((button) => button.addEventListener("click", () => {
    activeStatus = button.dataset.skillStatus;
    selectFilter(statusButtons, button);
    applySkillFilters();
  }));
  search?.addEventListener("input", applySkillFilters);
  backToList?.addEventListener("click", () => {
    const tabsHeight = skillCenter.querySelector(".skill-section-tabs")?.getBoundingClientRect().height || 0;
    const tabsTop = Number.parseFloat(getComputedStyle(skillCenter).getPropertyValue("--skill-tabs-top")) || 0;
    const targetTop = window.scrollY + catalogShell.getBoundingClientRect().top - tabsTop - tabsHeight - 8;
    window.scrollTo({top: Math.max(0, targetTop), behavior: "smooth"});
  });
  window.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      search?.focus();
    }
  });
  skillCenter.querySelector("[data-skill-rescan]")?.addEventListener("click", () => window.location.reload());

  const showSkillPane = (name) => {
    const tabs = [...dialog.querySelectorAll("[data-skill-detail-tab]")];
    const panes = [...dialog.querySelectorAll("[data-skill-detail-pane]")];
    tabs.forEach((tab) => {
      const active = tab.dataset.skillDetailTab === name;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
    });
    panes.forEach((pane) => {
      const active = pane.dataset.skillDetailPane === name;
      pane.classList.toggle("is-active", active);
      pane.hidden = !active;
    });
  };

  const renderSkillDetail = (payload) => {
    dialog.querySelector("[data-skill-detail-title]").textContent = payload.title;
    dialog.querySelector("[data-skill-detail-name]").textContent = payload.name;
    dialog.querySelector("[data-skill-detail-description]").textContent = payload.description;
    const status = dialog.querySelector("[data-skill-detail-status]");
    status.textContent = `${payload.group_label} · ${payload.status_label}`;
    dialog.querySelector("[data-skill-detail-files]").textContent = `${payload.file_count} 文件 / ${payload.directory_count} 目录`;
    dialog.querySelector("[data-skill-detail-size]").textContent = payload.size_display;
    dialog.querySelector("[data-skill-detail-fingerprint]").textContent = payload.fingerprint;
    dialog.querySelector("[data-skill-detail-version]").textContent = payload.release_tag;
    dialog.querySelector('[data-skill-detail-pane="preview"]').innerHTML = payload.skill_html;
    dialog.querySelector('[data-skill-detail-pane="source"] code').textContent = payload.skill_source;

    const filePane = dialog.querySelector('[data-skill-detail-pane="files"]');
    filePane.replaceChildren();
    payload.files.forEach((file) => {
      const row = document.createElement("div");
      const path = document.createElement("code");
      const meta = document.createElement("small");
      path.textContent = file.path;
      meta.textContent = `${file.type} · ${file.size}`;
      row.append(path, meta);
      filePane.appendChild(row);
    });

    const relationPane = dialog.querySelector('[data-skill-detail-pane="relations"]');
    relationPane.replaceChildren();
    const relations = [...payload.relations];
    payload.required_skills.forEach((skill) => {
      if (!relations.some((item) => item.skill === skill && item.type === "requires")) {
        relations.unshift({direction: "调用", skill, type_label: "必需依赖", reason: payload.dependency_reason});
      }
    });
    if (!relations.length) {
      const empty = document.createElement("div");
      empty.className = "skill-empty-state";
      empty.textContent = "此技能可独立使用，当前清单未声明固定协作关系。";
      relationPane.appendChild(empty);
    } else {
      relations.forEach((relation) => {
        const card = document.createElement("article");
        const title = document.createElement("strong");
        const type = document.createElement("span");
        const reason = document.createElement("p");
        title.textContent = `${relation.direction} · ${relation.skill}`;
        type.textContent = relation.type_label;
        reason.textContent = relation.reason || "正式清单已声明此协作关系。";
        card.append(title, type, reason);
        relationPane.appendChild(card);
      });
    }
    showSkillPane("preview");
  };

  const detailTabs = [...(dialog?.querySelectorAll("[data-skill-detail-tab]") || [])];
  detailTabs.forEach((tab) => {
    tab.addEventListener("click", () => showSkillPane(tab.dataset.skillDetailTab));
  });
  bindTabKeyboard(detailTabs, (tab) => showSkillPane(tab.dataset.skillDetailTab));
  dialog?.querySelectorAll("[data-skill-dialog-close]").forEach((button) => {
    button.addEventListener("click", () => dialog.close());
  });
  dialog?.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });

  rows.forEach((row) => row.addEventListener("click", async () => {
    if (!dialog) return;
    loading.hidden = false;
    loading.textContent = "正在读取正式技能清单…";
    content.hidden = true;
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
    try {
      const response = await fetch(`/skills/catalog/${encodeURIComponent(row.dataset.skillOpen)}`, {headers: {Accept: "application/json"}});
      if (!response.ok) throw new Error("技能详情暂时不可用");
      renderSkillDetail(await response.json());
      loading.hidden = true;
      content.hidden = false;
    } catch (error) {
      loading.textContent = error.message || "技能详情暂时不可用";
    }
  }));
}
