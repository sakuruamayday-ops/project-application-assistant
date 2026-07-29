const bridge = window.jiaotang;

const demoOverview = {
  os: { platform: navigator.platform.toLowerCase().includes("win") ? "win32" : "darwin", arch: "arm64", version: "preview" },
  product: { name: "企业全生命周期助手", releaseTag: "V1.3.1.3", skillCount: 49, managerVersion: "0.2.0" },
  settings: { portalUrl: "https://zshjiaotang.cn" },
  appTrust: {
    signed: false,
    trustedByOs: false,
    summary: "界面预览未执行操作系统签名检查",
    details: "请在 Electron 桌面进程中运行。",
  },
  platforms: [
    { id: "workbuddy", name: "WorkBuddy", vendor: "腾讯", support: "adapter", detected: true, channel: "workbuddy", installMode: "workbuddy-marketplace", targetRoot: null, canInstallAutomatically: false, detectedPaths: ["/Applications/WorkBuddy.app"], notes: "下载本地插件市场 ZIP，在 WorkBuddy 内使用 /plugin 安装。" },
    { id: "trae", name: "TRAE", vendor: "字节跳动", support: "full", detected: true, channel: "generic", installMode: "managed-directory", targetRoot: "~/.trae-cn/skills", canInstallAutomatically: true, notes: "中国版使用用户级 .trae-cn/skills。" },
    { id: "kimi-code", name: "Kimi Code", vendor: "月之暗面", support: "full", detected: false, channel: "generic", installMode: "shared-agents-directory", targetRoot: "~/.agents/skills", canInstallAutomatically: true, notes: "与 TRAE 共用托管目录。" },
    { id: "lingma", name: "通义灵码", vendor: "阿里云", support: "guided", detected: false, channel: "generic", installMode: "guided-import", targetRoot: null, canInstallAutomatically: false, notes: "官方尚未公开稳定的用户级 Skills 导入接口。" },
    { id: "qoder", name: "Qoder", vendor: "阿里云", support: "adapter", detected: false, channel: "generic", installMode: "plugin-or-project", targetRoot: null, canInstallAutomatically: false, notes: "首版生成已验证导入包。" },
    { id: "cherry-studio", name: "Cherry Studio", vendor: "CherryHQ", support: "guided", detected: true, channel: "generic", installMode: "guided-import", targetRoot: null, canInstallAutomatically: false, notes: "通过官方界面导入 ZIP。" },
  ],
  targets: [
    { targetRoot: "~/.trae-cn/skills", platformIds: ["trae"] },
  ],
  compatibility: {
    skillCount: 49,
    platforms: [
      { platformId: "workbuddy", platformName: "WorkBuddy", support: "full", label: "完整同步", compatible: 49, review: 0, total: 49 },
      { platformId: "trae", platformName: "TRAE", support: "full", label: "完整同步", compatible: 49, review: 0, total: 49 },
      { platformId: "kimi-code", platformName: "Kimi Code", support: "full", label: "完整同步", compatible: 49, review: 0, total: 49 },
      { platformId: "lingma", platformName: "通义灵码", support: "guided", label: "引导导入", compatible: 49, review: 49, total: 49 },
      { platformId: "qoder", platformName: "Qoder", support: "adapter", label: "适配导入", compatible: 49, review: 49, total: 49 },
      { platformId: "cherry-studio", platformName: "Cherry Studio", support: "guided", label: "引导导入", compatible: 49, review: 49, total: 49 },
    ],
  },
  registry: { targets: {}, backups: [] },
  adapters: {
    sequence: 2026072801,
    revision: "2026.07.28.1",
    publishedAt: "2026-07-28T10:30:00+08:00",
    source: "built-in",
  },
  scan: {
    scannedAt: new Date().toISOString(),
    durationMs: 86,
    searchedPlatformCount: 6,
    detectedPlatformCount: 3,
  },
  audit: {
    status: "ready",
    warning: null,
  },
};

const state = {
  overview: null,
  channels: null,
  artifacts: new Map(),
  action: null,
  currentView: "overview",
  platformFilter: "all",
};

const viewMeta = {
  overview: ["CONTROL ROOM / 总览", "技能交付控制台"],
  platforms: ["ADAPTERS / 平台", "平台与托管目录"],
  updates: ["RELEASE CHANNELS / 更新", "签名发布通道"],
  compatibility: ["CAPABILITY LEDGER / 兼容性", "49项技能兼容账本"],
  security: ["TRUST CHAIN / 安全", "应用与技能包安全中心"],
};

const supportLabels = {
  full: "完整同步",
  adapter: "适配导入",
  guided: "引导导入",
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function shortHash(value) {
  if (!value) return "—";
  return `${value.slice(0, 10)}…${value.slice(-6)}`;
}

function formatBytes(value) {
  if (!Number.isFinite(Number(value))) return "—";
  const bytes = Number(value);
  if (bytes > 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  if (bytes > 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${bytes} B`;
}

function monogram(name) {
  const known = {
    WorkBuddy: "W",
    TRAE: "T",
    "Kimi Code": "K",
    通义灵码: "灵",
    Qoder: "Q",
    "Cherry Studio": "C",
  };
  return known[name] || name.slice(0, 1);
}

function toast(title, detail = "", kind = "info") {
  const region = document.querySelector("#toast-region");
  const element = document.createElement("div");
  element.className = `toast ${kind === "error" ? "error" : ""}`;
  element.innerHTML = `<strong>${escapeHtml(title)}</strong><span>${escapeHtml(detail)}</span>`;
  region.append(element);
  setTimeout(() => element.remove(), 5200);
}

function setBusy(button, busy, label = "处理中…") {
  if (!button) return;
  if (busy) {
    button.dataset.previousLabel = button.textContent;
    button.textContent = label;
    button.disabled = true;
  } else {
    button.textContent = button.dataset.previousLabel || button.textContent;
    button.disabled = false;
  }
}

function navigate(view) {
  state.currentView = view;
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.classList.toggle("is-active", item.dataset.view === view);
  });
  document.querySelectorAll("[data-view-panel]").forEach((panel) => {
    panel.classList.toggle("is-active", panel.dataset.viewPanel === view);
  });
  const [eyebrow, title] = viewMeta[view];
  document.querySelector("#view-eyebrow").textContent = eyebrow;
  document.querySelector("#view-title").textContent = title;
}

function renderTrust() {
  const trust = state.overview.appTrust;
  const passed = trust.signed && trust.trustedByOs;
  const localAuthorization = trust.distributionMode === "local-user-authorization";
  document.querySelector("#trust-title").textContent = passed ? "系统信任链通过" : "当前构建采用本地授权";
  const seal = document.querySelector("#trust-seal");
  seal.textContent = passed ? "可信" : "本地授权";
  seal.className = `trust-seal ${passed ? "good" : "warn"}`;
  document.querySelector("#trust-meter-fill").style.width = passed ? "100%" : "66%";
  document.querySelector("#trust-summary").textContent = localAuthorization && !passed
    ? "管理器自身不含 Developer ID 或 Authenticode 签名，需由用户在本机明确授权；下载的 Skills 仍独立执行签名与逐文件哈希验证。"
    : trust.summary;
  const stateElement = document.querySelector("#app-signing-state");
  stateElement.textContent = passed ? "操作系统验证通过" : "未建立系统发布者身份";
  stateElement.className = `security-state ${passed ? "good" : "warn"}`;
  const applicationDetail = localAuthorization && !passed
    ? "本地授权发行模式：应用未签名，系统可能显示未知开发者或未知发布者；企业策略可能不允许例外。"
    : trust.details || trust.summary;
  document.querySelector("#app-signing-detail").textContent = state.overview.audit?.warning
    ? `${applicationDetail} ${state.overview.audit.warning}`
    : applicationDetail;
}

function renderPlatformStrip() {
  const element = document.querySelector("#platform-strip");
  element.innerHTML = state.overview.platforms.map((platform) => `
    <article class="platform-mini">
      <span class="platform-status ${platform.detected ? "detected" : ""}" title="${platform.detected ? "本机已发现" : "本机未发现"}"></span>
      <div class="platform-monogram">${escapeHtml(monogram(platform.name))}</div>
      <h3>${escapeHtml(platform.name)}</h3>
      <p>${escapeHtml(supportLabels[platform.support] || "专用适配")}</p>
    </article>
  `).join("");
}

function platformAction(platform) {
  if (!platform.detected) {
    return `<button class="button ghost" type="button" disabled>本机未安装</button>`;
  }
  if (platform.id === "workbuddy") {
    return `<button class="button ghost" data-platform-action="workbuddy" data-platform-id="${platform.id}" type="button">准备安装</button>`;
  }
  if (platform.canInstallAutomatically) {
    return `<button class="button primary compact" data-platform-action="generic" data-platform-id="${platform.id}" type="button">一键导入</button>`;
  }
  return `<button class="button ghost" data-platform-action="guided" data-platform-id="${platform.id}" type="button">准备导入</button>`;
}

function renderPlatforms() {
  const list = document.querySelector("#platform-list");
  const empty = document.querySelector("#platform-list-empty");
  const allPlatforms = state.overview.platforms;
  const detected = state.overview.platforms.filter((item) => item.detected);
  const automatic = detected.filter((item) => item.canInstallAutomatically);
  const workBuddy = detected.some((item) => item.id === "workbuddy");
  const visible = allPlatforms.filter((platform) => {
    if (state.platformFilter === "detected") return platform.detected;
    if (state.platformFilter === "automatic") return platform.detected && platform.canInstallAutomatically;
    return true;
  });
  document.querySelector("#discovery-title").textContent = detected.length
    ? `已发现 ${detected.length} 个 Agent 平台`
    : "暂未发现已安装的 Agent 平台";
  document.querySelector("#discovery-detail").textContent = detected.length
    ? `${automatic.length} 个可直接同步${workBuddy ? "，WorkBuddy 使用应用内插件市场" : ""}；其余平台按官方界面导入。`
    : "扫描范围包括系统应用目录、常见用户安装目录和已配置命令位置。";
  const scan = state.overview.scan;
  document.querySelector("#scan-meta").textContent = scan?.scannedAt
    ? `最近扫描 ${new Date(scan.scannedAt).toLocaleTimeString("zh-CN", { hour12: false })} · ${scan.durationMs} ms · 适配器 ${state.overview.adapters?.revision || "内置"} / ${state.overview.adapters?.sequence || "—"} · 未读取用户文档`
    : "尚未执行本机扫描";
  document.querySelector("#platform-count-all").textContent = allPlatforms.length;
  document.querySelector("#platform-count-detected").textContent = detected.length;
  document.querySelector("#platform-count-automatic").textContent = automatic.length;
  const installAll = document.querySelector("#install-detected-button");
  installAll.disabled = automatic.length === 0;
  installAll.textContent = automatic.length
    ? `一键导入全部 ${automatic.length} 个平台`
    : "没有可一键写入的平台";
  empty.hidden = visible.length > 0;
  list.innerHTML = visible.map((platform) => `
    <article class="platform-row ${platform.detected ? "is-detected" : "is-missing"}">
      <div class="platform-monogram">${escapeHtml(monogram(platform.name))}</div>
      <div>
        <h3>${escapeHtml(platform.name)}${platform.detected ? '<span class="installed-mark">已安装</span>' : ""}</h3>
        <p>${escapeHtml(platform.vendor)} · ${escapeHtml(platform.notes)}</p>
      </div>
      <div>
        <span class="support-badge ${platform.support}">${escapeHtml(supportLabels[platform.support] || "专用适配")}</span>
        <small>${platform.detected ? `扫描命中 · ${escapeHtml(platform.detectedPaths?.[0] || "已知入口")}` : "支持导入，等待本机安装"}</small>
      </div>
      <div class="path-value" title="${escapeHtml(platform.targetRoot || "通过平台界面导入")}">
        ${escapeHtml(platform.canInstallAutomatically ? platform.targetRoot : "通过平台官方界面完成")}
      </div>
      ${platformAction(platform)}
    </article>
  `).join("");
}

function renderTargets() {
  const targets = document.querySelector("#managed-target-list");
  const registryTargets = state.overview.registry?.targets || {};
  if (!state.overview.targets.length) {
    targets.innerHTML = `<div class="target-row"><div><strong>尚未发现托管目录</strong><span>安装支持的 Agent 后重新扫描。</span></div></div>`;
    return;
  }
  targets.innerHTML = state.overview.targets.map((target) => {
    const record = registryTargets[target.targetRoot];
    return `
      <article class="target-row">
        <div>
          <strong>${escapeHtml(target.targetRoot)}</strong>
          <span>${escapeHtml(target.platformIds.join(" + "))} · ${record ? `已登记 ${record.version}` : "尚未由管理器接管"}</span>
        </div>
        <button class="button ghost" data-reveal="${escapeHtml(target.targetRoot)}" type="button">打开目录</button>
        <button class="button danger" data-rollback="${escapeHtml(target.targetRoot)}" type="button" ${record ? "" : "disabled"}>回滚</button>
      </article>
    `;
  }).join("");
}

function renderCompatibility() {
  const report = state.overview.compatibility;
  const detected = state.overview.platforms.filter((item) => item.detected).length;
  const automatic = state.overview.platforms.filter((item) => item.canInstallAutomatically).length;
  document.querySelector("#compatibility-summary").innerHTML = `
    <article class="metric-card"><span class="kicker">SIGNED SKILLS</span><strong>${report.skillCount}</strong><p>当前正式技能总数</p></article>
    <article class="metric-card"><span class="kicker">DETECTED</span><strong>${detected}</strong><p>本机发现的平台入口</p></article>
    <article class="metric-card"><span class="kicker">AUTO TARGETS</span><strong>${automatic}</strong><p>具备稳定目录的自动目标</p></article>
  `;
  const platformsById = new Map(state.overview.platforms.map((item) => [item.id, item]));
  document.querySelector("#matrix-body").innerHTML = report.platforms.map((row) => {
    const platform = platformsById.get(row.platformId);
    const full = row.support === "full";
    return `
      <tr>
        <td>${escapeHtml(row.platformName)}</td>
        <td class="${platform?.detected ? "cell-good" : "cell-muted"}">${platform?.detected ? "已发现" : "未发现"}</td>
        <td class="${full ? "cell-good" : "cell-review"}">${escapeHtml(row.label)}</td>
        <td class="${full ? "cell-good" : "cell-review"}">${full ? "随包校验" : "需平台复验"}</td>
        <td class="${row.platformId === "cherry-studio" ? "cell-review" : "cell-good"}">${row.platformId === "cherry-studio" ? "单独配置" : "可接入"}</td>
        <td>${escapeHtml(platform?.installMode || "—")}</td>
      </tr>
    `;
  }).join("");
}

function renderChannels() {
  const empty = document.querySelector("#channel-empty");
  const grid = document.querySelector("#channel-grid");
  if (!state.channels) {
    empty.hidden = false;
    grid.innerHTML = "";
    return;
  }
  empty.hidden = true;
  const names = { generic: "通用 Skills", workbuddy: "WorkBuddy 跨平台包" };
  grid.innerHTML = state.channels.channels.map((channel) => {
    const artifact = state.artifacts.get(channel.id);
    const verified = Boolean(artifact);
    return `
      <article class="channel-card">
        <span class="channel-badge support-badge ${verified ? "full" : "adapter"}">${verified ? "本机会话已验签" : "等待下载验证"}</span>
        <h3>${escapeHtml(names[channel.id] || channel.id)}</h3>
        <span class="version">${channel.available ? `V${escapeHtml(channel.version)}` : "暂无正式版本"}</span>
        <div class="channel-meta">
          <span>文件大小 <code>${formatBytes(channel.file_size)}</code></span>
          <span>SHA-256 <code title="${escapeHtml(channel.sha256)}">${escapeHtml(shortHash(channel.sha256))}</code></span>
          <span>发布时间 <code>${escapeHtml(channel.published_at || "—")}</code></span>
        </div>
        <button class="button ${verified ? "ghost" : "primary"}" data-download-channel="${escapeHtml(channel.id)}" type="button" ${channel.available ? "" : "disabled"}>
          ${verified ? "重新下载并验证" : "下载并验证签名"}
        </button>
      </article>
    `;
  }).join("");
}

function updateConnection(connected) {
  document.querySelector("#connection-dot").classList.toggle("is-online", connected);
  document.querySelector("#connection-label").textContent = connected ? "发布门户已连接" : "尚未连接";
  document.querySelector("#connect-button").textContent = connected ? "断开门户" : "连接发布门户";
}

function renderAll() {
  document.querySelector("#skill-count").textContent = state.overview.product.skillCount;
  document.querySelector("#portal-url").value = state.overview.settings.portalUrl;
  renderTrust();
  renderPlatformStrip();
  renderPlatforms();
  renderTargets();
  renderCompatibility();
  renderChannels();
}

async function refreshOverview() {
  try {
    state.overview = bridge ? await bridge.overview() : demoOverview;
    renderAll();
  } catch (error) {
    state.overview = demoOverview;
    renderAll();
    toast("读取本机状态失败", error.message, "error");
  }
}

async function scanLocalAgents(button) {
  setBusy(button, true, "正在扫描…");
  try {
    if (bridge) {
      const result = await bridge.scanPlatforms();
      state.overview = { ...state.overview, ...result };
    } else {
      await new Promise((resolve) => setTimeout(resolve, 420));
      state.overview = {
        ...state.overview,
        scan: {
          ...state.overview.scan,
          scannedAt: new Date().toISOString(),
        },
      };
    }
    renderPlatformStrip();
    renderPlatforms();
    renderTargets();
    renderCompatibility();
    navigate("platforms");
    const found = state.overview.platforms.filter((item) => item.detected).length;
    toast("本机 Agent 扫描完成", `共检查 ${state.overview.platforms.length} 个主流平台，发现 ${found} 个已安装平台。`);
  } catch (error) {
    toast("扫描未完成", error.message, "error");
  } finally {
    setBusy(button, false);
  }
}

function openConnectDialog() {
  document.querySelector("#connect-dialog").showModal();
  setTimeout(() => document.querySelector("#access-token").focus(), 30);
}

function closeActionDialog() {
  document.querySelector("#action-dialog").close();
  state.action = null;
}

function openAction({ kicker, title, html, confirmLabel = "继续", onConfirm, disabled = false }) {
  document.querySelector("#action-kicker").textContent = kicker;
  document.querySelector("#action-title").textContent = title;
  document.querySelector("#action-content").innerHTML = html;
  const confirm = document.querySelector("#action-confirm");
  confirm.textContent = confirmLabel;
  confirm.disabled = disabled;
  state.action = onConfirm;
  document.querySelector("#action-dialog").showModal();
}

async function connectPortal() {
  if (!bridge) {
    toast("界面预览模式", "桌面进程启动后才能连接真实门户。");
    return;
  }
  const portalUrl = document.querySelector("#portal-url").value.trim();
  const authMode = document.querySelector("#auth-mode").value;
  const accessToken = document.querySelector("#access-token").value.trim();
  const button = document.querySelector("#connect-submit");
  setBusy(button, true, "正在连接…");
  try {
    state.channels = await bridge.connectPortal({ portalUrl, authMode, accessToken });
    const scanned = await bridge.scanPlatforms();
    state.overview = { ...state.overview, ...scanned };
    document.querySelector("#access-token").value = "";
    document.querySelector("#connect-dialog").close();
    updateConnection(true);
    renderPlatformStrip();
    renderPlatforms();
    renderTargets();
    renderCompatibility();
    renderChannels();
    navigate("updates");
    const adapter = state.channels.platform_adapter;
    const adapterDetail = adapter?.status === "verified"
      ? `平台适配器 ${adapter.revision} 已验签更新。`
      : `平台适配器沿用 ${adapter?.revision || "内置版本"}。`;
    toast(
      "发布门户已连接",
      `已读取 ${state.channels.channels.length} 个发布通道；${adapterDetail}`,
    );
  } catch (error) {
    toast("连接失败", error.message, "error");
  } finally {
    setBusy(button, false);
  }
}

async function ensureArtifact(channelId, button) {
  if (state.artifacts.has(channelId)) return state.artifacts.get(channelId);
  if (!state.channels) {
    openConnectDialog();
    throw new Error("请先连接发布门户");
  }
  setBusy(button, true, "下载与验签中…");
  try {
    const artifact = await bridge.downloadAndVerify(channelId);
    state.artifacts.set(channelId, artifact);
    renderChannels();
    toast(
      "签名与完整性验证通过",
      `${artifact.verification.signatures} 份签名，${artifact.verification.verifiedFiles} 个文件哈希匹配。`,
    );
    return artifact;
  } finally {
    setBusy(button, false);
  }
}

async function installToDetectedPlatforms(button) {
  if (!bridge) {
    toast("界面预览模式", "桌面进程启动后才能扫描和安装。");
    return;
  }
  try {
    await ensureArtifact("generic", button);
    const batch = await bridge.planDetectedInstall();
    const conflicts = batch.targets.flatMap((target) => target.conflicts || []);
    const targetRows = batch.targets.map((target) => `
      <li>
        <strong>${escapeHtml(target.platformIds.join(" + "))}</strong>
        <span class="path-value">${escapeHtml(target.targetRoot)}</span>
        <small>${target.skillCount} 项技能 · 新增 ${target.additions} · 更新 ${target.replacements}</small>
      </li>
    `).join("");
    const conflictCopy = conflicts.length
      ? `<p><strong>发现 ${conflicts.length} 个未登记同名目录，已阻止覆盖。</strong></p>`
      : "<p>每个目标独立执行原子更新并保留回滚副本；不会请求管理员权限。</p>";
    openAction({
      kicker: "DISCOVERED AGENTS",
      title: conflicts.length ? "需要先处理目录冲突" : `导入到 ${batch.targets.length} 个已发现目标`,
      html: `${conflictCopy}<ul class="install-target-list">${targetRows}</ul><p>WorkBuddy 如已发现，使用该平台行内按钮下载插件市场包，然后在 WorkBuddy 内完成添加和安装。</p>`,
      confirmLabel: "确认一键导入",
      disabled: conflicts.length > 0,
      onConfirm: async () => {
        const result = await bridge.executeDetectedInstall(batch.batchId);
        closeActionDialog();
        await refreshOverview();
        toast("多平台导入完成", `${result.results.length} 个 Skills 目录已更新并登记回滚点。`);
      },
    });
  } catch (error) {
    if (error.message !== "请先连接发布门户") toast("一键安装未完成", error.message, "error");
  }
}

async function handlePlatformAction(button) {
  const platform = state.overview.platforms.find((item) => item.id === button.dataset.platformId);
  if (!platform || !bridge) return;
  try {
    if (button.dataset.platformAction === "workbuddy") {
      const artifact = await ensureArtifact("workbuddy", button);
      await bridge.showItem(artifact.downloaded.path);
      toast(
        "WorkBuddy 插件市场包已就绪",
        "解压 ZIP 后，在 WorkBuddy 内使用 /plugin marketplace add 添加目录，再安装 jiaotang-workbuddy-skills@jiaotang。",
      );
      return;
    }
    const artifact = await ensureArtifact("generic", button);
    if (button.dataset.platformAction === "guided") {
      await bridge.revealPath(artifact.downloaded.path);
      toast("已打开已验证安装包", "请使用平台官方导入界面选择该 ZIP。");
      return;
    }
    if (!platform.targetRoot) throw new Error("当前平台没有可用的托管目录");
    const plan = await bridge.planGenericInstall({
      targetRoot: platform.targetRoot,
      platformIds: state.overview.platforms
        .filter((item) => item.targetRoot === platform.targetRoot)
        .map((item) => item.id),
    });
    const conflicts = plan.conflicts.length
      ? `<p><strong>发现 ${plan.conflicts.length} 个未登记同名目录，已阻止覆盖：</strong></p><ul>${plan.conflicts.slice(0, 8).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`
      : `<p>将安装 ${plan.skillCount} 项技能，新增 ${plan.additions.length} 项，替换 ${plan.replacements.length} 项已登记内容。</p><p>当前内容将移动到同盘备份区，可从管理器回滚。</p>`;
    openAction({
      kicker: "ATOMIC INSTALL PLAN",
      title: conflicts ? "需要处理同名冲突" : `导入到 ${platform.name}`,
      html: conflicts,
      confirmLabel: "确认一键导入",
      disabled: plan.conflicts.length > 0,
      onConfirm: async () => {
        const result = await bridge.executeGenericInstall(plan.planId);
        closeActionDialog();
        await refreshOverview();
        toast("Skills 导入完成", `${result.skillCount} 项技能已更新到 ${result.targetRoot}`);
      },
    });
  } catch (error) {
    if (error.message !== "请先连接发布门户") toast("操作未完成", error.message, "error");
  }
}

async function handleRollback(targetRoot) {
  if (!bridge) return;
  openAction({
    kicker: "RECOVERABLE ROLLBACK",
    title: "回滚最近一次托管更新",
    html: `<p>目标目录：<span class="path-value">${escapeHtml(targetRoot)}</span></p><p>当前托管版本不会被删除，而会移动到 displaced 恢复区；随后恢复最近备份。</p>`,
    confirmLabel: "执行可恢复回滚",
    onConfirm: async () => {
      const result = await bridge.rollback(targetRoot);
      closeActionDialog();
      await refreshOverview();
      toast("回滚完成", result.restoredVersion ? `已恢复 ${result.restoredVersion}` : "已恢复到未托管状态");
    },
  });
}

document.addEventListener("click", async (event) => {
  const nav = event.target.closest("[data-view]");
  if (nav) navigate(nav.dataset.view);
  const go = event.target.closest("[data-go]");
  if (go) navigate(go.dataset.go);
  if (event.target.closest("[data-open-connect]") || event.target.closest("#hero-connect")) openConnectDialog();
  if (event.target.closest("#connect-button")) {
    if (state.channels && bridge) {
      await bridge.disconnectPortal();
      state.channels = null;
      state.artifacts.clear();
      updateConnection(false);
      renderChannels();
      toast("已断开发布门户", "会话访问令牌已从内存清除。");
    } else {
      openConnectDialog();
    }
  }
  const scanButton = event.target.closest("#rescan-button, #platform-rescan-button");
  if (scanButton) await scanLocalAgents(scanButton);
  const platformFilter = event.target.closest("[data-platform-filter]");
  if (platformFilter) {
    state.platformFilter = platformFilter.dataset.platformFilter;
    document.querySelectorAll("[data-platform-filter]").forEach((button) => {
      const active = button === platformFilter;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    renderPlatforms();
  }
  const installDetected = event.target.closest("#install-detected-button");
  if (installDetected) await installToDetectedPlatforms(installDetected);
  const channelButton = event.target.closest("[data-download-channel]");
  if (channelButton && bridge) {
    try {
      await ensureArtifact(channelButton.dataset.downloadChannel, channelButton);
    } catch (error) {
      toast("验证失败", error.message, "error");
    }
  }
  const platformButton = event.target.closest("[data-platform-action]");
  if (platformButton) await handlePlatformAction(platformButton);
  const reveal = event.target.closest("[data-reveal]");
  if (reveal && bridge) await bridge.revealPath(reveal.dataset.reveal);
  const rollback = event.target.closest("[data-rollback]");
  if (rollback) await handleRollback(rollback.dataset.rollback);
  if (event.target.closest("#open-audit-log") && bridge) {
    const result = await bridge.revealAuditLog();
    if (result.status !== "shown") toast("无法打开审计日志", result.detail || "未知错误", "error");
  }
  if (event.target.closest("[data-close-action]")) closeActionDialog();
  if (event.target.closest("#action-confirm") && state.action) {
    const confirm = document.querySelector("#action-confirm");
    setBusy(confirm, true, "正在执行…");
    try {
      await state.action();
    } catch (error) {
      toast("操作失败", error.message, "error");
      setBusy(confirm, false);
    }
  }
});

document.querySelector("#auth-mode").addEventListener("change", (event) => {
  const adminToken = event.target.value === "admin-token";
  document.querySelector("#access-token-field").hidden = !adminToken;
  document.querySelector("#access-token").required = adminToken;
});

document.querySelector("#connect-form").addEventListener("submit", (event) => {
  if (event.submitter?.value === "cancel") return;
  event.preventDefault();
  connectPortal();
});

const requestedView = new URLSearchParams(window.location.search).get("view");
if (requestedView && viewMeta[requestedView]) navigate(requestedView);
refreshOverview();
