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
const { readPlatformConfig, detectPlatforms, uniqueManagedTargets } = require("../core/platforms.cjs");
const { readCatalog, buildCompatibilityReport } = require("../core/compatibility.cjs");
const { fetchChannels, downloadArtifact, normalizedPortalUrl } = require("../core/portal-client.cjs");
const { loadExistingDeviceCredentials } = require("../core/device-auth.cjs");
const { inspectApplicationTrust, verifySkillArchive } = require("../core/security.cjs");
const { loadRegistry } = require("../core/registry.cjs");
const {
  planGenericInstall,
  executeGenericInstall,
  rollbackLatest,
} = require("../core/update-engine.cjs");
const {
  stageFixedInstaller,
  launchFixedInstaller,
  workBuddyRunning,
} = require("../core/fixed-installer.cjs");

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
};

function managerPaths() {
  const root = app.getPath("userData");
  return {
    root,
    cache: path.join(root, "cache"),
    registry: path.join(root, "registry.json"),
    settings: path.join(root, "settings.json"),
  };
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
  const platformConfig = readPlatformConfig(platformConfigPath);
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
    targets: uniqueManagedTargets(platforms),
    compatibility: buildCompatibilityReport(catalog, platforms),
    registry,
    workBuddyRunning: workBuddyRunning(),
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
  appTrust: inspectApplicationTrust(process.execPath),
}));

ipcMain.handle("portal:connect", async (_event, payload) => {
  const portalUrl = assertAllowedPortal(payload.portalUrl);
  const authMode = payload.authMode === "admin-token" ? "admin-token" : "existing-device";
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
  state.channels = channels;
  saveSettings({ portalUrl });
  return channels;
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
  return artifact;
});

ipcMain.handle("install:plan-generic", (_event, payload) => {
  const artifact = state.verifiedArtifacts.get("generic");
  if (!artifact) throw new Error("请先下载并验证通用 Skills 包");
  const plan = planGenericInstall({
    archivePath: artifact.downloaded.path,
    targetRoot: payload.targetRoot,
    registryPath: managerPaths().registry,
    platformIds: payload.platformIds || [],
  });
  const planId = crypto.randomUUID();
  state.installPlans.set(planId, plan);
  return { ...plan, planId };
});

ipcMain.handle("install:execute-generic", (_event, payload) => {
  if (payload.confirmation !== "INSTALL") throw new Error("安装确认无效");
  const plan = state.installPlans.get(payload.planId);
  const artifact = state.verifiedArtifacts.get("generic");
  if (!plan || !artifact) throw new Error("安装计划已失效，请重新生成");
  const result = executeGenericInstall({
    plan,
    registryPath: managerPaths().registry,
    artifactSha256: artifact.verification.archiveSha256,
  });
  state.installPlans.delete(payload.planId);
  return result;
});

ipcMain.handle("install:stage-workbuddy", (_event, payload) => {
  const channelId = payload.channelId;
  const artifact = state.verifiedArtifacts.get(channelId);
  if (!artifact || !["macos", "windows"].includes(channelId)) {
    throw new Error("请先下载并验证当前系统对应的 WorkBuddy 包");
  }
  return stageFixedInstaller({
    archivePath: artifact.downloaded.path,
    cacheRoot: managerPaths().cache,
  });
});

ipcMain.handle("install:launch-workbuddy", (_event, payload) => {
  if (payload.confirmation !== "RUN_FIXED_INSTALLER") throw new Error("安装确认无效");
  return launchFixedInstaller(payload.staged);
});

ipcMain.handle("install:rollback", (_event, payload) => {
  if (payload.confirmation !== "ROLLBACK") throw new Error("回滚确认无效");
  return rollbackLatest({
    targetRoot: payload.targetRoot,
    registryPath: managerPaths().registry,
  });
});

ipcMain.handle("path:reveal", async (_event, value) => {
  if (!value || typeof value !== "string") throw new Error("路径无效");
  return shell.openPath(path.resolve(value));
});

app.whenReady().then(() => {
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
