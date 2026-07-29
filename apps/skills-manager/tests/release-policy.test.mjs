import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(appRoot, "..", "..");
const require = createRequire(import.meta.url);
const packageMetadata = require("../package.json");
const unsignedConfig = require("../electron-builder.unsigned-local.cjs");
const releaseCheck = path.join(appRoot, "scripts", "release-security-check.mjs");

function unsignedPeBuffer() {
  const buffer = Buffer.alloc(512);
  buffer.write("MZ", 0, "ascii");
  buffer.writeUInt32LE(0x80, 0x3c);
  buffer.write("PE\u0000\u0000", 0x80, "ascii");
  buffer.writeUInt16LE(240, 0x80 + 20);
  buffer.writeUInt16LE(0x20b, 0x80 + 24);
  buffer.writeUInt32LE(16, 0x80 + 24 + 108);
  return buffer;
}

function runGate(args) {
  return spawnSync(process.execPath, [releaseCheck, ...args], {
    encoding: "utf8",
  });
}

test("unsigned-local packaging is explicit and versioned independently", () => {
  assert.equal(packageMetadata.version, "0.2.0");
  assert.equal(unsignedConfig.forceCodeSigning, false);
  assert.equal(unsignedConfig.mac.identity, null);
  assert.equal(unsignedConfig.mac.hardenedRuntime, false);
  assert.equal(unsignedConfig.win.signExecutable, false);
  assert.equal(unsignedConfig.win.signAndEditExecutable, true);
  assert.equal(unsignedConfig.win.verifyUpdateCodeSignature, false);
  assert.equal(
    unsignedConfig.artifactName,
    "Jiaotang-Skills-Manager-${version}-unsigned-local-${os}-${arch}.${ext}",
  );
  assert.match(packageMetadata.scripts["package:mac:unsigned-local"], /unsigned-local/);
  assert.match(packageMetadata.scripts["package:win:unsigned-local"], /unsigned-local/);
});

test("release workflow, portal manifest and Word manual share one immutable asset contract", () => {
  const workflow = fs.readFileSync(
    path.join(
      repoRoot,
      "docs",
      "archive",
      "workflows",
      "skills-manager-unsigned-release-v0.2.0.yml",
    ),
    "utf8",
  );
  const releaseNotes = fs.readFileSync(
    path.join(repoRoot, "docs", "releases", "skills-manager-v0.2.0.md"),
    "utf8",
  );
  const nativeRelease = JSON.parse(
    fs.readFileSync(
      path.join(
        repoRoot,
        "services",
        "knowledge-portal",
        "static",
        "skills-manager",
        "native-release.json",
      ),
      "utf8",
    ),
  );
  const expectedFiles = [
    "Jiaotang-Skills-Manager-0.2.0-unsigned-local-mac-arm64.dmg",
    "Jiaotang-Skills-Manager-0.2.0-unsigned-local-mac-x64.dmg",
    "Jiaotang-Skills-Manager-0.2.0-unsigned-local-win-x64.exe",
  ];
  assert.equal(nativeRelease.tag, "skills-manager-v0.2.0");
  assert.equal(
    nativeRelease.github_release_url,
    "https://github.com/sakuruamayday-ops/project-application-assistant/releases/tag/skills-manager-v0.2.0",
  );
  assert.match(workflow, /RELEASE_TAG: "skills-manager-v0\.2\.0"/);
  assert.ok(["pending", "published", "retired"].includes(nativeRelease.state));
  const isPublished = nativeRelease.state === "published";
  const isHistorical = ["published", "retired"].includes(nativeRelease.state);
  assert.equal(nativeRelease.available, isPublished);
  if (isHistorical) {
    assert.match(nativeRelease.published_at, /^\d{4}-\d{2}-\d{2}T.*Z$/);
  } else {
    assert.equal(nativeRelease.published_at, null);
  }
  assert.equal(nativeRelease.publication_policy, "release_then_reviewed_portal_backfill");
  assert.deepEqual(
    nativeRelease.artifacts.map((artifact) => artifact.file_name),
    expectedFiles,
  );
  for (const fileName of expectedFiles) {
    assert.match(workflow, new RegExp(fileName));
    assert.ok(releaseNotes.includes(`\`${fileName}\``));
  }
  for (const artifact of nativeRelease.artifacts) {
    assert.equal(artifact.available, isPublished);
    if (isHistorical) {
      assert.match(artifact.sha256, /^[0-9a-f]{64}$/);
    } else {
      assert.equal(artifact.sha256, "");
    }
  }
  assert.equal(
    nativeRelease.user_manual.file_name,
    "Jiaotang-Skills-Manager-0.2.0-User-Manual.docx",
  );
  assert.equal(nativeRelease.user_manual.available, isPublished);
  if (isHistorical) {
    assert.match(nativeRelease.user_manual.sha256, /^[0-9a-f]{64}$/);
  } else {
    assert.equal(nativeRelease.user_manual.sha256, "");
  }
  assert.match(workflow, /USER_MANUAL_SOURCE:/);
  assert.match(workflow, /USER_MANUAL_ASSET:/);
  assert.match(workflow, /RELEASE_NOTES_SOURCE: "docs\/releases\/skills-manager-v0\.2\.0\.md"/);
  assert.match(workflow, /--notes-file "\$\{RELEASE_NOTES_SOURCE\}"/);
  assert.doesNotMatch(workflow, /cat > release-notes\.md/);
  assert.match(workflow, /documentation:/);
  assert.match(workflow, /manual_sha/);
  assert.match(workflow, /native-release\.published\.json/);
  assert.match(workflow, /reviewed_backfill_required: true/);
  assert.ok(releaseNotes.includes("`Jiaotang-Skills-Manager-0.2.0-User-Manual.docx`"));
  assert.ok(releaseNotes.includes("`native-release.published.json`"));
});

test("WorkBuddy channel audit accepts only a fresh collection build", () => {
  const auditScript = fs.readFileSync(
    path.join(
      appRoot,
      "scripts",
      "build-workbuddy-channel-audit.mjs",
    ),
    "utf8",
  );
  assert.match(auditScript, /"source-audit"/);
  assert.match(auditScript, /fresh-collection-build/);
  assert.match(auditScript, /verifySkillArchive/);
  assert.match(auditScript, /outer_fixed_installers: false/);
  assert.doesNotMatch(auditScript, /repack-audit|legacy-repack/);
});

test("explicit unsigned-local mode accepts an unsigned PE and writes a release audit", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "jiaotang-release-gate-"));
  const artifact = path.join(
    root,
    "Jiaotang-Skills-Manager-0.2.0-unsigned-local-win-x64.exe",
  );
  const auditPath = path.join(root, "release-trust.json");
  const payload = unsignedPeBuffer();
  fs.writeFileSync(artifact, payload);

  const result = runGate([
    "--mode",
    "unsigned-local-authorization",
    "--artifact",
    artifact,
    "--audit-output",
    auditPath,
  ]);
  assert.equal(result.status, 0, result.stderr || result.stdout);
  const audit = JSON.parse(fs.readFileSync(auditPath, "utf8"));
  assert.equal(audit.schema, "jiaotang-skills-manager-release-audit/v1");
  assert.equal(audit.status, "pass");
  assert.equal(audit.mode, "unsigned-local-authorization");
  assert.equal(audit.manager_version, "0.2.0");
  assert.equal(audit.os_trust, "local-user-exception");
  assert.deepEqual(audit.target_platforms, ["win32"]);
  assert.equal(audit.artifacts[0].platform, "win32");
  assert.equal(audit.artifacts[0].local_authorization_required, true);
  assert.equal(
    audit.artifacts[0].sha256,
    crypto.createHash("sha256").update(payload).digest("hex"),
  );
  assert.deepEqual(audit.skills_content_scope, {
    bundled: false,
    verified: false,
    release_channel: "independent-portal-skills-channels",
    statement: "This desktop-client audit does not bundle or verify Skills content.",
  });
});

test("unsigned-local mode rejects artifacts without an explicit filename marker", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "jiaotang-release-name-"));
  const artifact = path.join(root, "Jiaotang-Skills-Manager-0.2.0-win-x64.exe");
  const auditPath = path.join(root, "release-trust.json");
  fs.writeFileSync(artifact, unsignedPeBuffer());

  const result = runGate([
    "--mode",
    "unsigned-local-authorization",
    "--artifact",
    artifact,
    "--audit-output",
    auditPath,
  ]);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /文件名必须包含 -unsigned-local-/);
  assert.equal(JSON.parse(fs.readFileSync(auditPath, "utf8")).status, "fail");
});

test("release gate rejects an artifact whose filename has a stale manager version", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "jiaotang-release-version-"));
  const artifact = path.join(
    root,
    "Jiaotang-Skills-Manager-0.1.0-unsigned-local-win-x64.exe",
  );
  fs.writeFileSync(artifact, unsignedPeBuffer());

  const result = runGate([
    "--mode",
    "unsigned-local-authorization",
    "--artifact",
    artifact,
  ]);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /文件名版本必须与管理器 0\.2\.0 一致/);
});

test("unsigned-local mode rejects a PE that contains an Authenticode certificate table", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "jiaotang-release-signed-pe-"));
  const artifact = path.join(
    root,
    "Jiaotang-Skills-Manager-0.2.0-unsigned-local-win-x64.exe",
  );
  const payload = unsignedPeBuffer();
  const certificateDirectory = 0x80 + 24 + 112 + (8 * 4);
  payload.writeUInt32LE(0x180, certificateDirectory);
  payload.writeUInt32LE(32, certificateDirectory + 4);
  fs.writeFileSync(artifact, payload);

  const result = runGate([
    "--mode",
    "unsigned-local-authorization",
    "--artifact",
    artifact,
  ]);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /包含 Authenticode 证书表/);
});

test("signed mode does not silently accept an unsigned-local artifact", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "jiaotang-release-signed-"));
  const artifact = path.join(
    root,
    "Jiaotang-Skills-Manager-0.2.0-unsigned-local-win-x64.exe",
  );
  fs.writeFileSync(artifact, unsignedPeBuffer());

  const result = runGate(["--artifact", artifact]);
  assert.notEqual(result.status, 0);
});
