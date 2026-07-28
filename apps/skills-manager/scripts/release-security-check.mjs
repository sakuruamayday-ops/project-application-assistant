import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const packageMetadata = JSON.parse(
  fs.readFileSync(path.join(appRoot, "package.json"), "utf8"),
);
const MODES = new Set(["signed", "unsigned-local-authorization"]);

function run(command, args) {
  const result = commandResult(command, args);
  if (result.status !== 0) {
    throw new Error(
      `${command} ${args.join(" ")} 校验失败\n${result.stderr || result.stdout || result.error || ""}`,
    );
  }
  return `${result.stdout || ""}${result.stderr || ""}`.trim();
}

function commandResult(command, args) {
  return spawnSync(command, args, {
    encoding: "utf8",
    windowsHide: true,
  });
}

function parseArguments(argv) {
  const options = {
    artifacts: [],
    mode: "signed",
    auditOutput: null,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const current = argv[index];
    if (current === "--artifact" && argv[index + 1]) {
      options.artifacts.push(path.resolve(argv[++index]));
    } else if (current === "--mode" && argv[index + 1]) {
      options.mode = argv[++index];
    } else if (current === "--audit-output" && argv[index + 1]) {
      options.auditOutput = path.resolve(argv[++index]);
    } else {
      throw new Error(`无法识别的参数：${current}`);
    }
  }
  if (!MODES.has(options.mode)) {
    throw new Error(`无法识别的发布校验模式：${options.mode}`);
  }
  if (!options.artifacts.length) {
    throw new Error("请至少传入一个 --artifact <.app|.dmg|.pkg|.exe|.msi>");
  }
  if (!options.auditOutput) {
    options.auditOutput = path.join(
      path.dirname(options.artifacts[0]),
      "release-trust.json",
    );
  }
  return options;
}

function sha256File(file) {
  return crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex");
}

function artifactRecord(artifact) {
  const stat = fs.statSync(artifact);
  return {
    file: path.basename(artifact),
    platform: /\.(?:exe|msi)$/i.test(artifact) ? "win32" : "darwin",
    bytes: stat.size,
    sha256: stat.isFile() ? sha256File(artifact) : null,
  };
}

function verifyMacSigned(artifact) {
  if (artifact.endsWith(".app")) {
    run("codesign", ["--verify", "--deep", "--strict", "--verbose=2", artifact]);
    run("spctl", ["--assess", "--type", "execute", "--verbose=4", artifact]);
    return;
  }
  if (artifact.endsWith(".dmg") || artifact.endsWith(".pkg")) {
    run("xcrun", ["stapler", "validate", artifact]);
    run("spctl", [
      "--assess",
      "--type",
      artifact.endsWith(".pkg") ? "install" : "open",
      "--verbose=4",
      artifact,
    ]);
    return;
  }
  throw new Error(`无法识别的 macOS 发行物：${artifact}`);
}

function verifyWindowsSigned(artifact) {
  if (process.platform !== "win32") {
    throw new Error("Windows Authenticode 必须在 Windows 发布机上完成验证");
  }
  const escaped = artifact.replaceAll("'", "''");
  const script = [
    `$s=Get-AuthenticodeSignature -LiteralPath '${escaped}'`,
    "if ($s.Status -ne 'Valid') { Write-Error ($s.Status.ToString() + ': ' + $s.StatusMessage); exit 1 }",
    "$s.SignerCertificate.Subject",
  ].join("; ");
  run("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", script]);
}

function findCertificateTable(buffer) {
  if (buffer.length < 0x40 || buffer.toString("ascii", 0, 2) !== "MZ") {
    throw new Error("Windows 发行物不是有效的 PE 文件");
  }
  const peOffset = buffer.readUInt32LE(0x3c);
  if (
    peOffset + 24 > buffer.length
    || buffer.toString("ascii", peOffset, peOffset + 4) !== "PE\u0000\u0000"
  ) {
    throw new Error("Windows 发行物缺少有效的 PE 头");
  }
  const optionalSize = buffer.readUInt16LE(peOffset + 20);
  const optionalOffset = peOffset + 24;
  if (optionalSize < 104 || optionalOffset + optionalSize > buffer.length) {
    throw new Error("Windows 发行物的 PE 可选头不完整");
  }
  const optionalMagic = buffer.readUInt16LE(optionalOffset);
  const dataDirectoryOffset = optionalMagic === 0x20b
    ? optionalOffset + 112
    : optionalMagic === 0x10b
      ? optionalOffset + 96
      : null;
  if (dataDirectoryOffset === null) {
    throw new Error("Windows 发行物使用了无法识别的 PE 可选头");
  }
  const directoryCountOffset = optionalMagic === 0x20b
    ? optionalOffset + 108
    : optionalOffset + 92;
  if (
    directoryCountOffset + 4 > optionalOffset + optionalSize
    || buffer.readUInt32LE(directoryCountOffset) < 5
  ) {
    throw new Error("Windows 发行物缺少 Authenticode 证书目录");
  }
  const certificateDirectory = dataDirectoryOffset + (8 * 4);
  if (certificateDirectory + 8 > optionalOffset + optionalSize) {
    throw new Error("Windows 发行物的 PE 证书目录不完整");
  }
  return {
    offset: buffer.readUInt32LE(certificateDirectory),
    size: buffer.readUInt32LE(certificateDirectory + 4),
  };
}

function verifyWindowsUnsigned(artifact) {
  if (!artifact.endsWith(".exe")) {
    throw new Error("本地授权模式当前只接受 Windows NSIS .exe 安装器");
  }
  const certificate = findCertificateTable(fs.readFileSync(artifact));
  if (certificate.offset !== 0 || certificate.size !== 0) {
    throw new Error("unsigned-local 产物包含 Authenticode 证书表，发行模式与文件状态不一致");
  }
}

function verifyMacUnsignedApp(appPath) {
  const verification = commandResult(
    "codesign",
    ["--verify", "--deep", "--strict", "--verbose=2", appPath],
  );
  const details = commandResult("codesign", ["--display", "--verbose=4", appPath]);
  const diagnostic = `${verification.stdout || ""}\n${verification.stderr || ""}\n${details.stdout || ""}\n${details.stderr || ""}`;
  if (verification.status === 0) {
    throw new Error("unsigned-local macOS 应用意外通过完整代码签名验证");
  }
  if (details.status === 0) {
    const linkerAdHoc = /\bSignature=adhoc\b/.test(diagnostic)
      && /\blink(er)?-signed\b/.test(diagnostic)
      && /\bTeamIdentifier=not set\b/.test(diagnostic)
      && !/\bAuthority=/.test(diagnostic);
    if (!linkerAdHoc) {
      throw new Error("unsigned-local macOS 应用包含非预期的发布者或应用级签名");
    }
    return;
  }
  if (!/not signed|未签名/i.test(diagnostic)) {
    throw new Error(`无法确认 macOS 应用处于未签名状态\n${diagnostic.trim()}`);
  }
}

function mountedAppPath(mountPoint) {
  const entries = fs.readdirSync(mountPoint, { withFileTypes: true });
  const app = entries.find((entry) => entry.isDirectory() && entry.name.endsWith(".app"));
  if (!app) throw new Error("DMG 中没有找到 macOS .app");
  return path.join(mountPoint, app.name);
}

function verifyMacUnsigned(artifact) {
  if (process.platform !== "darwin") {
    throw new Error("macOS 未签名状态与 DMG 完整性必须在 macOS 发布机上验证");
  }
  if (artifact.endsWith(".app")) {
    verifyMacUnsignedApp(artifact);
    return;
  }
  if (!artifact.endsWith(".dmg")) {
    throw new Error("本地授权模式当前只接受 macOS .app 或 .dmg");
  }
  run("hdiutil", ["verify", artifact]);
  const output = run("hdiutil", ["attach", "-readonly", "-nobrowse", artifact]);
  const mountPoint = output
    .split(/\r?\n/)
    .map((line) => line.split("\t").at(-1)?.trim())
    .find((value) => value?.startsWith("/Volumes/"));
  if (!mountPoint) throw new Error("无法识别 DMG 挂载点");
  try {
    verifyMacUnsignedApp(mountedAppPath(mountPoint));
  } finally {
    run("hdiutil", ["detach", mountPoint]);
  }
}

function verifySigned(artifact) {
  if (/\.(?:exe|msi)$/i.test(artifact)) verifyWindowsSigned(artifact);
  else verifyMacSigned(artifact);
  return {
    platform_trust: "platform-signed",
    local_authorization_required: false,
  };
}

function verifyUnsignedLocal(artifact) {
  if (!path.basename(artifact).includes("-unsigned-local-")) {
    throw new Error("本地授权发行物文件名必须包含 -unsigned-local-");
  }
  if (/\.exe$/i.test(artifact)) verifyWindowsUnsigned(artifact);
  else verifyMacUnsigned(artifact);
  return {
    platform_trust: "local-user-exception",
    local_authorization_required: true,
  };
}

function verifyArtifactVersion(artifact) {
  const expected = `-${packageMetadata.version}-`;
  if (!path.basename(artifact).includes(expected)) {
    throw new Error(`发行物文件名版本必须与管理器 ${packageMetadata.version} 一致`);
  }
}

function auditDocument({ mode, status, artifacts, error = null }) {
  const targetPlatforms = [...new Set(artifacts.map((artifact) => artifact.platform))];
  return {
    schema: "jiaotang-skills-manager-release-audit/v1",
    status,
    mode,
    generated_at: new Date().toISOString(),
    manager_version: packageMetadata.version,
    target_platforms: targetPlatforms,
    os_trust: mode === "signed" ? "platform-signed" : "local-user-exception",
    skills_content_scope: {
      bundled: false,
      verified: false,
      release_channel: "independent-portal-skills-channels",
      statement: "This desktop-client audit does not bundle or verify Skills content.",
    },
    artifacts,
    error,
  };
}

function writeAudit(target, audit) {
  fs.mkdirSync(path.dirname(target), { recursive: true });
  const temporary = `${target}.${process.pid}.tmp`;
  fs.writeFileSync(temporary, `${JSON.stringify(audit, null, 2)}\n`, {
    encoding: "utf8",
    mode: 0o600,
  });
  fs.renameSync(temporary, target);
}

function main(argv) {
  const options = parseArguments(argv);
  const records = [];
  try {
    for (const artifact of options.artifacts) {
      if (!fs.existsSync(artifact)) throw new Error(`发行物不存在：${artifact}`);
      verifyArtifactVersion(artifact);
      const record = artifactRecord(artifact);
      records.push(record);
      const trust = options.mode === "signed"
        ? verifySigned(artifact)
        : verifyUnsignedLocal(artifact);
      Object.assign(record, trust);
      console.log(`release trust verified (${options.mode}): ${artifact}`);
    }
    writeAudit(
      options.auditOutput,
      auditDocument({
        mode: options.mode,
        status: "pass",
        artifacts: records,
      }),
    );
    console.log(`release audit: ${options.auditOutput}`);
  } catch (error) {
    writeAudit(
      options.auditOutput,
      auditDocument({
        mode: options.mode,
        status: "fail",
        artifacts: records,
        error: String(error.message || error),
      }),
    );
    throw error;
  }
}

main(process.argv.slice(2));
