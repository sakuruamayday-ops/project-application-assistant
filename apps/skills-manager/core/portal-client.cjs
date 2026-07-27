const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { Readable } = require("node:stream");
const { pipeline } = require("node:stream/promises");
const { signedHeaders } = require("./device-auth.cjs");

function normalizedPortalUrl(value) {
  const url = new URL(value);
  if (url.protocol !== "https:" && !["localhost", "127.0.0.1"].includes(url.hostname)) {
    throw new Error("门户地址必须使用 HTTPS");
  }
  url.pathname = url.pathname.replace(/\/+$/, "");
  url.search = "";
  url.hash = "";
  return url;
}

function requestHeaders({ accessToken, credentials, method, url, body = Buffer.alloc(0) }) {
  const headers = {
    Accept: "application/json",
    "User-Agent": "jiaotang-skills-manager/0.1",
  };
  if (credentials) Object.assign(headers, signedHeaders(credentials, method, url, body));
  else if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  return headers;
}

async function fetchChannels({ portalUrl, accessToken, credentials, signal }) {
  const base = normalizedPortalUrl(portalUrl);
  const endpoint = new URL("/v1/skills/channels", base);
  const response = await fetch(endpoint, {
    headers: requestHeaders({
      accessToken,
      credentials,
      method: "GET",
      url: endpoint,
    }),
    signal,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`读取发布通道失败：HTTP ${response.status} ${detail.slice(0, 160)}`);
  }
  const payload = await response.json();
  if (payload.schema !== "jiaotang-skill-channels/v1" || !Array.isArray(payload.channels)) {
    throw new Error("门户返回了无法识别的发布通道格式");
  }
  return payload;
}

async function downloadArtifact({
  portalUrl,
  accessToken,
  credentials,
  channel,
  destination,
  signal,
}) {
  const base = normalizedPortalUrl(portalUrl);
  const endpoint = new URL(channel.download_url, base);
  if (endpoint.origin !== base.origin) {
    throw new Error("下载地址越过了已连接门户的来源边界");
  }
  const response = await fetch(endpoint, {
    headers: requestHeaders({
      accessToken,
      credentials,
      method: "GET",
      url: endpoint,
    }),
    signal,
    redirect: "error",
  });
  if (!response.ok || !response.body) {
    throw new Error(`下载失败：HTTP ${response.status}`);
  }
  fs.mkdirSync(path.dirname(destination), { recursive: true, mode: 0o700 });
  const temporary = `${destination}.part`;
  const hash = crypto.createHash("sha256");
  let bytes = 0;
  const source = Readable.fromWeb(response.body);
  source.on("data", (chunk) => {
    bytes += chunk.length;
    if (bytes > 1024 * 1024 * 1024) source.destroy(new Error("下载包超过 1 GiB 安全上限"));
    hash.update(chunk);
  });
  try {
    await pipeline(source, fs.createWriteStream(temporary, { mode: 0o600 }));
    fs.renameSync(temporary, destination);
  } catch (error) {
    if (fs.existsSync(temporary)) fs.unlinkSync(temporary);
    throw error;
  }
  return {
    path: destination,
    sha256: hash.digest("hex"),
    bytes,
  };
}

module.exports = {
  normalizedPortalUrl,
  fetchChannels,
  downloadArtifact,
};
