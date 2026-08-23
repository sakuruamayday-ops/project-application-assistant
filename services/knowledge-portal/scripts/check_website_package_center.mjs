import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const portalRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (relative) => fs.readFileSync(path.join(portalRoot, relative), "utf8");

const skillTemplate = read("templates/skill_center.html");
const clientTemplate = read("templates/client_downloads.html");
const portalTemplate = read("templates/portal.html");
const portalScript = read("static/portal.js");
for (const required of [
  "下载通用包",
  "统一通用包",
  "其他兼容宿主可下载通用包后自行导入",
]) {
  if (!skillTemplate.includes(required)) {
    throw new Error(`Skills 下载中心缺少必要内容：${required}`);
  }
}
for (const required of [
  "client_release.downloads.macos",
  "macos.architecture_label",
  "下载 macOS {{ macos.architecture_label }}版",
  "client_release.downloads.windows",
  "下载 Windows 版",
  "直接覆盖安装 V{{ client_release.version }}",
  "xattr -dr com.apple.quarantine",
  "无法一键复制？显示手动粘贴方法",
]) {
  if (!clientTemplate.includes(required)) {
    throw new Error(`客户端下载中心缺少必要内容：${required}`);
  }
}
for (const required of [
  'data-agent-platform="macos"',
  'data-agent-platform="windows"',
  "一键安装 macOS 版",
  "一键安装 Windows 版",
]) {
  if (!portalTemplate.includes(required)) {
    throw new Error(`Agent 连接入口缺少必要内容：${required}`);
  }
}
for (const forbidden of [
  'data-platform-package="trae"',
  'data-platform-package="qoder"',
  'data-platform-package="lingma"',
  'data-platform-package="kimi-code"',
  'data-platform-package="cherry-studio"',
  "下载旧版宿主专用包",
]) {
  if (skillTemplate.includes(forbidden)) {
    throw new Error(`网站安装包下载中心仍包含已停用的平台入口：${forbidden}`);
  }
}
for (const required of [
  'form.set("platform", platform)',
  '["macos", "windows"].includes(platform)',
]) {
  if (!portalScript.includes(required)) {
    throw new Error(`网站一键安装入口未绑定用户选择的平台：${required}`);
  }
}
console.log(
  "Website package center gate: generic Skills + dual-architecture macOS client + Windows client + explicit Agent install entries",
);
