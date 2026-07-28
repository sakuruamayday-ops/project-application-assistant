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

function signedPluginFixture(root, {
  metadataNamespace = "codex-workbuddy-plugin-manifest",
  signingNamespace = "codex-workbuddy-plugin-manifest",
  additionalPublicKey = "",
  tamperPayload = false,
  tamperSignature = false,
  extraFiles = {},
} = {}) {
  const keyPath = path.join(root, "fixture-key");
  run("ssh-keygen", ["-q", "-t", "ed25519", "-N", "", "-f", keyPath]);
  const publicKey = fs.readFileSync(`${keyPath}.pub`, "utf8");
  const fingerprint = run("ssh-keygen", ["-lf", `${keyPath}.pub`, "-E", "sha256"])
    .stdout.match(/SHA256:[^\s]+/)[0];
  const payload = Buffer.from("signed fixture payload\n");
  const manifest = {
    files: {
      "payload.txt": crypto.createHash("sha256").update(payload).digest("hex"),
    },
  };
  const manifestPath = path.join(root, "plugin-release-manifest.json");
  fs.writeFileSync(manifestPath, JSON.stringify(manifest));
  run("ssh-keygen", ["-Y", "sign", "-f", keyPath, "-n", signingNamespace, manifestPath]);
  let signature = fs.readFileSync(`${manifestPath}.sig`);
  if (tamperSignature) {
    signature = Buffer.from(signature);
    const index = signature.indexOf(0x41, signature.indexOf(0x0a) + 1);
    assert.notEqual(index, -1);
    signature[index] = 0x42;
  }
  const archivePath = path.join(root, "fixture.zip");
  const zip = new AdmZip();
  zip.addFile("jiaotang/payload.txt", tamperPayload ? Buffer.from("tampered\n") : payload);
  zip.addFile("jiaotang/plugin-release-manifest.json", fs.readFileSync(manifestPath));
  zip.addFile("jiaotang/plugin-release-manifest.json.sig", signature);
  zip.addFile("jiaotang/plugin-release-signature.json", Buffer.from(JSON.stringify({
    algorithm: "OpenSSH-Ed25519",
    public_key_fingerprint: fingerprint,
    signature_namespace: metadataNamespace,
    signed_file: "plugin-release-manifest.json",
    signature: "plugin-release-manifest.json.sig",
    public_key: "publisher-ed25519.pub",
  })));
  zip.addFile(
    "jiaotang/publisher-ed25519.pub",
    Buffer.from(`${publicKey.trim()}\n${additionalPublicKey}`),
  );
  for (const [name, content] of Object.entries(extraFiles)) {
    zip.addFile(name, Buffer.from(content));
  }
  zip.writeZip(archivePath);
  return {
    archivePath,
    securityConfig: {
      publisher: {
        identity: "jiaotang-codex-skill-release",
        ed25519_fingerprint: fingerprint,
        public_key: publicKey,
      },
    },
  };
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

test("archive audit rejects Unix symbolic links", () => {
  const fakeZip = {
    getEntries: () => [{
      entryName: "skill/link",
      attr: 0xa1ff0000,
      header: { size: 4 },
    }],
  };
  assert.throws(() => validateArchiveEntries(fakeZip), /符号链接/);
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
    algorithm: "OpenSSH-Ed25519",
    public_key_fingerprint: fingerprint,
    signature_namespace: "codex-workbuddy-plugin-manifest",
    signed_file: "plugin-release-manifest.json",
    signature: "plugin-release-manifest.json.sig",
    public_key: "publisher-ed25519.pub",
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
        public_key: publicKey,
      },
    },
    platform: "win32",
  });
  assert.equal(result.status, "verified");
  assert.equal(result.signatures, 1);
  assert.equal(result.verifiedFiles, 1);
  assert.deepEqual(result.signedContentAllowlist, ["jiaotang/payload.txt"]);
});

test("pinned fingerprint cannot be smuggled through an attacker key comment", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "jiaotang-manager-key-comment-"));
  const trustedKey = path.join(root, "trusted-key");
  const attackerKey = path.join(root, "attacker-key");
  run("ssh-keygen", ["-q", "-t", "ed25519", "-N", "", "-f", trustedKey]);
  run("ssh-keygen", ["-q", "-t", "ed25519", "-N", "", "-f", attackerKey]);
  const trustedFingerprint = run(
    "ssh-keygen",
    ["-lf", `${trustedKey}.pub`, "-E", "sha256"],
  ).stdout.match(/SHA256:[^\s]+/)[0];
  const attackerParts = fs.readFileSync(`${attackerKey}.pub`, "utf8").trim().split(/\s+/);
  const attackerPublicKey = `${attackerParts[0]} ${attackerParts[1]} forged-${trustedFingerprint}\n`;

  const payload = Buffer.from("attacker payload\n");
  const manifest = {
    files: {
      "payload.txt": crypto.createHash("sha256").update(payload).digest("hex"),
    },
  };
  const manifestPath = path.join(root, "plugin-release-manifest.json");
  fs.writeFileSync(manifestPath, JSON.stringify(manifest));
  run("ssh-keygen", [
    "-Y", "sign",
    "-f", attackerKey,
    "-n", "codex-workbuddy-plugin-manifest",
    manifestPath,
  ]);
  const archivePath = path.join(root, "forged.zip");
  const zip = new AdmZip();
  zip.addFile("jiaotang/payload.txt", payload);
  zip.addLocalFile(manifestPath, "jiaotang");
  zip.addLocalFile(`${manifestPath}.sig`, "jiaotang");
  zip.addFile("jiaotang/plugin-release-signature.json", Buffer.from(JSON.stringify({
    algorithm: "OpenSSH-Ed25519",
    public_key_fingerprint: trustedFingerprint,
    signature_namespace: "codex-workbuddy-plugin-manifest",
    signed_file: "plugin-release-manifest.json",
    signature: "plugin-release-manifest.json.sig",
    public_key: "publisher-ed25519.pub",
  })));
  zip.addFile("jiaotang/publisher-ed25519.pub", Buffer.from(attackerPublicKey));
  zip.writeZip(archivePath);

  assert.throws(
    () => verifySkillArchive({
      archivePath,
      expectedSha256: crypto
        .createHash("sha256")
        .update(fs.readFileSync(archivePath))
        .digest("hex"),
      securityConfig: {
        publisher: {
          identity: "jiaotang-codex-skill-release",
          ed25519_fingerprint: trustedFingerprint,
          public_key: fs.readFileSync(`${trustedKey}.pub`, "utf8"),
        },
      },
    }),
    /归档发布公钥与内置固定公钥不一致/,
  );
});

test("archive public key rejects a second appended key", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "jiaotang-manager-multiple-keys-"));
  const secondKey = path.join(root, "second-key");
  run("ssh-keygen", ["-q", "-t", "ed25519", "-N", "", "-f", secondKey]);
  const fixture = signedPluginFixture(root, {
    additionalPublicKey: fs.readFileSync(`${secondKey}.pub`, "utf8"),
  });
  assert.throws(
    () => verifySkillArchive(fixture),
    /必须且只能包含一把公钥/,
  );
});

test("fixed WorkBuddy namespace rejects metadata namespace substitution", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "jiaotang-manager-namespace-"));
  const fixture = signedPluginFixture(root, {
    metadataNamespace: "codex-skill-manifest",
  });
  assert.throws(
    () => verifySkillArchive(fixture),
    /签名命名空间不匹配/,
  );
});

test("native SSHSIG verification rejects a modified signature and needs no platform ssh-keygen", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "jiaotang-manager-native-sshsig-"));
  const fixture = signedPluginFixture(root, { tamperSignature: true });
  assert.throws(
    () => verifySkillArchive({ ...fixture, platform: "win32" }),
    /签名|SSHSIG|Base64/,
  );
});

test("verified WorkBuddy directory rejects an unsigned extra executable", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "jiaotang-manager-extra-file-"));
  const fixture = signedPluginFixture(root, {
    extraFiles: {
      "jiaotang/unsigned-installer.cmd": "@echo off\r\n",
    },
  });
  assert.throws(
    () => verifySkillArchive(fixture),
    /未被签名清单覆盖/,
  );
});

test("verified payload hash rejects content changed after signing", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "jiaotang-manager-tampered-payload-"));
  const fixture = signedPluginFixture(root, { tamperPayload: true });
  assert.throws(
    () => verifySkillArchive(fixture),
    /文件哈希不匹配/,
  );
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
