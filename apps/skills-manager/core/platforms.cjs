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

function defaultDiscoveryRoots(platform = process.platform) {
  if (platform === "darwin") {
    return ["/Applications", "~/Applications"];
  }
  if (platform === "win32") {
    return [
      "%LOCALAPPDATA%/Programs",
      "%PROGRAMFILES%",
      "%PROGRAMFILES(X86)%",
    ];
  }
  return [];
}

function walkForNames(root, expectedNames, maxDepth = 3, maxEntries = 4000, skipBundles = false) {
  const found = [];
  const queue = [{ directory: root, depth: 0 }];
  let inspected = 0;
  while (queue.length && inspected < maxEntries) {
    const current = queue.shift();
    let entries = [];
    try {
      entries = fs.readdirSync(current.directory, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const entry of entries) {
      inspected += 1;
      if (inspected > maxEntries) break;
      const absolute = path.join(current.directory, entry.name);
      if (expectedNames.has(entry.name.toLowerCase())) found.push(absolute);
      const packageDirectory = skipBundles && /\.(app|framework|bundle)$/i.test(entry.name);
      if (entry.isDirectory() && !packageDirectory && current.depth < maxDepth) {
        queue.push({ directory: absolute, depth: current.depth + 1 });
      }
    }
  }
  return found;
}

function discoverApplicationPaths(platformConfig, platform = process.platform, options = {}) {
  const configured = platformConfig.applications || [];
  const expectedNames = new Set(configured.map((item) => path.basename(expandPath(item, platform)).toLowerCase()));
  if (!expectedNames.size) return [];
  const roots = options.discoveryRoots || defaultDiscoveryRoots(platform);
  const discovered = [];
  for (const configuredRoot of roots) {
    const root = expandPath(configuredRoot, platform);
    if (!root || !fs.existsSync(root)) continue;
    discovered.push(...walkForNames(
      root,
      expectedNames,
      options.maxDepth ?? 3,
      options.maxEntries ?? 4000,
      platform === "darwin",
    ));
  }
  return [...new Set(discovered.map((item) => path.normalize(item)))];
}

function detectPlatforms(config, platform = process.platform, options = {}) {
  return config.platforms.map((definition) => {
    const platformConfig = definition[platform] || { applications: [], managed_roots: [] };
    const applications = (platformConfig.applications || []).map((item) => inspectPath(item, platform));
    const configuredPaths = new Set(applications.map((item) => path.normalize(item.resolved)));
    const discoveredApplications = discoverApplicationPaths(platformConfig, platform, options)
      .filter((item) => !configuredPaths.has(path.normalize(item)))
      .map((item) => ({
        configured: null,
        resolved: item,
        exists: true,
        discovered: true,
      }));
    applications.push(...discoveredApplications);
    const managedRoots = (platformConfig.managed_roots || []).map((item) => inspectPath(item, platform));
    const detected = applications.some((item) => item.exists);
    const writableRoot = managedRoots.find((item) => item.exists) || managedRoots[0] || null;
    const detectedPaths = applications.filter((item) => item.exists).map((item) => item.resolved);
    return {
      id: definition.id,
      name: definition.name,
      vendor: definition.vendor,
      support: definition.support,
      channel: definition.channel,
      installMode: definition.install_mode,
      notes: definition.notes,
      detected,
      detectionMethod: detectedPaths.length ? "bounded-system-locations" : "not-found",
      detectedPaths,
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

function automaticDetectedTargets(platforms) {
  return uniqueManagedTargets(platforms.filter((item) => item.detected && item.canInstallAutomatically));
}

module.exports = {
  automaticDetectedTargets,
  defaultDiscoveryRoots,
  discoverApplicationPaths,
  readPlatformConfig,
  detectPlatforms,
  uniqueManagedTargets,
};
