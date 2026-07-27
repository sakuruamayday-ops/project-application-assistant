import assert from "node:assert/strict";
import test from "node:test";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { normalizedPortalUrl } = require("../core/portal-client.cjs");

test("portal URL requires HTTPS outside local development", () => {
  assert.equal(normalizedPortalUrl("https://zshjiaotang.cn/path/?x=1#fragment").toString(), "https://zshjiaotang.cn/path");
  assert.equal(normalizedPortalUrl("http://127.0.0.1:8000").origin, "http://127.0.0.1:8000");
  assert.throws(() => normalizedPortalUrl("http://example.com"), /必须使用 HTTPS/);
});
