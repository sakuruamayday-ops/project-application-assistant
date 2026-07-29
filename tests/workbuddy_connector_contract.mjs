import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";

import {
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

const portalConnector = await readFile(
  new URL("../services/knowledge-portal/installers/jiaotang-agent.mjs", import.meta.url),
);
const packagedConnector = await readFile(
  new URL("../skills/_runtime/jiaotang-kb/jiaotang-agent.mjs", import.meta.url),
);
assert.deepEqual(packagedConnector, portalConnector);

process.stdout.write("WorkBuddy connector contract passed.\n");
