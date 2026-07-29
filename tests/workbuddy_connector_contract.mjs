import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";

import {
  activationCanonical,
  appendUrlPath,
  expectedInstallerSha256,
  testCredentialPath,
} from "../services/knowledge-portal/installers/jiaotang-agent.mjs";


const manifest = {
  installer_sha256: "a".repeat(64),
  workbuddy_plugin: {connector_sha256: "b".repeat(64)},
};

assert.equal(expectedInstallerSha256(manifest, false), "a".repeat(64));
assert.equal(expectedInstallerSha256(manifest, true), "b".repeat(64));
process.env.JIAOTANG_TEST_CREDENTIAL_FILE = "C:\\temp\\jiaotang-test.json";
delete process.env.JIAOTANG_ENABLE_TEST_CREDENTIAL_FILE;
assert.equal(testCredentialPath(), "");
process.env.JIAOTANG_ENABLE_TEST_CREDENTIAL_FILE = "1";
assert.equal(
  testCredentialPath(),
  "C:\\temp\\jiaotang-test.json",
);
delete process.env.JIAOTANG_TEST_CREDENTIAL_FILE;
delete process.env.JIAOTANG_ENABLE_TEST_CREDENTIAL_FILE;
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
const connectorSource = portalConnector.toString("utf8");
assert.match(
  connectorSource,
  /argumentsValue\["result-url"\] = resultEndpoint\.toString\(\)/,
);
const pluginServeStart = connectorSource.indexOf("async function pluginServe");
const pluginServeEnd = connectorSource.indexOf(
  "function installationFailure",
  pluginServeStart,
);
assert.ok(pluginServeStart >= 0 && pluginServeEnd > pluginServeStart);
assert.match(
  connectorSource.slice(pluginServeStart, pluginServeEnd),
  /reportInstallationResult\(\s*installationArguments,/,
);

process.stdout.write("WorkBuddy connector contract passed.\n");
