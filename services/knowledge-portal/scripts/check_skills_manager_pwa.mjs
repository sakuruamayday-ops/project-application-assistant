import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const portalRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const required = [
  "templates/skills_manager_pwa.html",
  "static/skills-manager/app.css",
  "static/skills-manager/polish.css",
  "static/skills-manager/app.js",
  "static/skills-manager/zip-reader.js",
  "static/skills-manager/sw.js",
  "static/skills-manager/manifest.webmanifest",
  "static/skills-manager/platform-capabilities.json",
];
const missing = required.filter((relative) => !fs.existsSync(path.join(portalRoot, relative)));
if (missing.length) throw new Error(`PWA缺少文件：\n${missing.join("\n")}`);

const capabilityPath = path.join(
  portalRoot,
  "static/skills-manager/platform-capabilities.json",
);
const capabilities = JSON.parse(fs.readFileSync(capabilityPath, "utf8"));
if (capabilities.schema !== "jiaotang-skills-manager-capabilities/v1") {
  throw new Error("平台能力清单schema不受支持");
}
if (capabilities.directory_sync.managed_skill_count !== 49) {
  throw new Error("平台能力清单必须声明49项托管技能");
}
for (const platform of ["macos", "windows"]) {
  if (capabilities.delivery.native_clients[platform].status !== "blocked_until_signed") {
    throw new Error(`${platform}原生正式发布未被证书门禁阻断`);
  }
}
const serviceWorker = fs.readFileSync(
  path.join(portalRoot, "static/skills-manager/sw.js"),
  "utf8",
);
const staticBlock = serviceWorker.match(/const STATIC = \[([\s\S]*?)\];/)?.[1] || "";
if (staticBlock.includes('"/skills-manager"')) {
  throw new Error("带用户名的Skills管理器HTML不得进入Service Worker静态缓存");
}
if (!serviceWorker.includes('url.pathname === "/skills-manager"')) {
  throw new Error("Skills管理器HTML必须使用仅联网会话响应");
}

console.log("PWA release gate: 49 skills, native signing blocked, session HTML uncached");
