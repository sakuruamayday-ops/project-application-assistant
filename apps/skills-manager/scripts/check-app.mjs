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
];

const missing = required.filter((relative) => !fs.existsSync(path.join(appRoot, relative)));
if (missing.length) {
  console.error(`missing files:\n${missing.join("\n")}`);
  process.exit(1);
}

const platformConfig = JSON.parse(fs.readFileSync(path.join(appRoot, "config/platforms.json"), "utf8"));
const catalog = JSON.parse(fs.readFileSync(path.join(appRoot, "data/skill-catalog.json"), "utf8"));
if (catalog.count !== 49) throw new Error(`skill catalog count must be 49, got ${catalog.count}`);
if (platformConfig.platforms.length < 6) throw new Error("platform adapter catalog is incomplete");

console.log(`check: ${catalog.count} skills, ${platformConfig.platforms.length} platform adapters`);
