import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const {
  automaticDetectedTargets,
  detectPlatforms,
  uniqueManagedTargets,
} = require("../core/platforms.cjs");

test("platform detection deduplicates a shared managed directory", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "jiaotang-manager-platform-"));
  const shared = path.join(root, "shared-skills");
  const appPath = path.join(root, "TRAE.app");
  fs.mkdirSync(shared, { recursive: true });
  fs.mkdirSync(appPath, { recursive: true });
  const base = {
    vendor: "test",
    support: "full",
    channel: "generic",
    install_mode: "shared-agents-directory",
    notes: "",
  };
  const detected = detectPlatforms({
    platforms: [
      {
        ...base,
        id: "trae",
        name: "TRAE",
        darwin: { applications: [appPath], managed_roots: [shared] },
      },
      {
        ...base,
        id: "kimi",
        name: "Kimi",
        darwin: { applications: [], managed_roots: [shared] },
      },
    ],
  }, "darwin");
  assert.equal(detected[0].detected, true);
  assert.equal(detected[0].canInstallAutomatically, true);
  const targets = uniqueManagedTargets(detected);
  assert.equal(targets.length, 1);
  assert.deepEqual(targets[0].platformIds, ["trae", "kimi"]);
});

test("bounded discovery finds a supported app outside the configured exact path", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "jiaotang-manager-discovery-"));
  const nested = path.join(root, "vendor", "TRAE.app");
  fs.mkdirSync(nested, { recursive: true });
  const detected = detectPlatforms({
    platforms: [{
      id: "trae",
      name: "TRAE",
      vendor: "test",
      support: "full",
      channel: "generic",
      install_mode: "managed-directory",
      notes: "",
      darwin: {
        applications: ["/Applications/TRAE.app"],
        managed_roots: [path.join(root, "skills")],
      },
    }],
  }, "darwin", { discoveryRoots: [root], maxDepth: 2 });
  assert.equal(detected[0].detected, true);
  assert.deepEqual(detected[0].detectedPaths, [nested]);
});

test("one-click targets include only detected automatic platforms", () => {
  const targets = automaticDetectedTargets([
    { id: "trae", detected: true, canInstallAutomatically: true, targetRoot: "/tmp/skills" },
    { id: "kimi", detected: false, canInstallAutomatically: true, targetRoot: "/tmp/agents" },
    { id: "qoder", detected: true, canInstallAutomatically: false, targetRoot: null },
  ]);
  assert.deepEqual(targets, [{ targetRoot: "/tmp/skills", platformIds: ["trae"] }]);
});
