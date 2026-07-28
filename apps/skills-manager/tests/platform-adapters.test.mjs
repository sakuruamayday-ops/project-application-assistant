import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const {
  loadLatestAdapterBundle,
  parseAdapterBundle,
  storeAdapterBundle,
  validatePlatformConfig,
} = require("../core/platform-adapters.cjs");
const { appendAuditEvent, verifyAuditChain } = require("../core/audit.cjs");
const { sha256 } = require("../core/security.cjs");

function run(command, args) {
  const result = spawnSync(command, args, { encoding: "utf8" });
  assert.equal(result.status, 0, result.stderr || result.stdout);
  return (result.stdout || result.stderr).trim();
}

function signedBundle(config, signer = null) {
  const root = signer?.root || fs.mkdtempSync(path.join(os.tmpdir(), "jiaotang-adapters-test-"));
  const privateKey = signer?.privateKey || path.join(root, "publisher");
  const manifestPath = path.join(root, `platform-adapters-${config.sequence}.json`);
  if (!signer) run("ssh-keygen", ["-q", "-t", "ed25519", "-N", "", "-f", privateKey]);
  const publicKey = signer?.publicKey || fs.readFileSync(`${privateKey}.pub`, "utf8").trim();
  const fingerprint = signer?.fingerprint || run(
    "ssh-keygen",
    ["-lf", `${privateKey}.pub`, "-E", "sha256"],
  ).split(/\s+/)[1];
  const manifest = Buffer.from(`${JSON.stringify(config, null, 2)}\n`);
  fs.writeFileSync(manifestPath, manifest);
  run("ssh-keygen", [
    "-Y",
    "sign",
    "-f",
    privateKey,
    "-n",
    "jiaotang-skills-manager-platform-adapters",
    manifestPath,
  ]);
  const signature = fs.readFileSync(`${manifestPath}.sig`);
  const metadata = {
    schema: "jiaotang-skills-manager-adapter-signature/v1",
    sequence: config.sequence,
    revision: config.revision,
    identity: "test-publisher",
    signature_namespace: "jiaotang-skills-manager-platform-adapters",
    public_key_fingerprint: fingerprint,
    manifest_sha256: sha256(manifest),
  };
  const securityConfig = {
    publisher: {
      identity: "test-publisher",
      ed25519_fingerprint: fingerprint,
      public_key: publicKey,
    },
    platform_adapters: {
      namespace: "jiaotang-skills-manager-platform-adapters",
      maximum_bytes: 262144,
    },
  };
  return {
    manifest,
    signature,
    metadata,
    securityConfig,
    signer: { root, privateKey, publicKey, fingerprint },
  };
}

function adapterConfig(revision = "2026.07.28.1", sequence = 2026072801) {
  return {
    schema: "jiaotang-skills-manager-platforms/v1",
    sequence,
    revision,
    published_at: "2026-07-28T10:30:00+08:00",
    minimum_manager_version: "0.2.0",
    platforms: [{
      id: "test-agent",
      name: "Test Agent",
      vendor: "test",
      support: "full",
      channel: "generic",
      install_mode: "managed-directory",
      notes: "test",
      darwin: { applications: ["/Applications/Test.app"], managed_roots: ["~/.test/skills"] },
      win32: {
        applications: ["%LOCALAPPDATA%/Programs/Test/Test.exe"],
        managed_roots: ["%USERPROFILE%/.test/skills"],
      },
    }],
  };
}

test("signed remote platform adapters verify and survive an audited cache reload", () => {
  const config = adapterConfig();
  const source = signedBundle(config);
  const bundle = parseAdapterBundle({
    ...source,
    managerVersion: "0.2.0",
  });
  assert.equal(bundle.config.revision, config.revision);
  assert.equal(bundle.verification.status, "verified");

  const cache = fs.mkdtempSync(path.join(os.tmpdir(), "jiaotang-adapters-cache-"));
  storeAdapterBundle(cache, bundle);
  const loaded = loadLatestAdapterBundle(cache, source.securityConfig, "0.2.0");
  assert.equal(loaded.config.revision, config.revision);
  assert.equal(loaded.verification.sha256, bundle.verification.sha256);
});

test("platform adapter schema rejects executable or unknown fields", () => {
  const config = adapterConfig();
  config.platforms[0].command = "rm -rf /";
  assert.throws(
    () => validatePlatformConfig(config, "0.2.0"),
    /未允许字段/,
  );
});

test("platform adapter requires a compatible manager version", () => {
  const config = adapterConfig();
  config.minimum_manager_version = "0.3.0";
  assert.throws(
    () => validatePlatformConfig(config, "0.2.0"),
    /至少需要管理器 0.3.0/,
  );
});

test("adapter cache uses signed numeric sequence and rejects replay below the built-in floor", () => {
  const cache = fs.mkdtempSync(path.join(os.tmpdir(), "jiaotang-adapters-order-"));
  const older = signedBundle(adapterConfig("2026.07.28.9", 9));
  const newer = signedBundle(adapterConfig("2026.07.28.10", 10), older.signer);
  storeAdapterBundle(cache, parseAdapterBundle({ ...older, managerVersion: "0.2.0" }));
  storeAdapterBundle(cache, parseAdapterBundle({ ...newer, managerVersion: "0.2.0" }));
  const loaded = loadLatestAdapterBundle(
    cache,
    older.securityConfig,
    "0.2.0",
    process.platform,
    10,
  );
  assert.equal(loaded.config.sequence, 10);
  assert.equal(loaded.config.revision, "2026.07.28.10");

  const replayOnly = fs.mkdtempSync(path.join(os.tmpdir(), "jiaotang-adapters-replay-"));
  storeAdapterBundle(replayOnly, parseAdapterBundle({ ...older, managerVersion: "0.2.0" }));
  const rejected = loadLatestAdapterBundle(
    replayOnly,
    older.securityConfig,
    "0.2.0",
    process.platform,
    10,
  );
  assert.match(rejected.error, /低于内置下限/);
});

test("audit log redacts secrets and remains append-only", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "jiaotang-audit-test-"));
  const destination = appendAuditEvent(root, "portal-connect", "completed", {
    token: "must-not-leak",
    nested: { bootstrapUrl: "must-not-leak", revision: "1" },
  });
  appendAuditEvent(root, "platform-scan", "completed", { detected: 2 });
  const lines = fs.readFileSync(destination, "utf8").trim().split("\n").map(JSON.parse);
  assert.equal(lines.length, 2);
  assert.equal(lines[0].details.token, "[REDACTED]");
  assert.equal(lines[0].details.nested.bootstrapUrl, "[REDACTED]");
  assert.equal(lines[0].details.nested.revision, "1");
  assert.equal(lines[1].previous_hash, lines[0].event_hash);
  assert.deepEqual(verifyAuditChain(root), {
    status: "verified",
    count: 2,
    lastHash: lines[1].event_hash,
  });
  const tampered = fs.readFileSync(destination, "utf8").replace('"detected":2', '"detected":3');
  fs.writeFileSync(destination, tampered);
  assert.throws(() => verifyAuditChain(root), /哈希不匹配/);
});
