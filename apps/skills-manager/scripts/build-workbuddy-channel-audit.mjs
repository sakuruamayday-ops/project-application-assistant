import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { verifySkillArchive } from "../core/security.cjs";


const appRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);

function argumentsFrom(argv) {
  const options = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!key?.startsWith("--") || !value) {
      throw new Error(`参数不完整：${key || "<empty>"}`);
    }
    options[key.slice(2)] = value;
  }
  for (const required of [
    "package",
    "source-audit",
    "audit-output",
    "checksums-output",
    "version",
    "tag",
    "git-commit",
  ]) {
    if (!options[required]) throw new Error(`缺少 --${required}`);
  }
  return options;
}

function sha256(file) {
  return crypto
    .createHash("sha256")
    .update(fs.readFileSync(file))
    .digest("hex");
}

function writeNew(file, content) {
  const target = path.resolve(file);
  if (fs.existsSync(target)) {
    throw new Error(`输出已存在，拒绝覆盖：${target}`);
  }
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, content, { encoding: "utf8", mode: 0o600 });
}

const options = argumentsFrom(process.argv.slice(2));
const packagePath = path.resolve(options.package);
const security = JSON.parse(
  fs.readFileSync(path.join(appRoot, "config", "security.json"), "utf8"),
);
const actualSha = sha256(packagePath);
const sourceAuditPath = path.resolve(options["source-audit"]);
const source = JSON.parse(fs.readFileSync(sourceAuditPath, "utf8"));
const workbuddy = source?.public_suite_artifacts?.find(
  (item) => item?.requested_artifact_type === "workbuddy-plugin-suite",
);
if (
  source?.schema_version !== 2
  || source?.artifact_type !== "bundle-only-skill-suite-double-release"
  || source?.release_tag !== `V${options.version}`
  || source?.failed !== 0
  || workbuddy?.status !== "pass"
  || workbuddy?.archive_sha256 !== actualSha
  || path.basename(workbuddy?.archive || "") !== path.basename(packagePath)
) {
  throw new Error("集合发布审计与 WorkBuddy 候选文件不一致");
}
const sourceProvenance = {
  mode: "fresh-collection-build",
  audit_file: path.basename(sourceAuditPath),
  audit_sha256: sha256(sourceAuditPath),
  build_mode: source.build_mode,
  release_gate_status: source.release_gates?.status,
  skill_count: source.skill_count,
};
const verification = verifySkillArchive({
  archivePath: packagePath,
  expectedSha256: actualSha,
  securityConfig: security,
});
if (verification.artifactType !== "workbuddy-plugin") {
  throw new Error("候选文件不是 WorkBuddy 插件市场包");
}
const sidecars = [
  `${packagePath}.sha256`,
  `${packagePath}.sig`,
  packagePath.replace(/\.zip$/i, "-publisher-ed25519.pub"),
  `${packagePath}.signature.json`,
];
for (const sidecar of sidecars) {
  if (!fs.statSync(sidecar, { throwIfNoEntry: false })?.isFile()) {
    throw new Error(`WorkBuddy 候选缺少完整性旁车：${path.basename(sidecar)}`);
  }
}
const audit = {
  schema: "jiaotang-workbuddy-channel-release-audit/v1",
  status: "pass",
  version: options.version,
  tag: options.tag,
  git_commit: options["git-commit"],
  generated_at: new Date().toISOString(),
  distribution: "cross-platform-workbuddy-local-marketplace",
  source_provenance: sourceProvenance,
  artifact: {
    file: path.basename(packagePath),
    bytes: fs.statSync(packagePath).size,
    sha256: actualSha,
    outer_fixed_installers: false,
    install_mode: "workbuddy-in-app-local-marketplace",
    sidecars: sidecars.map((file) => ({
      file: path.basename(file),
      bytes: fs.statSync(file).size,
      sha256: sha256(file),
    })),
  },
  signature_verification: {
    status: verification.status,
    artifact_type: verification.artifactType,
    signatures: verification.signatures,
    verified_files: verification.verifiedFiles,
    verified_allowlist_files: verification.verifiedFileAllowlist.length,
    archive_entries: verification.entries,
    publisher_fingerprint: verification.publisherFingerprint,
  },
  compatibility: {
    skills_content_changed: false,
    existing_release_assets_mutated: false,
    existing_users_forced_to_update: false,
  },
};
writeNew(
  options["audit-output"],
  `${JSON.stringify(audit, null, 2)}\n`,
);
const auditPath = path.resolve(options["audit-output"]);
const checksumLines = [
  `${actualSha}  ${path.basename(packagePath)}`,
  ...sidecars.map((file) => `${sha256(file)}  ${path.basename(file)}`),
  `${sha256(auditPath)}  ${path.basename(auditPath)}`,
];
writeNew(options["checksums-output"], `${checksumLines.join("\n")}\n`);
console.log(JSON.stringify(audit, null, 2));
