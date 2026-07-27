(function () {
  const decoder = new TextDecoder();
  const u16 = (view, offset) => view.getUint16(offset, true);
  const u32 = (view, offset) => view.getUint32(offset, true);
  const safePath = (value) => {
    const path = value.replaceAll("\\", "/").replace(/^\.\/+/, "");
    const segments = path.replace(/\/$/, "").split("/");
    if (
      !path
      || path.startsWith("/")
      || segments.some((segment) => !segment || segment === "." || segment === "..")
      || /^[A-Za-z]:\//.test(path)
      || path.includes("\0")
    ) throw new Error(`ZIP路径不安全：${value}`);
    return path;
  };
  async function inflate(data) {
    const stream = new Blob([data]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
    return new Uint8Array(await new Response(stream).arrayBuffer());
  }
  async function readZip(buffer) {
    const bytes = new Uint8Array(buffer);
    const view = new DataView(buffer);
    let eocd = -1;
    for (let i = bytes.length - 22; i >= Math.max(0, bytes.length - 65557); i -= 1) {
      if (u32(view, i) === 0x06054b50) { eocd = i; break; }
    }
    if (eocd < 0) throw new Error("不是有效ZIP文件");
    const count = u16(view, eocd + 10);
    let cursor = u32(view, eocd + 16);
    const entries = new Map();
    let expanded = 0;
    for (let index = 0; index < count; index += 1) {
      if (u32(view, cursor) !== 0x02014b50) throw new Error("ZIP中央目录损坏");
      const flags = u16(view, cursor + 8);
      const method = u16(view, cursor + 10);
      const compressedSize = u32(view, cursor + 20);
      const size = u32(view, cursor + 24);
      const nameLength = u16(view, cursor + 28);
      const extraLength = u16(view, cursor + 30);
      const commentLength = u16(view, cursor + 32);
      const localOffset = u32(view, cursor + 42);
      const name = safePath(decoder.decode(bytes.slice(cursor + 46, cursor + 46 + nameLength)));
      cursor += 46 + nameLength + extraLength + commentLength;
      if (name.endsWith("/")) continue;
      if (flags & 1) throw new Error("不支持加密ZIP");
      if (![0, 8].includes(method)) throw new Error(`不支持ZIP压缩算法：${method}`);
      if (entries.has(name)) throw new Error(`ZIP包含重复路径：${name}`);
      if (u32(view, localOffset) !== 0x04034b50) throw new Error("ZIP本地文件头损坏");
      const localNameLength = u16(view, localOffset + 26);
      const localExtraLength = u16(view, localOffset + 28);
      const start = localOffset + 30 + localNameLength + localExtraLength;
      const compressed = bytes.slice(start, start + compressedSize);
      const data = method === 0 ? compressed : await inflate(compressed);
      if (data.length !== size) throw new Error(`ZIP文件长度不匹配：${name}`);
      expanded += size;
      if (expanded > 1024 * 1024 * 1024) throw new Error("ZIP解压后超过1 GiB安全上限");
      entries.set(name, data);
    }
    return entries;
  }
  window.JiaotangZip = { readZip };
})();
