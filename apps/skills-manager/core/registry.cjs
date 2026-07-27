const fs = require("node:fs");
const path = require("node:path");

const EMPTY_REGISTRY = {
  schema: "jiaotang-skills-manager-registry/v1",
  targets: {},
  backups: [],
};

function loadRegistry(registryPath) {
  if (!fs.existsSync(registryPath)) return structuredClone(EMPTY_REGISTRY);
  const parsed = JSON.parse(fs.readFileSync(registryPath, "utf8"));
  if (parsed.schema !== EMPTY_REGISTRY.schema) throw new Error("无法识别本机安装登记表");
  parsed.targets ||= {};
  parsed.backups ||= [];
  return parsed;
}

function saveRegistry(registryPath, registry) {
  fs.mkdirSync(path.dirname(registryPath), { recursive: true, mode: 0o700 });
  const temporary = `${registryPath}.tmp`;
  fs.writeFileSync(temporary, `${JSON.stringify(registry, null, 2)}\n`, { mode: 0o600 });
  fs.renameSync(temporary, registryPath);
}

module.exports = {
  loadRegistry,
  saveRegistry,
};
