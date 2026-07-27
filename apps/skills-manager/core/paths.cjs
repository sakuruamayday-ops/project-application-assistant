const os = require("node:os");
const path = require("node:path");

function expandPath(value, platform = process.platform, environment = process.env) {
  if (!value) return value;
  let expanded = value;
  if (expanded === "~" || expanded.startsWith("~/")) {
    expanded = path.join(os.homedir(), expanded.slice(2));
  }
  expanded = expanded.replace(/%([^%]+)%/g, (_, key) => environment[key] || environment[key.toUpperCase()] || `%${key}%`);
  return path.normalize(expanded);
}

function safeRelativePath(value) {
  const normalized = value.replaceAll("\\", "/");
  if (
    normalized.startsWith("/")
    || normalized.includes("../")
    || normalized === ".."
    || /^[A-Za-z]:\//.test(normalized)
    || normalized.includes("\0")
  ) {
    throw new Error(`不安全的归档路径：${value}`);
  }
  return normalized.replace(/^\.\/+/, "");
}

function timestampId(date = new Date()) {
  return date.toISOString().replace(/[-:.TZ]/g, "").slice(0, 14);
}

module.exports = {
  expandPath,
  safeRelativePath,
  timestampId,
};
