const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const crypto = require("node:crypto");
const { spawnSync } = require("node:child_process");
const AdmZip = require("adm-zip");
const { safeRelativePath } = require("./paths.cjs");

function sha256(data) {
  return crypto.createHash("sha256").update(data).digest("hex");
}

function commandResult(command, args, options = {}) {
  const result = spawnSync(command, args, {
    encoding: "utf8",
    windowsHide: true,
    timeout: options.timeout || 15_000,
    input: options.input,
  });
  return {
    ok: result.status === 0,
    status: result.status,
    stdout: result.stdout || "",
    stderr: result.stderr || "",
    error: result.error ? String(result.error.message || result.error) : null,
  };
}

function sshKeygenPath(platform = process.platform) {
  if (platform === "win32") {
    const windows = process.env.WINDIR || "C:\\Windows";
    const candidate = path.join(windows, "System32", "OpenSSH", "ssh-keygen.exe");
    return fs.existsSync(candidate) ? candidate : "ssh-keygen.exe";
  }
  return "ssh-keygen";
}

function inspectApplicationTrust(executablePath, platform = process.platform) {
  if (platform === "darwin") {
    const bundlePath = executablePath.includes(".app/")
      ? `${executablePath.slice(0, executablePath.indexOf(".app/"))}.app`
      : executablePath;
    const signature = commandResult("codesign", ["--verify", "--deep", "--strict", "--verbose=2", bundlePath]);
    const assessment = commandResult("spctl", ["--assess", "--type", "execute", "--verbose=4", bundlePath]);
    return {
      platform,
      signed: signature.ok,
      trustedByOs: assessment.ok,
      summary: signature.ok && assessment.ok
        ? "Developer ID 签名与 Gatekeeper 评估通过"
        : "当前构建未通过 Developer ID/Gatekeeper 完整评估",
      details: [signature.stderr, assessment.stderr].filter(Boolean).join("\n").trim(),
    };
  }
  if (platform === "win32") {
    const escaped = executablePath.replaceAll("'", "''");
    const script = `$s=Get-AuthenticodeSignature -LiteralPath '${escaped}'; $s | Select-Object Status,StatusMessage,SignerCertificate | ConvertTo-Json -Depth 4 -Compress`;
    const result = commandResult("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", script]);
    let payload = null;
    try {
      payload = JSON.parse(result.stdout);
    } catch {
      payload = null;
    }
    const trusted = result.ok && payload?.Status === "Valid";
    return {
      platform,
      signed: Boolean(payload?.SignerCertificate),
      trustedByOs: trusted,
      summary: trusted ? "Authenticode 签名验证通过" : "当前构建未通过 Authenticode 完整验证",
      details: payload?.StatusMessage || result.stderr || result.error || "",
    };
  }
  return {
    platform,
    signed: false,
    trustedByOs: false,
    summary: "当前系统没有配置桌面发行签名检查",
    details: "",
  };
}

function validateArchiveEntries(zip) {
  const seen = new Set();
  let expandedBytes = 0;
  for (const entry of zip.getEntries()) {
    const normalized = safeRelativePath(entry.entryName);
    if (seen.has(normalized)) throw new Error(`归档包含重复路径：${normalized}`);
    seen.add(normalized);
    expandedBytes += Number(entry.header?.size || 0);
    if (expandedBytes > 1024 * 1024 * 1024) throw new Error("归档解压后超过 1 GiB 安全上限");
  }
  return { entries: seen.size, expandedBytes };
}

function parseJsonEntry(zip, entryName) {
  const entry = zip.getEntry(entryName);
  if (!entry) throw new Error(`归档缺少 ${entryName}`);
  try {
    return JSON.parse(entry.getData().toString("utf8"));
  } catch {
    throw new Error(`${entryName} 不是有效 JSON`);
  }
}

function verifyPublicKeyFingerprint(publicKey, expectedFingerprint, temporaryDirectory, platform) {
  const keyPath = path.join(temporaryDirectory, "publisher-ed25519.pub");
  fs.writeFileSync(keyPath, publicKey, { mode: 0o600 });
  const result = commandResult(sshKeygenPath(platform), ["-lf", keyPath, "-E", "sha256"]);
  if (!result.ok || !result.stdout.includes(expectedFingerprint)) {
    throw new Error(`发布公钥指纹不匹配：${result.stderr || result.stdout || result.error || "无法读取"}`);
  }
}

function verifyOpenSshSignature({
  manifest,
  signature,
  publicKey,
  namespace,
  identity,
  temporaryDirectory,
  platform,
}) {
  const allowedSigners = path.join(temporaryDirectory, "allowed_signers");
  const signaturePath = path.join(temporaryDirectory, `manifest-${crypto.randomUUID()}.sig`);
  fs.writeFileSync(allowedSigners, `${identity} ${publicKey.trim()}\n`, { mode: 0o600 });
  fs.writeFileSync(signaturePath, signature, { mode: 0o600 });
  const result = commandResult(
    sshKeygenPath(platform),
    ["-Y", "verify", "-f", allowedSigners, "-I", identity, "-n", namespace, "-s", signaturePath],
    { input: manifest },
  );
  if (!result.ok) {
    throw new Error(`Ed25519 签名验证失败：${result.stderr || result.stdout || result.error || "未知原因"}`);
  }
}

function verifyManifestFiles(zip, manifestEntryName, manifest) {
  const base = path.posix.dirname(manifestEntryName);
  const files = manifest.files;
  if (!files || typeof files !== "object" || Array.isArray(files)) {
    throw new Error(`${manifestEntryName} 缺少 files 哈希表`);
  }
  let verified = 0;
  for (const [relative, expected] of Object.entries(files)) {
    const safe = safeRelativePath(relative);
    const full = `${base}/${safe}`;
    const entry = zip.getEntry(full);
    if (!entry) throw new Error(`清单记录的文件缺失：${full}`);
    const actual = sha256(entry.getData());
    if (actual !== String(expected).toLowerCase()) {
      throw new Error(`文件哈希不匹配：${full}`);
    }
    verified += 1;
  }
  return verified;
}

function signatureUnits(zip) {
  const names = zip.getEntries().map((entry) => entry.entryName);
  const pluginManifest = names.find((name) => name.endsWith("/plugin-release-manifest.json"));
  if (pluginManifest) {
    return [{
      manifestEntry: pluginManifest,
      signatureEntry: `${pluginManifest}.sig`,
      metadataEntry: pluginManifest.replace("plugin-release-manifest.json", "plugin-release-signature.json"),
      publicKeyEntry: pluginManifest.replace("plugin-release-manifest.json", "publisher-ed25519.pub"),
      kind: "workbuddy-plugin",
    }];
  }
  return names
    .filter((name) => name.endsWith("/release-manifest.json"))
    .map((manifestEntry) => ({
      manifestEntry,
      signatureEntry: `${manifestEntry}.sig`,
      metadataEntry: manifestEntry.replace("release-manifest.json", "release-signature.json"),
      publicKeyEntry: manifestEntry.replace("release-manifest.json", "publisher-ed25519.pub"),
      kind: "skill",
    }));
}

function verifySkillArchive({
  archivePath,
  expectedSha256,
  securityConfig,
  platform = process.platform,
}) {
  const archive = fs.readFileSync(archivePath);
  const actualArchiveSha = sha256(archive);
  if (expectedSha256 && actualArchiveSha !== expectedSha256.toLowerCase()) {
    throw new Error(`下载包 SHA-256 不匹配：期望 ${expectedSha256}，实际 ${actualArchiveSha}`);
  }
  const zip = new AdmZip(archive);
  const entryAudit = validateArchiveEntries(zip);
  const units = signatureUnits(zip);
  if (!units.length) throw new Error("归档没有可验证的签名清单");
  const temporaryDirectory = fs.mkdtempSync(path.join(os.tmpdir(), "jiaotang-signature-"));
  let verifiedFiles = 0;
  try {
    for (const unit of units) {
      const manifestEntry = zip.getEntry(unit.manifestEntry);
      const signatureEntry = zip.getEntry(unit.signatureEntry);
      const publicKeyEntry = zip.getEntry(unit.publicKeyEntry);
      if (!manifestEntry || !signatureEntry || !publicKeyEntry) {
        throw new Error(`${unit.manifestEntry} 的签名伴随物不完整`);
      }
      const metadata = parseJsonEntry(zip, unit.metadataEntry);
      const publicKey = publicKeyEntry.getData().toString("utf8");
      const expectedFingerprint = securityConfig.publisher.ed25519_fingerprint;
      if (metadata.public_key_fingerprint !== expectedFingerprint) {
        throw new Error(`${unit.metadataEntry} 声明了未受信任的发布公钥`);
      }
      verifyPublicKeyFingerprint(publicKey, expectedFingerprint, temporaryDirectory, platform);
      verifyOpenSshSignature({
        manifest: manifestEntry.getData(),
        signature: signatureEntry.getData(),
        publicKey,
        namespace: metadata.signature_namespace,
        identity: securityConfig.publisher.identity,
        temporaryDirectory,
        platform,
      });
      verifiedFiles += verifyManifestFiles(
        zip,
        unit.manifestEntry,
        JSON.parse(manifestEntry.getData().toString("utf8")),
      );
    }
  } finally {
    fs.rmSync(temporaryDirectory, { recursive: true, force: true });
  }
  return {
    status: "verified",
    archiveSha256: actualArchiveSha,
    entries: entryAudit.entries,
    expandedBytes: entryAudit.expandedBytes,
    signatures: units.length,
    verifiedFiles,
    artifactType: units[0].kind,
    publisherFingerprint: securityConfig.publisher.ed25519_fingerprint,
  };
}

module.exports = {
  sha256,
  inspectApplicationTrust,
  validateArchiveEntries,
  verifySkillArchive,
};
