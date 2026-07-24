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
  temporary.style.position = "fixed";
  temporary.style.opacity = "0";
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

document.addEventListener("click", async (event) => {
  const agentBootstrapButton = event.target.closest("[data-copy-agent-bootstrap]");
  if (agentBootstrapButton) {
    const card = agentBootstrapButton.closest("[data-agent-bootstrap]");
    const status = card?.querySelector("[data-agent-copy-status]");
    const originalMarkup = agentBootstrapButton.innerHTML;
    agentBootstrapButton.disabled = true;
    agentBootstrapButton.classList.add("is-loading");
    status?.classList.remove("is-error");
    agentBootstrapButton.innerHTML = "<span>正在生成安全配置…</span><small>请稍候</small>";
    try {
      const form = new URLSearchParams();
      form.set("csrf_token", card?.dataset.csrfToken || "");
      const response = await fetch("/agent-bootstrap-codes", {
        method: "POST",
        headers: {"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
        body: form,
      });
      const payload = await response.json();
      if (!response.ok || !payload.prompt) {
        throw new Error(payload.detail || "无法生成一键配置");
      }
      await copyToClipboard(payload.prompt);
      agentBootstrapButton.classList.remove("is-loading");
      agentBootstrapButton.innerHTML = "<span>已复制，发送给 Agent</span><small>60分钟内有效</small>";
      agentBootstrapButton.classList.add("copy-success");
      if (status) status.textContent = "现在只需粘贴到当前本地 Agent 的对话框。";
      window.setTimeout(() => {
        agentBootstrapButton.innerHTML = originalMarkup;
        agentBootstrapButton.classList.remove("copy-success");
        agentBootstrapButton.disabled = false;
      }, 4000);
    } catch (error) {
      agentBootstrapButton.innerHTML = originalMarkup;
      agentBootstrapButton.disabled = false;
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

const userApiStorageKey = "jiaotang-user-model-api";
const userApiForm = document.querySelector("#assistant-form");
if (userApiForm) {
  const apiBase = userApiForm.querySelector('[name="user_api_base"]');
  const apiKey = userApiForm.querySelector('[name="user_api_key"]');
  const apiModel = userApiForm.querySelector('[name="user_api_model"]');
  const enabled = document.querySelector("#user-api-enabled");
  try {
    const saved = JSON.parse(localStorage.getItem(userApiStorageKey) || "null");
    if (saved) {
      apiBase.value = saved.apiBase || "";
      apiKey.value = saved.apiKey || "";
      apiModel.value = saved.apiModel || "";
      enabled.checked = Boolean(saved.enabled);
    }
  } catch {
    localStorage.removeItem(userApiStorageKey);
  }
  document.querySelector("#save-user-api")?.addEventListener("click", () => {
    localStorage.setItem(userApiStorageKey, JSON.stringify({
      apiBase: apiBase.value.trim(),
      apiKey: apiKey.value.trim(),
      apiModel: apiModel.value.trim(),
      enabled: enabled.checked,
    }));
    const button = document.querySelector("#save-user-api");
    button.textContent = "已保存";
    window.setTimeout(() => { button.textContent = "保存到当前浏览器"; }, 1500);
  });
  document.querySelector("#clear-user-api")?.addEventListener("click", () => {
    localStorage.removeItem(userApiStorageKey);
    apiBase.value = "";
    apiKey.value = "";
    apiModel.value = "";
    enabled.checked = false;
  });
}

const ROUTE_SECTIONS = {
  "/portal": "overview",
  "/cockpit": "cockpit",
  "/access": "api-access",
  "/skills": "skills",
  "/feedback": "feedback",
  "/admin/operations": "health-admin",
  "/admin/knowledge-update": "knowledge-admin",
  "/admin/releases": "skill-admin",
  "/admin/members": "members",
};

document.querySelectorAll("a.page-transition-link").forEach((link) => {
  link.addEventListener("click", (event) => {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const singlePage = document.querySelector(".single-page");
    const targetUrl = new URL(link.href, window.location.origin);
    const sectionId = targetUrl.hash.slice(1) || ROUTE_SECTIONS[targetUrl.pathname];
    const section = sectionId ? document.getElementById(sectionId) : null;
    if (singlePage && section) {
      event.preventDefault();
      section.scrollIntoView({behavior: "smooth", block: "start"});
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
  const targetUrl = new URL(link.href, window.location.origin);
  if (targetUrl.origin !== window.location.origin) return;
  const sectionId = targetUrl.hash.slice(1) || ROUTE_SECTIONS[targetUrl.pathname];
  const section = sectionId ? document.getElementById(sectionId) : null;
  if (!section) return;
  event.preventDefault();
  section.scrollIntoView({behavior: "smooth", block: "start"});
  history.replaceState(null, "", `/portal#${sectionId}`);
});

const sectionLinks = [...document.querySelectorAll("[data-section-link]")];
const observedSections = sectionLinks
  .map((link) => document.getElementById(link.dataset.sectionLink))
  .filter(Boolean);
if (sectionLinks.length && observedSections.length && "IntersectionObserver" in window) {
  const sectionObserver = new IntersectionObserver((entries) => {
    const visible = entries
      .filter((entry) => entry.isIntersecting)
      .sort((left, right) => right.intersectionRatio - left.intersectionRatio)[0];
    if (!visible) return;
    sectionLinks.forEach((link) => {
      link.classList.toggle("active", link.dataset.sectionLink === visible.target.id);
    });
  }, {rootMargin: "-28% 0px -58%", threshold: [0.05, 0.2, 0.45]});
  observedSections.forEach((section) => sectionObserver.observe(section));
}

const waterfallBoundary = document.querySelector(".portal-page:not(.single-page) .page-continuation[data-auto-next]");
if (waterfallBoundary) {
  let wheelProgress = 0;
  let touchStartY = null;
  let navigating = false;
  let resetTimer = null;
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const pageAtTop = () => window.scrollY <= 2;
  const pageAtBottom = () => window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 3;
  const nestedScrollerConsumes = (target, delta) => {
    const scroller = target instanceof Element ? target.closest(".table-wrap,.release-modal-card,.account-menu-panel,.manual-content") : null;
    if (!scroller || scroller.scrollHeight <= scroller.clientHeight + 2) return false;
    return delta > 0
      ? scroller.scrollTop + scroller.clientHeight < scroller.scrollHeight - 2
      : scroller.scrollTop > 2;
  };
  const destinationFor = (direction) => direction === "next"
    ? waterfallBoundary.dataset.autoNext
    : waterfallBoundary.dataset.autoPrevious;
  const resetWaterfall = () => {
    wheelProgress = 0;
    waterfallBoundary.classList.remove("is-armed");
  };
  const navigateWaterfall = (direction) => {
    const destination = destinationFor(direction);
    if (!destination || navigating) return;
    navigating = true;
    sessionStorage.setItem("jiaotang-page-direction", direction);
    document.body.classList.add("is-page-leaving");
    document.body.classList.toggle("is-page-leaving-previous", direction === "previous");
    window.setTimeout(() => { window.location.href = destination; }, reducedMotion ? 10 : 430);
  };
  const accumulateWaterfall = (direction, amount) => {
    if (!destinationFor(direction)) return;
    wheelProgress += Math.min(Math.abs(amount), 70);
    if (wheelProgress >= 38) waterfallBoundary.classList.add("is-armed");
    window.clearTimeout(resetTimer);
    resetTimer = window.setTimeout(resetWaterfall, 420);
    if (wheelProgress >= 130) navigateWaterfall(direction);
  };

  window.addEventListener("wheel", (event) => {
    if (navigating || event.ctrlKey || nestedScrollerConsumes(event.target, event.deltaY)) return;
    const direction = event.deltaY > 0 ? "next" : "previous";
    const atBoundary = direction === "next" ? pageAtBottom() : pageAtTop();
    if (!atBoundary || !destinationFor(direction)) {
      resetWaterfall();
      return;
    }
    event.preventDefault();
    accumulateWaterfall(direction, event.deltaY);
  }, {passive: false});

  window.addEventListener("touchstart", (event) => {
    touchStartY = event.touches[0]?.clientY ?? null;
  }, {passive: true});
  window.addEventListener("touchend", (event) => {
    if (touchStartY === null || navigating) return;
    const endY = event.changedTouches[0]?.clientY ?? touchStartY;
    const delta = touchStartY - endY;
    touchStartY = null;
    if (Math.abs(delta) < 80) return;
    const direction = delta > 0 ? "next" : "previous";
    const atBoundary = direction === "next" ? pageAtBottom() : pageAtTop();
    if (atBoundary) navigateWaterfall(direction);
  }, {passive: true});

  window.addEventListener("keydown", (event) => {
    const targetIsInteractive = event.target instanceof Element
      && event.target.closest("input,textarea,select,button,[contenteditable='true']");
    if (navigating || targetIsInteractive) return;
    const nextKey = event.key === "PageDown" || event.key === "ArrowDown";
    const previousKey = event.key === "PageUp" || event.key === "ArrowUp";
    if (nextKey && pageAtBottom() && destinationFor("next")) {
      event.preventDefault();
      navigateWaterfall("next");
    } else if (previousKey && pageAtTop() && destinationFor("previous")) {
      event.preventDefault();
      navigateWaterfall("previous");
    }
  });
}
