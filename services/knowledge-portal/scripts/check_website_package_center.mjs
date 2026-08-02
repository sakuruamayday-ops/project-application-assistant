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
console.log(
  "Website package center gate: only generic + WorkBuddy packages are presented",
);
