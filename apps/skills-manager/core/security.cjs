const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { spawnSync } = require("node:child_process");
const AdmZip = require("adm-zip");
const { safeRelativePath } = require("./paths.cjs");

const SIGNATURE_NAMESPACES = Object.freeze({
  generic: "codex-skill-manifest",
  genericSuite: "codex-skill-suite-manifest",
  workbuddy: "codex-workbuddy-plugin-manifest",
  platformAdapters: "jiaotang-skills-manager-platform-adapters",
});
const ALLOWED_SIGNATURE_NAMESPACES = new Set(Object.values(SIGNATURE_NAMESPACES));
const SSH_ED25519 = "ssh-ed25519";
const SSHSIG_MAGIC = Buffer.from("SSHSIG", "ascii");

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
    const unixMode = (Number(entry.attr || entry.header?.attr || 0) >>> 16) & 0xffff;
    if ((unixMode & 0xf000) === 0xa000) {
      throw new Error(`归档不得包含符号链接：${normalized}`);
    }
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

function sshString(value) {
  const data = Buffer.isBuffer(value) ? value : Buffer.from(value);
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length, 0);
  return Buffer.concat([length, data]);
}

class SshReader {
  constructor(buffer, label) {
    this.buffer = buffer;
    this.label = label;
    this.offset = 0;
  }

  bytes(length) {
    if (!Number.isSafeInteger(length) || length < 0 || this.offset + length > this.buffer.length) {
      throw new Error(`${this.label} 数据截断或长度非法`);
    }
    const value = this.buffer.subarray(this.offset, this.offset + length);
    this.offset += length;
    return value;
  }

  uint32() {
    return this.bytes(4).readUInt32BE(0);
  }

  string() {
    return this.bytes(this.uint32());
  }

  finish() {
    if (this.offset !== this.buffer.length) {
      throw new Error(`${this.label} 含未解析的尾随数据`);
    }
  }
}

function decodeStrictBase64(value, label) {
  const encoded = String(value);
  if (!encoded || !/^[A-Za-z0-9+/]+={0,2}$/.test(encoded) || encoded.length % 4 === 1) {
    throw new Error(`${label} 不是规范 Base64`);
  }
  const decoded = Buffer.from(encoded, "base64");
  if (decoded.toString("base64").replace(/=+$/u, "") !== encoded.replace(/=+$/u, "")) {
    throw new Error(`${label} 不是规范 Base64`);
  }
  return decoded;
}

function parseOpenSshEd25519PublicKey(value, label = "Ed25519 公钥") {
  const text = Buffer.isBuffer(value) ? value.toString("utf8") : String(value);
  if (text.includes("\0")) throw new Error(`${label} 含非法 NUL 字符`);
  const lines = text.trim().split(/\r?\n/u);
  if (lines.length !== 1) {
    throw new Error(`${label} 必须且只能包含一把公钥`);
  }
  const match = lines[0].match(/^ssh-ed25519[ \t]+([A-Za-z0-9+/=]+)(?:[ \t]+.*)?$/u);
  if (!match) throw new Error(`${label} 不是单行 OpenSSH Ed25519 公钥`);
  const blob = decodeStrictBase64(match[1], `${label}主体`);
  const reader = new SshReader(blob, label);
  const algorithm = reader.string().toString("ascii");
  const rawKey = reader.string();
  reader.finish();
  if (algorithm !== SSH_ED25519 || rawKey.length !== 32) {
    throw new Error(`${label} 不是有效 Ed25519 公钥`);
  }
  const canonicalBlob = Buffer.concat([sshString(SSH_ED25519), sshString(rawKey)]);
  if (!blob.equals(canonicalBlob)) throw new Error(`${label} 编码不规范`);
  const fingerprint = `SHA256:${crypto.createHash("sha256").update(blob).digest("base64").replace(/=+$/u, "")}`;
  const keyObject = crypto.createPublicKey({
    key: {
      kty: "OKP",
      crv: "Ed25519",
      x: rawKey.toString("base64url"),
    },
    format: "jwk",
  });
  return { blob, rawKey, fingerprint, keyObject };
}

function bindPinnedPublisherKey(suppliedPublicKey, publisher) {
  if (!publisher?.public_key || !publisher?.ed25519_fingerprint) {
    throw new Error("安全配置缺少固定发布公钥或指纹");
  }
  const pinned = parseOpenSshEd25519PublicKey(publisher.public_key, "内置发布公钥");
  if (pinned.fingerprint !== publisher.ed25519_fingerprint) {
    throw new Error("安全配置中的发布公钥与固定指纹不一致");
  }
  const supplied = parseOpenSshEd25519PublicKey(suppliedPublicKey, "归档发布公钥");
  if (!supplied.blob.equals(pinned.blob)) {
    throw new Error("归档发布公钥与内置固定公钥不一致");
  }
  return pinned;
}

function parseOpenSshSignature(value) {
  const text = Buffer.isBuffer(value) ? value.toString("utf8") : String(value);
  const match = text.trim().match(
    /^-----BEGIN SSH SIGNATURE-----\r?\n([A-Za-z0-9+/=\r\n]+)\r?\n-----END SSH SIGNATURE-----$/u,
  );
  if (!match) throw new Error("签名不是规范的 OpenSSH SSHSIG 文本");
  const encoded = match[1].replace(/\r?\n/gu, "");
  const blob = decodeStrictBase64(encoded, "OpenSSH SSHSIG");
  const reader = new SshReader(blob, "OpenSSH SSHSIG");
  if (!reader.bytes(SSHSIG_MAGIC.length).equals(SSHSIG_MAGIC)) {
    throw new Error("OpenSSH SSHSIG 魔数不正确");
  }
  const version = reader.uint32();
  const publicKeyBlob = reader.string();
  const namespace = reader.string();
  const reserved = reader.string();
  const hashAlgorithm = reader.string();
  const signatureBlob = reader.string();
  reader.finish();
  if (version !== 1) throw new Error(`不支持的 OpenSSH SSHSIG 版本：${version}`);

  const signatureReader = new SshReader(signatureBlob, "OpenSSH Ed25519 签名");
  const signatureAlgorithm = signatureReader.string().toString("ascii");
  const signature = signatureReader.string();
  signatureReader.finish();
  if (signatureAlgorithm !== SSH_ED25519 || signature.length !== 64) {
    throw new Error("OpenSSH SSHSIG 不是有效 Ed25519 签名");
  }
  return {
    publicKeyBlob,
    namespace,
    reserved,
    hashAlgorithm,
    signature,
  };
}

function verifyNativeOpenSshSignature({
  payload,
  signature,
  pinnedKey,
  namespace,
}) {
  if (!ALLOWED_SIGNATURE_NAMESPACES.has(namespace)) {
    throw new Error(`不允许的签名命名空间：${namespace}`);
  }
  const parsed = parseOpenSshSignature(signature);
  if (!parsed.publicKeyBlob.equals(pinnedKey.blob)) {
    throw new Error("签名内嵌公钥与内置固定公钥不一致");
  }
  if (parsed.namespace.toString("utf8") !== namespace) {
    throw new Error(`签名命名空间不匹配：期望 ${namespace}`);
  }
  if (parsed.reserved.length !== 0) {
    throw new Error("OpenSSH SSHSIG reserved 字段必须为空");
  }
  const hashName = parsed.hashAlgorithm.toString("ascii");
  if (hashName !== "sha256" && hashName !== "sha512") {
    throw new Error(`不支持的 OpenSSH SSHSIG 哈希算法：${hashName}`);
  }
  const payloadBuffer = Buffer.isBuffer(payload) ? payload : Buffer.from(payload);
  const payloadDigest = crypto.createHash(hashName).update(payloadBuffer).digest();
  const signedData = Buffer.concat([
    SSHSIG_MAGIC,
    sshString(namespace),
    sshString(parsed.reserved),
    sshString(hashName),
    sshString(payloadDigest),
  ]);
  if (!crypto.verify(null, signedData, pinnedKey.keyObject, parsed.signature)) {
    throw new Error("Ed25519 签名验证失败");
  }
}

function verifyDetachedOpenSshPayload({
  payload,
  signature,
  publicKey,
  pinnedPublicKey = publicKey,
  expectedFingerprint,
  namespace,
  identity,
}) {
  const publisher = {
    public_key: Buffer.isBuffer(pinnedPublicKey) ? pinnedPublicKey.toString("utf8") : String(pinnedPublicKey),
    ed25519_fingerprint: expectedFingerprint,
  };
  const pinnedKey = bindPinnedPublisherKey(publicKey, publisher);
  verifyNativeOpenSshSignature({
    payload,
    signature,
    pinnedKey,
    namespace,
  });
  return {
    status: "verified",
    sha256: sha256(payload),
    publisherFingerprint: expectedFingerprint,
    namespace,
    identity,
  };
}

function verifyManifestFiles(zip, manifestEntryName, manifest) {
  const base = path.posix.dirname(manifestEntryName);
  const files = manifest.files;
  if (!files || typeof files !== "object" || Array.isArray(files)) {
    throw new Error(`${manifestEntryName} 缺少 files 哈希表`);
  }
  const verifiedFiles = new Set();
  let verified = 0;
  for (const [relative, expected] of Object.entries(files)) {
    const safe = safeRelativePath(relative);
    if (!safe || safe.endsWith("/")) throw new Error(`${manifestEntryName} 包含非法文件路径：${relative}`);
    if (!/^[0-9a-f]{64}$/u.test(String(expected))) {
      throw new Error(`${manifestEntryName} 包含非法 SHA-256：${relative}`);
    }
    const full = base === "." ? safe : `${base}/${safe}`;
    const entry = zip.getEntry(full);
    if (!entry || entry.isDirectory) throw new Error(`清单记录的文件缺失：${full}`);
    const actual = sha256(entry.getData());
    if (actual !== expected) {
      throw new Error(`文件哈希不匹配：${full}`);
    }
    verifiedFiles.add(full);
    verified += 1;
  }
  return { verified, files: verifiedFiles };
}

function signatureUnits(zip) {
  const names = zip.getEntries().filter((entry) => !entry.isDirectory).map((entry) => entry.entryName);
  const pluginManifests = names.filter((name) => name.endsWith("/plugin-release-manifest.json"));
  const suiteManifests = names.filter((name) => name.endsWith("/suite-release-manifest.json"));
  const skillManifests = names.filter((name) => (
    name.endsWith("/release-manifest.json")
    && !name.endsWith("/plugin-release-manifest.json")
    && !name.endsWith("/suite-release-manifest.json")
  ));
  if (pluginManifests.length > 1 || suiteManifests.length > 1) {
    throw new Error("归档包含多个顶层签名清单");
  }
  if (pluginManifests.length) {
    const pluginManifest = pluginManifests[0];
    const pluginBase = `${path.posix.dirname(pluginManifest)}/`;
    if (
      suiteManifests.length
      || skillManifests.some((manifestEntry) => !manifestEntry.startsWith(pluginBase))
    ) {
      throw new Error("归档混合了 WorkBuddy 与通用技能签名格式");
    }
    return [{
      manifestEntry: pluginManifest,
      signatureEntry: `${pluginManifest}.sig`,
      metadataEntry: pluginManifest.replace("plugin-release-manifest.json", "plugin-release-signature.json"),
      publicKeyEntry: pluginManifest.replace("plugin-release-manifest.json", "publisher-ed25519.pub"),
      kind: "workbuddy-plugin",
      namespace: SIGNATURE_NAMESPACES.workbuddy,
    }];
  }
  const units = [];
  if (suiteManifests.length) {
    const manifestEntry = suiteManifests[0];
    units.push({
      manifestEntry,
      signatureEntry: manifestEntry.replace("suite-release-manifest.json", "suite-release-manifest.sig"),
      metadataEntry: null,
      publicKeyEntry: manifestEntry.replace("suite-release-manifest.json", "publisher-ed25519.pub"),
      kind: "generic-suite",
      namespace: SIGNATURE_NAMESPACES.genericSuite,
    });
  }
  units.push(...skillManifests.map((manifestEntry) => ({
      manifestEntry,
      signatureEntry: `${manifestEntry}.sig`,
      metadataEntry: manifestEntry.replace("release-manifest.json", "release-signature.json"),
      publicKeyEntry: manifestEntry.replace("release-manifest.json", "publisher-ed25519.pub"),
      kind: "generic-skill",
      namespace: SIGNATURE_NAMESPACES.generic,
    })));
  return units;
}

function validateSignatureMetadata(metadata, unit, expectedFingerprint) {
  if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)) {
    throw new Error(`${unit.metadataEntry} 不是有效签名元数据`);
  }
  if (metadata.algorithm !== "OpenSSH-Ed25519") {
    throw new Error(`${unit.metadataEntry} 声明了不支持的签名算法`);
  }
  if (metadata.signature_namespace !== unit.namespace) {
    throw new Error(`${unit.metadataEntry} 的签名命名空间不匹配`);
  }
  if (metadata.public_key_fingerprint !== expectedFingerprint) {
    throw new Error(`${unit.metadataEntry} 声明了未受信任的发布公钥`);
  }
  if (metadata.signed_file !== path.posix.basename(unit.manifestEntry)) {
    throw new Error(`${unit.metadataEntry} 的 signed_file 与清单不一致`);
  }
  if (metadata.signature !== path.posix.basename(unit.signatureEntry)) {
    throw new Error(`${unit.metadataEntry} 的 signature 与签名文件不一致`);
  }
  if (metadata.public_key !== path.posix.basename(unit.publicKeyEntry)) {
    throw new Error(`${unit.metadataEntry} 的 public_key 与公钥文件不一致`);
  }
}

function validateWorkBuddyEnvelope(zip, unit, verifiedAllowlist) {
  const pluginBase = `${path.posix.dirname(unit.manifestEntry)}/`;
  const pluginsMarker = "/plugins/";
  const markerIndex = pluginBase.indexOf(pluginsMarker);
  const allowedEnvelope = new Set();
  if (markerIndex >= 0) {
    const archiveRoot = pluginBase.slice(0, markerIndex);
    const pluginDirectory = pluginBase.slice(pluginBase.lastIndexOf("/", pluginBase.length - 2) + 1, -1);
    const marketplaceEntry = `${archiveRoot}/.codebuddy-plugin/marketplace.json`;
    const installGuideEntry = `${archiveRoot}/INSTALL.md`;
    allowedEnvelope.add(marketplaceEntry);
    allowedEnvelope.add(installGuideEntry);
    const marketplace = parseJsonEntry(zip, marketplaceEntry);
    const pluginManifestEntry = `${pluginBase}.codebuddy-plugin/plugin.json`;
    if (!verifiedAllowlist.has(pluginManifestEntry)) {
      throw new Error("WorkBuddy plugin.json 未被签名清单覆盖");
    }
    const pluginManifest = parseJsonEntry(zip, pluginManifestEntry);
    const allowedMarketplaceKeys = new Set(["name", "description", "owner", "plugins"]);
    const allowedOwnerKeys = new Set(["name"]);
    const allowedPluginKeys = new Set(["name", "description", "version", "source"]);
    if (
      Object.keys(marketplace).some((key) => !allowedMarketplaceKeys.has(key))
      || !marketplace.owner
      || typeof marketplace.owner !== "object"
      || Array.isArray(marketplace.owner)
      || Object.keys(marketplace.owner).some((key) => !allowedOwnerKeys.has(key))
    ) {
      throw new Error("WorkBuddy marketplace.json 含未允许字段");
    }
    const marketplacePlugin = marketplace.plugins?.[0];
    if (
      !Array.isArray(marketplace.plugins)
      || marketplace.plugins.length !== 1
      || !marketplacePlugin
      || typeof marketplacePlugin !== "object"
      || Array.isArray(marketplacePlugin)
      || Object.keys(marketplacePlugin).some((key) => !allowedPluginKeys.has(key))
      || marketplace.name !== path.posix.basename(archiveRoot)
      || marketplacePlugin.name !== pluginDirectory
      || marketplacePlugin.name !== pluginManifest.name
      || marketplacePlugin.version !== pluginManifest.version
      || marketplacePlugin.source !== `./plugins/${pluginDirectory}`
    ) {
      throw new Error("WorkBuddy marketplace.json 未固定指向已验签插件目录");
    }
    for (const value of [
      marketplace.name,
      marketplace.description,
      marketplace.owner.name,
      marketplacePlugin.name,
      marketplacePlugin.description,
      marketplacePlugin.version,
      marketplacePlugin.source,
    ]) {
      if (typeof value !== "string" || !value || /[\0\r\n]/u.test(value)) {
        throw new Error("WorkBuddy marketplace.json 包含非法文本字段");
      }
    }
  }
  for (const entry of zip.getEntries()) {
    if (entry.isDirectory) continue;
    const name = entry.entryName;
    if (name.startsWith(pluginBase)) {
      if (!verifiedAllowlist.has(name)) {
        throw new Error(`WorkBuddy 插件包含未被签名清单覆盖的文件：${name}`);
      }
      continue;
    }
    if (!allowedEnvelope.has(name)) {
      throw new Error(`WorkBuddy 包含未经允许的外层文件：${name}`);
    }
  }
}

function validateGenericEnvelope(zip, units, verifiedAllowlist, publisher) {
  const suiteUnit = units.find((unit) => unit.kind === "generic-suite");
  if (suiteUnit) {
    const archiveRoot = path.posix.dirname(suiteUnit.manifestEntry);
    const publisherMetadataEntry = `${archiveRoot}/publisher-key.json`;
    const allowedEnvelope = new Set([publisherMetadataEntry]);
    for (const entry of zip.getEntries()) {
      if (entry.isDirectory) continue;
      if (!verifiedAllowlist.has(entry.entryName) && !allowedEnvelope.has(entry.entryName)) {
        throw new Error(`通用技能包包含未被签名清单覆盖的文件：${entry.entryName}`);
      }
    }
    const suiteManifest = parseJsonEntry(zip, suiteUnit.manifestEntry);
    const signedSuiteManifest = `${archiveRoot}/skills/suite-manifest.json`;
    if (!verifiedAllowlist.has(signedSuiteManifest)) {
      throw new Error("通用技能包的 suite-manifest.json 未被套件签名清单覆盖");
    }
    const publisherMetadata = parseJsonEntry(zip, publisherMetadataEntry);
    if (
      Object.keys(publisherMetadata).some((key) => !["algorithm", "fingerprint_sha256"].includes(key))
      || publisherMetadata.algorithm !== "Ed25519"
      || publisherMetadata.fingerprint_sha256 !== publisher.ed25519_fingerprint
    ) {
      throw new Error("通用技能包的 publisher-key.json 与内置发布公钥不一致");
    }
    if (suiteManifest.artifact_type !== "skill-suite") {
      throw new Error("suite-release-manifest.json 的 artifact_type 不正确");
    }
    return;
  }
  for (const entry of zip.getEntries()) {
    if (!entry.isDirectory && !verifiedAllowlist.has(entry.entryName)) {
      throw new Error(`通用技能包包含未被签名清单覆盖的文件：${entry.entryName}`);
    }
  }
}

function verifySkillArchive({
  archivePath,
  expectedSha256,
  securityConfig,
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
  const publisher = securityConfig?.publisher;
  if (!publisher?.identity) throw new Error("安全配置缺少发布者身份");
  const verifiedAllowlist = new Set();
  const signedContentAllowlist = new Set();
  let verifiedFiles = 0;
  for (const unit of units) {
    const manifestEntry = zip.getEntry(unit.manifestEntry);
    const signatureEntry = zip.getEntry(unit.signatureEntry);
    const publicKeyEntry = zip.getEntry(unit.publicKeyEntry);
    if (!manifestEntry || !signatureEntry || !publicKeyEntry) {
      throw new Error(`${unit.manifestEntry} 的签名伴随物不完整`);
    }
    if (unit.metadataEntry) {
      const metadata = parseJsonEntry(zip, unit.metadataEntry);
      validateSignatureMetadata(metadata, unit, publisher.ed25519_fingerprint);
      verifiedAllowlist.add(unit.metadataEntry);
    }
    const publicKey = publicKeyEntry.getData();
    verifyDetachedOpenSshPayload({
      payload: manifestEntry.getData(),
      signature: signatureEntry.getData(),
      publicKey,
      pinnedPublicKey: publisher.public_key,
      expectedFingerprint: publisher.ed25519_fingerprint,
      namespace: unit.namespace,
      identity: publisher.identity,
    });
    const manifest = parseJsonEntry(zip, unit.manifestEntry);
    const fileAudit = verifyManifestFiles(zip, unit.manifestEntry, manifest);
    verifiedFiles += fileAudit.verified;
    for (const file of fileAudit.files) {
      signedContentAllowlist.add(file);
      verifiedAllowlist.add(file);
    }
    verifiedAllowlist.add(unit.manifestEntry);
    verifiedAllowlist.add(unit.signatureEntry);
    verifiedAllowlist.add(unit.publicKeyEntry);
  }
  const artifactType = units[0].kind === "workbuddy-plugin" ? "workbuddy-plugin" : "generic-skills";
  if (artifactType === "workbuddy-plugin") {
    validateWorkBuddyEnvelope(zip, units[0], verifiedAllowlist);
  } else {
    validateGenericEnvelope(zip, units, verifiedAllowlist, publisher);
  }
  return {
    status: "verified",
    archiveSha256: actualArchiveSha,
    entries: entryAudit.entries,
    expandedBytes: entryAudit.expandedBytes,
    signatures: units.length,
    verifiedFiles,
    artifactType,
    publisherFingerprint: publisher.ed25519_fingerprint,
    verifiedFileAllowlist: [...verifiedAllowlist].sort(),
    signedContentAllowlist: [...signedContentAllowlist].sort(),
  };
}

module.exports = {
  SIGNATURE_NAMESPACES,
  sha256,
  inspectApplicationTrust,
  parseOpenSshEd25519PublicKey,
  validateArchiveEntries,
  verifyDetachedOpenSshPayload,
  verifySkillArchive,
};
