import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";

function run(command, args) {
  const result = spawnSync(command, args, {
    encoding: "utf8",
    windowsHide: true,
  });
  if (result.status !== 0) {
    throw new Error(
      `${command} ${args.join(" ")} 校验失败\n${result.stderr || result.stdout || result.error || ""}`,
    );
  }
  return (result.stdout || result.stderr || "").trim();
}

function parseArtifacts(argv) {
  const values = [];
  for (let index = 0; index < argv.length; index += 1) {
    if (argv[index] === "--artifact" && argv[index + 1]) values.push(argv[++index]);
  }
  return values.map((value) => path.resolve(value));
}

function verifyMac(artifact) {
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

function verifyWindows(artifact) {
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

const artifacts = parseArtifacts(process.argv.slice(2));
if (!artifacts.length) {
  throw new Error("请至少传入一个 --artifact <.app|.dmg|.pkg|.exe|.msi>");
}

for (const artifact of artifacts) {
  if (!fs.existsSync(artifact)) throw new Error(`发行物不存在：${artifact}`);
  if (/\.(?:exe|msi)$/i.test(artifact)) verifyWindows(artifact);
  else verifyMac(artifact);
  console.log(`release trust verified: ${artifact}`);
}
