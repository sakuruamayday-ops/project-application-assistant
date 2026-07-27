import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const AdmZip = require("adm-zip");
const { validateArchiveEntries, verifySkillArchive } = require("../core/security.cjs");
const { signedHeaders } = require("../core/device-auth.cjs");

function run(command, args) {
  const result = spawnSync(command, args, { encoding: "utf8" });
  assert.equal(result.status, 0, result.stderr || result.stdout);
  return result;
}

test("archive audit rejects path traversal", () => {
  const fakeZip = {
    getEntries: () => [{
      entryName: "../escape.txt",
      header: { size: 1 },
    }],
  };
  assert.throws(() => validateArchiveEntries(fakeZip), /不安全的归档路径/);
});

test("verifier accepts a pinned OpenSSH Ed25519 manifest and every listed file", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "jiaotang-manager-signature-"));
  const keyPath = path.join(root, "release-key");
  run("ssh-keygen", ["-q", "-t", "ed25519", "-N", "", "-f", keyPath]);
  const publicKey = fs.readFileSync(`${keyPath}.pub`, "utf8");
  const fingerprint = run("ssh-keygen", ["-lf", `${keyPath}.pub`, "-E", "sha256"])
    .stdout.match(/SHA256:[^\s]+/)[0];
  const payload = Buffer.from("signed payload\n");
  const manifest = {
    files: {
      "payload.txt": crypto.createHash("sha256").update(payload).digest("hex"),
    },
  };
  const manifestPath = path.join(root, "plugin-release-manifest.json");
  fs.writeFileSync(manifestPath, JSON.stringify(manifest));
  run("ssh-keygen", [
    "-Y", "sign",
    "-f", keyPath,
    "-n", "codex-workbuddy-plugin-manifest",
    manifestPath,
  ]);
  const metadata = {
    public_key_fingerprint: fingerprint,
    signature_namespace: "codex-workbuddy-plugin-manifest",
  };
  const archivePath = path.join(root, "signed.zip");
  const zip = new AdmZip();
  zip.addFile("jiaotang/payload.txt", payload);
  zip.addLocalFile(manifestPath, "jiaotang");
  zip.addLocalFile(`${manifestPath}.sig`, "jiaotang");
  zip.addFile("jiaotang/plugin-release-signature.json", Buffer.from(JSON.stringify(metadata)));
  zip.addFile("jiaotang/publisher-ed25519.pub", Buffer.from(publicKey));
  zip.writeZip(archivePath);

  const archiveSha = crypto.createHash("sha256").update(fs.readFileSync(archivePath)).digest("hex");
  const result = verifySkillArchive({
    archivePath,
    expectedSha256: archiveSha,
    securityConfig: {
      publisher: {
        identity: "jiaotang-codex-skill-release",
        ed25519_fingerprint: fingerprint,
      },
    },
  });
  assert.equal(result.status, "verified");
  assert.equal(result.signatures, 1);
  assert.equal(result.verifiedFiles, 1);
});

test("existing device credentials produce a verifiable request signature", () => {
  const { publicKey, privateKey } = crypto.generateKeyPairSync("ed25519");
  const credentials = {
    token: "member-token",
    privateKey: privateKey.export({ type: "pkcs8", format: "pem" }).toString(),
    deviceId: "device:test-existing-binding",
    deviceName: "Existing Mac",
    keyId: "ed25519:test",
  };
  const url = "https://zshjiaotang.cn/v1/skills/channels";
  const headers = signedHeaders(credentials, "GET", url);
  const canonical = Buffer.from([
    "JIAOTANG-SIGNATURE-V1",
    "GET",
    "/v1/skills/channels",
    headers["X-Jiaotang-Timestamp"],
    headers["X-Jiaotang-Nonce"],
    crypto.createHash("sha256").update(Buffer.alloc(0)).digest("hex"),
    crypto.createHash("sha256").update(credentials.token).digest("hex"),
  ].join("\n"));
  assert.equal(
    crypto.verify(
      null,
      canonical,
      publicKey,
      Buffer.from(headers["X-Jiaotang-Signature"], "base64url"),
    ),
    true,
  );
});
