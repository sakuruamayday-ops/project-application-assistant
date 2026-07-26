#!/usr/bin/env node

import {
  createHash,
  generateKeyPairSync,
  randomUUID,
  sign as signMessage,
} from "node:crypto";
import {execFileSync, spawn, spawnSync} from "node:child_process";
import {
  chmodSync,
  copyFileSync,
  existsSync,
  mkdirSync,
  readFileSync,
  realpathSync,
  renameSync,
  writeFileSync,
} from "node:fs";
import {homedir, hostname, tmpdir} from "node:os";
import {basename, dirname, join, resolve} from "node:path";
import {fileURLToPath} from "node:url";
import readline from "node:readline";


const VERSION = "1.0.0";
const SIGNATURE_VERSION = "JIAOTANG-SIGNATURE-V1";
const ENROLLMENT_VERSION = "JIAOTANG-ENROLLMENT-V1";
const KEYCHAIN_SERVICE = "cn.zshjiaotang.knowledge-device";
const KEYCHAIN_ACCOUNT = "jiaotang-kb";
const MAC_SECURITY_COMMAND = "/usr/bin/security";


function base64url(value) {
  return Buffer.from(value).toString("base64url");
}


function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}


function parseArguments(argv) {
  const values = {_: []};
  for (let index = 0; index < argv.length; index += 1) {
    const item = argv[index];
    if (!item.startsWith("--")) {
      values._.push(item);
      continue;
    }
    const key = item.slice(2);
    const next = argv[index + 1];
    if (next && !next.startsWith("--")) {
      values[key] = next;
      index += 1;
    } else {
      values[key] = true;
    }
  }
  return values;
}


function atomicWrite(path, content, mode = 0o600) {
  mkdirSync(dirname(path), {recursive: true});
  const temporary = `${path}.${process.pid}.tmp`;
  writeFileSync(temporary, content, {encoding: "utf8", mode});
  renameSync(temporary, path);
  chmodSync(path, mode);
}


function platformValue(override) {
  return override || process.platform;
}


function agentRoot(home = homedir()) {
  return join(home, ".jiaotang");
}


function installedScriptPath(home = homedir()) {
  return join(agentRoot(home), "bin", "jiaotang-kb-mcp.mjs");
}


function testCredentialPath() {
  return process.env.JIAOTANG_TEST_CREDENTIAL_FILE || "";
}


function macLoginKeychainPath(home = homedir()) {
  const keychain = join(home, "Library", "Keychains", "login.keychain-db");
  return existsSync(keychain) ? keychain : "";
}


function storeCredentials(credentials, platform, home = homedir()) {
  const serialized = Buffer.from(JSON.stringify(credentials), "utf8").toString("base64");
  if (testCredentialPath()) {
    atomicWrite(testCredentialPath(), serialized, 0o600);
    return;
  }
  if (platform === "darwin") {
    const keychain = macLoginKeychainPath(home);
    const args = [
      "add-generic-password",
      "-U",
      "-a",
      KEYCHAIN_ACCOUNT,
      "-s",
      KEYCHAIN_SERVICE,
      "-w",
      serialized,
    ];
    if (keychain) args.push(keychain);
    execFileSync(
      MAC_SECURITY_COMMAND,
      args,
      {stdio: ["ignore", "ignore", "pipe"]},
    );
    return;
  }
  if (platform === "win32") {
    const credentialPath = join(agentRoot(home), "device-credential.dpapi");
    mkdirSync(dirname(credentialPath), {recursive: true});
    const script = [
      "$plain=[Convert]::FromBase64String($env:JIAOTANG_SECRET_B64)",
      "$protected=[Security.Cryptography.ProtectedData]::Protect($plain,$null,[Security.Cryptography.DataProtectionScope]::CurrentUser)",
      "[IO.File]::WriteAllBytes($env:JIAOTANG_SECRET_PATH,$protected)",
    ].join(";");
    const result = spawnSync(
      "powershell.exe",
      ["-NoProfile", "-NonInteractive", "-Command", script],
      {
        encoding: "utf8",
        env: {
          ...process.env,
          JIAOTANG_SECRET_B64: Buffer.from(serialized, "utf8").toString("base64"),
          JIAOTANG_SECRET_PATH: credentialPath,
        },
      },
    );
    if (result.status !== 0) {
      throw new Error(`Windows 凭据保存失败：${String(result.stderr || "").trim()}`);
    }
    return;
  }
  throw new Error(`不支持的操作系统：${platform}`);
}


function loadCredentials(platform, home = homedir()) {
  let serialized = "";
  if (testCredentialPath()) {
    serialized = readFileSync(testCredentialPath(), "utf8").trim();
  } else if (platform === "darwin") {
    const lookupArgs = [
      "find-generic-password",
      "-a",
      KEYCHAIN_ACCOUNT,
      "-s",
      KEYCHAIN_SERVICE,
      "-w",
    ];
    const keychain = macLoginKeychainPath(home);
    const candidates = keychain ? [[...lookupArgs, keychain], lookupArgs] : [lookupArgs];
    let lastError;
    for (const args of candidates) {
      try {
        serialized = execFileSync(
          MAC_SECURITY_COMMAND,
          args,
          {encoding: "utf8", stdio: ["ignore", "pipe", "pipe"]},
        ).trim();
        break;
      } catch (error) {
        lastError = error;
      }
    }
    if (!serialized) throw lastError || new Error("macOS 登录钥匙串中没有设备凭据");
  } else if (platform === "win32") {
    const credentialPath = join(agentRoot(home), "device-credential.dpapi");
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
        env: {...process.env, JIAOTANG_SECRET_PATH: credentialPath},
      },
    );
    if (result.status !== 0) {
      throw new Error(`Windows 凭据读取失败：${String(result.stderr || "").trim()}`);
    }
    serialized = Buffer.from(result.stdout.trim(), "base64").toString("utf8");
  } else {
    throw new Error(`不支持的操作系统：${platform}`);
  }
  return JSON.parse(Buffer.from(serialized, "base64").toString("utf8"));
}


function mcpServerConfiguration(scriptPath = installedScriptPath()) {
  return {
    command: process.execPath,
    args: [scriptPath, "serve"],
  };
}


function mergeJsonMcpConfig(configPath, server) {
  let existing = {};
  if (existsSync(configPath)) {
    existing = JSON.parse(readFileSync(configPath, "utf8"));
  }
  existing.mcpServers = existing.mcpServers || {};
  existing.mcpServers["jiaotang-kb"] = server;
  atomicWrite(configPath, `${JSON.stringify(existing, null, 2)}\n`);
  return configPath;
}


function tomlString(value) {
  return JSON.stringify(String(value));
}


function mergeCodexConfig(configPath, server) {
  const sectionPattern =
    /(?:^|\n)\[mcp_servers\.jiaotang_kb\]\n[\s\S]*?(?=\n\[[^\]]+\]|\s*$)/m;
  const section = [
    "[mcp_servers.jiaotang_kb]",
    `command = ${tomlString(server.command)}`,
    `args = [${server.args.map(tomlString).join(", ")}]`,
    "startup_timeout_sec = 30",
    "",
  ].join("\n");
  const original = existsSync(configPath) ? readFileSync(configPath, "utf8") : "";
  const updated = sectionPattern.test(original)
    ? original.replace(sectionPattern, `\n${section}`)
    : `${original.trimEnd()}${original.trim() ? "\n\n" : ""}${section}`;
  atomicWrite(configPath, updated);
  return configPath;
}


function commandExists(command) {
  const checker = process.platform === "win32" ? "where.exe" : "which";
  return spawnSync(checker, [command], {stdio: "ignore"}).status === 0;
}


function detectHost(requestedHost, home = homedir()) {
  if (requestedHost && requestedHost !== "auto") return requestedHost;
  if (
    process.env.CODEBUDDY_PLUGIN_ROOT
    || process.env.CODEBUDDY_SKILL_DIR
    || process.env.WORKBUDDY_HOME
  ) return "workbuddy";
  if (process.env.CODEX_HOME || process.env.CODEX_THREAD_ID) return "codex";
  if (process.env.CLAUDECODE || process.env.CLAUDE_CODE_ENTRYPOINT) return "claude-code";
  if (existsSync(join(home, ".workbuddy"))) return "workbuddy";
  if (existsSync(process.env.CODEX_HOME || join(home, ".codex"))) return "codex";
  if (existsSync(join(home, ".claude"))) return "claude-code";
  return "generic-mcp";
}


function configureHost(host, home, server) {
  if (host === "workbuddy") {
    return mergeJsonMcpConfig(join(home, ".workbuddy", "mcp.json"), server);
  }
  if (host === "codex") {
    return mergeCodexConfig(
      join(process.env.CODEX_HOME || join(home, ".codex"), "config.toml"),
      server,
    );
  }
  if (host === "claude-code") {
    if (commandExists("claude")) {
      const result = spawnSync(
        "claude",
        [
          "mcp",
          "add-json",
          "jiaotang-kb",
          JSON.stringify(server),
          "--scope",
          "user",
        ],
        {encoding: "utf8"},
      );
      if (result.status === 0) return "claude:user";
    }
    return mergeJsonMcpConfig(join(home, ".claude", "mcp.json"), server);
  }
  return mergeJsonMcpConfig(join(agentRoot(home), "mcp.json"), server);
}


function enrollmentCanonical({
  enrollmentCode,
  deviceId,
  deviceName,
  platform,
  agentHost,
  publicKey,
}) {
  return Buffer.from(
    [
      ENROLLMENT_VERSION,
      enrollmentCode,
      deviceId,
      deviceName,
      platform,
      agentHost,
      publicKey,
    ].join("\n"),
    "utf8",
  );
}


function requestCanonical({
  method,
  requestTarget,
  timestamp,
  nonce,
  body,
  token,
}) {
  return Buffer.from(
    [
      SIGNATURE_VERSION,
      method.toUpperCase(),
      requestTarget,
      timestamp,
      nonce,
      sha256(body),
      sha256(token),
    ].join("\n"),
    "utf8",
  );
}


function signedHeaders(credentials, method, url, body = Buffer.alloc(0)) {
  const targetUrl = new URL(url);
  const requestTarget = `${targetUrl.pathname}${targetUrl.search}`;
  const timestamp = String(Math.floor(Date.now() / 1000));
  const nonce = base64url(Buffer.from(randomUUID(), "utf8"));
  const signature = signMessage(
    null,
    requestCanonical({
      method,
      requestTarget,
      timestamp,
      nonce,
      body,
      token: credentials.token,
    }),
    credentials.privateKey,
  );
  return {
    Authorization: `Bearer ${credentials.token}`,
    "X-Jiaotang-Device-ID": credentials.deviceId,
    "X-Jiaotang-Device-Name": credentials.deviceName,
    "X-Jiaotang-Key-ID": credentials.keyId,
    "X-Jiaotang-Timestamp": timestamp,
    "X-Jiaotang-Nonce": nonce,
    "X-Jiaotang-Signature": base64url(signature),
  };
}


async function signedFetch(credentials, url, options = {}) {
  const method = String(options.method || "GET").toUpperCase();
  const body = options.body
    ? Buffer.isBuffer(options.body)
      ? options.body
      : Buffer.from(options.body)
    : Buffer.alloc(0);
  const headers = {
    ...(options.headers || {}),
    ...signedHeaders(credentials, method, url, body),
  };
  return fetch(url, {...options, method, body: body.length ? body : undefined, headers});
}


async function testStdioMcpConnection(scriptPath, platform, home) {
  const requestId = `jiaotang-install-${randomUUID()}`;
  const request = {
    jsonrpc: "2.0",
    id: requestId,
    method: "initialize",
    params: {
      protocolVersion: "2025-06-18",
      capabilities: {},
      clientInfo: {name: "jiaotang-installer", version: VERSION},
    },
  };
  await new Promise((resolvePromise, rejectPromise) => {
    const child = spawn(
      process.execPath,
      [scriptPath, "serve", "--platform", platform, "--home", home],
      {stdio: ["pipe", "pipe", "pipe"]},
    );
    let settled = false;
    let stderr = "";
    const output = readline.createInterface({
      input: child.stdout,
      crlfDelay: Infinity,
      terminal: false,
    });
    const finish = (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      output.close();
      child.kill();
      if (error) rejectPromise(error);
      else resolvePromise();
    };
    const timeout = setTimeout(
      () => finish(new Error("MCP 初始化等待服务器确认超时")),
      20000,
    );
    child.stderr.on("data", (chunk) => {
      stderr = `${stderr}${String(chunk)}`.slice(-500);
    });
    child.on("error", (error) => finish(error));
    child.on("exit", (code) => {
      if (!settled) {
        finish(new Error(`MCP 代理提前退出：${code}${stderr ? `；${stderr.trim()}` : ""}`));
      }
    });
    output.on("line", (line) => {
      try {
        const message = JSON.parse(line);
        if (message.id !== requestId) return;
        if (message.error) {
          finish(new Error(`MCP 初始化失败：${message.error.message || "未知错误"}`));
          return;
        }
        if (message.result) finish();
      } catch {}
    });
    child.stdin.write(`${JSON.stringify(request)}\n`);
  });
}


async function install(argumentsValue) {
  let installationStage = "validation";
  try {
  const pluginMode = argumentsValue["plugin-mode"] === true;
  const bootstrapUrl = String(argumentsValue["bootstrap-url"] || "");
  const platform = platformValue(argumentsValue.platform);
  const home = resolve(String(argumentsValue.home || homedir()));
  const host = detectHost(String(argumentsValue.host || "auto"), home);
  if (!bootstrapUrl) throw new Error("缺少 bootstrap-url");
  if (!["darwin", "win32"].includes(platform)) {
    throw new Error(`当前安装器仅支持 macOS 和 Windows：${platform}`);
  }
  const bootstrap = new URL(bootstrapUrl);
  if (
    bootstrap.protocol !== "https:"
    && !(bootstrap.protocol === "http:" && ["127.0.0.1", "localhost"].includes(bootstrap.hostname))
  ) {
    throw new Error("一次性引导地址必须使用 HTTPS");
  }
  installationStage = "bootstrap_manifest";
  const manifestResponse = await fetch(bootstrap);
  if (!manifestResponse.ok) {
    throw new Error(`引导清单读取失败：HTTP ${manifestResponse.status}`);
  }
  const manifest = await manifestResponse.json();
  if (manifest.schema !== "jiaotang-agent-bootstrap/v1") {
    throw new Error("引导清单版本不受支持");
  }
  if (new URL(manifest.installer_url).origin !== bootstrap.origin) {
    throw new Error("安装组件来源与引导服务不一致");
  }
  installationStage = "integrity_verification";
  const runningInstaller = readFileSync(fileURLToPath(import.meta.url));
  if (
    !/^[a-f0-9]{64}$/.test(String(manifest.installer_sha256 || ""))
    || sha256(runningInstaller) !== manifest.installer_sha256
  ) {
    throw new Error("安装组件完整性校验失败");
  }
  const enrollmentCode = decodeURIComponent(basename(bootstrap.pathname));
  const {publicKey, privateKey} = generateKeyPairSync("ed25519");
  const publicKeyValue = base64url(
    publicKey.export({type: "spki", format: "der"}),
  );
  const privateKeyValue = privateKey.export({type: "pkcs8", format: "pem"}).toString();
  const deviceId = `device:${randomUUID()}`;
  const deviceName = String(argumentsValue["device-name"] || hostname() || `${platform} Agent`).slice(0, 100);
  const platformName = `${platform}-${process.arch}`;
  installationStage = "device_registration";
  const proof = base64url(
    signMessage(
      null,
      enrollmentCanonical({
        enrollmentCode,
        deviceId,
        deviceName,
        platform: platformName,
        agentHost: host,
        publicKey: publicKeyValue,
      }),
      privateKey,
    ),
  );
  const registrationResponse = await fetch(`${bootstrapUrl}/register`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      public_key: publicKeyValue,
      proof,
      device_id: deviceId,
      device_name: deviceName,
      platform: platformName,
      agent_host: host,
    }),
  });
  if (!registrationResponse.ok) {
    let detail = `HTTP ${registrationResponse.status}`;
    try {
      detail = (await registrationResponse.json()).detail || detail;
    } catch {}
    throw new Error(`设备登记失败：${detail}`);
  }
  const registration = await registrationResponse.json();
  const credentials = {
    version: 1,
    keyId: registration.key_id,
    token: registration.token,
    privateKey: privateKeyValue,
    deviceId,
    deviceName,
    platform: platformName,
    agentHost: host,
    apiBaseUrl: registration.api_base_url,
    mcpUrl: registration.mcp_url,
  };

  installationStage = "credential_storage";
  const targetScript = pluginMode
    ? fileURLToPath(import.meta.url)
    : installedScriptPath(home);
  if (!pluginMode) {
    mkdirSync(dirname(targetScript), {recursive: true});
    copyFileSync(fileURLToPath(import.meta.url), targetScript);
    chmodSync(targetScript, 0o700);
  }
  storeCredentials(credentials, platform, home);
  const storedCredentials = loadCredentials(platform, home);
  if (
    storedCredentials.keyId !== credentials.keyId
    || storedCredentials.token !== credentials.token
  ) {
    throw new Error("系统凭据库回读校验失败");
  }
  const credentialSavedResponse = await signedFetch(
    storedCredentials,
    `${credentials.apiBaseUrl}/device-installation/credential-saved`,
    {method: "POST"},
  );
  if (!credentialSavedResponse.ok) {
    throw new Error(`凭据保存上报失败：HTTP ${credentialSavedResponse.status}`);
  }
  installationStage = "host_configuration";
  const configPath = pluginMode
    ? "workbuddy:signed-plugin"
    : configureHost(host, home, mcpServerConfiguration(targetScript));
  installationStage = "mcp_connection";
  await testStdioMcpConnection(targetScript, platform, home);
  installationStage = "server_verification";
  const statusResponse = await signedFetch(
    storedCredentials,
    `${credentials.apiBaseUrl}/device-installation/status`,
  );
  if (!statusResponse.ok) {
    throw new Error(`安装状态确认失败：HTTP ${statusResponse.status}`);
  }
  const installationStatus = await statusResponse.json();
  if (!installationStatus.configured) {
    throw new Error("服务器尚未确认首次签名 MCP 连接");
  }
  const activationRequired = host === "workbuddy" && !pluginMode;
  const nextAction = activationRequired
    ? "连接成功。请在 WorkBuddy 左侧「连接器」中找到 `jiaotang-kb`，然后点击「启用」。"
    : null;
  return {
    schema: "jiaotang-agent-result/v1",
    ok: true,
    status: "configured",
    host,
    platform,
    config: configPath,
    health: "ok",
    mcp: "connected",
    stages: installationStatus.stages,
    reload_may_be_required: activationRequired,
    activation_required: activationRequired,
    next_action: nextAction,
    user_message: activationRequired
      ? "配置成功，WorkBuddy 还需要启用新连接器。"
      : "配置成功",
  };
  } catch (error) {
    if (error && typeof error === "object") {
      error.installationStage = error.installationStage || installationStage;
    }
    throw error;
  }
}


async function pluginServe(argumentsValue) {
  const platform = platformValue(argumentsValue.platform);
  const home = resolve(String(argumentsValue.home || homedir()));
  const pluginData = String(process.env.CODEBUDDY_PLUGIN_DATA || "");
  const enrollmentMarker = pluginData
    ? join(pluginData, "jiaotang-kb-enrollment.json")
    : "";
  try {
    loadCredentials(platform, home);
  } catch (credentialError) {
    if (enrollmentMarker && existsSync(enrollmentMarker)) {
      throw new Error(
        "插件已完成过设备登记，但系统凭据当前不可读取；"
        + "请检查钥匙串或Windows用户凭据后重试",
        {cause: credentialError},
      );
    }
    const bootstrapUrl = String(
      argumentsValue["bootstrap-url"]
      || process.env.CODEBUDDY_PLUGIN_OPTION_BOOTSTRAP_URL
      || "",
    );
    if (!bootstrapUrl) {
      throw new Error("插件尚未绑定，请重新启用插件并填写门户生成的一次性引导地址");
    }
    await install({
      ...argumentsValue,
      "bootstrap-url": bootstrapUrl,
      "plugin-mode": true,
      host: "workbuddy",
    });
    if (enrollmentMarker) {
      atomicWrite(
        enrollmentMarker,
        `${JSON.stringify({version: 1, enrolled: true})}\n`,
        0o600,
      );
    }
  }
  await serve(argumentsValue);
}


function installationFailure(error, argumentsValue = {}) {
  const stage = String(error?.installationStage || "unknown");
  const message = String(error?.message || error || "未知错误")
    .replace(/jbe_[A-Za-z0-9_-]+/g, "[已隐藏安装码]")
    .replace(/jtk_[A-Za-z0-9_-]+/g, "[已隐藏凭据]");
  const nextActions = {
    validation: "请确认当前 Agent 在 macOS 或 Windows 本地运行，然后回到门户重新复制安装配置。",
    bootstrap_manifest: "请回到门户重新复制新的安装配置，并让 Agent 只执行一次。",
    integrity_verification: "请停止使用当前安装文件，回到门户重新复制安装配置。",
    device_registration: "请稍后重试；若仍失败，请回到门户点击“更换绑定设备”后重新复制安装配置。",
    credential_storage: "请允许 Agent 使用系统钥匙串或 Windows 凭据管理器，然后重新执行安装。",
    host_configuration: "请确认 Agent 有权写入本机 MCP 配置目录，然后重新执行安装。",
    mcp_connection: "请重新执行安装；若仍失败，请检查本机 Agent 是否允许启动 stdio MCP 连接器。",
    server_verification: "请重新执行安装，让服务器完成首次签名与 MCP 连接确认。",
    unknown: "请将本次安装结果完整发给管理员处理。",
  };
  return {
    schema: "jiaotang-agent-result/v1",
    ok: false,
    status: "failed",
    error_stage: stage,
    user_message: `安装失败：${message}`,
    next_action: nextActions[stage] || nextActions.unknown,
    host: detectHost(String(argumentsValue.host || "auto")),
    platform: `${platformValue(argumentsValue.platform)}-${process.arch}`,
  };
}


async function reportInstallationResult(argumentsValue, result) {
  const resultUrl = String(argumentsValue["result-url"] || "");
  if (!resultUrl) return false;
  try {
    const endpoint = new URL(resultUrl);
    if (
      endpoint.protocol !== "https:"
      && !(endpoint.protocol === "http:" && ["127.0.0.1", "localhost"].includes(endpoint.hostname))
    ) {
      return false;
    }
    const response = await fetch(endpoint, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(result),
    });
    return response.ok;
  } catch {
    return false;
  }
}


function parseSsePayload(text) {
  const messages = [];
  for (const line of text.split(/\r?\n/)) {
    if (!line.startsWith("data:")) continue;
    const value = line.slice(5).trim();
    if (!value || value === "[DONE]") continue;
    messages.push(JSON.parse(value));
  }
  return messages;
}


async function serve(argumentsValue) {
  const platform = platformValue(argumentsValue.platform);
  const home = resolve(String(argumentsValue.home || homedir()));
  const credentials = loadCredentials(platform, home);
  let mcpSessionId = "";
  const input = readline.createInterface({
    input: process.stdin,
    crlfDelay: Infinity,
    terminal: false,
  });
  input.on("line", async (line) => {
    let request;
    try {
      request = JSON.parse(line);
      const body = Buffer.from(JSON.stringify(request), "utf8");
      const headers = {
        "Content-Type": "application/json",
        Accept: "application/json, text/event-stream",
      };
      if (mcpSessionId) headers["Mcp-Session-Id"] = mcpSessionId;
      const response = await signedFetch(credentials, credentials.mcpUrl, {
        method: "POST",
        headers,
        body,
      });
      const returnedSession = response.headers.get("mcp-session-id");
      if (returnedSession) mcpSessionId = returnedSession;
      const responseText = await response.text();
      if (!response.ok) {
        throw new Error(`upstream HTTP ${response.status}: ${responseText.slice(0, 300)}`);
      }
      const messages = response.headers.get("content-type")?.includes("text/event-stream")
        ? parseSsePayload(responseText)
        : responseText.trim()
          ? [JSON.parse(responseText)]
          : [];
      for (const message of messages) {
        process.stdout.write(`${JSON.stringify(message)}\n`);
      }
    } catch (error) {
      if (request?.id !== undefined) {
        process.stdout.write(
          `${JSON.stringify({
            jsonrpc: "2.0",
            id: request.id,
            error: {code: -32000, message: String(error.message || error)},
          })}\n`,
        );
      }
    }
  });
}


function simulateConfig(argumentsValue) {
  const home = resolve(String(argumentsValue.home || join(tmpdir(), "jiaotang-agent-test")));
  const host = detectHost(String(argumentsValue.host || "auto"), home);
  const scriptPath = join(home, ".jiaotang", "bin", "jiaotang-kb-mcp.mjs");
  return {
    host,
    config: configureHost(host, home, mcpServerConfiguration(scriptPath)),
  };
}


async function main() {
  const argumentsValue = parseArguments(process.argv.slice(2));
  const command = argumentsValue._[0] || "";
  if (command === "install") {
    try {
      const result = await install(argumentsValue);
      result.reported_to_portal = await reportInstallationResult(argumentsValue, result);
      process.stdout.write(`${JSON.stringify(result)}\n`);
    } catch (error) {
      const result = installationFailure(error, argumentsValue);
      result.reported_to_portal = await reportInstallationResult(argumentsValue, result);
      process.stdout.write(`${JSON.stringify(result)}\n`);
      process.exitCode = 1;
    }
    return;
  }
  if (command === "serve") {
    await serve(argumentsValue);
    return;
  }
  if (command === "plugin-serve") {
    await pluginServe(argumentsValue);
    return;
  }
  if (command === "simulate-config") {
    process.stdout.write(`${JSON.stringify(simulateConfig(argumentsValue))}\n`);
    return;
  }
  process.stderr.write(
    `jiaotang-agent ${VERSION}\n用法：install | serve | plugin-serve | simulate-config\n`,
  );
  process.exitCode = 2;
}


export {
  configureHost,
  detectHost,
  enrollmentCanonical,
  installationFailure,
  mergeCodexConfig,
  mergeJsonMcpConfig,
  requestCanonical,
  reportInstallationResult,
  signedHeaders,
};


if (
  process.argv[1]
  && realpathSync(fileURLToPath(import.meta.url)) === realpathSync(resolve(process.argv[1]))
) {
  main().catch((error) => {
    process.stderr.write(`${String(error.message || error)}\n`);
    process.exitCode = 1;
  });
}
