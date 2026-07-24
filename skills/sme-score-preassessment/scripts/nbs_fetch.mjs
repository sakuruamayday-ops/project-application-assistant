import { execFileSync } from "node:child_process";
import fs from "node:fs";
import fsp from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const yearbookIndexUrl = "https://www.stats.gov.cn/sj/ndsj/";
const columns = [
  "enterprise_units", "total_assets", "current_assets", "receivables",
  "inventory", "finished_goods", "total_liabilities", "revenue",
  "operating_cost", "selling_expense", "admin_expense",
  "financial_expense", "total_profit", "average_employees"
];
const xBounds = [0.14, 0.205, 0.265, 0.325, 0.39, 0.45, 0.51, 0.57, 0.635, 0.695, 0.755, 0.82, 0.88, 0.94, 1.01];

function arg(name, fallback = null) {
  const i = process.argv.indexOf(name);
  return i >= 0 && i + 1 < process.argv.length ? process.argv[i + 1] : fallback;
}

function normalizeText(s) {
  return s
    .replace(/[，,]/g, "、")
    .replace(/\s+/g, "")
    .replace(/煤崁/g, "煤炭")
    .replace(/煤广/g, "煤炭")
    .replace(/^煤开采/g, "煤炭开采")
    .replace(/劇鞋/g, "制鞋")
    .replace(/寡具/g, "家具")
    .replace(/剃造/g, "制造")
    .replace(/制品和制鞋业$/, "制品和制鞋业")
    .trim();
}

function parseNumber(raw, columnIndex) {
  let s = raw.replace(/[,\s]/g, "").replace(/[Oo]/g, "0").replace(/[—−]/g, "-").replace(/:/g, ".").replace(/\.$/, "");
  if (!/^-?\d+(?:\.\d+)?$/.test(s)) return null;
  if (columnIndex > 0 && columnIndex < 13 && !s.includes(".")) {
    const neg = s.startsWith("-");
    const digits = neg ? s.slice(1) : s;
    if (digits.length >= 2) s = `${neg ? "-" : ""}${digits.slice(0, -1)}.${digits.slice(-1)}`;
  }
  return Number(s);
}

function parseTsv(tsv) {
  const obs = tsv.trim().split(/\r?\n/).slice(1).map(line => {
    const [x, y, w, h, confidence, ...textParts] = line.split("\t");
    return { x: Number(x), y: Number(y), w: Number(w), h: Number(h), confidence: Number(confidence), text: textParts.join("\t").trim() };
  }).filter(o => o.text);

  const numeric = obs.filter(o => {
    const cleaned = o.text.replace(/[,\s]/g, "").replace(/[Oo]/g, "0").replace(/[—−]/g, "-").replace(/:/g, ".").replace(/\.$/, "");
    return o.x >= 0.14 && /^-?\d+(?:\.\d+)?$/.test(cleaned);
  });
  const groups = [];
  for (const item of numeric.sort((a, b) => b.y - a.y || a.x - b.x)) {
    let group = groups.find(g => Math.abs(g.y - item.y) <= 0.0045);
    if (!group) {
      group = { y: item.y, items: [] };
      groups.push(group);
    }
    group.items.push(item);
    group.y = group.items.reduce((s, x) => s + x.y, 0) / group.items.length;
  }
  const dataRows = groups.filter(g => g.items.length >= 12).sort((a, b) => b.y - a.y);
  const labels = obs.filter(o => o.x < 0.14 && o.y < 0.91 && o.y > 0.02);

  return dataRows.map((row, idx) => {
    const prev = idx === 0 ? null : dataRows[idx - 1];
    const next = idx === dataRows.length - 1 ? null : dataRows[idx + 1];
    const upper = !prev ? row.y + 0.014 : (prev.y - row.y > 0.026 ? row.y + 0.009 : (prev.y + row.y) / 2);
    const lower = !next ? row.y - 0.014 : (row.y - next.y > 0.026 ? next.y + 0.009 : (row.y + next.y) / 2);
    const name = normalizeText(labels
      .filter(o => o.y <= upper && o.y > lower)
      .sort((a, b) => b.y - a.y || a.x - b.x)
      .map(o => o.text)
      .join(""));
    const values = {};
    for (let col = 0; col < columns.length; col++) {
      const candidates = row.items.filter(o => o.x >= xBounds[col] && o.x < xBounds[col + 1]);
      const chosen = candidates.sort((a, b) => b.confidence - a.confidence)[0];
      values[columns[col]] = chosen ? parseNumber(chosen.text, col) : null;
    }
    return { name, ...values };
  }).filter(r => r.name);
}

function validateRows(rows, map) {
  const expected = new Map(map.industries.map(x => [x.name, x.code]));
  const matched = [];
  for (const row of rows) {
    let exact = [...expected.keys()].find(name => normalizeText(name) === normalizeText(row.name));
    if (!exact) {
      exact = [...expected.keys()].find(name => normalizeText(name).includes(normalizeText(row.name)) || normalizeText(row.name).includes(normalizeText(name)));
    }
    if (exact) matched.push({ code: expected.get(exact), name: exact, ...Object.fromEntries(Object.entries(row).filter(([k]) => k !== "name")) });
  }
  if (matched.length < 35) {
    throw new Error(`OCR 行业匹配仅 ${matched.length}/41，低于自动发布阈值 35；需人工检查源图或映射表。`);
  }
  const unmatched = rows.map(r => r.name).filter(name => !matched.some(m => normalizeText(m.name) === normalizeText(name)));
  if (unmatched.length) console.error(`OCR 未映射行: ${unmatched.join(" | ")}`);
  for (const row of matched) {
    const required = ["total_assets", "total_liabilities", "revenue", "operating_cost", "selling_expense", "admin_expense", "total_profit", "average_employees"];
    const missing = required.filter(k => !Number.isFinite(row[k]));
    if (missing.length) throw new Error(`${row.name} 缺失字段: ${missing.join(", ")}；OCR行=${JSON.stringify(row)}`);
  }
  return matched;
}

async function download(url, target) {
  const response = await fetch(url, { headers: { "User-Agent": "Mozilla/5.0 Codex SME benchmark updater" } });
  if (!response.ok) throw new Error(`下载失败 ${response.status}: ${url}`);
  await fsp.writeFile(target, Buffer.from(await response.arrayBuffer()));
}

async function fetchDecodedText(url) {
  const response = await fetch(url, { headers: { "User-Agent": "Mozilla/5.0 Codex SME benchmark updater" } });
  if (!response.ok) throw new Error(`页面下载失败 ${response.status}: ${url}`);
  const bytes = await response.arrayBuffer();
  for (const encoding of ["utf-8", "gb18030"]) {
    try {
      const text = new TextDecoder(encoding, { fatal: true }).decode(bytes);
      if (/统计年鉴|中国统计|China Statistical/i.test(text)) return text;
    } catch {
      // 尝试下一编码。
    }
  }
  return new TextDecoder("gb18030").decode(bytes);
}

async function discoverYearbooks(limit = 3) {
  const indexHtml = await fetchDecodedText(yearbookIndexUrl);
  const editions = [...indexHtml.matchAll(/(?:href=["'][^"']*\/)?(\d{4})\/(?:indexch\.htm)?["']/gi)]
    .map(match => Number(match[1]))
    .filter(year => year >= 2000 && year <= new Date().getFullYear() + 1);
  const uniqueEditions = [...new Set(editions)].sort((a, b) => b - a);
  if (!uniqueEditions.length) throw new Error("国家统计局年鉴目录未识别到可用版本。");

  const discovered = [];
  for (const yearbookYear of uniqueEditions) {
    const noteUrl = `https://www.stats.gov.cn/sj/ndsj/${yearbookYear}/html/note.htm`;
    let dataYear = null;
    try {
      const note = stripHtml(await fetchDecodedText(noteUrl));
      const match = note.match(/系统收录[^。]{0,100}?(\d{4})年(?:经济|社会|全国|数据)/);
      if (match) dataYear = Number(match[1]);
    } catch {
      // 个别旧版没有统一编者说明页面，后续按版本年份校验回退。
    }
    if (!dataYear) dataYear = yearbookYear - 1;
    const sourceUrl = `https://www.stats.gov.cn/sj/ndsj/${yearbookYear}/html/C13-02.jpg`;
    const sourceCheck = await fetch(sourceUrl, { method: "HEAD", headers: { "User-Agent": "Mozilla/5.0 Codex SME benchmark updater" } });
    if (sourceCheck.ok) discovered.push({ dataYear, yearbookYear, sourceUrl, noteUrl });
    if (discovered.length >= limit) break;
  }
  if (discovered.length < 2) throw new Error(`仅识别到 ${discovered.length} 个可用年鉴版本，无法形成同比结构基准。`);
  return discovered.sort((a, b) => a.dataYear - b.dataYear);
}

function stripHtml(html) {
  return html
    .replace(/<br\s*\/?>/gi, " ")
    .replace(/<[^>]+>/g, "")
    .replace(/&nbsp;|&#160;/gi, " ")
    .replace(/&#39;|&apos;/gi, "'")
    .replace(/&amp;/gi, "&")
    .replace(/\s+/g, " ")
    .trim();
}

async function fetchAnnualGrowth(url, year, map) {
  const response = await fetch(url, { headers: { "User-Agent": "Mozilla/5.0 Codex SME benchmark updater" } });
  if (!response.ok) throw new Error(`年度快报下载失败 ${response.status}: ${url}`);
  const html = await response.text();
  const rows = [];
  for (const match of html.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi)) {
    const cells = [...match[1].matchAll(/<td\b[^>]*>([\s\S]*?)<\/td>/gi)].map(x => stripHtml(x[1]));
    if (cells.length < 7) continue;
    const rawName = normalizeText(cells[0].replace(/^其中[:：]?/, ""));
    const industry = map.industries.find(x => normalizeText(x.name) === rawName);
    if (!industry) continue;
    const nums = cells.slice(1).map(x => Number(x.replace(/[,%\s]/g, "")));
    if (nums.slice(0, 6).every(Number.isFinite)) {
      rows.push({
        code: industry.code,
        name: industry.name,
        revenue: nums[0],
        revenue_growth: nums[1] / 100,
        operating_cost: nums[2],
        operating_cost_growth: nums[3] / 100,
        total_profit: nums[4],
        total_profit_growth: nums[5] / 100
      });
    }
  }
  const deduped = [...new Map(rows.map(x => [x.code, x])).values()];
  if (deduped.length < 35) throw new Error(`年度快报仅解析 ${deduped.length}/41 个行业，停止覆盖增长率。`);
  return { year, source_url: url, accessed_at: new Date().toISOString().slice(0, 10), rows: deduped };
}

async function main() {
  const output = path.resolve(arg("--output", path.join(process.cwd(), "nbs_benchmarks.json")));
  const cacheDir = path.resolve(arg("--cache-dir", path.join(path.dirname(output), "nbs_cache")));
  const yearsArg = arg("--years", "auto");
  const discovered = await discoverYearbooks(3);
  const requestedYears = yearsArg === "auto" ? null : yearsArg.split(",").map(Number);
  const selected = requestedYears
    ? requestedYears.map(dataYear => {
        const hit = discovered.find(item => item.dataYear === dataYear);
        if (!hit) throw new Error(`官方最近年鉴中未识别到 ${dataYear} 数据期。可用数据期：${discovered.map(x => x.dataYear).join("、")}`);
        return hit;
      })
    : discovered;
  const years = selected.map(item => item.dataYear);
  const map = JSON.parse(await fsp.readFile(path.join(here, "../assets/nbs_industry_map.json"), "utf8"));
  await fsp.mkdir(cacheDir, { recursive: true });
  const registry = {
    generated_at: new Date().toISOString(),
    unit: { financial: "亿元", average_employees: "万人" },
    table: "按行业分规模以上工业企业主要指标 13-2",
    years: {}
  };

  for (const { dataYear: year, yearbookYear, sourceUrl, noteUrl } of selected) {
    const imagePath = path.join(cacheDir, `C13-02_${year}.jpg`);
    const tsvPath = path.join(cacheDir, `C13-02_${year}.ocr.tsv`);
    if (!fs.existsSync(imagePath)) await download(sourceUrl, imagePath);
    const tsv = execFileSync("xcrun", ["swift", path.join(here, "nbs_vision_ocr.swift"), imagePath], { encoding: "utf8", maxBuffer: 20 * 1024 * 1024 });
    await fsp.writeFile(tsvPath, tsv);
    const rows = validateRows(parseTsv(tsv), map);
    registry.years[String(year)] = {
      data_year: year,
      yearbook_year: yearbookYear,
      yearbook_title: `中国统计年鉴${yearbookYear}`,
      source_url: sourceUrl,
      note_url: noteUrl,
      accessed_at: new Date().toISOString().slice(0, 10),
      rows
    };
  }
  const annualUrl = arg("--annual-url");
  const annualYear = Number(arg("--annual-year", ""));
  if (annualUrl) {
    if (!Number.isFinite(annualYear)) throw new Error("使用 --annual-url 时必须提供 --annual-year。");
    registry.annual_growth = await fetchAnnualGrowth(annualUrl, annualYear, map);
  }
  await fsp.writeFile(output, JSON.stringify(registry, null, 2));
  console.log(JSON.stringify({
    output,
    selected_yearbooks: selected,
    years,
    rows: Object.fromEntries(Object.entries(registry.years).map(([y, v]) => [y, v.rows.length]))
  }));
}

main().catch(error => {
  console.error(error.stack || error.message);
  process.exit(1);
});
