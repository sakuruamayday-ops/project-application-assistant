import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";

import {
  activationCanonical,
  appendUrlPath,
  expectedInstallerSha256,
} from "../services/knowledge-portal/installers/jiaotang-agent.mjs";


const manifest = {
  installer_sha256: "a".repeat(64),
  workbuddy_plugin: {connector_sha256: "b".repeat(64)},
};

assert.equal(expectedInstallerSha256(manifest, false), "a".repeat(64));
assert.equal(expectedInstallerSha256(manifest, true), "b".repeat(64));
assert.equal(
  appendUrlPath(
    "https://zshjiaotang.cn/v1/agent-bootstrap/jbe_test?platform=unified",
    "register",
  ).toString(),
  "https://zshjiaotang.cn/v1/agent-bootstrap/jbe_test/register?platform=unified",
);
assert.equal(
  activationCanonical({
    enrollmentCode: "jbe_test",
    deviceId: "device:test-installation",
    keyId: "jdk_test-key-identifier-1234",
    token: "jtk_test-token",
  }).toString("utf8"),
  [
    "JIAOTANG-ACTIVATION-V1",
    "jbe_test",
    "device:test-installation",
    "jdk_test-key-identifier-1234",
    "0a71f0ef9d9862e9273b2898c42371d5ad4d0cd30a396567550fa68f53e43255",
  ].join("\n"),
);

const portalConnector = await readFile(
  new URL("../services/knowledge-portal/installers/jiaotang-agent.mjs", import.meta.url),
);
const packagedConnector = await readFile(
  new URL("../skills/_runtime/jiaotang-kb/jiaotang-agent.mjs", import.meta.url),
);
assert.deepEqual(packagedConnector, portalConnector);

process.stdout.write("WorkBuddy connector contract passed.\n");
