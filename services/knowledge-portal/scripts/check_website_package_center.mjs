import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const portalRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (relative) => fs.readFileSync(path.join(portalRoot, relative), "utf8");

const skillCenterTemplate = read("templates/skill_center.html");
const portalTemplate = read("templates/portal.html");
for (const required of [
  "下载通用包",
  "统一通用技能包",
  "不再提供 WorkBuddy 专用技能包",
  "前往客户端下载",
]) {
  if (!skillCenterTemplate.includes(required)) {
    throw new Error(`网站技能中心缺少必要内容：${required}`);
  }
}
for (const forbidden of [
  'data-platform-package="trae"',
  'data-platform-package="qoder"',
  'data-platform-package="lingma"',
  'data-platform-package="kimi-code"',
  'data-platform-package="cherry-studio"',
  "下载 WorkBuddy 包",
]) {
  if (skillCenterTemplate.includes(forbidden)) {
    throw new Error(`网站技能中心仍包含已停用的平台入口：${forbidden}`);
  }
}
for (const required of [
  "下载共创企业助手",
  "下载 {{ artifact.platform_label }} 安装包",
  "{{ desktop_release.message }}",
]) {
  if (!portalTemplate.includes(required)) {
    throw new Error(`网站客户端下载页缺少必要内容：${required}`);
  }
}
console.log(
  "Website package center gate: universal Skills package plus status-aware desktop releases",
);
