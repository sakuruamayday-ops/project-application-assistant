const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const crypto = require("node:crypto");
const { execFileSync, spawnSync } = require("node:child_process");

const KEYCHAIN_SERVICE = "cn.zshjiaotang.knowledge-device";
const KEYCHAIN_ACCOUNT = "jiaotang-kb";
const SIGNATURE_VERSION = "JIAOTANG-SIGNATURE-V1";

function sha256(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

function macLoginKeychainPath() {
  const candidate = path.join(os.homedir(), "Library", "Keychains", "login.keychain-db");
  return fs.existsSync(candidate) ? candidate : "";
}

function parseSerializedCredential(serialized) {
  if (!serialized) throw new Error("本机没有已绑定的焦糖设备凭据");
  const value = JSON.parse(Buffer.from(serialized.trim(), "base64").toString("utf8"));
  const required = ["keyId", "token", "privateKey", "deviceId", "deviceName"];
  if (required.some((key) => !value[key])) throw new Error("本机焦糖设备凭据不完整");
  return value;
}

function loadExistingDeviceCredentials(platform = process.platform) {
  if (platform === "darwin") {
    const base = [
      "find-generic-password",
      "-a", KEYCHAIN_ACCOUNT,
      "-s", KEYCHAIN_SERVICE,
      "-w",
    ];
    const keychain = macLoginKeychainPath();
    const candidates = keychain ? [[...base, keychain], base] : [base];
    let lastError = null;
    for (const args of candidates) {
      try {
        return parseSerializedCredential(execFileSync("/usr/bin/security", args, {
          encoding: "utf8",
          stdio: ["ignore", "pipe", "pipe"],
        }));
      } catch (error) {
        lastError = error;
      }
    }
    throw new Error(`无法读取 macOS 登录钥匙串中的既有设备凭据：${lastError?.stderr || "未找到"}`);
  }
  if (platform === "win32") {
    const credentialPath = path.join(os.homedir(), ".jiaotang", "device-credential.dpapi");
    if (!fs.existsSync(credentialPath)) throw new Error("本机没有已绑定的 Windows DPAPI 设备凭据");
    const script = [
      "$protected=[IO.File]::ReadAllBytes($env:JIAOTANG_SECRET_PATH)",
      "$plain=[Security.Cryptography.ProtectedData]::Unprotect($protected,$null,[Security.Cryptography.DataProtectionScope]::CurrentUser)",
      "[Console]::Out.Write([Convert]::ToBase64String($plain))",
    ].join(";");
    const result = spawnSync(
      "powershell.exe",
      ["-NoProfile", "-NonInteractive", "-Command", script],
      {
        encoding: "utf8",
        windowsHide: true,
        env: { ...process.env, JIAOTANG_SECRET_PATH: credentialPath },
      },
    );
    if (result.status !== 0) {
      throw new Error(`无法读取 Windows DPAPI 设备凭据：${String(result.stderr || "").trim()}`);
    }
    return parseSerializedCredential(
      Buffer.from(result.stdout.trim(), "base64").toString("utf8"),
    );
  }
  throw new Error(`当前系统不支持读取既有设备凭据：${platform}`);
}

function signedHeaders(credentials, method, url, body = Buffer.alloc(0)) {
  const target = new URL(url);
  const requestTarget = `${target.pathname}${target.search}`;
  const timestamp = String(Math.floor(Date.now() / 1000));
  const nonce = Buffer.from(crypto.randomUUID(), "utf8").toString("base64url");
  const canonical = Buffer.from([
    SIGNATURE_VERSION,
    method.toUpperCase(),
    requestTarget,
    timestamp,
    nonce,
    sha256(body),
    sha256(credentials.token),
  ].join("\n"), "utf8");
  const signature = crypto.sign(null, canonical, credentials.privateKey).toString("base64url");
  return {
    Authorization: `Bearer ${credentials.token}`,
    "X-Jiaotang-Device-ID": credentials.deviceId,
    "X-Jiaotang-Device-Name": credentials.deviceName,
    "X-Jiaotang-Key-ID": credentials.keyId,
    "X-Jiaotang-Timestamp": timestamp,
    "X-Jiaotang-Nonce": nonce,
    "X-Jiaotang-Signature": signature,
  };
}

module.exports = {
  loadExistingDeviceCredentials,
  signedHeaders,
};
