#!/usr/bin/env node
import assert from "node:assert/strict";
import {mkdtemp} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {spawn} from "node:child_process";
import {createRequire} from "node:module";
import {setTimeout as delay} from "node:timers/promises";

const require = createRequire(import.meta.url);
const {chromium} = require("playwright");
const port = 18767;
const baseUrl = `http://127.0.0.1:${port}`;
const dataDir = await mkdtemp(join(tmpdir(), "jiaotang-install-flow-"));
const python = process.env.JIAOTANG_BROWSER_TEST_PYTHON || ".venv/bin/python";
const server = spawn(python, ["tests/browser_route_server.py"], {
  env: {
    ...process.env,
    JIAOTANG_BROWSER_TEST_DATA: dataDir,
    JIAOTANG_BROWSER_TEST_PORT: String(port),
    JIAOTANG_BROWSER_TEST_SKILL_RELEASE_FIXTURE: "1",
  },
  stdio: ["ignore", "pipe", "pipe"],
});
let serverLog = "";
server.stdout.on("data", (chunk) => { serverLog += chunk; });
server.stderr.on("data", (chunk) => { serverLog += chunk; });

async function waitForServer() {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    try {
      if ((await fetch(`${baseUrl}/setup`)).ok) return;
    } catch {}
    await delay(125);
  }
  throw new Error(`安装流程 UX 测试服务启动超时\n${serverLog}`);
}

let browser;
try {
  await waitForServer();
  browser = await chromium.launch({
    headless: true,
    executablePath: process.env.JIAOTANG_BROWSER_EXECUTABLE || undefined,
  });
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
  const errors = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(error.message));

  await page.goto(`${baseUrl}/setup`);
  await page.fill('input[name="setup_key"]', "browser-route-setup");
  await page.fill('input[name="username"]', "install-admin");
  await page.fill('input[name="password"]', "install-route-password-123");
  await Promise.all([
    page.waitForURL("**/login?initialized=1"),
    page.click('button[type="submit"]'),
  ]);
  await page.fill('input[name="username"]', "install-admin");
  await page.fill('input[name="password"]', "install-route-password-123");
  await Promise.all([
    page.waitForURL("**/portal"),
    page.click('button[type="submit"]'),
  ]);
  await page.goto(`${baseUrl}/skills`, {waitUntil: "networkidle"});
  await page.locator('[data-skill-tab-target="install"]').first().click();
  const installPane = page.locator('[data-skill-section-pane="install"]');
  assert.equal(await installPane.isVisible(), true, "安装与设备页必须可见");
  const bindingButton = installPane.locator("[data-copy-agent-binding]");
  assert.equal(await bindingButton.count(), 1, "必须有独立的第三步绑定按钮");
  assert.equal(await bindingButton.isHidden(), true, "第二步授权前第三步必须隐藏");
  const desktop = await page.evaluate(() => ({
    documentWidth: document.documentElement.scrollWidth,
    viewportWidth: window.innerWidth,
    columns: getComputedStyle(document.querySelector(".skill-install-grid")).gridTemplateColumns,
    label: document.querySelector("[data-copy-agent-binding]")?.textContent || "",
  }));
  assert.equal(desktop.documentWidth, desktop.viewportWidth, "桌面安装流程不得横向溢出");
  assert.equal(desktop.columns.split(" ").length, 2, "桌面安装与验收应为双栏");
  assert.match(desktop.label, /第三步.*bootstrap/s, "第三步按钮必须明确标注 bootstrap");
  if (process.env.JIAOTANG_INSTALL_DESKTOP_SCREENSHOT) {
    await page.screenshot({path: process.env.JIAOTANG_INSTALL_DESKTOP_SCREENSHOT, fullPage: true});
  }

  await page.setViewportSize({width: 390, height: 844});
  await page.reload({waitUntil: "networkidle"});
  await page.locator('[data-skill-tab-target="install"]').first().click();
  const mobile = await page.evaluate(() => ({
    documentWidth: document.documentElement.scrollWidth,
    viewportWidth: window.innerWidth,
    columns: getComputedStyle(document.querySelector(".skill-install-grid")).gridTemplateColumns,
  }));
  assert.equal(mobile.documentWidth, mobile.viewportWidth, "390px 安装流程不得横向溢出");
  assert.equal(mobile.columns.split(" ").length, 1, "移动端安装与验收应为单栏");
  if (process.env.JIAOTANG_INSTALL_MOBILE_SCREENSHOT) {
    await page.screenshot({path: process.env.JIAOTANG_INSTALL_MOBILE_SCREENSHOT, fullPage: true});
  }
  assert.deepEqual(errors, [], `页面不应产生控制台错误：${errors.join("；")}`);
  process.stdout.write("INSTALL_FLOW_UX_PASS\n");
} finally {
  await browser?.close();
  server.kill("SIGTERM");
}
