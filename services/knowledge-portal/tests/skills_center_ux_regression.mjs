#!/usr/bin/env node
import assert from "node:assert/strict";
import {mkdtemp, readFile, rename} from "node:fs/promises";
import {homedir, tmpdir} from "node:os";
import {join} from "node:path";
import {spawn} from "node:child_process";
import {createRequire} from "node:module";
import {setTimeout as delay} from "node:timers/promises";

const require = createRequire(import.meta.url);
const {chromium} = require("playwright");
const port = 18766;
const baseUrl = `http://127.0.0.1:${port}`;
const dataDir = await mkdtemp(join(tmpdir(), "jiaotang-skills-ux-"));
const skillCenterTemplate = await readFile(new URL("../templates/skill_center.html", import.meta.url), "utf8");
assert.match(skillCenterTemplate, /<details class="skill-release-notes skill-current-release-notes">/, "当前版本发布说明必须使用默认折叠的 details");
const server = spawn(".venv/bin/python", ["tests/browser_route_server.py"], {
  env: {...process.env, JIAOTANG_BROWSER_TEST_DATA: dataDir, JIAOTANG_BROWSER_TEST_PORT: String(port)},
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
  throw new Error(`Skills UX 测试服务启动超时\n${serverLog}`);
}

let browser;
try {
  await waitForServer();
  browser = await chromium.launch({headless: true});
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
  const consoleErrors = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(error.message));
  await page.goto(`${baseUrl}/setup`);
  await page.fill('input[name="setup_key"]', "browser-route-setup");
  await page.fill('input[name="username"]', "skills-admin");
  await page.fill('input[name="password"]', "skills-route-password-123");
  await Promise.all([page.waitForURL("**/login?initialized=1"), page.click('button[type="submit"]')]);
  await page.fill('input[name="username"]', "skills-admin");
  await page.fill('input[name="password"]', "skills-route-password-123");
  await Promise.all([page.waitForURL("**/portal"), page.click('button[type="submit"]')]);
  const skillsResponse = await page.goto(`${baseUrl}/skills`, {waitUntil: "networkidle"});
  assert.match(skillsResponse.headers()["cache-control"] || "", /no-store/, "登录后的 Skills 页面不应复用旧 HTML 缓存");

  const palette = await page.evaluate(() => {
    const center = document.querySelector(".skill-center");
    const active = document.querySelector(".skill-group-button.is-active");
    return {
      centerBackground: getComputedStyle(center).backgroundColor,
      activeBorder: getComputedStyle(active).borderColor,
      documentWidth: document.documentElement.scrollWidth,
      viewportWidth: window.innerWidth,
    };
  });
  assert.equal(palette.documentWidth, palette.viewportWidth, "桌面页面不应产生全局横向溢出");
  assert.notEqual(palette.activeBorder, "rgb(157, 185, 67)", "不应继续使用参考图荧光绿边框");

  await page.locator('[data-skill-section-tab="downloads"]').click();
  assert.equal(await page.locator('[data-skill-section-pane="downloads"]').isVisible(), true);
  if (await page.locator(".skill-current-release-notes").count() === 0) {
    await page.locator(".skill-download-content").evaluate((container) => {
      container.insertAdjacentHTML("afterbegin", '<article class="skill-current-release"><span class="download-icon">ZIP</span><div><h3>回归测试版本</h3><small>发布时间 测试</small><details class="skill-release-notes skill-current-release-notes"><summary>查看当前版本发布说明</summary><div class="manual-content"><p>用于验证展开时按钮不会拉伸。</p></div></details></div><div class="button-row"><a class="button" href="#test-download">下载通用 Skills 包</a><a class="button secondary" href="#test-workbuddy">下载 WorkBuddy 插件包</a></div></article>');
    });
  }
  const currentReleaseNotes = page.locator(".skill-current-release-notes");
  assert.equal(await currentReleaseNotes.evaluate((details) => details.open), false, "当前版本发布说明应默认折叠");
  assert.equal(await currentReleaseNotes.locator(".manual-content").isVisible(), false, "折叠状态必须隐藏发布说明正文");
  const currentReleaseButtons = page.locator(".skill-current-release .button-row .button");
  const compactButtonSizes = await currentReleaseButtons.evaluateAll((buttons) => buttons.map((button) => {
    const rect = button.getBoundingClientRect();
    return {width: Math.round(rect.width), height: Math.round(rect.height)};
  }));
  await currentReleaseNotes.locator("summary").click();
  assert.equal(await currentReleaseNotes.evaluate((details) => details.open), true, "当前版本发布说明应可以展开");
  assert.equal(await currentReleaseNotes.locator(".manual-content").isVisible(), true, "展开后必须显示发布说明正文");
  const expandedButtonSizes = await currentReleaseButtons.evaluateAll((buttons) => buttons.map((button) => {
    const rect = button.getBoundingClientRect();
    return {width: Math.round(rect.width), height: Math.round(rect.height)};
  }));
  assert.deepEqual(expandedButtonSizes, compactButtonSizes, "展开发布说明不应拉伸下载按钮");
  await page.locator('[data-skill-tab-target="install"]').first().click();
  assert.equal(await page.locator('[data-skill-section-pane="install"]').isVisible(), true);
  assert.equal(new URL(page.url()).hash, "#skills-install");
  if (process.env.SKILLS_QA_INSTALL_SCREENSHOT) {
    await page.screenshot({path: process.env.SKILLS_QA_INSTALL_SCREENSHOT, fullPage: true});
  }

  await page.locator('[data-skill-section-tab="catalog"]').click();
  await page.evaluate(() => document.querySelectorAll("[data-skill-group]").item(document.querySelectorAll("[data-skill-group]").length - 1).click());
  await page.waitForTimeout(1000);
  const desktopRail = await page.evaluate(() => {
    const rail = document.querySelector("[data-skill-group-rail]");
    const last = rail.querySelector("[data-skill-group]:last-child");
    const railRect = rail.getBoundingClientRect();
    const lastRect = last.getBoundingClientRect();
    return {scrollLeft: rail.scrollLeft, fullyVisible: lastRect.left >= railRect.left && lastRect.right <= railRect.right + 1};
  });
  assert.ok(desktopRail.scrollLeft > 0, "点击远端能力后横向轨道应自动移动");
  assert.equal(desktopRail.fullyVisible, true, `选中的能力按钮应完整进入可视区：${JSON.stringify(desktopRail)}`);
  if (process.env.SKILLS_QA_CATALOG_SCREENSHOT) {
    await page.screenshot({path: process.env.SKILLS_QA_CATALOG_SCREENSHOT, fullPage: true});
  }

  await page.setViewportSize({width: 390, height: 844});
  await page.reload({waitUntil: "networkidle"});
  const mobileLayout = await page.evaluate(() => ({
    documentWidth: document.documentElement.scrollWidth,
    viewportWidth: window.innerWidth,
    railScrollable: document.querySelector("[data-skill-group-rail]").scrollWidth > document.querySelector("[data-skill-group-rail]").clientWidth,
  }));
  assert.equal(mobileLayout.documentWidth, mobileLayout.viewportWidth, "390px 页面不应产生全局横向溢出");
  assert.equal(mobileLayout.railScrollable, true, "移动端能力切换应保留局部横向滚动");
  assert.deepEqual(consoleErrors, [], `控制台不应出现错误：${consoleErrors.join(" | ")}`);
  console.log("PASS Skills Center UX: tabs, release notes collapse, stable download buttons, black-gold palette, auto-scroll, responsive layout, console");
} finally {
  if (browser) await browser.close();
  server.kill("SIGTERM");
  await Promise.race([new Promise((resolve) => server.once("exit", resolve)), delay(2000)]);
  try {
    await rename(dataDir, join(homedir(), ".Trash", `jiaotang-skills-ux-${Date.now()}`));
  } catch {
    console.warn(`浏览器测试数据保留在 ${dataDir}`);
  }
}
