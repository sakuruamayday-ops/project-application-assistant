const fs = require("node:fs");
const path = require("node:path");
const AdmZip = require("adm-zip");
const { loadRegistry, saveRegistry } = require("./registry.cjs");
const { safeRelativePath, timestampId } = require("./paths.cjs");

function findSuiteManifest(zip) {
  const candidates = zip.getEntries()
    .map((entry) => entry.entryName)
    .filter((name) => name.endsWith("/skills/suite-manifest.json"));
  if (candidates.length !== 1) {
    throw new Error(`通用包必须包含且只能包含一份 suite-manifest.json，当前为 ${candidates.length} 份`);
  }
  return candidates[0];
}

function genericInstallEntries(manifest) {
  const entries = [];
  for (const skill of manifest.skills || []) {
    entries.push(safeRelativePath(skill));
  }
  for (const shared of manifest.shared_paths || []) {
    entries.push(safeRelativePath(shared));
  }
  return [...new Set(entries)];
}

function targetState(registry, targetRoot) {
  return registry.targets[path.resolve(targetRoot)] || null;
}

function planGenericInstall({ archivePath, targetRoot, registryPath, platformIds = [] }) {
  const zip = new AdmZip(archivePath);
  const suiteEntry = findSuiteManifest(zip);
  const manifest = JSON.parse(zip.getEntry(suiteEntry).getData().toString("utf8"));
  const sourcePrefix = path.posix.dirname(suiteEntry);
  const entries = genericInstallEntries(manifest);
  const registry = loadRegistry(registryPath);
  const current = targetState(registry, targetRoot);
  const managed = new Set(current?.managedEntries || []);
  const conflicts = [];
  const replacements = [];
  const additions = [];
  for (const relative of entries) {
    const destination = path.join(targetRoot, ...relative.split("/"));
    if (!fs.existsSync(destination)) {
      additions.push(relative);
    } else if (managed.has(relative)) {
      replacements.push(relative);
    } else {
      conflicts.push(relative);
    }
  }
  return {
    schema: "jiaotang-skills-manager-install-plan/v1",
    archivePath,
    targetRoot: path.resolve(targetRoot),
    sourcePrefix,
    version: String(manifest.release?.version || manifest.release?.tag || "unknown"),
    releaseTag: String(manifest.release?.tag || ""),
    skillCount: (manifest.skills || []).length,
    entries,
    additions,
    replacements,
    conflicts,
    platformIds,
    ready: conflicts.length === 0 && entries.length > 0,
  };
}

function copyToStage(zip, plan, stageRoot) {
  const sourcePrefix = `${plan.sourcePrefix}/`;
  for (const relative of plan.entries) {
    const sourceName = `${sourcePrefix}${relative}`;
    const matching = zip.getEntries().filter((entry) => (
      entry.entryName === sourceName
      || entry.entryName.startsWith(`${sourceName}/`)
    ));
    if (!matching.length) throw new Error(`发布包缺少安装路径：${relative}`);
    for (const entry of matching) {
      if (entry.isDirectory) continue;
      const suffix = entry.entryName.slice(sourcePrefix.length);
      const safe = safeRelativePath(suffix);
      const destination = path.join(stageRoot, ...safe.split("/"));
      fs.mkdirSync(path.dirname(destination), { recursive: true, mode: 0o700 });
      const executable = /\.(?:command|sh)$/i.test(safe) || safe.includes("/scripts/");
      fs.writeFileSync(destination, entry.getData(), { mode: executable ? 0o700 : 0o600 });
    }
  }
}

function executeGenericInstall({
  plan,
  registryPath,
  artifactSha256,
}) {
  if (!plan.ready) throw new Error("安装计划仍存在未处理冲突，禁止执行");
  const registry = loadRegistry(registryPath);
  const installId = timestampId();
  const targetRoot = path.resolve(plan.targetRoot);
  const internalRoot = path.join(targetRoot, ".jiaotang-skills-manager");
  const stageRoot = path.join(internalRoot, "staging", installId);
  const backupRoot = path.join(internalRoot, "backups", installId);
  fs.mkdirSync(stageRoot, { recursive: true, mode: 0o700 });
  fs.mkdirSync(backupRoot, { recursive: true, mode: 0o700 });
  const zip = new AdmZip(plan.archivePath);
  copyToStage(zip, plan, stageRoot);
  const backupEntries = [];
  for (const relative of plan.entries) {
    const destination = path.join(targetRoot, ...relative.split("/"));
    const staged = path.join(stageRoot, ...relative.split("/"));
    const backup = path.join(backupRoot, ...relative.split("/"));
    const existed = fs.existsSync(destination);
    backupEntries.push({ relative, existed });
    if (existed) {
      fs.mkdirSync(path.dirname(backup), { recursive: true, mode: 0o700 });
      fs.renameSync(destination, backup);
    }
    fs.mkdirSync(path.dirname(destination), { recursive: true, mode: 0o700 });
    fs.renameSync(staged, destination);
  }
  const previous = registry.targets[targetRoot] || null;
  registry.targets[targetRoot] = {
    version: plan.version,
    releaseTag: plan.releaseTag,
    artifactSha256,
    platformIds: plan.platformIds,
    skillCount: plan.skillCount,
    managedEntries: plan.entries,
    installedAt: new Date().toISOString(),
  };
  registry.backups.unshift({
    id: installId,
    targetRoot,
    backupRoot,
    entries: backupEntries,
    previous,
    createdAt: new Date().toISOString(),
  });
  saveRegistry(registryPath, registry);
  return {
    status: "installed",
    installId,
    targetRoot,
    version: plan.version,
    skillCount: plan.skillCount,
    backupRoot,
  };
}

function rollbackLatest({ targetRoot, registryPath }) {
  const registry = loadRegistry(registryPath);
  const resolvedTarget = path.resolve(targetRoot);
  const backup = registry.backups.find((item) => item.targetRoot === resolvedTarget);
  if (!backup) throw new Error("没有可用于当前目标的回滚记录");
  const displacedRoot = path.join(
    resolvedTarget,
    ".jiaotang-skills-manager",
    "displaced",
    `${timestampId()}-rollback`,
  );
  for (const item of backup.entries) {
    const current = path.join(resolvedTarget, ...item.relative.split("/"));
    if (fs.existsSync(current)) {
      const displaced = path.join(displacedRoot, ...item.relative.split("/"));
      fs.mkdirSync(path.dirname(displaced), { recursive: true, mode: 0o700 });
      fs.renameSync(current, displaced);
    }
    if (item.existed) {
      const saved = path.join(backup.backupRoot, ...item.relative.split("/"));
      if (!fs.existsSync(saved)) throw new Error(`回滚备份缺失：${item.relative}`);
      fs.mkdirSync(path.dirname(current), { recursive: true, mode: 0o700 });
      fs.renameSync(saved, current);
    }
  }
  if (backup.previous) {
    registry.targets[resolvedTarget] = backup.previous;
  } else {
    delete registry.targets[resolvedTarget];
  }
  registry.backups = registry.backups.filter((item) => item.id !== backup.id);
  saveRegistry(registryPath, registry);
  return {
    status: "rolled-back",
    targetRoot: resolvedTarget,
    displacedRoot,
    restoredVersion: backup.previous?.version || null,
  };
}

module.exports = {
  findSuiteManifest,
  genericInstallEntries,
  planGenericInstall,
  executeGenericInstall,
  rollbackLatest,
};
