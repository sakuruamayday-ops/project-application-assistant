import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repositoryRoot = path.resolve(appRoot, "../..");

function argument(name) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : null;
}

function run(command, args) {
  const result = spawnSync(command, args, { encoding: "utf8" });
  if (result.status !== 0) {
    throw new Error(`${command} 执行失败：${result.stderr || result.stdout || result.error || ""}`);
  }
  return (result.stdout || result.stderr).trim();
}

const signingKey = argument("--signing-key");
if (!signingKey) throw new Error("请传入 --signing-key <Ed25519 私钥>");
const source = path.join(appRoot, "config", "platforms.json");
const outputDirectory = path.resolve(
  argument("--output-dir")
    || path.join(repositoryRoot, "services", "knowledge-portal", "static", "skills-manager"),
);
const manifest = fs.readFileSync(source);
const config = JSON.parse(manifest.toString("utf8"));
if (
  config.schema !== "jiaotang-skills-manager-platforms/v1"
  || !Number.isSafeInteger(config.sequence)
  || config.sequence < 1
  || !config.revision
) {
  throw new Error("平台适配器源文件 schema、sequence 或 revision 无效");
}

const temporaryDirectory = fs.mkdtempSync(path.join(os.tmpdir(), "jiaotang-adapter-release-"));
try {
  const temporaryManifest = path.join(temporaryDirectory, "platform-adapters.json");
  fs.writeFileSync(temporaryManifest, manifest, { mode: 0o600 });
  run("ssh-keygen", [
    "-Y",
    "sign",
    "-f",
    path.resolve(signingKey),
    "-n",
    "jiaotang-skills-manager-platform-adapters",
    temporaryManifest,
  ]);
  const publicKeyPath = `${path.resolve(signingKey)}.pub`;
  const fingerprint = run("ssh-keygen", ["-lf", publicKeyPath, "-E", "sha256"])
    .split(/\s+/)[1];
  const metadata = {
    schema: "jiaotang-skills-manager-adapter-signature/v1",
    sequence: config.sequence,
    revision: config.revision,
    identity: "jiaotang-codex-skill-release",
    signature_namespace: "jiaotang-skills-manager-platform-adapters",
    public_key_fingerprint: fingerprint,
    manifest_sha256: crypto.createHash("sha256").update(manifest).digest("hex"),
    signed_at: new Date().toISOString(),
  };

  fs.mkdirSync(outputDirectory, { recursive: true });
  fs.copyFileSync(source, path.join(outputDirectory, "platform-adapters.json"));
  fs.copyFileSync(
    `${temporaryManifest}.sig`,
    path.join(outputDirectory, "platform-adapters.json.sig"),
  );
  fs.writeFileSync(
    path.join(outputDirectory, "platform-adapters-signature.json"),
    `${JSON.stringify(metadata, null, 2)}\n`,
  );
  console.log(JSON.stringify({
    status: "pass",
    sequence: config.sequence,
    revision: config.revision,
    manifest_sha256: metadata.manifest_sha256,
    public_key_fingerprint: fingerprint,
    output_directory: outputDirectory,
  }, null, 2));
} finally {
  if (process.platform === "darwin") {
    const trashRoot = path.join(os.homedir(), ".Trash");
    fs.mkdirSync(trashRoot, { recursive: true });
    fs.renameSync(
      temporaryDirectory,
      path.join(trashRoot, `${path.basename(temporaryDirectory)}-${crypto.randomUUID()}`),
    );
  }
}
