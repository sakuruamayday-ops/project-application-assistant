import assert from "node:assert/strict";
import test from "node:test";
import { pathToFileURL } from "node:url";

import AdmZip from "adm-zip";

globalThis.window = {};
const readerUrl = new URL(
  "../../../services/knowledge-portal/static/skills-manager/zip-reader.js",
  import.meta.url,
);
await import(`${pathToFileURL(readerUrl.pathname).href}?test=${Date.now()}`);

function exactArrayBuffer(buffer) {
  return buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.byteLength);
}

test("PWA ZIP reader expands a normal deflate archive", async () => {
  const archive = new AdmZip();
  archive.addFile("suite/skills/example/SKILL.md", Buffer.from("# example\n"));
  const files = await window.JiaotangZip.readZip(exactArrayBuffer(archive.toBuffer()));
  assert.equal(
    new TextDecoder().decode(files.get("suite/skills/example/SKILL.md")),
    "# example\n",
  );
});

test("PWA ZIP reader rejects a traversal segment", async () => {
  const archive = new AdmZip();
  archive.addFile("ok/file", Buffer.from("unsafe"));
  const bytes = Buffer.from(archive.toBuffer());
  const central = bytes.indexOf(Buffer.from([0x50, 0x4b, 0x01, 0x02]));
  assert.ok(central >= 0);
  Buffer.from("../evil").copy(bytes, central + 46);
  await assert.rejects(
    window.JiaotangZip.readZip(exactArrayBuffer(bytes)),
    /ZIP路径不安全/,
  );
});
