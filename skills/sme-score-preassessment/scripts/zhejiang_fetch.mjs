import fsp from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const officialRoot = "https://zjjcmspublicnew.oss-cn-hangzhou-zwynet-d01-a.internet.cloud.zj.gov.cn/cms_files/jcms1/web3077/site/flash/tjj/Reports1";

function arg(name, fallback = null) {
  const i = process.argv.indexOf(name);
  return i >= 0 && i + 1 < process.argv.length ? process.argv[i + 1] : fallback;
}

function normalizeText(value) {
  return String(value ?? "")
    .replace(/\s+/g, "")
    .replace(/[()]/g, match => match === "(" ? "（" : "）")
    .replace(/、/g, "和")
    .trim();
}

async function fetchText(url) {
  const response = await fetch(url, {
    headers: { "User-Agent": "Mozilla/5.0 Codex Zhejiang SME benchmark updater" }
  });
  if (!response.ok) throw new Error(`页面下载失败 ${response.status}: ${url}`);
  return response.text();
}

function resolveTableUrl(indexUrl, href) {
  return new URL(href.replace(/^\.\//, ""), indexUrl).toString();
}

async function discoverYearbooks(limit = 3) {
  const results = [];
  const currentYear = new Date().getFullYear();
  for (let edition = currentYear; edition >= currentYear - 7; edition--) {
    const indexUrl = `${officialRoot}/${edition}浙江统计年鉴/indexcn.html`;
    let html;
    try {
      html = await fetchText(indexUrl);
    } catch {
      continue;
    }
    const hrefs = [...html.matchAll(/(?:href|main)=["']([^"']*按行业分的规模以上工业企业主要经济指标[^"']*\.html)["']/g)]
      .map(match => match[1]);
    const href = hrefs.find(item => /（\d{4}年）/.test(item));
    if (!href) continue;
    const dataYear = Number(href.match(/（(\d{4})年）/)?.[1]);
    if (!Number.isFinite(dataYear)) continue;
    results.push({
      dataYear,
      yearbookYear: edition,
      indexUrl,
      tableUrl: resolveTableUrl(indexUrl, href),
      tableLabel: decodeURIComponent(href.split("/").at(-1).replace(/\.html$/i, ""))
    });
    if (results.length >= limit) break;
  }
  if (results.length < 2) throw new Error(`仅识别到 ${results.length} 个浙江统计年鉴行业表，无法形成同比基准。`);
  return results.sort((a, b) => a.dataYear - b.dataYear);
}

function parseEmbeddedData(html) {
  const marker = "var data = ";
  const start = html.indexOf(marker);
  if (start < 0) throw new Error("浙江统计年鉴表未找到嵌入数据。");
  const jsonStart = start + marker.length;
  const jsonEnd = html.indexOf(";", jsonStart);
  if (jsonEnd < 0) throw new Error("浙江统计年鉴表嵌入数据结尾未识别。");
  return JSON.parse(html.slice(jsonStart, jsonEnd).trim());
}

function numberOrNull(value) {
  const text = String(value ?? "").replace(/[,\s]/g, "");
  if (!text || !/^-?\d+(?:\.\d+)?$/.test(text)) return null;
  return Number(text);
}

function parseIndustryRows(payload, map) {
  const expected = new Map(map.industries.map(item => [normalizeText(item.name), item]));
  const rows = [];
  for (const raw of payload.data ?? []) {
    const industry = expected.get(normalizeText(raw[0]));
    if (!industry) continue;
    const row = {
      code: industry.code,
      name: industry.name,
      enterprise_units: numberOrNull(raw[1]),
      total_assets: numberOrNull(raw[4]),
      total_liabilities: numberOrNull(raw[5]),
      revenue: numberOrNull(raw[8]),
      operating_cost: numberOrNull(raw[9]),
      selling_expense: numberOrNull(raw[11]),
      admin_expense: numberOrNull(raw[12]),
      financial_expense: numberOrNull(raw[13]),
      total_profit: numberOrNull(raw[14]),
      average_employees: numberOrNull(raw[17])
    };
    const required = ["total_assets", "total_liabilities", "revenue", "operating_cost", "selling_expense", "admin_expense", "total_profit", "average_employees"];
    if (required.every(key => Number.isFinite(row[key]))) rows.push(row);
  }
  if (rows.length < 30) throw new Error(`浙江统计年鉴仅映射 ${rows.length} 个有效工业行业，停止覆盖缓存。`);
  return rows;
}

async function main() {
  const output = path.resolve(arg("--output", path.join(here, "../assets/zhejiang_benchmarks_latest.json")));
  const map = JSON.parse(await fsp.readFile(path.join(here, "../assets/nbs_industry_map.json"), "utf8"));
  const selected = await discoverYearbooks(3);
  const accessedAt = new Date().toISOString().slice(0, 10);
  const registry = {
    generated_at: new Date().toISOString(),
    region: "浙江省",
    agency: "浙江省统计局",
    scope: "浙江省规模以上工业企业",
    unit: { financial: "亿元", average_employees: "万人" },
    table: "按行业分的规模以上工业企业主要经济指标",
    years: {}
  };

  for (const item of selected) {
    const html = await fetchText(item.tableUrl);
    const payload = parseEmbeddedData(html);
    const rows = parseIndustryRows(payload, map);
    registry.years[String(item.dataYear)] = {
      data_year: item.dataYear,
      yearbook_year: item.yearbookYear,
      yearbook_title: `浙江统计年鉴${item.yearbookYear}`,
      table_label: item.tableLabel,
      source_url: item.tableUrl,
      index_url: item.indexUrl,
      accessed_at: accessedAt,
      rows
    };
  }

  await fsp.mkdir(path.dirname(output), { recursive: true });
  await fsp.writeFile(output, JSON.stringify(registry, null, 2));
  console.log(JSON.stringify({
    output,
    selected_yearbooks: selected,
    rows: Object.fromEntries(Object.entries(registry.years).map(([year, value]) => [year, value.rows.length]))
  }));
}

main().catch(error => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
