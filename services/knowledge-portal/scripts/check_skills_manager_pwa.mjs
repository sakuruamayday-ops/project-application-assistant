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
  "static/skills-manager/native-release.json",
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
  const client = capabilities.delivery.native_clients[platform];
  if (client.status !== "user_authorized_unsigned") {
    throw new Error(`${platform}未声明为用户本机授权的未签名客户端`);
  }
  if (!client.enterprise_policy_may_block) {
    throw new Error(`${platform}必须明确企业策略仍可能阻止运行`);
  }
}
const nativeReleasePath = process.env.JIAOTANG_NATIVE_RELEASE_PATH
  ? path.resolve(process.env.JIAOTANG_NATIVE_RELEASE_PATH)
  : path.join(portalRoot, "static/skills-manager/native-release.json");
const nativeRelease = JSON.parse(fs.readFileSync(nativeReleasePath, "utf8"));
if (nativeRelease.schema !== "jiaotang-skills-manager-native-release/v1") {
  throw new Error("桌面客户端发布元数据schema不受支持");
}
if (
  nativeRelease.version !== "0.2.0"
  || nativeRelease.tag !== "skills-manager-v0.2.0"
  || nativeRelease.distribution !== "user_authorized_unsigned"
  || nativeRelease.publication_policy !== "release_then_reviewed_portal_backfill"
) {
  throw new Error("V0.2.0桌面客户端版本、tag或两阶段发布策略无效");
}
if (!["pending", "published"].includes(nativeRelease.state)) {
  throw new Error("桌面客户端发布状态必须是pending或published");
}
const isPublished = nativeRelease.state === "published";
if (nativeRelease.available !== isPublished) {
  throw new Error("桌面客户端state与available不一致");
}
if (
  (
    isPublished
    && (
      typeof nativeRelease.published_at !== "string"
      || !Number.isFinite(Date.parse(nativeRelease.published_at))
    )
  )
  || (!isPublished && nativeRelease.published_at !== null)
) {
  throw new Error("桌面客户端发布时间与发布状态不一致");
}
if (!Array.isArray(nativeRelease.artifacts) || nativeRelease.artifacts.length !== 3) {
  throw new Error("桌面客户端必须声明macOS arm64、macOS x64和Windows x64三项产物");
}
const releaseBase = "https://github.com/sakuruamayday-ops/project-application-assistant/releases";
if (nativeRelease.github_release_url !== `${releaseBase}/tag/${nativeRelease.tag}`) {
  throw new Error("桌面客户端GitHub Release地址无效");
}
const expectedArtifacts = new Map([
  ["macos-arm64", {
    platform: "macos",
    arch: "arm64",
    downloadUrl: "/skills-manager/download/macos/arm64",
    fileName: "Jiaotang-Skills-Manager-0.2.0-unsigned-local-mac-arm64.dmg",
  }],
  ["macos-x64", {
    platform: "macos",
    arch: "x64",
    downloadUrl: "/skills-manager/download/macos/x64",
    fileName: "Jiaotang-Skills-Manager-0.2.0-unsigned-local-mac-x64.dmg",
  }],
  ["windows-x64", {
    platform: "windows",
    arch: "x64",
    downloadUrl: "/skills-manager/download/windows/x64",
    fileName: "Jiaotang-Skills-Manager-0.2.0-unsigned-local-win-x64.exe",
  }],
]);
const shaPattern = /^[0-9a-f]{64}$/;
for (const artifact of nativeRelease.artifacts) {
  const expected = expectedArtifacts.get(artifact.id);
  if (
    !expected
    || artifact.platform !== expected.platform
    || artifact.arch !== expected.arch
    || artifact.download_url !== expected.downloadUrl
    || artifact.file_name !== expected.fileName
    || artifact.github_asset_url
      !== `${releaseBase}/download/${nativeRelease.tag}/${expected.fileName}`
    || artifact.available !== isPublished
    || (isPublished ? !shaPattern.test(artifact.sha256) : artifact.sha256 !== "")
  ) {
    throw new Error(`桌面客户端产物元数据无效：${artifact.id}`);
  }
  expectedArtifacts.delete(artifact.id);
}
if (expectedArtifacts.size) {
  throw new Error(`桌面客户端发布目标缺失：${[...expectedArtifacts.keys()].join(", ")}`);
}
const expectedManual = "Jiaotang-Skills-Manager-0.2.0-User-Manual.docx";
const manual = nativeRelease.user_manual;
if (
  !manual
  || manual.file_name !== expectedManual
  || manual.download_url !== "/skills-manager/download/user-manual"
  || manual.github_asset_url
    !== `${releaseBase}/download/${nativeRelease.tag}/${expectedManual}`
  || manual.available !== isPublished
  || (isPublished ? !shaPattern.test(manual.sha256) : manual.sha256 !== "")
) {
  throw new Error("桌面客户端Word用户手册元数据无效");
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

console.log(
  `PWA release gate: 49 skills, unsigned native release ${nativeRelease.state}, `
  + "Word manual tracked, session HTML uncached",
);
