import assert from "node:assert/strict";
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

function fixtureArchive(root, marker) {
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
  zip.writeZip(archive);
  return archive;
}

test("generic update blocks unmanaged conflicts and preserves rollback", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "jiaotang-manager-update-"));
  const target = path.join(root, "skills");
  const registry = path.join(root, "state", "registry.json");
  fs.mkdirSync(path.join(target, "alpha"), { recursive: true });
  fs.writeFileSync(path.join(target, "alpha", "SKILL.md"), "user-owned\n");

  const firstArchive = fixtureArchive(root, "1.0.0");
  const blocked = planGenericInstall({
    archivePath: firstArchive,
    targetRoot: target,
    registryPath: registry,
    platformIds: ["trae"],
  });
  assert.equal(blocked.ready, false);
  assert.deepEqual(blocked.conflicts, ["alpha"]);

  const cleanTarget = path.join(root, "managed-skills");
  const firstPlan = planGenericInstall({
    archivePath: firstArchive,
    targetRoot: cleanTarget,
    registryPath: registry,
    platformIds: ["trae", "kimi-code"],
  });
  const first = executeGenericInstall({
    plan: firstPlan,
    registryPath: registry,
    artifactSha256: "first-sha",
  });
  assert.equal(first.status, "installed");
  assert.match(fs.readFileSync(path.join(cleanTarget, "alpha", "SKILL.md"), "utf8"), /1\.0\.0/);
  assert.equal(fs.statSync(path.join(cleanTarget, "alpha", "scripts", "check.sh")).mode & 0o700, 0o700);

  const secondArchive = fixtureArchive(root, "1.1.0");
  const secondPlan = planGenericInstall({
    archivePath: secondArchive,
    targetRoot: cleanTarget,
    registryPath: registry,
    platformIds: ["trae", "kimi-code"],
  });
  assert.equal(secondPlan.ready, true);
  assert.deepEqual(secondPlan.replacements.sort(), ["_shared/policy.md", "alpha"]);
  executeGenericInstall({
    plan: secondPlan,
    registryPath: registry,
    artifactSha256: "second-sha",
  });
  assert.match(fs.readFileSync(path.join(cleanTarget, "alpha", "SKILL.md"), "utf8"), /1\.1\.0/);

  const rolledBack = rollbackLatest({ targetRoot: cleanTarget, registryPath: registry });
  assert.equal(rolledBack.restoredVersion, "1.0.0");
  assert.match(fs.readFileSync(path.join(cleanTarget, "alpha", "SKILL.md"), "utf8"), /1\.0\.0/);
  assert.equal(
    fs.readFileSync(path.join(rolledBack.displacedRoot, "alpha", "SKILL.md"), "utf8"),
    "# alpha 1.1.0\n",
  );
});
