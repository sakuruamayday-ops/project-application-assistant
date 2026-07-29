import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const portalRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (relative) => fs.readFileSync(path.join(portalRoot, relative), "utf8");

const template = read("templates/skill_center.html");
for (const required of [
  "下载通用包",
  "下载 WorkBuddy 包",
  "固定双产物",
  "其他宿主不再规划或展示平台专用版本",
]) {
  if (!template.includes(required)) {
    throw new Error(`网站安装包下载中心缺少必要内容：${required}`);
  }
}
for (const forbidden of [
  'data-platform-package="trae"',
  'data-platform-package="qoder"',
  'data-platform-package="lingma"',
  'data-platform-package="kimi-code"',
  'data-platform-package="cherry-studio"',
]) {
  if (template.includes(forbidden)) {
    throw new Error(`网站安装包下载中心仍包含已停用的平台入口：${forbidden}`);
  }
}
if (template.includes('href="/skills-manager"')) {
  throw new Error("正式 Skills 页面不得继续提供客户端入口");
}

const nativeRelease = JSON.parse(
  read("static/skills-manager/native-release.json"),
);
if (
  nativeRelease.schema !== "jiaotang-skills-manager-native-release/v1"
  || nativeRelease.state !== "retired"
  || nativeRelease.available !== false
  || nativeRelease.replacement_url !== "/skills#skills-downloads"
) {
  throw new Error("原生客户端历史清单必须处于 retired 且不可下载");
}
if (
  !Array.isArray(nativeRelease.artifacts)
  || nativeRelease.artifacts.some((artifact) => artifact.available !== false)
  || nativeRelease.user_manual?.available !== false
) {
  throw new Error("原生客户端及其手册不得继续标记为可用");
}

const capabilities = JSON.parse(
  read("static/skills-manager/platform-capabilities.json"),
);
if (
  capabilities.delivery?.primary !== "website_package_center"
  || capabilities.delivery?.skills_manager_status !== "retired"
  || capabilities.directory_sync?.enabled !== false
  || JSON.stringify(Object.keys(capabilities.platforms || {}).sort())
    !== JSON.stringify(["generic", "workbuddy"])
) {
  throw new Error("平台能力清单未固定为通用版与 WorkBuddy 版");
}

const serviceWorker = read("static/skills-manager/sw.js");
for (const required of [
  "RETIRED_CACHE_PREFIX",
  "caches.delete",
  "self.registration.unregister()",
]) {
  if (!serviceWorker.includes(required)) {
    throw new Error(`旧 PWA Service Worker 未完成退役处理：${required}`);
  }
}
if (serviceWorker.includes("cache.addAll") || serviceWorker.includes("cache.put")) {
  throw new Error("退役 Service Worker 不得继续缓存客户端资源");
}

console.log(
  "Website package center gate: only generic + WorkBuddy available, "
  + "other platform packages absent, native client retired",
);
