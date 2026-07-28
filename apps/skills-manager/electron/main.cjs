const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const crypto = require("node:crypto");
const {
  app,
  BrowserWindow,
  dialog,
  ipcMain,
  shell,
} = require("electron");
const {
  automaticDetectedTargets,
  readPlatformConfig,
  detectPlatforms,
  uniqueManagedTargets,
} = require("../core/platforms.cjs");
const { readCatalog, buildCompatibilityReport } = require("../core/compatibility.cjs");
const {
  fetchChannels,
  fetchPlatformAdapterBundle,
  downloadArtifact,
  normalizedPortalUrl,
} = require("../core/portal-client.cjs");
const { loadExistingDeviceCredentials } = require("../core/device-auth.cjs");
const { inspectApplicationTrust, verifySkillArchive } = require("../core/security.cjs");
const {
  assertAdapterNotDowngraded,
  loadLatestAdapterBundle,
  parseAdapterBundle,
  storeAdapterBundle,
  validatePlatformConfig,
} = require("../core/platform-adapters.cjs");
const { appendAuditEvent } = require("../core/audit.cjs");
const { loadRegistry } = require("../core/registry.cjs");
const {
  planGenericInstall,
  executeGenericInstall,
  rollbackLatest,
} = require("../core/update-engine.cjs");

const APP_ROOT = path.resolve(__dirname, "..");
const platformConfigPath = path.join(APP_ROOT, "config", "platforms.json");
const securityConfigPath = path.join(APP_ROOT, "config", "security.json");
const catalogPath = path.join(APP_ROOT, "data", "skill-catalog.json");
const state = {
  accessToken: "",
  deviceCredentials: null,
  channels: null,
  verifiedArtifacts: new Map(),
  installPlans: new Map(),
  installBatches: new Map(),
  platformConfig: null,
  platformConfigSource: "built-in",
  auditWarning: null,
  auditSessionId: crypto.randomUUID(),
};

function managerPaths() {
  const root = app.getPath("userData");
  return {
    root,
    cache: path.join(root, "cache"),
    registry: path.join(root, "registry.json"),
    settings: path.join(root, "settings.json"),
    adapters: path.join(root, "platform-adapters"),
  };
}

function audit(event, outcome, details = {}, { required = false } = {}) {
  try {
    const destination = appendAuditEvent(managerPaths().root, event, outcome, details, {
      sessionId: state.auditSessionId,
    });
    state.auditWarning = null;
    return destination;
  } catch (error) {
    state.auditWarning = `审计日志写入失败：${error.message}`;
    if (required) throw new Error(state.auditWarning);
    return null;
  }
}

function loadSettings() {
  const file = managerPaths().settings;
  if (!fs.existsSync(file)) return { portalUrl: "https://zshjiaotang.cn" };
  try {
    const value = JSON.parse(fs.readFileSync(file, "utf8"));
    return { portalUrl: value.portalUrl || "https://zshjiaotang.cn" };
  } catch {
    return { portalUrl: "https://zshjiaotang.cn" };
  }
}

function saveSettings(value) {
  const paths = managerPaths();
  fs.mkdirSync(paths.root, { recursive: true, mode: 0o700 });
  fs.writeFileSync(paths.settings, `${JSON.stringify({
    portalUrl: value.portalUrl,
  }, null, 2)}\n`, { mode: 0o600 });
}

function securityConfig() {
  return JSON.parse(fs.readFileSync(securityConfigPath, "utf8"));
}

function currentPlatformConfig() {
  if (!state.platformConfig) {
    state.platformConfig = validatePlatformConfig(
      readPlatformConfig(platformConfigPath),
      app.getVersion(),
    );
    state.platformConfigSource = "built-in";
  }
  return state.platformConfig;
}

function currentAdapterMarker() {
  const config = currentPlatformConfig();
  return {
    sequence: config.sequence,
    revision: config.revision,
  };
}

function assertAdapterPlanCurrent(marker) {
  const current = currentAdapterMarker();
  if (
    !marker
    || marker.sequence !== current.sequence
    || marker.revision !== current.revision
  ) {
    throw new Error("平台适配器已更新，安装计划已失效，请重新扫描并生成计划");
  }
}

function auditedMutation(event, details, operation) {
  audit(event, "started", details, { required: true });
  let operationCompleted = false;
  try {
    const result = operation();
    operationCompleted = true;
    audit(event, "completed", { ...details, result }, { required: true });
    return result;
  } catch (error) {
    audit(event, "failed", {
      ...details,
      operationCompleted,
      message: error.message,
    });
    if (operationCompleted) {
      throw new Error(`操作已经完成，但审计日志收尾失败：${error.message}`);
    }
    throw error;
  }
}

function initializePlatformAdapters() {
  const builtIn = currentPlatformConfig();
  const cached = loadLatestAdapterBundle(
    managerPaths().adapters,
    securityConfig(),
    app.getVersion(),
    process.platform,
    builtIn.sequence,
  );
  if (cached?.config) {
    state.platformConfig = cached.config;
    state.platformConfigSource = "verified-cache";
    audit("platform-adapter-load", "verified-cache", {
      revision: cached.config.revision,
      sequence: cached.config.sequence,
      sha256: cached.verification.sha256,
    });
    return;
  }
  audit("platform-adapter-load", "built-in-fallback", {
    revision: state.platformConfig.revision,
    sequence: state.platformConfig.sequence,
    cacheError: cached?.error || null,
  });
}

function assertAllowedPortal(portalUrl) {
  const normalized = normalizedPortalUrl(portalUrl);
  const localDevelopment = ["localhost", "127.0.0.1"].includes(normalized.hostname);
  const allowed = new Set(securityConfig().allowed_download_origins || []);
  if (!localDevelopment && !allowed.has(normalized.origin)) {
    throw new Error(`门户来源未列入应用信任清单：${normalized.origin}`);
  }
  return normalized.toString().replace(/\/$/, "");
}

function platformSnapshot() {
  const startedAt = Date.now();
  const platformConfig = currentPlatformConfig();
  const platforms = detectPlatforms(platformConfig);
  const catalog = readCatalog(catalogPath);
  const registry = loadRegistry(managerPaths().registry);
  return {
    os: {
      platform: process.platform,
      arch: process.arch,
      version: os.release(),
    },
    product: {
      name: catalog.product,
      releaseTag: catalog.releaseTag,
      skillCount: catalog.count,
      managerVersion: app.getVersion(),
    },
    platforms,
    targets: uniqueManagedTargets(platforms.filter((item) => item.detected)),
    compatibility: buildCompatibilityReport(catalog, platforms),
    registry,
    adapters: {
      sequence: platformConfig.sequence,
      revision: platformConfig.revision,
      publishedAt: platformConfig.published_at,
      source: state.platformConfigSource,
    },
    scan: {
      scannedAt: new Date().toISOString(),
      durationMs: Date.now() - startedAt,
      searchedPlatformCount: platforms.length,
      detectedPlatformCount: platforms.filter((item) => item.detected).length,
    },
    audit: {
      status: state.auditWarning ? "warning" : "ready",
      warning: state.auditWarning,
      directory: path.join(managerPaths().root, "audit"),
    },
  };
}

function createWindow() {
  const window = new BrowserWindow({
    width: 1440,
    height: 940,
    minWidth: 1080,
    minHeight: 720,
    title: "焦糖 Skills 管理器",
    backgroundColor: "#0d0f0f",
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
    },
  });
  window.removeMenu();
  window.loadFile(path.join(APP_ROOT, "renderer", "index.html"));
  window.once("ready-to-show", () => window.show());
  window.webContents.setWindowOpenHandler(({ url }) => {
    const allowed = normalizedPortalUrl(loadSettings().portalUrl);
    const candidate = new URL(url);
    if (candidate.origin === allowed.origin) shell.openExternal(url);
    return { action: "deny" };
  });
  window.webContents.on("will-navigate", (event, url) => {
    if (!url.startsWith("file:")) event.preventDefault();
  });
}

ipcMain.handle("app:overview", () => ({
  ...platformSnapshot(),
  settings: loadSettings(),
  appTrust: {
    ...inspectApplicationTrust(process.execPath),
    distributionMode: securityConfig().application_distribution.mode,
    publisherSignature: securityConfig().application_distribution.publisher_signature,
  },
}));

ipcMain.handle("platforms:scan", () => {
  audit("platform-scan", "started", {
    revision: currentPlatformConfig().revision,
    sequence: currentPlatformConfig().sequence,
  });
  try {
    const snapshot = platformSnapshot();
    audit("platform-scan", "completed", {
      revision: snapshot.adapters.revision,
      sequence: snapshot.adapters.sequence,
      source: snapshot.adapters.source,
      durationMs: snapshot.scan.durationMs,
      searchedPlatformCount: snapshot.scan.searchedPlatformCount,
      detectedPlatformCount: snapshot.scan.detectedPlatformCount,
      detectedPlatformIds: snapshot.platforms.filter((item) => item.detected).map((item) => item.id),
    });
    return {
      platforms: snapshot.platforms,
      targets: snapshot.targets,
      compatibility: snapshot.compatibility,
      registry: snapshot.registry,
      adapters: snapshot.adapters,
      scan: snapshot.scan,
      audit: {
        status: state.auditWarning ? "warning" : "ready",
        warning: state.auditWarning,
      },
    };
  } catch (error) {
    audit("platform-scan", "failed", { message: error.message });
    throw error;
  }
});

ipcMain.handle("portal:connect", async (_event, payload) => {
  const authMode = payload.authMode === "admin-token" ? "admin-token" : "existing-device";
  audit("portal-connect", "started", { authMode });
  try {
    const portalUrl = assertAllowedPortal(payload.portalUrl);
    state.accessToken = authMode === "admin-token" ? String(payload.accessToken || "") : "";
    state.deviceCredentials = authMode === "existing-device"
      ? loadExistingDeviceCredentials()
      : null;
    if (authMode === "admin-token" && !state.accessToken) {
      throw new Error("管理员访问令牌不能为空");
    }
    const channels = await fetchChannels({
      portalUrl,
      accessToken: state.accessToken,
      credentials: state.deviceCredentials,
    });
    let adapterUpdate;
    try {
      const bundle = await fetchPlatformAdapterBundle({
        portalUrl,
        accessToken: state.accessToken,
        credentials: state.deviceCredentials,
        securityConfig: securityConfig(),
      });
      const verified = parseAdapterBundle({
        ...bundle,
        securityConfig: securityConfig(),
        managerVersion: app.getVersion(),
      });
      assertAdapterNotDowngraded(verified.config, currentPlatformConfig());
      storeAdapterBundle(managerPaths().adapters, verified);
      state.platformConfig = verified.config;
      state.platformConfigSource = "verified-remote";
      state.installPlans.clear();
      state.installBatches.clear();
      adapterUpdate = {
        status: "verified",
        sequence: verified.config.sequence,
        revision: verified.config.revision,
        sha256: verified.verification.sha256,
      };
      audit("platform-adapter-update", "verified", adapterUpdate);
    } catch (error) {
      adapterUpdate = {
        status: "built-in-fallback",
        sequence: currentPlatformConfig().sequence,
        revision: currentPlatformConfig().revision,
        detail: error.message,
      };
      audit("platform-adapter-update", "built-in-fallback", adapterUpdate);
    }
    state.channels = channels;
    saveSettings({ portalUrl });
    audit("portal-connect", "completed", {
      authMode,
      channelCount: channels.channels.length,
      adapterStatus: adapterUpdate.status,
      adapterSequence: adapterUpdate.sequence,
      adapterRevision: adapterUpdate.revision,
    });
    return { ...channels, platform_adapter: adapterUpdate };
  } catch (error) {
    audit("portal-connect", "failed", { authMode, message: error.message });
    throw error;
  }
});

ipcMain.handle("portal:disconnect", () => {
  state.accessToken = "";
  state.deviceCredentials = null;
  state.channels = null;
  state.verifiedArtifacts.clear();
  return { status: "disconnected" };
});

ipcMain.handle("directory:choose", async () => {
  const result = await dialog.showOpenDialog({
    title: "选择 Agent 的 Skills 目录",
    properties: ["openDirectory", "createDirectory"],
  });
  return result.canceled ? null : result.filePaths[0];
});

ipcMain.handle("artifact:download-verify", async (_event, payload) => {
  audit("artifact-verify", "started", { channelId: payload.channelId });
  try {
    if (!state.channels) throw new Error("请先连接发布门户");
    const channel = state.channels.channels.find((item) => item.id === payload.channelId);
    if (!channel?.available) throw new Error("当前发布通道没有可下载版本");
    const settings = loadSettings();
    const cache = managerPaths().cache;
    const fileName = path.basename(
      channel.file_name || `jiaotang-${channel.id}-${channel.version}.zip`,
    );
    const destination = path.join(cache, "downloads", fileName);
    const downloaded = await downloadArtifact({
      portalUrl: settings.portalUrl,
      accessToken: state.accessToken,
      credentials: state.deviceCredentials,
      channel,
      destination,
    });
    const verification = verifySkillArchive({
      archivePath: destination,
      expectedSha256: channel.sha256,
      securityConfig: securityConfig(),
    });
    const artifact = { channel, downloaded, verification };
    state.verifiedArtifacts.set(channel.id, artifact);
    audit("artifact-verify", "verified", {
      channelId: channel.id,
      version: channel.version,
      sha256: verification.archiveSha256,
      bytes: downloaded.bytes,
      verifiedFiles: verification.verifiedFiles,
    });
    return artifact;
  } catch (error) {
    audit("artifact-verify", "failed", {
      channelId: payload.channelId,
      message: error.message,
    });
    throw error;
  }
});

ipcMain.handle("install:plan-generic", (_event, payload) => {
  const artifact = state.verifiedArtifacts.get("generic");
  if (!artifact) throw new Error("请先下载并验证通用 Skills 包");
  const plan = planGenericInstall({
    archivePath: artifact.downloaded.path,
    targetRoot: payload.targetRoot,
    registryPath: managerPaths().registry,
    platformIds: payload.platformIds || [],
    verification: artifact.verification,
  });
  plan.adapter = currentAdapterMarker();
  const planId = crypto.randomUUID();
  state.installPlans.set(planId, plan);
  return { ...plan, planId };
});

ipcMain.handle("install:execute-generic", (_event, payload) => {
  if (payload.confirmation !== "INSTALL") throw new Error("安装确认无效");
  const plan = state.installPlans.get(payload.planId);
  const artifact = state.verifiedArtifacts.get("generic");
  if (!plan || !artifact) throw new Error("安装计划已失效，请重新生成");
  assertAdapterPlanCurrent(plan.adapter);
  const result = auditedMutation("platform-import", {
    mode: "single",
    targetRoot: plan.targetRoot,
    platformIds: plan.platformIds,
    releaseTag: plan.releaseTag,
    adapter: plan.adapter,
  }, () => executeGenericInstall({
      plan,
      registryPath: managerPaths().registry,
      artifactSha256: artifact.verification.archiveSha256,
    }));
  state.installPlans.delete(payload.planId);
  return result;
});

ipcMain.handle("install:plan-detected", () => {
  const artifact = state.verifiedArtifacts.get("generic");
  if (!artifact) throw new Error("请先下载并验证通用 Skills 包");
  const adapter = currentAdapterMarker();
  const platforms = detectPlatforms(currentPlatformConfig());
  const targets = automaticDetectedTargets(platforms);
  if (!targets.length) throw new Error("没有发现可自动安装的 Agent 平台");
  const plans = targets.map((target) => planGenericInstall({
    archivePath: artifact.downloaded.path,
    targetRoot: target.targetRoot,
    registryPath: managerPaths().registry,
    platformIds: target.platformIds,
    verification: artifact.verification,
  }));
  for (const plan of plans) plan.adapter = adapter;
  const batchId = crypto.randomUUID();
  state.installBatches.set(batchId, { plans, adapter });
  return {
    batchId,
    targets: plans.map((plan) => ({
      targetRoot: plan.targetRoot,
      platformIds: plan.platformIds,
      skillCount: plan.skillCount,
      additions: plan.additions.length,
      replacements: plan.replacements.length,
      conflicts: plan.conflicts,
    })),
  };
});

ipcMain.handle("install:execute-detected", (_event, payload) => {
  if (payload.confirmation !== "INSTALL_ALL") throw new Error("批量安装确认无效");
  const batch = state.installBatches.get(payload.batchId);
  const artifact = state.verifiedArtifacts.get("generic");
  if (!batch || !artifact) throw new Error("批量安装计划已失效，请重新生成");
  const { plans, adapter } = batch;
  assertAdapterPlanCurrent(adapter);
  if (plans.some((plan) => plan.conflicts.length)) {
    throw new Error("存在未登记的同名目录，已阻止批量覆盖");
  }
  const results = auditedMutation("platform-import", {
    mode: "detected-batch",
    targetCount: plans.length,
    targets: plans.map((plan) => ({
      targetRoot: plan.targetRoot,
      platformIds: plan.platformIds,
    })),
    adapter,
  }, () => plans.map((plan) => executeGenericInstall({
      plan,
      registryPath: managerPaths().registry,
      artifactSha256: artifact.verification.archiveSha256,
    })));
  state.installBatches.delete(payload.batchId);
  return { results };
});

ipcMain.handle("install:rollback", (_event, payload) => {
  if (payload.confirmation !== "ROLLBACK") throw new Error("回滚确认无效");
  const result = auditedMutation("platform-rollback", {
    targetRoot: payload.targetRoot,
  }, () => rollbackLatest({
      targetRoot: payload.targetRoot,
      registryPath: managerPaths().registry,
    }));
  return result;
});

ipcMain.handle("path:reveal", async (_event, value) => {
  if (!value || typeof value !== "string") throw new Error("路径无效");
  return shell.openPath(path.resolve(value));
});

ipcMain.handle("path:show-item", (_event, value) => {
  if (!value || typeof value !== "string") throw new Error("路径无效");
  shell.showItemInFolder(path.resolve(value));
  return { status: "shown", path: path.resolve(value) };
});

ipcMain.handle("audit:reveal", async () => {
  const directory = path.join(managerPaths().root, "audit");
  fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
  const result = await shell.openPath(directory);
  return { status: result ? "failed" : "shown", path: directory, detail: result || null };
});

app.whenReady().then(() => {
  initializePlatformAdapters();
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  state.accessToken = "";
  state.deviceCredentials = null;
  if (process.platform !== "darwin") app.quit();
});
