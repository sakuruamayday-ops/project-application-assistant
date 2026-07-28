const state = {
  channels: null,
  nativeRelease: null,
  capabilities: null,
  canSyncDirectory: false,
  installPrompt: null,
};
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const encode = new TextEncoder();
const decode = new TextDecoder();

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function toast(title, detail = "") {
  const item = document.createElement("div");
  item.className = "toast";
  item.innerHTML = `<strong></strong><span></span>`;
  item.querySelector("strong").textContent = title;
  item.querySelector("span").textContent = detail;
  $("#toasts").append(item);
  setTimeout(() => item.remove(), 5200);
}

function progress(title, detail) {
  $("#progress-title").textContent = title;
  $("#progress-detail").textContent = detail;
  $("#progress-close").hidden = true;
  $("#progress").showModal();
}

function finishProgress(title, detail) {
  $("#progress-title").textContent = title;
  $("#progress-detail").textContent = detail;
  $("#progress-close").hidden = false;
}

function navigate(view) {
  $$(".nav").forEach((item) => item.classList.toggle("active", item.dataset.view === view));
  $$(".view").forEach((item) => item.classList.toggle("active", item.dataset.panel === view));
  $("#page-title").textContent = { overview: "技能交付控制台", platforms: "平台与托管目录", security: "安全与信任边界" }[view];
}

function evaluateCapabilities(manifest) {
  const checks = {
    secureContext: window.isSecureContext,
    webCrypto: Boolean(window.crypto?.subtle),
    directoryPicker: "showDirectoryPicker" in window,
    directoryRemove: Boolean(window.FileSystemDirectoryHandle?.prototype?.removeEntry),
    zipDeflate: "DecompressionStream" in window,
  };
  const missing = manifest.directory_sync.required_browser_capabilities
    .filter((name) => !checks[name]);
  state.capabilities = { manifest, checks, missing };
  state.canSyncDirectory = missing.length === 0;
  $$("[data-sync]").forEach((button) => {
    button.disabled = !state.canSyncDirectory;
    button.title = state.canSyncDirectory ? "" : `缺少能力：${missing.join("、")}`;
  });
  $("#capability-state").textContent = state.canSyncDirectory
    ? "当前浏览器可安全同步目录"
    : "当前浏览器仅支持下载";
  $("#capability-detail").textContent = state.canSyncDirectory
    ? "安全上下文、SHA-256、ZIP解压和目录授权能力均已就绪。"
    : `缺少 ${missing.join("、")}，不会尝试写入本地目录。`;
}

async function loadControlPlane() {
  const [channelResponse, capabilityResponse, nativeReleaseResponse] = await Promise.all([
    fetch("/v1/web/skills/channels", { credentials: "same-origin" }),
    fetch("/static/skills-manager/platform-capabilities.json", { credentials: "same-origin" }),
    fetch("/v1/web/skills-manager/native-release", { credentials: "same-origin" })
      .catch(() => null),
  ]);
  if (!channelResponse.ok) throw new Error(`读取发布通道失败：HTTP ${channelResponse.status}`);
  if (!capabilityResponse.ok) throw new Error(`读取能力清单失败：HTTP ${capabilityResponse.status}`);
  state.channels = await channelResponse.json();
  state.nativeRelease = nativeReleaseResponse?.ok
    ? await nativeReleaseResponse.json()
    : null;
  evaluateCapabilities(await capabilityResponse.json());
  const labels = { generic: "通用 Skills", workbuddy: "WorkBuddy 跨平台包" };
  $("#channels").innerHTML = state.channels.channels.map((item) => `
    <article class="channel">
      <small>${labels[item.id] || item.id}</small>
      <h3>${item.available ? "当前正式版本" : "当前未发布"}</h3>
      <strong>${item.available ? `V${item.version}` : "—"}</strong>
      <p><code>${item.available ? `${item.sha256.slice(0, 10)}…${item.sha256.slice(-6)}` : "等待发布"}</code></p>
    </article>`).join("");
  const available = state.channels.channels.filter((item) => item.available).length;
  $("#release-state").textContent = `${available} 条通道已就绪`;
  $("#release-detail").textContent = "通用 Skills 与跨平台 WorkBuddy 保持两条独立内容通道；桌面客户端使用单独版本，不会推动 Skills 强制升级。";
  renderNativeRelease();
}

function renderNativeRelease() {
  const release = state.nativeRelease;
  const container = $("#native-client-list");
  const manualAction = $("#native-user-manual");
  if (!release) {
    manualAction.removeAttribute("href");
    manualAction.classList.add("is-disabled");
    manualAction.setAttribute("aria-disabled", "true");
    manualAction.textContent = "暂时无法读取 Word 用户手册状态";
    container.innerHTML = `
      <article class="native-client-card is-pending">
        <div class="native-platform-line"><span>桌面客户端</span><small>可选</small></div>
        <h3>暂时无法读取候选包状态</h3>
        <p>PWA 与 Skills 下载仍可继续使用；刷新页面后再检查桌面客户端下载。</p>
        <span class="ghost native-download is-disabled" aria-disabled="true">候选包状态不可用</span>
      </article>`;
    return;
  }
  const manualAvailable = Boolean(
    release.available
    && release.user_manual?.available
    && release.user_manual?.download_url,
  );
  manualAction.textContent = manualAvailable
    ? "下载 Word 用户手册"
    : "Word 用户手册随正式包发布";
  manualAction.classList.toggle("is-disabled", !manualAvailable);
  manualAction.setAttribute("aria-disabled", String(!manualAvailable));
  if (manualAvailable) {
    manualAction.href = release.user_manual.download_url;
  } else {
    manualAction.removeAttribute("href");
  }
  const labels = {
    "macos-arm64": ["macOS", "Apple Silicon", "在“隐私与安全性”中确认打开"],
    "macos-x64": ["macOS", "Intel", "在“隐私与安全性”中确认打开"],
    "windows-x64": ["Windows", "64 位", "SmartScreen 或企业策略可能阻止"],
  };
  container.innerHTML = release.artifacts.map((artifact) => {
    const [platform, architecture, guidance] = labels[artifact.id] || [
      artifact.platform,
      artifact.arch,
      "按本机系统提示确认",
    ];
    const available = Boolean(release.available && artifact.available);
    const digest = artifact.sha256
      ? `${artifact.sha256.slice(0, 10)}…${artifact.sha256.slice(-6)}`
      : "正式产物生成后公布";
    const action = available
      ? `<a class="primary native-download" href="${escapeHtml(artifact.download_url)}">下载本机授权版</a>`
      : '<span class="ghost native-download is-disabled" aria-disabled="true">候选包待发布</span>';
    return `
      <article class="native-client-card ${available ? "is-ready" : "is-pending"}">
        <div class="native-platform-line">
          <span>${escapeHtml(platform)}</span>
          <small>${escapeHtml(architecture)}</small>
        </div>
        <h3>${escapeHtml(artifact.file_name)}</h3>
        <dl>
          <div><dt>客户端版本</dt><dd>V${escapeHtml(release.version)}</dd></div>
          <div><dt>SHA-256</dt><dd><code title="${escapeHtml(artifact.sha256)}">${escapeHtml(digest)}</code></dd></div>
        </dl>
        <p>${escapeHtml(guidance)}</p>
        ${action}
      </article>`;
  }).join("");
}

function channel(id) {
  const value = state.channels?.channels.find((item) => item.id === id);
  if (!value?.available) throw new Error(`发布通道 ${id} 当前不可用`);
  return value;
}

async function sha256(buffer) {
  const digest = await crypto.subtle.digest("SHA-256", buffer);
  return [...new Uint8Array(digest)].map((value) => value.toString(16).padStart(2, "0")).join("");
}

async function downloadChannel(id) {
  const item = channel(id);
  const response = await fetch(item.download_url, { credentials: "same-origin" });
  if (!response.ok) throw new Error(`下载失败：HTTP ${response.status}`);
  const buffer = await response.arrayBuffer();
  const actual = await sha256(buffer);
  if (actual !== item.sha256.toLowerCase()) throw new Error(`SHA-256不一致：${actual}`);
  return { item, buffer };
}

async function getDirectory(root, segments, create = false) {
  let current = root;
  for (const segment of segments) current = await current.getDirectoryHandle(segment, { create });
  return current;
}

async function readJson(root, pathSegments, fallback) {
  try {
    const parent = await getDirectory(root, pathSegments.slice(0, -1));
    const file = await parent.getFileHandle(pathSegments.at(-1));
    return JSON.parse(await (await file.getFile()).text());
  } catch {
    return structuredClone(fallback);
  }
}

async function writeFile(root, relative, data) {
  const parts = relative.split("/");
  const parent = await getDirectory(root, parts.slice(0, -1), true);
  const file = await parent.getFileHandle(parts.at(-1), { create: true });
  const writer = await file.createWritable();
  await writer.write(data);
  await writer.close();
}

async function pathKind(root, relative) {
  const parts = relative.split("/");
  let parent;
  try {
    parent = await getDirectory(root, parts.slice(0, -1));
  } catch {
    return null;
  }
  try { await parent.getDirectoryHandle(parts.at(-1)); return "directory"; } catch {}
  try { await parent.getFileHandle(parts.at(-1)); return "file"; } catch {}
  return null;
}

async function copyDirectory(source, target) {
  for await (const [name, handle] of source.entries()) {
    if (handle.kind === "directory") {
      await copyDirectory(handle, await target.getDirectoryHandle(name, { create: true }));
    } else {
      const file = await handle.getFile();
      const output = await target.getFileHandle(name, { create: true });
      const writer = await output.createWritable();
      await writer.write(await file.arrayBuffer());
      await writer.close();
    }
  }
}

async function copyPath(root, relative, backupRoot) {
  const kind = await pathKind(root, relative);
  if (!kind) return false;
  const parts = relative.split("/");
  const sourceParent = await getDirectory(root, parts.slice(0, -1));
  const targetParent = await getDirectory(backupRoot, parts.slice(0, -1), true);
  if (kind === "directory") {
    await copyDirectory(
      await sourceParent.getDirectoryHandle(parts.at(-1)),
      await targetParent.getDirectoryHandle(parts.at(-1), { create: true }),
    );
  } else if (kind === "file") {
    const input = await (await sourceParent.getFileHandle(parts.at(-1))).getFile();
    const output = await targetParent.getFileHandle(parts.at(-1), { create: true });
    const writer = await output.createWritable();
    await writer.write(await input.arrayBuffer());
    await writer.close();
  }
  return Boolean(kind);
}

async function removePath(root, relative) {
  const kind = await pathKind(root, relative);
  if (!kind) return false;
  const parts = relative.split("/");
  const parent = await getDirectory(root, parts.slice(0, -1));
  await parent.removeEntry(parts.at(-1), { recursive: kind === "directory" });
  return true;
}

function installEntries(manifest) {
  return [...new Set([...(manifest.skills || []), ...(manifest.shared_paths || [])])];
}

async function syncDirectory() {
  if (!state.canSyncDirectory) {
    throw new Error(`当前环境只允许下载：${state.capabilities?.missing.join("、") || "能力清单尚未就绪"}`);
  }
  const root = await window.showDirectoryPicker({ mode: "readwrite", id: "jiaotang-skills-target" });
  progress("正在验证发布包", "计算SHA-256并检查ZIP路径与结构。");
  const { item, buffer } = await downloadChannel("generic");
  const files = await window.JiaotangZip.readZip(buffer);
  const manifestNames = [...files.keys()].filter((name) => name.endsWith("/skills/suite-manifest.json"));
  if (manifestNames.length !== 1) throw new Error("通用包必须包含且只能包含一份suite-manifest.json");
  const manifestName = manifestNames[0];
  const prefix = manifestName.slice(0, -"suite-manifest.json".length);
  const manifest = JSON.parse(decode.decode(files.get(manifestName)));
  const entries = installEntries(manifest);
  if (!Array.isArray(manifest.skills) || manifest.skills.length !== 49) {
    throw new Error("发布包技能数量不是49项");
  }
  if (!entries.length) throw new Error("发布包没有可安装路径");
  const emptyRegistry = { schema: "jiaotang-pwa-registry/v1", targets: {}, backups: [] };
  const registryPath = [".jiaotang-skills-manager", "registry.json"];
  const registry = await readJson(root, registryPath, emptyRegistry);
  const managed = new Set(registry.managedEntries || []);
  const conflicts = [];
  for (const entry of entries) if (await pathKind(root, entry) && !managed.has(entry)) conflicts.push(entry);
  if (conflicts.length) throw new Error(`发现未托管同名内容，已停止：${conflicts.slice(0, 4).join("、")}`);
  const replacedEntries = [...new Set([...(registry.managedEntries || []), ...entries])];
  const stamp = new Date().toISOString().replaceAll(/[-:.TZ]/g, "").slice(0, 14);
  const internal = await getDirectory(root, [".jiaotang-skills-manager"], true);
  const backupRoot = await getDirectory(internal, ["backups", stamp], true);
  const existed = {};
  for (const entry of replacedEntries) existed[entry] = await copyPath(root, entry, backupRoot);
  const restorePoint = {
    id: stamp,
    entries: replacedEntries,
    existed,
    previousVersion: registry.version || null,
    previousManagedEntries: registry.managedEntries || [],
  };
  const pending = {
    ...registry,
    backups: [restorePoint, ...(registry.backups || [])].slice(0, 10),
    pendingTransaction: stamp,
  };
  await writeFile(root, registryPath.join("/"), encode.encode(`${JSON.stringify(pending, null, 2)}\n`));
  for (const entry of replacedEntries) await removePath(root, entry);
  progress("正在写入49项技能", "只写入发布清单列出的托管路径。");
  for (const [name, data] of files) {
    if (!name.startsWith(prefix) || name === manifestName) continue;
    const relative = name.slice(prefix.length);
    if (entries.some((entry) => relative === entry || relative.startsWith(`${entry}/`))) await writeFile(root, relative, data);
  }
  const next = {
    schema: "jiaotang-pwa-registry/v1",
    version: item.version,
    sha256: item.sha256,
    managedEntries: entries,
    installedAt: new Date().toISOString(),
    pendingTransaction: null,
    backups: pending.backups,
  };
  await writeFile(root, registryPath.join("/"), encode.encode(`${JSON.stringify(next, null, 2)}\n`));
  finishProgress("同步完成", `V${item.version}的49项技能已写入所选目录，并保留可恢复备份。`);
}

async function rollbackDirectory() {
  if (!window.showDirectoryPicker) throw new Error("当前浏览器不支持目录授权");
  const root = await window.showDirectoryPicker({ mode: "readwrite", id: "jiaotang-skills-target" });
  const registryPath = [".jiaotang-skills-manager", "registry.json"];
  const registry = await readJson(root, registryPath, null);
  const latest = registry?.backups?.[0];
  if (!latest) throw new Error("所选目录没有可用的管理器备份");
  progress("正在执行可恢复回滚", "当前版本先复制到displaced恢复区，再恢复上一份备份。");
  const internal = await getDirectory(root, [".jiaotang-skills-manager"], true);
  const displaced = await getDirectory(internal, ["displaced", `${Date.now()}-rollback`], true);
  const backup = await getDirectory(internal, ["backups", latest.id]);
  for (const entry of latest.entries) {
    await copyPath(root, entry, displaced);
    await removePath(root, entry);
    if (latest.existed[entry]) await copyPath(backup, entry, root);
  }
  registry.backups.shift();
  registry.version = latest.previousVersion || "rolled-back";
  registry.managedEntries = latest.previousManagedEntries || [];
  registry.pendingTransaction = null;
  await writeFile(root, registryPath.join("/"), encode.encode(`${JSON.stringify(registry, null, 2)}\n`));
  finishProgress("回滚完成", "上一份备份已恢复；刚才的当前版本仍保存在displaced目录。");
}

async function downloadAsFile(id) {
  progress("正在下载并校验", "浏览器会重新计算发布包SHA-256。");
  const { item, buffer } = await downloadChannel(id);
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([buffer], { type: "application/zip" }));
  link.download = item.file_name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 5000);
  finishProgress("下载完成", `${item.file_name}已通过SHA-256校验。`);
}

window.addEventListener("beforeinstallprompt", (event) => {
  event.preventDefault();
  state.installPrompt = event;
  $("#install-pwa").hidden = false;
});
$("#install-pwa").addEventListener("click", async () => {
  await state.installPrompt?.prompt();
  state.installPrompt = null;
  $("#install-pwa").hidden = true;
});
$("#refresh").addEventListener("click", () => loadControlPlane().then(() => toast("更新状态已刷新")).catch((error) => toast("刷新失败", error.message)));
$("#progress-close").addEventListener("click", () => $("#progress").close());
$$("[data-sync]").forEach((button) => button.addEventListener("click", () => syncDirectory().catch((error) => finishProgress("同步已停止", error.message))));
$$("[data-generic-download]").forEach((button) => button.addEventListener("click", () => downloadAsFile("generic").catch((error) => finishProgress("下载失败", error.message))));
$("[data-workbuddy]").addEventListener("click", () => downloadAsFile("workbuddy").catch((error) => finishProgress("下载失败", error.message)));
$("#rollback").addEventListener("click", () => rollbackDirectory().catch((error) => finishProgress("回滚未执行", error.message)));
$$(".nav").forEach((button) => button.addEventListener("click", () => navigate(button.dataset.view)));
$$("[data-view-jump]").forEach((button) => button.addEventListener("click", () => navigate(button.dataset.viewJump)));
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/skills-manager/sw.js", { scope: "/skills-manager" });
loadControlPlane().catch((error) => {
  $("#release-state").textContent = "控制面读取失败";
  $("#release-detail").textContent = error.message;
  $("#capability-state").textContent = "能力检查未完成";
  $("#capability-detail").textContent = "不会开放本地目录写入。";
});
