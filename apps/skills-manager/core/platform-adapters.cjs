const fs = require("node:fs");
const path = require("node:path");
const {
  SIGNATURE_NAMESPACES,
  sha256,
  verifyDetachedOpenSshPayload,
} = require("./security.cjs");

const SCHEMA = "jiaotang-skills-manager-platforms/v1";
const SUPPORT_LEVELS = new Set(["full", "adapter", "guided"]);
const CHANNELS = new Set(["generic", "workbuddy"]);
const INSTALL_MODES = new Set([
  "managed-directory",
  "shared-agents-directory",
  "workbuddy-marketplace",
  "guided-import",
  "plugin-or-project",
]);
const PLATFORM_KEYS = new Set([
  "id",
  "name",
  "vendor",
  "support",
  "channel",
  "install_mode",
  "notes",
  "darwin",
  "win32",
]);
const PLATFORM_OS_KEYS = new Set(["applications", "managed_roots"]);

function versionParts(value) {
  const match = String(value || "").match(/^(\d+)\.(\d+)\.(\d+)$/);
  if (!match) throw new Error(`无法识别的管理器版本：${value}`);
  return match.slice(1).map(Number);
}

function versionAtLeast(current, minimum) {
  const left = versionParts(current);
  const right = versionParts(minimum);
  for (let index = 0; index < left.length; index += 1) {
    if (left[index] !== right[index]) return left[index] > right[index];
  }
  return true;
}

function assertPlainString(value, field, { allowEmpty = false } = {}) {
  if (typeof value !== "string" || (!allowEmpty && !value.trim())) {
    throw new Error(`平台适配器字段无效：${field}`);
  }
  if (/[\0\r\n]/.test(value)) throw new Error(`平台适配器字段包含控制字符：${field}`);
}

function assertOnlyKeys(value, allowed, field) {
  for (const key of Object.keys(value || {})) {
    if (!allowed.has(key)) throw new Error(`平台适配器包含未允许字段：${field}.${key}`);
  }
}

function validatePathList(value, field) {
  if (!Array.isArray(value) || value.length > 32) {
    throw new Error(`平台适配器路径列表无效：${field}`);
  }
  for (const [index, item] of value.entries()) {
    assertPlainString(item, `${field}[${index}]`);
    if (item.length > 512) throw new Error(`平台适配器路径过长：${field}[${index}]`);
    if (/^(?:https?|file):/i.test(item)) {
      throw new Error(`平台适配器路径不得使用 URL：${field}[${index}]`);
    }
  }
}

function validatePlatformConfig(config, managerVersion) {
  if (!config || typeof config !== "object" || Array.isArray(config)) {
    throw new Error("平台适配器清单不是 JSON 对象");
  }
  assertOnlyKeys(
    config,
    new Set([
      "schema",
      "sequence",
      "revision",
      "published_at",
      "minimum_manager_version",
      "platforms",
    ]),
    "manifest",
  );
  if (config.schema !== SCHEMA) throw new Error("平台适配器 schema 不受支持");
  if (!Number.isSafeInteger(config.sequence) || config.sequence < 1) {
    throw new Error("平台适配器 sequence 必须是正安全整数");
  }
  assertPlainString(config.revision, "revision");
  assertPlainString(config.published_at, "published_at");
  assertPlainString(config.minimum_manager_version, "minimum_manager_version");
  if (Number.isNaN(Date.parse(config.published_at))) throw new Error("平台适配器发布时间无效");
  if (!versionAtLeast(managerVersion, config.minimum_manager_version)) {
    throw new Error(
      `平台适配器至少需要管理器 ${config.minimum_manager_version}，当前为 ${managerVersion}`,
    );
  }
  if (!Array.isArray(config.platforms) || !config.platforms.length || config.platforms.length > 32) {
    throw new Error("平台适配器平台数量无效");
  }
  const ids = new Set();
  for (const [index, platform] of config.platforms.entries()) {
    if (!platform || typeof platform !== "object" || Array.isArray(platform)) {
      throw new Error(`平台适配器第 ${index + 1} 项无效`);
    }
    assertOnlyKeys(platform, PLATFORM_KEYS, `platforms[${index}]`);
    for (const field of ["id", "name", "vendor", "support", "channel", "install_mode", "notes"]) {
      assertPlainString(platform[field], `platforms[${index}].${field}`, {
        allowEmpty: field === "notes",
      });
    }
    if (!/^[a-z0-9][a-z0-9-]{1,63}$/.test(platform.id)) {
      throw new Error(`平台适配器 id 无效：${platform.id}`);
    }
    if (ids.has(platform.id)) throw new Error(`平台适配器 id 重复：${platform.id}`);
    ids.add(platform.id);
    if (!SUPPORT_LEVELS.has(platform.support)) throw new Error(`平台支持等级无效：${platform.id}`);
    if (!CHANNELS.has(platform.channel)) throw new Error(`平台发布通道无效：${platform.id}`);
    if (!INSTALL_MODES.has(platform.install_mode)) throw new Error(`平台安装模式无效：${platform.id}`);
    for (const operatingSystem of ["darwin", "win32"]) {
      const value = platform[operatingSystem];
      if (!value || typeof value !== "object" || Array.isArray(value)) {
        throw new Error(`平台适配器缺少 ${platform.id}.${operatingSystem}`);
      }
      assertOnlyKeys(value, PLATFORM_OS_KEYS, `${platform.id}.${operatingSystem}`);
      validatePathList(value.applications, `${platform.id}.${operatingSystem}.applications`);
      validatePathList(value.managed_roots, `${platform.id}.${operatingSystem}.managed_roots`);
    }
  }
  return config;
}

function parseAdapterBundle({
  manifest,
  signature,
  metadata,
  securityConfig,
  managerVersion,
  platform = process.platform,
}) {
  const payload = Buffer.isBuffer(manifest) ? manifest : Buffer.from(manifest);
  const parsedMetadata = typeof metadata === "string" || Buffer.isBuffer(metadata)
    ? JSON.parse(Buffer.from(metadata).toString("utf8"))
    : metadata;
  const adapters = securityConfig.platform_adapters;
  const publisher = securityConfig.publisher;
  if (adapters.namespace !== SIGNATURE_NAMESPACES.platformAdapters) {
    throw new Error("安全配置中的平台适配器 namespace 不是程序固定值");
  }
  if (payload.length > Number(adapters.maximum_bytes || 262144)) {
    throw new Error("平台适配器清单超过大小上限");
  }
  if (parsedMetadata.schema !== "jiaotang-skills-manager-adapter-signature/v1") {
    throw new Error("平台适配器签名元数据 schema 不受支持");
  }
  if (parsedMetadata.identity !== publisher.identity) throw new Error("平台适配器发布者不匹配");
  if (parsedMetadata.signature_namespace !== SIGNATURE_NAMESPACES.platformAdapters) {
    throw new Error("平台适配器签名 namespace 不匹配");
  }
  if (parsedMetadata.public_key_fingerprint !== publisher.ed25519_fingerprint) {
    throw new Error("平台适配器发布公钥指纹不匹配");
  }
  if (parsedMetadata.manifest_sha256 !== sha256(payload)) {
    throw new Error("平台适配器签名元数据哈希不匹配");
  }
  const verification = verifyDetachedOpenSshPayload({
    payload,
    signature,
    publicKey: publisher.public_key,
    expectedFingerprint: publisher.ed25519_fingerprint,
    namespace: SIGNATURE_NAMESPACES.platformAdapters,
    identity: publisher.identity,
    platform,
  });
  const config = validatePlatformConfig(JSON.parse(payload.toString("utf8")), managerVersion);
  if (parsedMetadata.revision !== config.revision) {
    throw new Error("平台适配器签名元数据版本不匹配");
  }
  if (parsedMetadata.sequence !== config.sequence) {
    throw new Error("平台适配器签名元数据序列不匹配");
  }
  return { config, verification, metadata: parsedMetadata, manifest: payload, signature };
}

function safeRevision(value) {
  if (!/^[0-9A-Za-z._-]{1,80}$/.test(value)) throw new Error("平台适配器版本号不能用于缓存");
  return value;
}

function storeAdapterBundle(root, bundle) {
  const revision = safeRevision(bundle.config.revision);
  const directory = path.join(root, "revisions", revision);
  fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
  const files = {
    "platform-adapters.json": bundle.manifest,
    "platform-adapters.json.sig": bundle.signature,
    "platform-adapters-signature.json": Buffer.from(
      `${JSON.stringify(bundle.metadata, null, 2)}\n`,
    ),
  };
  for (const [name, content] of Object.entries(files)) {
    const destination = path.join(directory, name);
    if (fs.existsSync(destination)) {
      if (!fs.readFileSync(destination).equals(Buffer.from(content))) {
        throw new Error(`同版本平台适配器缓存内容不一致：${revision}`);
      }
      continue;
    }
    fs.writeFileSync(destination, content, { mode: 0o600, flag: "wx" });
  }
  return directory;
}

function loadLatestAdapterBundle(
  root,
  securityConfig,
  managerVersion,
  platform = process.platform,
  minimumSequence = 0,
) {
  const revisionsRoot = path.join(root, "revisions");
  if (!fs.existsSync(revisionsRoot)) return null;
  const revisions = fs.readdirSync(revisionsRoot, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name);
  const errors = [];
  const verified = [];
  for (const revision of revisions) {
    const directory = path.join(revisionsRoot, revision);
    try {
      const bundle = parseAdapterBundle({
        manifest: fs.readFileSync(path.join(directory, "platform-adapters.json")),
        signature: fs.readFileSync(path.join(directory, "platform-adapters.json.sig")),
        metadata: fs.readFileSync(path.join(directory, "platform-adapters-signature.json")),
        securityConfig,
        managerVersion,
        platform,
      });
      if (bundle.config.sequence < minimumSequence) {
        errors.push(
          `${revision}: sequence ${bundle.config.sequence} 低于内置下限 ${minimumSequence}`,
        );
        continue;
      }
      verified.push(bundle);
    } catch (error) {
      errors.push(`${revision}: ${error.message}`);
    }
  }
  verified.sort((left, right) => right.config.sequence - left.config.sequence);
  if (verified.length) return verified[0];
  return { error: errors.join("; ") || "没有可用的平台适配器缓存" };
}

function assertAdapterNotDowngraded(candidate, active) {
  if (candidate.sequence < active.sequence) {
    throw new Error(
      `平台适配器拒绝降级：收到 ${candidate.sequence}，当前 ${active.sequence}`,
    );
  }
  if (candidate.sequence === active.sequence && candidate.revision !== active.revision) {
    throw new Error("平台适配器相同 sequence 对应了不同 revision");
  }
  return true;
}

module.exports = {
  SCHEMA,
  assertAdapterNotDowngraded,
  loadLatestAdapterBundle,
  parseAdapterBundle,
  storeAdapterBundle,
  validatePlatformConfig,
  versionAtLeast,
};
