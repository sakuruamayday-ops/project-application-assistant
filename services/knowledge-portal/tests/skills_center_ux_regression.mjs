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
assert.match(skillCenterTemplate, /latest_release\.workbuddy_platforms/, "下载区必须按 WorkBuddy 平台渲染");
assert.match(skillCenterTemplate, /platform\.download_url/, "每个平台必须使用独立下载入口");
assert.match(skillCenterTemplate, /下载通道独立维护/, "下载区必须解释各平台独立发布策略");
assert.doesNotMatch(skillCenterTemplate, /platform\.feedback_status|OIDC 签名证明|GitHub Job/, "下载区不应再展示平台确认状态");
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
    const hero = center.querySelector(".skill-hero");
    const tabs = center.querySelector(".skill-section-tabs");
    const catalogShell = center.querySelector(".skill-catalog-shell");
    const feedbackLink = document.querySelector('[data-section-link="feedback"]');
    const skillsLink = document.querySelector('[data-section-link="skills"]');
    return {
      centerBackground: getComputedStyle(center).backgroundColor,
      activeBorder: getComputedStyle(active).borderColor,
      documentWidth: document.documentElement.scrollWidth,
      viewportWidth: window.innerWidth,
      overviewBeforeTabs: hero.compareDocumentPosition(tabs) & Node.DOCUMENT_POSITION_FOLLOWING,
      catalogAfterTabs: tabs.compareDocumentPosition(catalogShell) & Node.DOCUMENT_POSITION_FOLLOWING,
      catalogIsContinuous: Boolean(
        catalogShell.querySelector(".skill-group-switcher")
        && catalogShell.querySelector(".skill-filter-bar")
        && catalogShell.querySelector(".skill-catalog-table"),
      ),
      feedbackBeforeSkills: Boolean(
        feedbackLink.compareDocumentPosition(skillsLink) & Node.DOCUMENT_POSITION_FOLLOWING
      ),
    };
  });
  assert.equal(palette.documentWidth, palette.viewportWidth, "桌面页面不应产生全局横向溢出");
  assert.notEqual(palette.activeBorder, "rgb(157, 185, 67)", "不应继续使用参考图荧光绿边框");
  assert.ok(palette.overviewBeforeTabs, "Skills 总览必须位于页面内容最上方");
  assert.ok(palette.catalogAfterTabs, "技能目录必须紧随页面页签");
  assert.equal(palette.catalogIsContinuous, true, "分类、筛选与技能清单必须位于同一连续工作区");
  assert.equal(palette.feedbackBeforeSkills, true, "左侧留言反馈必须位于 Skills 中心之前");
  await page.evaluate(() => {
    const shell = document.querySelector(".skill-catalog-shell");
    window.scrollTo({top: window.scrollY + shell.getBoundingClientRect().top + 520, behavior: "instant"});
  });
  await page.waitForTimeout(100);
  const stickyBarsState = await page.evaluate(() => {
    const center = document.querySelector(".skill-center");
    const switcher = document.querySelector(".skill-group-switcher");
    const controls = document.querySelector(".skill-catalog-controls");
    const firstGroup = document.querySelector(".skill-group-button");
    return {
      groupTop: Math.round(switcher.getBoundingClientRect().top),
      expectedGroupTop: Math.round(Number.parseFloat(getComputedStyle(center).getPropertyValue("--skill-groups-top"))),
      groupPosition: getComputedStyle(switcher).position,
      controlsTop: Math.round(controls.getBoundingClientRect().top),
      expectedControlsTop: Math.round(Number.parseFloat(getComputedStyle(center).getPropertyValue("--skill-controls-top"))),
      controlsPosition: getComputedStyle(controls).position,
      groupHeight: Math.round(firstGroup.getBoundingClientRect().height),
      controlsHeight: Math.round(controls.getBoundingClientRect().height),
    };
  });
  assert.equal(stickyBarsState.groupPosition, "sticky", "技能分类轨道必须启用吸顶");
  assert.ok(Math.abs(stickyBarsState.groupTop - stickyBarsState.expectedGroupTop) <= 2, `分类轨道应固定在页签下方：${JSON.stringify(stickyBarsState)}`);
  assert.equal(stickyBarsState.controlsPosition, "sticky", "技能清单栏必须启用吸顶");
  assert.ok(Math.abs(stickyBarsState.controlsTop - stickyBarsState.expectedControlsTop) <= 2, `技能清单栏应固定在分类轨道下方：${JSON.stringify(stickyBarsState)}`);
  assert.ok(stickyBarsState.groupHeight <= 62, `技能目录按钮高度应压缩至 62px 内：${JSON.stringify(stickyBarsState)}`);
  assert.ok(stickyBarsState.controlsHeight <= 72, `技能清单栏高度应压缩至 72px 内：${JSON.stringify(stickyBarsState)}`);
  const backToList = page.locator("[data-skill-back-to-list]");
  const backButtonLayout = await backToList.evaluate((button) => ({
    position: getComputedStyle(button).position,
    followsCatalog: Boolean(
      document.querySelector(".skill-catalog-shell").compareDocumentPosition(button)
      & Node.DOCUMENT_POSITION_FOLLOWING
    ),
  }));
  assert.notEqual(backButtonLayout.position, "fixed", "返回清单顶部按钮不得悬浮覆盖内容");
  assert.equal(backButtonLayout.followsCatalog, true, "返回清单顶部按钮必须单独位于清单最下方");
  await backToList.scrollIntoViewIfNeeded();
  assert.equal(await backToList.isVisible(), true, "进入技能长清单后必须显示返回清单顶部按钮");
  await backToList.click();
  await page.waitForFunction(() => {
    const center = document.querySelector(".skill-center");
    const shell = document.querySelector(".skill-catalog-shell");
    const tabs = document.querySelector(".skill-section-tabs");
    const tabsTop = Number.parseFloat(getComputedStyle(center).getPropertyValue("--skill-tabs-top")) || 0;
    return Math.abs(shell.getBoundingClientRect().top - tabsTop - tabs.getBoundingClientRect().height - 8) <= 3;
  });

  await page.locator('[data-skill-section-tab="downloads"]').click();
  assert.equal(await page.locator('[data-skill-section-pane="downloads"]').isVisible(), true);
  assert.equal(await page.locator(".skill-platform-card").count(), 3, "下载区必须呈现通用、macOS、Windows 三个入口");
  assert.equal(await page.locator(".skill-platform-card.is-macos").isVisible(), true);
  assert.equal(await page.locator(".skill-platform-card.is-windows").isVisible(), true);
  assert.equal(await page.locator(".skill-platform-status").count(), 1, "只保留通用正式包状态，不展示平台确认");
  if (process.env.SKILLS_QA_DOWNLOAD_SCREENSHOT) {
    await page.screenshot({path: process.env.SKILLS_QA_DOWNLOAD_SCREENSHOT, fullPage: true});
  }
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
    const currentGroup = document.querySelector("[data-skill-current-group]");
    const railRect = rail.getBoundingClientRect();
    const lastRect = last.getBoundingClientRect();
    return {
      scrollLeft: rail.scrollLeft,
      fullyVisible: lastRect.left >= railRect.left && lastRect.right <= railRect.right + 1,
      currentGroup: currentGroup.textContent.trim(),
      selectedGroup: last.dataset.skillGroupLabel,
    };
  });
  assert.ok(desktopRail.scrollLeft > 0, "点击远端能力后横向轨道应自动移动");
  assert.equal(desktopRail.fullyVisible, true, `选中的能力按钮应完整进入可视区：${JSON.stringify(desktopRail)}`);
  assert.equal(desktopRail.currentGroup, desktopRail.selectedGroup, "当前位置提示必须与选中分类一致");
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
  await page.evaluate(() => {
    const shell = document.querySelector(".skill-catalog-shell");
    window.scrollTo({top: window.scrollY + shell.getBoundingClientRect().top + 520, behavior: "instant"});
  });
  await page.waitForTimeout(100);
  const mobileStickyState = await page.evaluate(() => {
    const center = document.querySelector(".skill-center");
    const controls = document.querySelector(".skill-catalog-controls");
    return {
      actualTop: Math.round(controls.getBoundingClientRect().top),
      expectedTop: Math.round(Number.parseFloat(getComputedStyle(center).getPropertyValue("--skill-controls-top"))),
      position: getComputedStyle(controls).position,
    };
  });
  assert.equal(mobileStickyState.position, "sticky", "移动端技能清单栏必须保持吸顶");
  assert.ok(Math.abs(mobileStickyState.actualTop - mobileStickyState.expectedTop) <= 2, `移动端技能清单栏定位错误：${JSON.stringify(mobileStickyState)}`);
  const mobileBackToList = page.locator("[data-skill-back-to-list]");
  await mobileBackToList.scrollIntoViewIfNeeded();
  assert.equal(await mobileBackToList.isVisible(), true, "移动端返回按钮必须位于清单末尾且可访问");
  const mobileOverflow = await page.evaluate(() => ({
    documentWidth: document.documentElement.scrollWidth,
    viewportWidth: window.innerWidth,
  }));
  assert.equal(mobileOverflow.documentWidth, mobileOverflow.viewportWidth, "移动端回顶按钮不应造成全局横向溢出");
  await page.goto(`${baseUrl}/algorithms`, {waitUntil: "networkidle"});
  assert.equal(await page.getByRole("heading", {name: "项目算法包"}).count(), 1, "算法包页面必须正常展示");
  assert.equal(await page.getByText("当前首要补齐", {exact: true}).count(), 1, "算法包页面必须展示动态补齐重点");
  assert.equal(await page.getByText("近7日查询", {exact: true}).count(), 1, "算法包页面必须展示真实查询频率");
  assert.equal(await page.getByText("它解决什么问题", {exact: true}).count(), 1, "算法包页面必须解释实际用途");
  await page.getByRole("link", {name: /正式规则包/}).click();
  await page.waitForLoadState("networkidle");
  assert.equal(new URL(page.url()).searchParams.get("coverage"), "rules-confirmed", "正式规则包卡片必须进入正式项目筛选");
  assert.equal(await page.locator(".algorithm-table tbody tr").count(), 8, "正式规则包筛选必须只展示8个已确认项目");
  await page.getByRole("link", {name: /专精特新小巨人/}).first().click();
  await page.waitForLoadState("networkidle");
  assert.equal(new URL(page.url()).searchParams.get("project"), "little-giant", "项目点击必须真实切换详情路由");
  assert.equal(await page.getByText("用途说明", {exact: true}).count(), 1, "算法包必须提供可点击详情");
  assert.equal(await page.getByText("查看算法包源配置 JSON", {exact: true}).count(), 1, "算法包详情必须提供源配置");
  await page.getByRole("link", {name: "返回完整清单"}).click();
  await page.waitForLoadState("networkidle");
  assert.equal(new URL(page.url()).pathname, "/algorithms", "返回按钮必须回到项目算法包页面");
  assert.equal(new URL(page.url()).search, "", "返回按钮必须清除项目详情参数");
  assert.equal(new URL(page.url()).hash, "#algorithm-catalog", "返回按钮必须定位完整清单");
  assert.equal(await page.locator("#algorithm-detail").count(), 0, "返回完整清单后不得残留旧项目详情");
  assert.equal(
    await page.locator(".algorithm-introduction").evaluate((element) => getComputedStyle(element).display),
    "grid",
    "算法包用途说明必须加载正式构建样式",
  );
  const algorithmMobileOverflow = await page.evaluate(() => ({
    documentWidth: document.documentElement.scrollWidth,
    viewportWidth: window.innerWidth,
    tableScrollable: document.querySelector(".table-wrap").scrollWidth > document.querySelector(".table-wrap").clientWidth,
  }));
  assert.equal(algorithmMobileOverflow.documentWidth, algorithmMobileOverflow.viewportWidth, "算法包移动端页面不应产生全局横向溢出");
  assert.equal(algorithmMobileOverflow.tableScrollable, true, "算法清单应在移动端保持局部横向滚动");
  assert.deepEqual(consoleErrors, [], `控制台不应出现错误：${consoleErrors.join(" | ")}`);
  console.log("PASS Skills Center and algorithm catalog UX: responsive layout, priority metrics, console");
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
