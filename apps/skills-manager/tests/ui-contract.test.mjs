import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

test("desktop UI exposes explicit Agent scan and per-platform import actions", () => {
  const html = fs.readFileSync(path.join(appRoot, "renderer", "index.html"), "utf8");
  const renderer = fs.readFileSync(path.join(appRoot, "renderer", "app.js"), "utf8");
  const preload = fs.readFileSync(path.join(appRoot, "electron", "preload.cjs"), "utf8");
  const main = fs.readFileSync(path.join(appRoot, "electron", "main.cjs"), "utf8");

  assert.match(html, /id="platform-rescan-button"[\s\S]*扫描本机 Agent/);
  assert.match(html, /data-platform-filter="all"/);
  assert.match(html, /data-platform-filter="detected"/);
  assert.match(html, /data-platform-filter="automatic"/);
  assert.match(renderer, /data-platform-action="generic"[\s\S]*一键导入/);
  assert.match(renderer, /data-platform-action="workbuddy"[\s\S]*准备安装/);
  assert.match(renderer, /data-platform-action="guided"[\s\S]*准备导入/);
  assert.match(preload, /scanPlatforms: \(\) => ipcRenderer\.invoke\("platforms:scan"\)/);
  assert.match(main, /ipcMain\.handle\("platforms:scan"/);
  assert.match(preload, /revealAuditLog: \(\) => ipcRenderer\.invoke\("audit:reveal"\)/);
  assert.match(main, /ipcMain\.handle\("audit:reveal"/);
});

test("mainstream platform catalog remains visible even when clients are absent", () => {
  const config = JSON.parse(
    fs.readFileSync(path.join(appRoot, "config", "platforms.json"), "utf8"),
  );
  assert.deepEqual(
    config.platforms.map((platform) => platform.id),
    [
      "workbuddy",
      "trae",
      "kimi-code",
      "lingma",
      "qoder",
      "cherry-studio",
    ],
  );
  for (const platform of config.platforms) {
    assert.ok(platform.darwin?.applications?.length, `${platform.id} 缺少 macOS 扫描入口`);
    assert.ok(platform.win32?.applications?.length, `${platform.id} 缺少 Windows 扫描入口`);
    assert.ok(platform.install_mode, `${platform.id} 缺少导入模式`);
  }
});

test("remote adapters are signed data updates with a built-in fallback", () => {
  const security = JSON.parse(
    fs.readFileSync(path.join(appRoot, "config", "security.json"), "utf8"),
  );
  const main = fs.readFileSync(path.join(appRoot, "electron", "main.cjs"), "utf8");
  const adapterModule = fs.readFileSync(
    path.join(appRoot, "core", "platform-adapters.cjs"),
    "utf8",
  );
  assert.equal(
    security.platform_adapters.namespace,
    "jiaotang-skills-manager-platform-adapters",
  );
  assert.match(main, /fetchPlatformAdapterBundle/);
  assert.match(main, /built-in-fallback/);
  assert.match(main, /detectPlatforms\(currentPlatformConfig\(\)\)/);
  assert.match(main, /assertAdapterPlanCurrent/);
  assert.match(adapterModule, /verifyDetachedOpenSshPayload/);
  assert.doesNotMatch(adapterModule, /exec(?:File)?Sync|shell\.openExternal|child_process/);
});

test("desktop release metadata reports manager 0.2.0 and local authorization", () => {
  const packageMetadata = JSON.parse(
    fs.readFileSync(path.join(appRoot, "package.json"), "utf8"),
  );
  const renderer = fs.readFileSync(path.join(appRoot, "renderer", "app.js"), "utf8");
  const html = fs.readFileSync(path.join(appRoot, "renderer", "index.html"), "utf8");
  const portalClient = fs.readFileSync(path.join(appRoot, "core", "portal-client.cjs"), "utf8");

  assert.equal(packageMetadata.version, "0.2.0");
  assert.match(renderer, /managerVersion: "0\.2\.0"/);
  assert.match(renderer, /未建立系统发布者身份/);
  assert.match(html, /unsigned-local/);
  assert.match(portalClient, /jiaotang-skills-manager\/0\.2/);
  assert.match(portalClient, /AbortSignal\.timeout/);
});
