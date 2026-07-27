const fs = require("node:fs");
const path = require("node:path");
const { expandPath } = require("./paths.cjs");

function readPlatformConfig(configPath) {
  return JSON.parse(fs.readFileSync(configPath, "utf8"));
}

function inspectPath(candidate, platform = process.platform) {
  const resolved = expandPath(candidate, platform);
  return {
    configured: candidate,
    resolved,
    exists: fs.existsSync(resolved),
  };
}

function detectPlatforms(config, platform = process.platform) {
  return config.platforms.map((definition) => {
    const platformConfig = definition[platform] || { applications: [], managed_roots: [] };
    const applications = (platformConfig.applications || []).map((item) => inspectPath(item, platform));
    const managedRoots = (platformConfig.managed_roots || []).map((item) => inspectPath(item, platform));
    const detected = applications.some((item) => item.exists);
    const writableRoot = managedRoots.find((item) => item.exists) || managedRoots[0] || null;
    return {
      id: definition.id,
      name: definition.name,
      vendor: definition.vendor,
      support: definition.support,
      channel: definition.channel,
      installMode: definition.install_mode,
      notes: definition.notes,
      detected,
      applications,
      managedRoots,
      targetRoot: writableRoot ? writableRoot.resolved : null,
      canInstallAutomatically: Boolean(
        definition.support === "full"
        && ["shared-agents-directory", "managed-directory"].includes(definition.install_mode)
        && writableRoot,
      ),
    };
  });
}

function uniqueManagedTargets(platforms) {
  const result = new Map();
  for (const item of platforms) {
    if (!item.targetRoot) continue;
    const key = path.resolve(item.targetRoot);
    const current = result.get(key) || { targetRoot: key, platformIds: [] };
    current.platformIds.push(item.id);
    result.set(key, current);
  }
  return [...result.values()];
}

module.exports = {
  readPlatformConfig,
  detectPlatforms,
  uniqueManagedTargets,
};
