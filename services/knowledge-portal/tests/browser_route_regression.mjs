#!/usr/bin/env node
import assert from "node:assert/strict";
import {mkdir, mkdtemp, rename} from "node:fs/promises";
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
  ["/algorithms", "algorithms"],
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
const screenshotDir = process.env.JIAOTANG_BROWSER_SCREENSHOT_DIR || "";
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

async function assertPortalSequence(page, expectedIds, roleLabel) {
  await page.waitForTimeout(180);
  const state = await page.evaluate((ids) => {
    const rendered = [...document.querySelectorAll("main section[id]")]
      .map((section) => section.id)
      .filter((id) => ids.includes(id));
    const navigation = [...document.querySelectorAll("[data-section-link]")]
      .map((link) => link.dataset.sectionLink)
      .filter((id) => ids.includes(id) && document.getElementById(id));
    const positions = ids.map((id) => ({
      id,
      top: document.getElementById(id)?.getBoundingClientRect().top ?? null,
    }));
    return {rendered, navigation, positions};
  }, expectedIds);
  assert.deepEqual(state.rendered, expectedIds, `${roleLabel}单页区块顺序必须与产品信息架构一致`);
  assert.deepEqual(state.navigation, expectedIds, `${roleLabel}侧栏顺序必须与单页区块一致`);
  assert.ok(
    state.positions.every((item, index) => index === 0 || item.top > state.positions[index - 1].top),
    `${roleLabel}区块的实际纵向位置必须严格递增：${JSON.stringify(state.positions)}`,
  );

  for (const sectionId of expectedIds) {
    await page.evaluate((expectedId) => {
      const section = document.getElementById(expectedId);
      if (!section) return;
      const rect = section.getBoundingClientRect();
      const absoluteTop = window.scrollY + rect.top;
      const viewportAnchor = Math.min(window.innerHeight * .36, 340);
      const insideOffset = Math.min(Math.max(rect.height / 2, 2), viewportAnchor);
      window.scrollTo({top: Math.max(0, absoluteTop + insideOffset - viewportAnchor), behavior: "auto"});
    }, sectionId);
    await page.waitForFunction((expectedId) => (
      document.querySelector(`[data-section-link="${expectedId}"].active`) !== null
    ), sectionId);
  }
}

async function readFlowState(locator) {
  return locator.evaluate((element) => {
    const slot = element.dataset.atelierFlowFrame;
    const style = getComputedStyle(element, `::${slot}`);
    return {
      slot,
      angle: style.getPropertyValue("--atelier-flow-angle").trim(),
      opacity: Number(style.opacity),
      animationName: style.animationName,
      animationPlayState: style.animationPlayState,
      backgroundImage: style.backgroundImage,
    };
  });
}

let browser;
try {
  await waitForServer();
  browser = await chromium.launch({
    headless: true,
    executablePath: process.env.JIAOTANG_BROWSER_EXECUTABLE || undefined,
  });
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
  await page.goto(`${baseUrl}/admin/members`, {waitUntil: "networkidle"});
  const authorizationForm = page.locator('form[action="/admin/registration-authorizations"]');
  await authorizationForm.locator('input[name="real_name"]').fill("普通成员");
  await authorizationForm.locator('input[name="identity_code"]').fill("0826");
  await Promise.all([
    page.waitForURL(/\/admin\/members#invite-\d+$/),
    authorizationForm.locator('button[type="submit"]').click(),
  ]);
  assert.match(await page.locator("main").innerText(), /普通成员/, "普通成员自助注册权限必须创建成功");
  await page.goto(`${baseUrl}/portal`, {waitUntil: "networkidle"});

  await page.waitForTimeout(160);
  const flowCoverage = await page.evaluate(() => {
    const samples = [
      ".hero-banner",
      ".hero-command",
      ".metrics",
      ".metrics > a",
      ".cockpit-radar",
      ".assistant-console",
      ".panel",
      ".table-wrap",
      ".status-pill",
    ];
    return {
      missing: samples.filter((selector) => !document.querySelector(selector)?.dataset.atelierFlowFrame),
      unavailable: document.querySelectorAll('[data-atelier-flow-frame="unavailable"]').length,
      decorated: document.querySelectorAll("[data-atelier-flow-frame]").length,
    };
  });
  assert.deepEqual(flowCoverage.missing, [], `所有主要框体都必须装配流光：${JSON.stringify(flowCoverage)}`);
  assert.equal(flowCoverage.unavailable, 0, `框体原有伪元素不得阻断流光：${JSON.stringify(flowCoverage)}`);
  assert.ok(flowCoverage.decorated > 30, `单页门户应覆盖全部框体而非少量入口：${JSON.stringify(flowCoverage)}`);

  const heroFrame = page.locator(".hero-banner");
  assert.equal(
    await page.locator("html").evaluate((element) => element.classList.contains("is-atelier-flow-document-visible")),
    true,
    "前台页面必须开放流光运行门禁",
  );
  await page.waitForFunction(() => document.querySelector(".hero-banner")?.classList.contains("is-atelier-flow-visible"));
  const heroFlowStart = await readFlowState(heroFrame);
  if (screenshotDir) {
    await mkdir(screenshotDir, {recursive: true});
    await heroFrame.screenshot({path: join(screenshotDir, "flow-glow-hero-t0.png")});
  }
  await page.waitForTimeout(420);
  const heroFlowEnd = await readFlowState(heroFrame);
  if (screenshotDir) await heroFrame.screenshot({path: join(screenshotDir, "flow-glow-hero-t1.png")});
  assert.ok(heroFlowStart.opacity >= .5, `主视觉大型框体应持续显示清晰流光：${JSON.stringify(heroFlowStart)}`);
  assert.equal(heroFlowStart.animationName, "atelier-flow-orbit", "大型框体应挂载流光轨道动画");
  assert.equal(heroFlowStart.animationPlayState, "running", "只有主视觉大型框体默认持续运行");
  assert.notEqual(heroFlowStart.angle, heroFlowEnd.angle, "大型框体流光角度必须随时间连续变化");
  assert.notEqual(
    heroFlowStart.backgroundImage,
    heroFlowEnd.backgroundImage,
    "大型框体的实际渐变背景必须随角度重新绘制，不能只改变未参与绘制的变量",
  );
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", {configurable: true, value: "hidden"});
    document.dispatchEvent(new Event("visibilitychange"));
  });
  assert.equal(
    await page.locator("html").evaluate((element) => element.classList.contains("is-atelier-flow-document-visible")),
    false,
    "页面进入后台时必须关闭流光运行门禁",
  );
  assert.equal((await readFlowState(heroFrame)).animationPlayState, "paused", "页面进入后台时大型框体必须暂停");
  await page.evaluate(() => {
    delete document.visibilityState;
    document.dispatchEvent(new Event("visibilitychange"));
  });
  assert.equal((await readFlowState(heroFrame)).animationPlayState, "running", "页面返回前台时可见大型框体必须恢复");

  await page.evaluate(() => window.scrollTo({top: document.documentElement.scrollHeight, behavior: "auto"}));
  await page.waitForFunction(() => !document.querySelector(".hero-banner")?.classList.contains("is-atelier-flow-visible"));
  assert.equal((await readFlowState(heroFrame)).animationPlayState, "paused", "大型框体离开视口后必须暂停");
  await heroFrame.scrollIntoViewIfNeeded();
  await page.waitForFunction(() => document.querySelector(".hero-banner")?.classList.contains("is-atelier-flow-visible"));
  assert.equal((await readFlowState(heroFrame)).animationPlayState, "running", "大型框体回到视口后必须恢复");

  const glowCard = page.locator(".metrics > a").first();
  const glowIdle = await readFlowState(glowCard);
  assert.equal(glowIdle.opacity, 0, `普通卡片默认必须完全静止：${JSON.stringify(glowIdle)}`);
  assert.equal(glowIdle.animationName, "atelier-flow-orbit", "可点击卡片应挂载流光轨道动画");
  assert.match(glowIdle.backgroundImage, /conic-gradient/, "流光边框应使用锥形渐变");
  assert.equal(glowIdle.animationPlayState, "paused", "普通卡片未悬停时不得占用动画资源");
  await glowCard.hover();
  await page.waitForTimeout(240);
  if (screenshotDir) await glowCard.screenshot({path: join(screenshotDir, "flow-glow-card-t0.png")});
  await page.waitForTimeout(420);
  const glowActive = await readFlowState(glowCard);
  if (screenshotDir) await glowCard.screenshot({path: join(screenshotDir, "flow-glow-card-t1.png")});
  assert.ok(glowActive.opacity > .95, `悬停后流光边框应明显增强：${JSON.stringify(glowActive)}`);
  assert.equal(glowActive.animationPlayState, "running", "悬停后流光轨道应开始运行");
  await page.mouse.move(2, 2);
  await page.keyboard.press("Tab");
  await glowCard.focus();
  await page.waitForTimeout(80);
  assert.equal((await readFlowState(glowCard)).animationPlayState, "running", "可见卡片聚焦时必须运行");
  await page.evaluate(() => window.scrollTo({top: document.documentElement.scrollHeight, behavior: "auto"}));
  await page.waitForFunction(() => !document.querySelector(".metrics > a")?.classList.contains("is-atelier-flow-visible"));
  assert.equal((await readFlowState(glowCard)).animationPlayState, "paused", "聚焦卡片离开视口后也必须暂停");
  await glowCard.scrollIntoViewIfNeeded();
  await page.waitForFunction(() => document.querySelector(".metrics > a")?.classList.contains("is-atelier-flow-visible"));

  const focusedField = page.locator('#feedback input[name="subject"]');
  await focusedField.focus();
  await page.waitForFunction(() => document.querySelector('#feedback input[name="subject"]')?.classList.contains("is-atelier-flow-visible"));
  const fieldGlow = await focusedField.evaluate((element) => {
    const style = getComputedStyle(element);
    return {animationName: style.animationName, animationPlayState: style.animationPlayState, backgroundImage: style.backgroundImage};
  });
  assert.equal(fieldGlow.animationName, "atelier-flow-orbit", "输入框聚焦后应启动流光边框");
  assert.equal(fieldGlow.animationPlayState, "running", "前台且位于视口内的输入框聚焦后必须运行");
  assert.match(fieldGlow.backgroundImage, /conic-gradient/, "输入框聚焦边框应使用锥形渐变");

  await page.emulateMedia({reducedMotion: "reduce"});
  await glowCard.focus();
  const reducedMotionGlow = await readFlowState(glowCard);
  assert.equal(reducedMotionGlow.animationName, "none", "减少动态效果模式必须停用流光动画");
  await page.emulateMedia({reducedMotion: "no-preference"});
  await glowCard.scrollIntoViewIfNeeded();
  await glowCard.focus();
  await page.waitForTimeout(180);
  if (screenshotDir) {
    await mkdir(screenshotDir, {recursive: true});
    await page.screenshot({path: join(screenshotDir, "flow-glow-desktop.png"), fullPage: false});
    await glowCard.screenshot({path: join(screenshotDir, "flow-glow-card-desktop.png")});
  }

  await page.goto(`${baseUrl}/algorithms`, {waitUntil: "networkidle"});
  await page.mouse.move(2, 2);
  assert.equal(await page.getByText("政策基线包", {exact: true}).count(), 0, "空的政策基线分类卡必须移除");
  assert.equal(await page.getByText("纯检索路由", {exact: true}).count(), 0, "空的纯检索路由卡必须移除");
  const activeAlgorithmCard = page.locator("a.algorithm-stat-card.is-active").first();
  await activeAlgorithmCard.scrollIntoViewIfNeeded();
  const algorithmGlowStart = await readFlowState(activeAlgorithmCard);
  await page.waitForTimeout(420);
  const algorithmGlowEnd = await readFlowState(activeAlgorithmCard);
  assert.equal(algorithmGlowStart.opacity, 0, `仅被选中的算法卡也必须保持静止：${JSON.stringify(algorithmGlowStart)}`);
  assert.equal(algorithmGlowStart.animationName, "atelier-flow-orbit", "算法卡应挂载流光轨道动画");
  assert.equal(algorithmGlowStart.animationPlayState, "paused", "当前算法卡不得因选中态持续运行");
  assert.equal(algorithmGlowStart.angle, algorithmGlowEnd.angle, "静止算法卡的流光角度不得自行变化");

  const hoverAlgorithmCard = page.locator("a.algorithm-stat-card").nth(1);
  await hoverAlgorithmCard.hover();
  await page.waitForTimeout(180);
  const hoveredAlgorithmGlow = await readFlowState(hoverAlgorithmCard);
  assert.ok(
    hoveredAlgorithmGlow.opacity > .95,
    "非当前算法卡悬停后应显示流光",
  );
  assert.equal(hoveredAlgorithmGlow.animationPlayState, "running", "只允许悬停算法卡开始流动");
  assert.equal((await readFlowState(activeAlgorithmCard)).animationPlayState, "paused", "悬停其他卡片时选中卡片仍应静止");
  await page.emulateMedia({reducedMotion: "reduce"});
  assert.equal(
    (await readFlowState(activeAlgorithmCard)).animationName,
    "none",
    "减少动态效果模式必须停用算法卡流光动画",
  );
  await page.emulateMedia({reducedMotion: "no-preference"});
  await page.mouse.move(1400, 20);
  await activeAlgorithmCard.evaluate((element) => element.blur());
  await page.waitForTimeout(180);
  if (screenshotDir) {
    await page.screenshot({path: join(screenshotDir, "algorithm-flow-glow-desktop.png"), fullPage: false});
    await activeAlgorithmCard.screenshot({path: join(screenshotDir, "algorithm-flow-card-desktop.png")});
  }

  const orderedSectionIds = ["overview", "cockpit", "algorithms", "api-access", "feedback", "skills", "health-admin"];
  await assertPortalSequence(page, orderedSectionIds, "管理员");

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
  await page.goto(`${baseUrl}/mcp-guide`, {waitUntil: "networkidle"});
  await page.goto(`${baseUrl}/admin/health/access`, {waitUntil: "networkidle"});
  const credentialSummary = page.locator('.credential-summary-link[href="/admin/users/1#access-credentials"]');
  assert.equal(await credentialSummary.isVisible(), true, "访问凭据数量应可点击进入成员凭据明细");
  await credentialSummary.click();
  await page.waitForURL("**/admin/users/1#access-credentials");
  const credentialPanel = page.locator("#access-credentials");
  assert.equal(await credentialPanel.isVisible(), true, "成员详情应展示访问凭据与设备面板");
  assert.equal(await credentialPanel.locator("[data-credential-select]").count(), 1, "测试管理员应展示一条可选凭据");
  assert.ok(
    await page.locator(".danger-zone").evaluate((element) => ["before", "after"].includes(element.dataset.atelierFlowFrame)),
    "风险面板仍是框体，应保留低亮度流光且不改变风险语义",
  );
  const batchRevoke = credentialPanel.locator("[data-credential-batch-submit]");
  assert.equal(await batchRevoke.isDisabled(), true, "未选择凭据时批量吊销按钮必须禁用");
  assert.equal(
    await batchRevoke.evaluate((element) => getComputedStyle(element, "::after").content),
    "none",
    "风险按钮不得叠加普通可点击框流光",
  );
  await credentialPanel.locator("[data-credential-select]").check();
  assert.equal(await batchRevoke.isEnabled(), true, "选择凭据后批量吊销按钮必须启用");
  assert.match(await credentialPanel.locator("[data-credential-selection]").innerText(), /已选择 1 条/);
  const credentialDesktopWidth = await page.evaluate(() => ({document: document.documentElement.scrollWidth, viewport: window.innerWidth}));
  assert.equal(credentialDesktopWidth.document, credentialDesktopWidth.viewport, "凭据详情桌面端不应出现页面级横向溢出");
  if (screenshotDir) {
    await mkdir(screenshotDir, {recursive: true});
    await page.screenshot({path: join(screenshotDir, "credential-detail-desktop.png"), fullPage: true});
  }
  await page.setViewportSize({width: 390, height: 844});
  await page.reload({waitUntil: "networkidle"});
  const credentialMobileWidth = await page.evaluate(() => ({document: document.documentElement.scrollWidth, viewport: window.innerWidth}));
  assert.equal(credentialMobileWidth.document, credentialMobileWidth.viewport, "凭据详情移动端不应出现页面级横向溢出");
  assert.equal(await page.locator("#access-credentials [data-credential-batch-submit]").isVisible(), true, "移动端应保留批量吊销入口");
  if (screenshotDir) {
    await page.screenshot({path: join(screenshotDir, "credential-detail-mobile.png"), fullPage: true});
  }
  await page.setViewportSize({width: 1440, height: 1000});
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
  const mobileGlowCard = page.locator(".metrics > a").first();
  await mobileGlowCard.scrollIntoViewIfNeeded();
  await mobileGlowCard.focus();
  await page.waitForTimeout(180);
  if (screenshotDir) {
    await page.screenshot({path: join(screenshotDir, "flow-glow-mobile.png"), fullPage: false});
    await mobileGlowCard.screenshot({path: join(screenshotDir, "flow-glow-card-mobile.png")});
  }
  await page.goto(`${baseUrl}/algorithms`, {waitUntil: "networkidle"});
  const mobileAlgorithmCard = page.locator("a.algorithm-stat-card.is-active").first();
  await mobileAlgorithmCard.scrollIntoViewIfNeeded();
  await page.waitForTimeout(180);
  if (screenshotDir) {
    await page.screenshot({path: join(screenshotDir, "algorithm-flow-glow-mobile.png"), fullPage: false});
    await mobileAlgorithmCard.screenshot({path: join(screenshotDir, "algorithm-flow-card-mobile.png")});
  }
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

  await page.context().clearCookies();
  await page.setViewportSize({width: 1440, height: 1000});
  await page.goto(`${baseUrl}/register`, {waitUntil: "networkidle"});
  await page.fill('input[name="username"]', "route-member");
  await page.fill('input[name="real_name"]', "普通成员");
  await page.fill('input[name="identity_code"]', "0826");
  await page.fill('input[name="company_name"]', "共创集团");
  await page.fill('input[name="password"]', "browser-member-password-123");
  await page.fill('input[name="confirm_password"]', "browser-member-password-123");
  await Promise.all([
    page.waitForURL("**/login?registered=1"),
    page.click('button[type="submit"]'),
  ]);
  await page.goto(`${baseUrl}/login`, {waitUntil: "networkidle"});
  await page.fill('input[name="username"]', "route-member");
  await page.fill('input[name="password"]', "browser-member-password-123");
  await page.click('button[type="submit"]');
  await page.waitForLoadState("networkidle");
  const memberLoginError = await page.locator(".notice.alert").textContent().catch(() => "");
  assert.match(page.url(), /\/portal(?:#.*)?$/, `普通成员登录失败：${memberLoginError || page.url()}`);

  const memberSectionIds = ["overview", "cockpit", "algorithms", "api-access", "feedback", "skills"];
  await assertPortalSequence(page, memberSectionIds, "普通成员");
  assert.equal(await page.locator('[data-section-link="health-admin"]').count(), 0, "普通成员不得看到管理员健康看板导航");
  assert.equal(await page.locator("#health-admin").count(), 0, "普通成员不得渲染管理员健康看板区块");

  for (const [legacyPath, sectionId] of [...routes].filter(([path]) => !path.startsWith("/admin/"))) {
    const response = await page.goto(`${baseUrl}${legacyPath}`, {waitUntil: "networkidle"});
    assert.equal(response?.status(), 200, `普通成员访问 ${legacyPath} 应返回 200`);
    await page.waitForURL(`**/portal#${sectionId}`);
    await page.waitForFunction((expectedId) => {
      const section = document.getElementById(expectedId);
      const activeLink = document.querySelector(`[data-section-link="${expectedId}"].active`);
      const rect = section?.getBoundingClientRect();
      return Boolean(activeLink && rect && rect.bottom > 0 && rect.top < window.innerHeight);
    }, sectionId);
  }

  await page.setViewportSize({width: 390, height: 844});
  await page.goto(`${baseUrl}/access`, {waitUntil: "networkidle"});
  await page.waitForTimeout(850);
  const mobileMemberLayout = await page.evaluate(() => {
    const sidebar = document.querySelector(".sidebar")?.getBoundingClientRect();
    const section = document.querySelector("#api-access")?.getBoundingClientRect();
    return {
      sidebarBottom: Math.round(sidebar?.bottom || 0),
      sectionTop: Math.round(section?.top || 0),
      sectionBottom: Math.round(section?.bottom || 0),
    };
  });
  assert.ok(
    mobileMemberLayout.sectionTop >= mobileMemberLayout.sidebarBottom - 1,
    `普通成员移动端目标章节不得被横向导航遮挡：${JSON.stringify(mobileMemberLayout)}`,
  );
  assert.ok(
    mobileMemberLayout.sectionTop < 844 && mobileMemberLayout.sectionBottom > 0,
    `普通成员移动端目标章节必须进入可视区：${JSON.stringify(mobileMemberLayout)}`,
  );
  console.log(`PASS browser route regression: ${routes.size} admin routes and ${memberSectionIds.length} member sections`);
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
