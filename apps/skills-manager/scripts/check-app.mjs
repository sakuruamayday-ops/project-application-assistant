import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const required = [
  "electron/main.cjs",
  "electron/preload.cjs",
  "renderer/index.html",
  "renderer/styles.css",
  "renderer/app.js",
  "config/platforms.json",
  "config/security.json",
  "data/skill-catalog.json",
  "docs/SECURITY_SIGNING.md",
  "docs/PLATFORM_SUPPORT.md",
  "build/icon.icns",
  "build/icon.png",
  "scripts/release-security-check.mjs",
  "scripts/build-platform-adapter-release.mjs",
  "electron-builder.unsigned-local.cjs",
];

const missing = required.filter((relative) => !fs.existsSync(path.join(appRoot, relative)));
if (missing.length) {
  console.error(`missing files:\n${missing.join("\n")}`);
  process.exit(1);
}

const platformConfig = JSON.parse(fs.readFileSync(path.join(appRoot, "config/platforms.json"), "utf8"));
const securityConfig = JSON.parse(fs.readFileSync(path.join(appRoot, "config/security.json"), "utf8"));
const catalog = JSON.parse(fs.readFileSync(path.join(appRoot, "data/skill-catalog.json"), "utf8"));
if (catalog.count !== 49) throw new Error(`skill catalog count must be 49, got ${catalog.count}`);
if (platformConfig.platforms.length < 6) throw new Error("platform adapter catalog is incomplete");
if (
  !Number.isSafeInteger(platformConfig.sequence)
  || platformConfig.sequence < 1
  || !platformConfig.revision
  || !platformConfig.minimum_manager_version
) {
  throw new Error("platform adapter release metadata is incomplete");
}
if (
  securityConfig.platform_adapters?.namespace
  !== "jiaotang-skills-manager-platform-adapters"
) {
  throw new Error("platform adapter signature namespace is not pinned");
}
if (!securityConfig.publisher?.public_key?.startsWith("ssh-ed25519 ")) {
  throw new Error("platform adapter publisher public key is not pinned");
}

console.log(`check: ${catalog.count} skills, ${platformConfig.platforms.length} platform adapters`);
