const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");

const SENSITIVE = /(authorization|bootstrap|credential|password|private|secret|token)/i;

function sanitized(value, depth = 0) {
  if (depth > 6) return "[DEPTH_LIMIT]";
  if (Array.isArray(value)) return value.slice(0, 100).map((item) => sanitized(item, depth + 1));
  if (!value || typeof value !== "object") return value;
  const result = {};
  for (const [key, item] of Object.entries(value)) {
    result[key] = SENSITIVE.test(key) ? "[REDACTED]" : sanitized(item, depth + 1);
  }
  return result;
}

function hashRecord(record) {
  return crypto.createHash("sha256").update(JSON.stringify(record)).digest("hex");
}

function auditFiles(directory) {
  if (!fs.existsSync(directory)) return [];
  return fs.readdirSync(directory)
    .filter((name) => /^events-\d{4}-\d{2}-\d{2}\.jsonl$/.test(name))
    .sort();
}

function lastAuditRecord(directory) {
  const files = auditFiles(directory);
  if (!files.length) return null;
  const latest = path.join(directory, files.at(-1));
  const lines = fs.readFileSync(latest, "utf8").split("\n").filter(Boolean);
  if (!lines.length) return null;
  const record = JSON.parse(lines.at(-1));
  if (record.schema !== "jiaotang-skills-manager-audit/v1" || !record.event_hash) {
    throw new Error("既有审计日志末条记录格式无效");
  }
  const { event_hash: eventHash, ...unsigned } = record;
  if (hashRecord(unsigned) !== eventHash) {
    throw new Error("既有审计日志末条记录哈希不匹配");
  }
  return record;
}

function appendAuditEvent(root, event, outcome, details = {}, options = {}) {
  const now = new Date();
  const directory = path.join(root, "audit");
  fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
  const day = now.toISOString().slice(0, 10);
  const destination = path.join(directory, `events-${day}.jsonl`);
  const previous = lastAuditRecord(directory);
  const record = {
    schema: "jiaotang-skills-manager-audit/v1",
    timestamp: now.toISOString(),
    session_id: options.sessionId || null,
    event,
    outcome,
    details: sanitized(details),
    previous_hash: previous?.event_hash || null,
  };
  const signedRecord = {
    ...record,
    event_hash: hashRecord(record),
  };
  fs.appendFileSync(destination, `${JSON.stringify(signedRecord)}\n`, { mode: 0o600 });
  return destination;
}

function verifyAuditChain(root) {
  const directory = path.join(root, "audit");
  let previousHash = null;
  let count = 0;
  for (const file of auditFiles(directory)) {
    const lines = fs.readFileSync(path.join(directory, file), "utf8").split("\n").filter(Boolean);
    for (const line of lines) {
      const record = JSON.parse(line);
      const { event_hash: eventHash, ...unsigned } = record;
      if (record.previous_hash !== previousHash) {
        throw new Error(`审计链前序哈希不匹配：${file}`);
      }
      if (!eventHash || hashRecord(unsigned) !== eventHash) {
        throw new Error(`审计记录哈希不匹配：${file}`);
      }
      previousHash = eventHash;
      count += 1;
    }
  }
  return { status: "verified", count, lastHash: previousHash };
}

module.exports = {
  appendAuditEvent,
  sanitized,
  verifyAuditChain,
};
