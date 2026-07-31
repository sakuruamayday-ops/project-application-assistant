#!/usr/bin/env node
import assert from "node:assert/strict";
import {mkdtemp, rename} from "node:fs/promises";
import {homedir, tmpdir} from "node:os";
import {join} from "node:path";
import {spawn} from "node:child_process";
import {createRequire} from "node:module";
import {setTimeout as delay} from "node:timers/promises";

const require = createRequire(import.meta.url);
const {chromium} = require("playwright");

const routes = new Map([
  ["/portal", "overview"],
  ["/cockpit", "cockpit"],
  ["/access", "api-access"],
  ["/skills", "skills"],
  ["/feedback", "feedback"],
  ["/admin/operations", "health-admin"],
  ["/admin/knowledge-update", "knowledge-admin"],
  ["/admin/releases", "skill-admin"],
  ["/admin/members", "members"],
]);

const port = 18765;
const baseUrl = `http://127.0.0.1:${port}`;
const dataDir = await mkdtemp(join(tmpdir(), "jiaotang-browser-routes-"));
const python = process.env.JIAOTANG_BROWSER_TEST_PYTHON || ".venv/bin/python";
const server = spawn(python, ["tests/browser_route_server.py"], {
  env: {
    ...process.env,
    JIAOTANG_BROWSER_TEST_DATA: dataDir,
    JIAOTANG_BROWSER_TEST_PORT: String(port),
  },
  stdio: ["ignore", "pipe", "pipe"],
});

let serverLog = "";
server.stdout.on("data", (chunk) => { serverLog += chunk; });
server.stderr.on("data", (chunk) => { serverLog += chunk; });

async function waitForServer() {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    try {
      const response = await fetch(`${baseUrl}/setup`);
      if (response.ok) return;
    } catch {
      // Server is still starting.
    }
    await delay(125);
  }
  throw new Error(`浏览器测试服务启动超时\n${serverLog}`);
}

let browser;
try {
  await waitForServer();
  browser = await chromium.launch({headless: true});
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
  await page.goto(`${baseUrl}/setup`);
  await page.fill('input[name="setup_key"]', "browser-route-setup");
  await page.fill('input[name="username"]', "route-admin");
  await page.fill('input[name="password"]', "browser-route-password-123");
  await Promise.all([
    page.waitForURL("**/login?initialized=1"),
    page.click('button[type="submit"]'),
  ]);
  await page.fill('input[name="username"]', "route-admin");
  await page.fill('input[name="password"]', "browser-route-password-123");
  await Promise.all([
    page.waitForURL("**/portal"),
    page.click('button[type="submit"]'),
  ]);

  for (const [legacyPath, sectionId] of routes) {
    const response = await page.goto(`${baseUrl}${legacyPath}`, {waitUntil: "networkidle"});
    assert.equal(response?.status(), 200, `${legacyPath} 应返回 200`);
    await page.waitForURL(`**/portal#${sectionId}`);
    await page.waitForFunction((expectedId) => {
      const section = document.getElementById(expectedId);
      const activeLink = document.querySelector(`[data-section-link="${expectedId}"].active`);
      const rect = section?.getBoundingClientRect();
      return Boolean(
        activeLink
        && rect
        && rect.bottom > 0
        && rect.top < window.innerHeight,
      );
    }, sectionId);
    const state = await page.evaluate((expectedId) => {
      const section = document.getElementById(expectedId);
      const activeLink = document.querySelector(`[data-section-link="${expectedId}"].active`);
      const rect = section?.getBoundingClientRect();
      return {
        exists: Boolean(section),
        active: Boolean(activeLink),
        visible: Boolean(rect && rect.bottom > 0 && rect.top < window.innerHeight),
      };
    }, sectionId);
    assert.equal(state.exists, true, `${legacyPath} 缺少 #${sectionId}`);
    assert.equal(state.visible, true, `${legacyPath} 未滚动到 #${sectionId}`);
    assert.equal(state.active, true, `${legacyPath} 未激活对应导航`);
    if (legacyPath === "/admin/operations") {
      assert.equal(await page.locator('a[href="/admin/health/deploy-gate"]').isVisible(), true, "健康看板应展示 Skills 部署门禁");
    }
  }
  await page.goto(`${baseUrl}/admin/health/deploy-gate`, {waitUntil: "networkidle"});
  assert.equal(await page.locator(".deployment-gate-boundary article").count(), 2, "部署门禁详情应明确展示两类门禁边界");
  const desktopWidth = await page.evaluate(() => ({document: document.documentElement.scrollWidth, viewport: window.innerWidth}));
  assert.equal(desktopWidth.document, desktopWidth.viewport, "部署门禁详情桌面端不应横向溢出");
  await page.setViewportSize({width: 390, height: 844});
  await page.reload({waitUntil: "networkidle"});
  const mobileWidth = await page.evaluate(() => ({document: document.documentElement.scrollWidth, viewport: window.innerWidth}));
  assert.equal(mobileWidth.document, mobileWidth.viewport, "部署门禁详情移动端不应横向溢出");
  await page.goto(`${baseUrl}/portal?mobile-layout-regression=1`, {waitUntil: "networkidle"});
  await page.waitForTimeout(850);
  const mobilePortalLayout = await page.evaluate(() => {
    const sidebar = document.querySelector(".sidebar")?.getBoundingClientRect();
    const topbar = document.querySelector(".topbar")?.getBoundingClientRect();
    const content = document.querySelector(".content-wrap")?.getBoundingClientRect();
    return {
      sidebarBottom: Math.round(sidebar?.bottom || 0),
      topbarTop: Math.round(topbar?.top || 0),
      topbarBottom: Math.round(topbar?.bottom || 0),
      contentTop: Math.round(content?.top || 0),
    };
  });
  assert.ok(
    mobilePortalLayout.topbarTop >= mobilePortalLayout.sidebarBottom - 1,
    `移动端账号栏不得与横向导航重叠：${JSON.stringify(mobilePortalLayout)}`,
  );
  assert.ok(
    mobilePortalLayout.contentTop >= mobilePortalLayout.topbarBottom - 1,
    `移动端正文不得被账号栏遮挡：${JSON.stringify(mobilePortalLayout)}`,
  );
  await page.goto(`${baseUrl}/cockpit`, {waitUntil: "networkidle"});
  await page.waitForTimeout(850);
  const mobileTargetLayout = await page.evaluate(() => {
    const sidebar = document.querySelector(".sidebar")?.getBoundingClientRect();
    const section = document.querySelector("#cockpit")?.getBoundingClientRect();
    return {
      sidebarBottom: Math.round(sidebar?.bottom || 0),
      sectionTop: Math.round(section?.top || 0),
      sectionBottom: Math.round(section?.bottom || 0),
    };
  });
  assert.ok(
    mobileTargetLayout.sectionTop >= mobileTargetLayout.sidebarBottom - 1,
    `移动端目标章节不得被横向导航遮挡：${JSON.stringify(mobileTargetLayout)}`,
  );
  assert.ok(
    mobileTargetLayout.sectionTop < 844 && mobileTargetLayout.sectionBottom > 0,
    `移动端目标章节必须进入可视区：${JSON.stringify(mobileTargetLayout)}`,
  );
  console.log(`PASS browser route regression: ${routes.size} legacy routes`);
} finally {
  if (browser) await browser.close();
  server.kill("SIGTERM");
  await Promise.race([
    new Promise((resolve) => server.once("exit", resolve)),
    delay(2000),
  ]);
  const trashedDataDir = join(
    homedir(),
    ".Trash",
    `jiaotang-browser-routes-${Date.now()}`,
  );
  try {
    await rename(dataDir, trashedDataDir);
  } catch {
    console.warn(`浏览器测试数据保留在 ${dataDir}`);
  }
}
