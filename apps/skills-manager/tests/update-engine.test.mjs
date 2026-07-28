import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const AdmZip = require("adm-zip");
const {
  planGenericInstall,
  executeGenericInstall,
  rollbackLatest,
} = require("../core/update-engine.cjs");

function fixtureArchive(root, marker, { extraFiles = {} } = {}) {
  const archive = path.join(root, `generic-${marker}.zip`);
  const zip = new AdmZip();
  zip.addFile("bundle/skills/suite-manifest.json", Buffer.from(JSON.stringify({
    release: { version: marker, tag: `V${marker}` },
    skills: ["alpha"],
    shared_paths: ["_shared/policy.md"],
  })));
  zip.addFile("bundle/skills/alpha/SKILL.md", Buffer.from(`# alpha ${marker}\n`));
  zip.addFile("bundle/skills/alpha/scripts/check.sh", Buffer.from("#!/bin/sh\nexit 0\n"));
  zip.addFile("bundle/skills/_shared/policy.md", Buffer.from(`policy ${marker}\n`));
  for (const [name, content] of Object.entries(extraFiles)) {
    zip.addFile(name, Buffer.from(content));
  }
  zip.writeZip(archive);
  return archive;
}

function fixtureVerification(archive, { exclude = [] } = {}) {
  const zip = new AdmZip(archive);
  const excluded = new Set(exclude);
  return {
    status: "verified",
    artifactType: "generic-skills",
    archiveSha256: crypto.createHash("sha256").update(fs.readFileSync(archive)).digest("hex"),
    verifiedFileAllowlist: zip.getEntries()
      .filter((entry) => !entry.isDirectory && !excluded.has(entry.entryName))
      .map((entry) => entry.entryName),
  };
}

test("generic update blocks unmanaged conflicts and preserves rollback", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "jiaotang-manager-update-"));
  const target = path.join(root, "skills");
  const registry = path.join(root, "state", "registry.json");
  fs.mkdirSync(path.join(target, "alpha"), { recursive: true });
  fs.writeFileSync(path.join(target, "alpha", "SKILL.md"), "user-owned\n");

  const firstArchive = fixtureArchive(root, "1.0.0");
  const firstVerification = fixtureVerification(firstArchive);
  const blocked = planGenericInstall({
    archivePath: firstArchive,
    targetRoot: target,
    registryPath: registry,
    platformIds: ["trae"],
    verification: firstVerification,
  });
  assert.equal(blocked.ready, false);
  assert.deepEqual(blocked.conflicts, ["alpha"]);

  const cleanTarget = path.join(root, "managed-skills");
  const firstPlan = planGenericInstall({
    archivePath: firstArchive,
    targetRoot: cleanTarget,
    registryPath: registry,
    platformIds: ["trae", "kimi-code"],
    verification: firstVerification,
  });
  const first = executeGenericInstall({
    plan: firstPlan,
    registryPath: registry,
    artifactSha256: firstVerification.archiveSha256,
  });
  assert.equal(first.status, "installed");
  assert.match(fs.readFileSync(path.join(cleanTarget, "alpha", "SKILL.md"), "utf8"), /1\.0\.0/);
  assert.equal(fs.statSync(path.join(cleanTarget, "alpha", "scripts", "check.sh")).mode & 0o700, 0o700);

  const secondArchive = fixtureArchive(root, "1.1.0");
  const secondVerification = fixtureVerification(secondArchive);
  const secondPlan = planGenericInstall({
    archivePath: secondArchive,
    targetRoot: cleanTarget,
    registryPath: registry,
    platformIds: ["trae", "kimi-code"],
    verification: secondVerification,
  });
  assert.equal(secondPlan.ready, true);
  assert.deepEqual(secondPlan.replacements.sort(), ["_shared/policy.md", "alpha"]);
  executeGenericInstall({
    plan: secondPlan,
    registryPath: registry,
    artifactSha256: secondVerification.archiveSha256,
  });
  assert.match(fs.readFileSync(path.join(cleanTarget, "alpha", "SKILL.md"), "utf8"), /1\.1\.0/);

  const stateBeforeRollback = JSON.parse(fs.readFileSync(registry, "utf8"));
  const latest = stateBeforeRollback.backups.find((item) => item.targetRoot === path.resolve(cleanTarget));
  const otherTarget = path.join(root, "same-id-other-target");
  stateBeforeRollback.backups.push({ ...latest, targetRoot: path.resolve(otherTarget) });
  fs.writeFileSync(registry, `${JSON.stringify(stateBeforeRollback, null, 2)}\n`);

  const rolledBack = rollbackLatest({ targetRoot: cleanTarget, registryPath: registry });
  assert.equal(rolledBack.restoredVersion, "1.0.0");
  assert.match(fs.readFileSync(path.join(cleanTarget, "alpha", "SKILL.md"), "utf8"), /1\.0\.0/);
  assert.equal(
    fs.readFileSync(path.join(rolledBack.displacedRoot, "alpha", "SKILL.md"), "utf8"),
    "# alpha 1.1.0\n",
  );
  const stateAfterRollback = JSON.parse(fs.readFileSync(registry, "utf8"));
  assert.equal(
    stateAfterRollback.backups.some((item) => (
      item.id === latest.id && item.targetRoot === path.resolve(otherTarget)
    )),
    true,
  );
});

test("generic plan rejects files under an install path that are absent from the signed allowlist", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "jiaotang-manager-unsigned-extra-"));
  const archive = fixtureArchive(root, "1.0.0", {
    extraFiles: {
      "bundle/skills/alpha/unsigned-hook.js": "throw new Error('unsigned');\n",
    },
  });
  const verification = fixtureVerification(archive, {
    exclude: ["bundle/skills/alpha/unsigned-hook.js"],
  });
  assert.throws(
    () => planGenericInstall({
      archivePath: archive,
      targetRoot: path.join(root, "skills"),
      registryPath: path.join(root, "registry.json"),
      verification,
    }),
    /未被签名清单覆盖/,
  );
});
