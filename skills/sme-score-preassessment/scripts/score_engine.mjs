import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { resolveIndustry, validateInput } from "./score_core.mjs";

let artifactTool;
try {
  artifactTool = await import("@oai/artifact-tool");
} catch (error) {
  const bundledModules = process.env.CODEX_BUNDLED_NODE_MODULES;
  if (!bundledModules) throw error;
  artifactTool = await import(pathToFileURL(path.join(bundledModules, "@oai/artifact-tool/dist/artifact_tool.mjs")).href);
}
const { FileBlob, SpreadsheetFile, Workbook } = artifactTool;

function arg(name, fallback = null) {
  const i = process.argv.indexOf(name);
  return i >= 0 && i + 1 < process.argv.length ? process.argv[i + 1] : fallback;
}

const mode = arg("--mode", "score");
const outputPath = path.resolve(arg("--output", "sme_score_output.xlsx"));
const skillDir = path.resolve(arg("--skill-dir", process.cwd()));
const benchmarkPath = path.resolve(arg("--benchmark", path.join(skillDir, "assets/nbs_benchmarks_2022_2025.json")));
const zhejiangBenchmarkPath = path.resolve(arg("--zhejiang-benchmark", path.join(skillDir, "assets/zhejiang_benchmarks_latest.json")));
const mapPath = path.resolve(arg("--industry-map", path.join(skillDir, "assets/nbs_industry_map.json")));
const factsPath = arg("--facts");
const seedPath = arg("--seed-json");
const previewDir = arg("--preview-dir");
const projectLevelOverride = arg("--project-level");

const COLORS = {
  navy: "#18324B", blue: "#2F6B8A", sky: "#DCEEF7", pale: "#EFF7FB",
  input: "#FFF2CC", green: "#E2F0D9", red: "#FCE4D6", gray: "#E7E6E6",
  dark: "#24323D", white: "#FFFFFF", line: "#B7C9D6"
};

function title(sheet, text, endCol = "H") {
  sheet.mergeCells(`A1:${endCol}1`);
  const r = sheet.getRange(`A1:${endCol}1`);
  r.values = [[text]];
  r.format.fill = COLORS.navy;
  r.format.font = { bold: true, color: COLORS.white, size: 16 };
  r.format.rowHeight = 30;
  r.format.verticalAlignment = "center";
  r.format.horizontalAlignment = "left";
}

function section(range) {
  range.format.fill = COLORS.blue;
  range.format.font = { bold: true, color: COLORS.white };
  range.format.borders = {
    top: { style: "medium", color: COLORS.blue },
    bottom: { style: "medium", color: COLORS.blue },
    left: { style: "medium", color: COLORS.blue },
    right: { style: "medium", color: COLORS.blue }
  };
}

function header(range) {
  range.format.fill = COLORS.sky;
  range.format.font = { bold: true, color: COLORS.dark };
  range.format.borders = {
    insideHorizontal: { style: "thin", color: COLORS.line },
    insideVertical: { style: "thin", color: COLORS.line },
    top: { style: "medium", color: COLORS.blue },
    bottom: { style: "medium", color: COLORS.blue },
    left: { style: "medium", color: COLORS.blue },
    right: { style: "medium", color: COLORS.blue }
  };
  range.format.horizontalAlignment = "center";
  range.format.verticalAlignment = "center";
  range.format.wrapText = true;
}

function body(range) {
  range.format.borders = {
    insideHorizontal: { style: "thin", color: "#D9E2E8" },
    insideVertical: { style: "thin", color: "#D9E2E8" },
    top: { style: "thin", color: COLORS.line },
    bottom: { style: "medium", color: COLORS.line },
    left: { style: "medium", color: COLORS.line },
    right: { style: "medium", color: COLORS.line }
  };
  range.format.verticalAlignment = "center";
}

function fmtPct(range) {
  range.format.numberFormat = "0.00%";
  range.format.horizontalAlignment = "right";
}

function fmtNum(range, format = "#,##0.00") {
  range.format.numberFormat = format;
  range.format.horizontalAlignment = "right";
}

function setWidths(sheet, widths) {
  for (const [col, width] of Object.entries(widths)) sheet.getRange(`${col}:${col}`).format.columnWidth = width;
}

async function exportAndVerify(workbook, sheets) {
  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  const errorScan = await workbook.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
    options: { useRegex: true, maxResults: 200 },
    summary: "final formula error scan"
  });
  if (errorScan.ndjson && /#REF!|#DIV\/0!|#VALUE!|#NAME\?|#N\/A/.test(errorScan.ndjson)) {
    if (process.argv.includes("--allow-formula-errors")) {
      console.error(errorScan.ndjson);
    } else {
    throw new Error(`公式错误扫描未通过: ${errorScan.ndjson.slice(0, 1200)}`);
    }
  }
  if (previewDir) {
    await fs.mkdir(previewDir, { recursive: true });
    for (const sheetName of sheets) {
      const blob = await workbook.render({ sheetName, autoCrop: "all", scale: 1.2, format: "png" });
      await fs.writeFile(path.join(previewDir, `${sheetName}.png`), new Uint8Array(await blob.arrayBuffer()));
    }
  }
  const out = await SpreadsheetFile.exportXlsx(workbook);
  await out.save(outputPath);
}

async function createInputWorkbook(seed = {}) {
  const workbook = Workbook.create();
  const sheet = workbook.worksheets.add("三年财务底表");
  sheet.showGridLines = false;
  title(sheet, "专精特新与小巨人前期评分｜三年财务底表", "F");
  sheet.mergeCells("A2:F2");
  sheet.getRange("A2:F2").values = [["黄色单元格由客户填写。金额统一使用万元，人数使用人；近三年、近两年、近一年按时间先后填写。保存时将文件名改为“企业完整名称_三年财务底表.xlsx”。评估版本可暂不填写，回传时告知使用省级专精特新版或小巨人版。"]];
  sheet.getRange("A2:F2").format = { fill: COLORS.pale, font: { color: COLORS.dark }, wrapText: true };
  sheet.getRange("A3:A8").values = [["企业完整名称"], ["统一社会信用代码"], ["主导产品或核心产品"], ["行业提示"], ["近一年对应财务年度"], ["拟评估版本，可暂不填"]];
  sheet.getRange("A3:A8").format = { fill: COLORS.sky, font: { bold: true, color: COLORS.dark } };
  sheet.getRange("B3:E8").format.fill = COLORS.input;
  sheet.getRange("A3:E8").format.borders = { preset: "all", style: "thin", color: COLORS.line };
  sheet.getRange("A3:E8").format.borders = {
    insideHorizontal: { style: "thin", color: COLORS.line },
    insideVertical: { style: "thin", color: COLORS.line },
    top: { style: "medium", color: COLORS.blue },
    bottom: { style: "medium", color: COLORS.blue },
    left: { style: "medium", color: COLORS.blue },
    right: { style: "medium", color: COLORS.blue }
  };
  sheet.getRange("B3:E8").format.wrapText = true;
  sheet.mergeCells("B3:E3"); sheet.mergeCells("B4:E4"); sheet.mergeCells("B5:E5"); sheet.mergeCells("B6:E6"); sheet.mergeCells("B8:E8");
  sheet.getRange("B3").values = [[seed.company_name ?? ""]];
  sheet.getRange("B4").values = [[seed.credit_code ?? ""]];
  sheet.getRange("B5").values = [[seed.main_product ?? ""]];
  sheet.getRange("B6").values = [[seed.industry_hint ?? ""]];
  sheet.getRange("B7").values = [[seed.latest_year ?? ""]];
  sheet.getRange("B7").dataValidation = { rule: { type: "whole", operator: "between", formula1: 2000, formula2: 2100 } };
  sheet.getRange("B8").values = [[seed.project_level ?? ""]];
  sheet.getRange("B8").dataValidation = { rule: { type: "list", values: ["省级专精特新中小企业", "专精特新“小巨人”"] } };

  sheet.getRange("A9:F9").values = [["填写口径", "", "", "", "", ""]];
  sheet.mergeCells("A9:F9"); section(sheet.getRange("A9:F9"));
  sheet.getRange("A10:F10").values = [["指标", "单位", "近三年", "近两年", "近一年", "口径说明"]];
  header(sheet.getRange("A10:F10"));
  const rows = [
    ["营业收入", "万元", "", "", "", "利润表营业收入"],
    ["营业成本", "万元", "", "", "", "利润表营业成本"],
    ["销售费用", "万元", "", "", "", "利润表销售费用"],
    ["管理费用", "万元", "", "", "", "利润表管理费用，含研发费用时仍按报表原值"],
    ["财务费用", "万元", "", "", "", "可选，不参与八项代理指标"],
    ["利润总额", "万元", "", "", "", "利润表利润总额"],
    ["净利润", "万元", "", "", "", "用于辅助校验"],
    ["资产总额", "万元", "", "", "", "年末资产总额"],
    ["负债总额", "万元", "", "", "", "年末负债总额"],
    ["净资产", "万元", "", "", "", "自动计算：资产总额减负债总额"],
    ["年平均从业人数", "人", "", "", "", "优先填年平均人数；无该数据时填年末人数并在备注说明"],
    ["研发费用", "万元", "", "", "", "可选，用于完整评分"],
    ["主营业务收入", "万元", "", "", "", "可选，用于门槛核验"],
    ["主导产品收入", "万元", "", "", "", "可选，用于专业化程度核验"]
  ];
  sheet.getRange("A11:F24").values = rows;
  body(sheet.getRange("A11:F24"));
  sheet.getRange("C11:E19").format.fill = COLORS.input;
  sheet.getRange("C21:E24").format.fill = COLORS.input;
  sheet.getRange("C20:E20").formulas = [["=C18-C19", "=D18-D19", "=E18-E19"]];
  sheet.getRange("C20:E20").format.fill = COLORS.green;
  const seedMetrics = seed.metrics ?? {};
  const rowKeys = ["revenue","operating_cost","selling_expense","admin_expense","financial_expense","total_profit","net_profit","total_assets","total_liabilities",null,"average_employees","rd_expense","main_business_revenue","main_product_revenue"];
  rowKeys.forEach((key, idx) => {
    if (!key || !Array.isArray(seedMetrics[key])) return;
    sheet.getRange(`C${11 + idx}:E${11 + idx}`).values = [seedMetrics[key]];
  });
  fmtNum(sheet.getRange("C11:E20"));
  fmtNum(sheet.getRange("C21:E24"));
  sheet.getRange("F11:F24").format.wrapText = true;
  setWidths(sheet, { A: 22, B: 10, C: 15, D: 15, E: 15, F: 42 });
  sheet.getRange("1:24").format.rowHeight = 22;
  sheet.getRange("2:2").format.rowHeight = 35;
  sheet.freezePanes.freezeRows(10);
  await exportAndVerify(workbook, ["三年财务底表"]);
}

function metricValues(matrix) {
  const rowMap = {
    revenue: 10, operating_cost: 11, selling_expense: 12, admin_expense: 13,
    financial_expense: 14, total_profit: 15, net_profit: 16, total_assets: 17,
    total_liabilities: 18, average_employees: 20, rd_expense: 21,
    main_business_revenue: 22, main_product_revenue: 23
  };
  const result = {};
  for (const [key, row] of Object.entries(rowMap)) result[key] = [2, 3, 4].map(col => Number(matrix[row]?.[col]));
  return result;
}

async function buildScore() {
  const inputPath = path.resolve(arg("--input"));
  const inputWb = await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));
  const inputSheet = inputWb.worksheets.getItem("三年财务底表");
  const matrix = inputSheet.getRange("A1:F30").values;
  const meta = {
    company_name: String(matrix[2]?.[1] ?? "").trim(),
    credit_code: String(matrix[3]?.[1] ?? "").trim(),
    main_product: String(matrix[4]?.[1] ?? "").trim(),
    industry_hint: String(matrix[5]?.[1] ?? "").trim(),
    latest_year: Number(matrix[6]?.[1]),
    project_level: String(projectLevelOverride ?? matrix[7]?.[1] ?? "").trim()
  };
  const inputBaseName = path.basename(inputPath).replace(/\.xlsx$/i, "");
  if (meta.company_name && !inputBaseName.includes(meta.company_name)) {
    throw new Error(`文件名校验失败：文件名必须包含企业完整名称“${meta.company_name}”。建议改名为“${meta.company_name}_三年财务底表.xlsx”。`);
  }
  const metrics = metricValues(matrix);
  validateInput(meta, metrics);
  const facts = factsPath ? JSON.parse(await fs.readFile(path.resolve(factsPath), "utf8")) : {};
  const map = JSON.parse(await fs.readFile(mapPath, "utf8"));
  const isLittleGiant = /小巨人/.test(meta.project_level);
  const benchmarkRegion = isLittleGiant ? "全国" : "浙江省";
  const benchmarkAgency = isLittleGiant ? "国家统计局" : "浙江省统计局";
  const selectedBenchmarkPath = isLittleGiant ? benchmarkPath : zhejiangBenchmarkPath;
  const registry = JSON.parse(await fs.readFile(selectedBenchmarkPath, "utf8"));
  const industry = resolveIndustry(map, meta, facts);

  const yearbookYears = Object.keys(registry.years).map(Number).filter(y => y <= meta.latest_year).sort((a, b) => a - b);
  if (yearbookYears.length < 2) throw new Error("统计局行业基准至少需要两个年度。");
  const latestBenchmarkYear = yearbookYears.at(-1);
  const priorBenchmarkYear = yearbookYears.at(-2);
  const latestYearbook = registry.years[String(latestBenchmarkYear)];
  const latestYearbookEdition = Number(
    latestYearbook.yearbook_year ??
    String(latestYearbook.source_url ?? "").match(/\/ndsj\/(\d{4})\//)?.[1] ??
    latestBenchmarkYear + 1
  );
  const latestYearbookTitle = latestYearbook.yearbook_title ?? `中国统计年鉴${latestYearbookEdition}`;
  const industryRows = yearbookYears.slice(-3).map(y => ({ year: y, ...registry.years[String(y)].rows.find(r => r.code === industry.code) }));
  if (industryRows.some(x => !x.name)) throw new Error(`统计局缓存缺少 ${industry.code} ${industry.name}`);
  const latestIndustry = industryRows.at(-1);
  const priorIndustry = industryRows.at(-2);
  const annualIndustry = registry.annual_growth?.year <= meta.latest_year
    ? registry.annual_growth.rows.find(r => r.code === industry.code)
    : null;
  const growthBenchmarkYear = annualIndustry ? registry.annual_growth.year : latestBenchmarkYear;
  const companyEquity = metrics.total_assets.map((x, i) => x - metrics.total_liabilities[i]);
  const industryEquity = industryRows.map(x => x.total_assets - x.total_liabilities);
  const companyProxy = [
    metrics.revenue[2] / metrics.average_employees[2],
    metrics.total_profit[2] / companyEquity[2],
    metrics.total_profit[2] / metrics.operating_cost[2],
    (metrics.selling_expense[2] + metrics.admin_expense[2]) / metrics.revenue[2],
    (metrics.revenue[2] - metrics.operating_cost[2]) / metrics.revenue[2],
    metrics.revenue[2] / metrics.revenue[1] - 1,
    metrics.total_profit[2] / metrics.total_profit[1] - 1,
    companyEquity[2] / companyEquity[1] - 1
  ];
  const industryProxy = [
    latestIndustry.revenue / latestIndustry.average_employees,
    latestIndustry.total_profit / industryEquity.at(-1),
    latestIndustry.total_profit / latestIndustry.operating_cost,
    (latestIndustry.selling_expense + latestIndustry.admin_expense) / latestIndustry.revenue,
    (latestIndustry.revenue - latestIndustry.operating_cost) / latestIndustry.revenue,
    annualIndustry?.revenue_growth ?? latestIndustry.revenue / priorIndustry.revenue - 1,
    annualIndustry?.total_profit_growth ?? latestIndustry.total_profit / priorIndustry.total_profit - 1,
    industryEquity.at(-1) / industryEquity.at(-2) - 1
  ];
  const tierFor = (company, benchmark, lowerIsBetter = false) => {
    if (lowerIsBetter) return company <= benchmark * 0.8 ? "领先档" : company <= benchmark ? "达标档" : "追赶档";
    if (benchmark <= 0) return company >= 0 ? "领先档" : company >= benchmark ? "达标档" : "追赶档";
    return company >= benchmark * 1.2 ? "领先档" : company >= benchmark ? "达标档" : "追赶档";
  };
  const nextTarget = (tier, current, benchmark, lowerIsBetter = false) => {
    if (tier === "领先档") return { level: "保持领先档", value: current };
    if (tier === "追赶档") return { level: "达到达标档", value: benchmark };
    if (lowerIsBetter) return { level: "达到领先档", value: benchmark * 0.8 };
    return { level: "达到领先档", value: benchmark <= 0 ? 0 : benchmark * 1.2 };
  };

  const workbook = Workbook.create();
  const summary = workbook.worksheets.add("评分总览");
  const finance = workbook.worksheets.add("三年财务底表");
  const mapping = workbook.worksheets.add("行业映射");
  const nbs = workbook.worksheets.add("统计局行业基准");
  const score = workbook.worksheets.add("八项对标评分");
  const fullScore = workbook.worksheets.add("全指标评分底稿");
  const target = workbook.worksheets.add("目标反推");
  const composition = workbook.worksheets.add("三档总分");
  const checks = workbook.worksheets.add("数据源与校验");
  for (const s of [summary, finance, mapping, nbs, score, fullScore, target, composition, checks]) s.showGridLines = false;

  title(finance, `${meta.company_name}｜三年财务底表`, "F");
  finance.getRange("A3:F3").values = [["指标", "单位", "近三年", "近两年", "近一年", "口径"]];
  header(finance.getRange("A3:F3"));
  const financeRows = [
    ["营业收入","万元",...metrics.revenue,"利润表"],
    ["营业成本","万元",...metrics.operating_cost,"利润表"],
    ["销售费用","万元",...metrics.selling_expense,"利润表"],
    ["管理费用","万元",...metrics.admin_expense,"利润表"],
    ["财务费用","万元",...metrics.financial_expense,"可选"],
    ["利润总额","万元",...metrics.total_profit,"利润表"],
    ["净利润","万元",...metrics.net_profit,"辅助校验"],
    ["资产总额","万元",...metrics.total_assets,"年末"],
    ["负债总额","万元",...metrics.total_liabilities,"年末"],
    ["净资产","万元","","","","资产总额减负债总额"],
    ["年平均从业人数","人",...metrics.average_employees,"无平均数时可用年末人数代理"],
    ["研发费用","万元",...metrics.rd_expense,"可选"],
    ["主营业务收入","万元",...metrics.main_business_revenue,"可选"],
    ["主导产品收入","万元",...metrics.main_product_revenue,"可选"]
  ];
  finance.getRange("A4:F17").values = financeRows;
  finance.getRange("C13:E13").formulas = [["=C11-C12","=D11-D12","=E11-E12"]];
  body(finance.getRange("A4:F17")); fmtNum(finance.getRange("C4:E17"));
  finance.getRange("C13:E13").format.fill = COLORS.green;
  finance.getRange("F4:F17").format.wrapText = true;
  setWidths(finance, { A: 22, B: 10, C: 15, D: 15, E: 15, F: 38 });
  finance.freezePanes.freezeRows(3);

  title(mapping, `${meta.company_name}｜行业映射`, "F");
  mapping.getRange("A3:B8").values = [
    ["项目","结果"],
    ["企业完整名称",meta.company_name],
    ["主导产品",meta.main_product || "由企查查和企业资料识别"],
    ["映射行业",`${industry.code} ${industry.name}`],
    ["映射置信度",industry.confidence],
    ["映射依据",industry.basis]
  ];
  header(mapping.getRange("A3:B3")); body(mapping.getRange("A4:B8"));
  mapping.getRange("A10:F10").values = [["证据优先级","证据","用途","当前值","状态","备注"]];
  header(mapping.getRange("A10:F10"));
  mapping.getRange("A11:F14").values = [
    ["1","主导产品及收入实质","决定统计行业","自动核验","采用","优先于登记标签"],
    ["2","企查查登记行业和经营范围","主体与业务复核",facts.qcc_industry ?? "本轮未返回","参考","不机械照抄"],
    ["3","企业官网、产品页、材料","产品边界复核",facts.main_products ?? meta.main_product ?? "待核验","参考","用于消除多行业歧义"],
    ["4","统计局行业表可用层级","确定基准",industry.name,"采用","规模以上工业企业大类口径"]
  ];
  body(mapping.getRange("A11:F14"));
  mapping.getRange("B4:B8").format.wrapText = true; mapping.getRange("B11:F14").format.wrapText = true;
  setWidths(mapping, { A: 18, B: 34, C: 24, D: 28, E: 12, F: 36 });

  title(nbs, `${industry.name}｜${benchmarkRegion}行业基准｜${latestBenchmarkYear}年数据期`, "K");
  nbs.mergeCells("A2:K2");
  nbs.getRange("A2:K2").values = [[`项目层级：${meta.project_level}。结构指标来源：《${latestYearbookTitle}》${latestYearbook.table_label ?? registry.table ?? ""}。年鉴版本为${latestYearbookEdition}年，表内最近数据期为${latestBenchmarkYear}年。`]];
  nbs.getRange("A2:K2").format = {
    fill: COLORS.pale,
    font: { color: COLORS.dark },
    wrapText: true,
    borders: { preset: "outside", style: "medium", color: COLORS.blue }
  };
  nbs.getRange("A3:K3").values = [["年份","资产总额","负债总额","营业收入","营业成本","销售费用","管理费用","利润总额","平均用工人数","数据层级","来源"]];
  header(nbs.getRange("A3:K3"));
  const nbsRows = industryRows.map(r => [
    r.year,r.total_assets,r.total_liabilities,r.revenue,r.operating_cost,r.selling_expense,r.admin_expense,r.total_profit,r.average_employees,
    `${benchmarkRegion}规模以上工业企业行业大类`,registry.years[String(r.year)].index_url ?? registry.years[String(r.year)].source_url
  ]);
  nbs.getRange(`A4:K${3 + nbsRows.length}`).values = nbsRows;
  body(nbs.getRange(`A4:K${3 + nbsRows.length}`)); fmtNum(nbs.getRange(`B4:I${3 + nbsRows.length}`));
  nbs.getRange(`J4:K${3 + nbsRows.length}`).format.wrapText = true;
  nbs.getRange(`A4:K${3 + nbsRows.length}`).format.rowHeight = 90;
  nbs.getRange("A9:H9").values = [["指标","公式口径","基准值","基准年度","增长快报值","快报年度","采用值","说明"]];
  header(nbs.getRange("A9:H9"));
  const latestRow = 3 + nbsRows.length;
  const priorRow = latestRow - 1;
  nbs.getRange("A10:H17").values = [
    ["人均营业收入","营业收入亿元÷平均用工万人", "",latestBenchmarkYear,"",growthBenchmarkYear,"","万元/人"],
    ["净资产收益率代理","利润总额÷期末净资产", "",latestBenchmarkYear,"",growthBenchmarkYear,"","非官方ROE，仅做代理"],
    ["成本利润率代理","利润总额÷营业成本", "",latestBenchmarkYear,"",growthBenchmarkYear,"","与行业表可比"],
    ["销售和管理费用率","销售费用加管理费用÷营业收入", "",latestBenchmarkYear,"",growthBenchmarkYear,"","低值更优"],
    ["毛利率代理","营业收入减营业成本÷营业收入", "",latestBenchmarkYear,"",growthBenchmarkYear,"","未扣税金及附加"],
    ["营业收入增长率","行业营业收入同比", "",latestBenchmarkYear,annualIndustry?.revenue_growth ?? "",growthBenchmarkYear,"",annualIndustry ? "采用同地域最新年度快报" : "采用同地域连续年鉴同比"],
    ["利润增长率","行业利润总额同比", "",latestBenchmarkYear,annualIndustry?.total_profit_growth ?? "",growthBenchmarkYear,"",annualIndustry ? "采用同地域最新年度快报" : "采用同地域连续年鉴同比"],
    ["净资产增速","期末净资产同比", "",latestBenchmarkYear,"",growthBenchmarkYear,"","年鉴表计算"]
  ];
  nbs.getRange("C10:C17").formulas = [[
    `=D${latestRow}/I${latestRow}`,
  ],[
    `=H${latestRow}/(B${latestRow}-C${latestRow})`
  ],[
    `=H${latestRow}/E${latestRow}`
  ],[
    `=(F${latestRow}+G${latestRow})/D${latestRow}`
  ],[
    `=(D${latestRow}-E${latestRow})/D${latestRow}`
  ],[
    `=D${latestRow}/D${priorRow}-1`
  ],[
    `=H${latestRow}/H${priorRow}-1`
  ],[
    `=(B${latestRow}-C${latestRow})/(B${priorRow}-C${priorRow})-1`
  ]];
  nbs.getRange("G10:G17").formulas = [
    ["=C10"],["=C11"],["=C12"],["=C13"],["=C14"],
    ["=IF(E15=\"\",C15,E15)"],["=IF(E16=\"\",C16,E16)"],["=C17"]
  ];
  body(nbs.getRange("A10:H17"));
  fmtNum(nbs.getRange("C10:C10")); fmtPct(nbs.getRange("C11:C17")); fmtNum(nbs.getRange("G10:G10")); fmtPct(nbs.getRange("G11:G17")); fmtPct(nbs.getRange("E10:E17"));
  nbs.getRange("B10:B17").format.wrapText = true; nbs.getRange("H10:H17").format.wrapText = true;
  setWidths(nbs, { A: 22, B: 31, C: 14, D: 12, E: 14, F: 12, G: 14, H: 28, I: 16, J: 26, K: 44 });

  title(score, `${meta.company_name}｜八项行业对标评分`, "I");
  score.mergeCells("A2:I2");
  score.getRange("A2:I2").values = [["评分规则：高值指标达到行业值120%为领先档；费用率不高于行业值80%为领先档；达标档按60%计分，追赶档按40%计分。"]];
  score.getRange("A2:I2").format = {
    fill: COLORS.pale,
    font: { color: COLORS.dark },
    wrapText: true,
    borders: { preset: "outside", style: "medium", color: COLORS.blue }
  };
  score.getRange("A3:I3").values = [["指标","满分","企业值","行业采用值","差距","档位","得分","弱点判断","提升方向"]];
  header(score.getRange("A3:I3"));
  const metricNames = ["人均营业收入","净资产收益率代理","成本利润率代理","销售和管理费用率","毛利率代理","营业收入增长率","利润增长率","净资产增速"];
  const maxPoints = [2,2,2,4,4,5,5,5];
  const tiers = companyProxy.map((x, i) => tierFor(x, industryProxy[i], i === 3));
  const points = tiers.map((tier, i) => maxPoints[i] * (tier === "领先档" ? 1 : tier === "达标档" ? 0.6 : 0.4));
  score.getRange("A4:B11").values = metricNames.map((name, i) => [name,maxPoints[i]]);
  score.getRange("C4:C11").formulas = [
    ["='三年财务底表'!E4/'三年财务底表'!E14"],
    ["='三年财务底表'!E9/'三年财务底表'!E13"],
    ["='三年财务底表'!E9/'三年财务底表'!E5"],
    ["=('三年财务底表'!E6+'三年财务底表'!E7)/'三年财务底表'!E4"],
    ["=('三年财务底表'!E4-'三年财务底表'!E5)/'三年财务底表'!E4"],
    ["='三年财务底表'!E4/'三年财务底表'!D4-1"],
    ["='三年财务底表'!E9/'三年财务底表'!D9-1"],
    ["='三年财务底表'!E13/'三年财务底表'!D13-1"]
  ];
  score.getRange("D4:D11").formulas = Array.from({length:8},(_,i)=>[`='统计局行业基准'!G${10+i}`]);
  score.getRange("E4:E11").formulas = Array.from({length:8},(_,i)=>[`=C${4+i}-D${4+i}`]);
  score.getRange("F4:H11").values = tiers.map((tier, i) => [
    tier,
    points[i],
    tier === "领先档" ? "优势" : tier === "达标档" ? "基本达标" : "优先提升"
  ]);
  score.getRange("I4:I11").values = [
    ["维持产出效率并补充员工口径说明"],["提升利润与资本使用效率"],["优化单位成本和产品结构"],
    ["控制销售管理费用增幅，拆分研发投入"],["提高高附加值产品占比"],["稳定订单和主导产品收入"],
    ["改善利润质量，核查一次性收益"],["控制负债并积累留存收益"]
  ];
  score.getRange("A12:F12").merge(); score.getRange("A12:F12").values = [["八项财务代理分合计"]];
  score.getRange("G12").formulas = [["=SUM(G4:G11)"]]; score.getRange("H12:I12").merge(); score.getRange("H12:I12").values = [["满分29分"]];
  section(score.getRange("A12:I12"));
  body(score.getRange("A4:I11"));
  fmtNum(score.getRange("C4:D4")); fmtPct(score.getRange("C5:E11")); fmtNum(score.getRange("G4:G12"),"0.0");
  score.getRange("H4:I11").format.wrapText = true;
  score.getRange("F4:F11").conditionalFormats.add("containsText",{text:"领先",format:{fill:COLORS.green,font:{color:"#375623"}}});
  score.getRange("F4:F11").conditionalFormats.add("containsText",{text:"追赶",format:{fill:COLORS.red,font:{color:"#9C0006"}}});
  setWidths(score, { A: 24, B: 9, C: 15, D: 15, E: 14, F: 12, G: 10, H: 14, I: 38 });

  const nonfinancialItems = Array.isArray(facts.nonfinancial_items) ? facts.nonfinancial_items : [];
  const nonfinancialById = new Map(nonfinancialItems.map(item => [item.id, item]));
  const ledgerDefs = [
    { id: "N01" }, { id: "N02" }, { id: "N03" }, { id: "N04" },
    { financeRow: 4, dimension: "精细化", indicator: "人均营业收入超出行业均值情况", maxPoints: 2 },
    { financeRow: 5, dimension: "精细化", indicator: "净资产收益率超出行业均值情况", maxPoints: 2 },
    { financeRow: 6, dimension: "精细化", indicator: "成本利润率超出行业均值情况", maxPoints: 2 },
    { financeRow: 7, dimension: "精细化", indicator: "销售和管理费用率超出行业均值情况", maxPoints: 4 },
    { id: "N05" },
    { financeRow: 8, dimension: "特色化", indicator: "毛利率超出行业均值情况", maxPoints: 4 },
    { id: "N06" }, { id: "N07" }, { id: "N08" },
    { id: "N09" }, { id: "N10" }, { id: "N11" }, { id: "N12" }, { id: "N13" }, { id: "N14" },
    { financeRow: 9, dimension: "成长性", indicator: "营业收入增长率超出行业均值情况", maxPoints: 5 },
    { financeRow: 10, dimension: "成长性", indicator: "利润增长率超出行业均值情况", maxPoints: 5 },
    { financeRow: 11, dimension: "成长性", indicator: "净资产增速超出行业均值情况", maxPoints: 5 }
  ];
  const missingNonfinancial = ledgerDefs.filter(x => x.id && !nonfinancialById.has(x.id)).map(x => x.id);
  if (missingNonfinancial.length) {
    throw new Error(`非财务逐项评分缺失：${missingNonfinancial.join("、")}。未形成逐项底稿时禁止输出总分。`);
  }
  const maxLedgerPoints = ledgerDefs.reduce((sum, def) => sum + Number(def.maxPoints ?? nonfinancialById.get(def.id)?.max_points ?? 0), 0);
  if (Math.abs(maxLedgerPoints - 100) > 0.001) {
    throw new Error(`全指标满分校验失败：当前合计${maxLedgerPoints}分，应为100分。`);
  }

  title(fullScore, `${meta.company_name}｜全指标评分底稿`, "L");
  fullScore.mergeCells("A2:L2");
  fullScore.getRange("A2:L2").values = [["本页是总分唯一来源。每项均列示满分、企业值、评分规则、三档得分、证据来源与缺口；三档总分只允许由本页逐项求和。该评分用于前期评估，不是官方评审分。"]];
  fullScore.getRange("A2:L2").format = {
    fill: COLORS.pale,
    font: { color: COLORS.dark },
    wrapText: true,
    borders: { preset: "outside", style: "medium", color: COLORS.blue }
  };
  fullScore.getRange("A3:L3").values = [["序号","维度","指标","满分","企业值","评分规则","保守档","基准档","条件档","证据来源","证据状态","缺口及提升动作"]];
  header(fullScore.getRange("A3:L3"));
  const ledgerRows = ledgerDefs.map((def, index) => {
    if (def.financeRow) {
      return [
        index + 1, def.dimension, def.indicator, def.maxPoints, "",
        "企业值与同地域行业基准比较：领先档100%，达标档60%，追赶档40%；费用率反向判断",
        "", "", "",
        `企业三年财务底表；${benchmarkAgency}${benchmarkRegion}行业基准`,
        "公式自动计算并完成行业三档判断",
        "详见八项对标评分与目标反推"
      ];
    }
    const item = nonfinancialById.get(def.id);
    return [
      index + 1, item.dimension, item.indicator, item.max_points, item.company_value,
      item.rule, item.conservative_points, item.baseline_points, item.conditional_points,
      item.evidence_source, item.evidence_status, item.gap_action
    ];
  });
  fullScore.getRange("A4:L25").values = ledgerRows;
  ledgerDefs.forEach((def, index) => {
    if (!def.financeRow) return;
    const row = 4 + index;
    fullScore.getRange(`E${row}`).formulas = [[`='八项对标评分'!C${def.financeRow}`]];
    fullScore.getRange(`G${row}:I${row}`).formulas = [[
      `='八项对标评分'!G${def.financeRow}`,
      `='八项对标评分'!G${def.financeRow}`,
      `='八项对标评分'!G${def.financeRow}`
    ]];
  });
  body(fullScore.getRange("A4:L25"));
  fullScore.getRange("A26:F26").merge();
  fullScore.getRange("A26:F26").values = [["全指标合计"]];
  fullScore.getRange("G26:I26").formulas = [["=SUM(G4:G25)","=SUM(H4:H25)","=SUM(I4:I25)"]];
  fullScore.getRange("J26:L26").merge();
  fullScore.getRange("J26:L26").values = [[`满分${maxLedgerPoints}分；无逐项明细不得形成总分`]];
  section(fullScore.getRange("A26:L26"));
  fmtNum(fullScore.getRange("D4:D25"),"0.0");
  fmtNum(fullScore.getRange("G4:I26"),"0.0");
  ledgerDefs.forEach((def, index) => {
    if (!def.financeRow) return;
    const row = 4 + index;
    if (def.financeRow === 4) fmtNum(fullScore.getRange(`E${row}`));
    else fmtPct(fullScore.getRange(`E${row}`));
  });
  fullScore.getRange("A29:E29").values = [["维度","满分","保守档","基准档","条件档"]];
  header(fullScore.getRange("A29:E29"));
  const dimensions = ["专业化","精细化","特色化","创新能力","成长性"];
  fullScore.getRange("A30:A34").values = dimensions.map(x => [x]);
  fullScore.getRange("B30:E34").formulas = dimensions.map((_, i) => {
    const row = 30 + i;
    return [
      `=SUMIF($B$4:$B$25,A${row},$D$4:$D$25)`,
      `=SUMIF($B$4:$B$25,A${row},$G$4:$G$25)`,
      `=SUMIF($B$4:$B$25,A${row},$H$4:$H$25)`,
      `=SUMIF($B$4:$B$25,A${row},$I$4:$I$25)`
    ];
  });
  fullScore.getRange("A35").values = [["合计"]];
  fullScore.getRange("B35:E35").formulas = [["=SUM(B30:B34)","=SUM(C30:C34)","=SUM(D30:D34)","=SUM(E30:E34)"]];
  body(fullScore.getRange("A30:E34"));
  section(fullScore.getRange("A35:E35"));
  fmtNum(fullScore.getRange("B30:E35"),"0.0");
  fullScore.getRange("E4:L25").format.wrapText = true;
  setWidths(fullScore, { A: 8, B: 12, C: 30, D: 9, E: 38, F: 48, G: 10, H: 10, I: 10, J: 42, K: 36, L: 46 });
  fullScore.getRange("4:25").format.rowHeight = 76;
  fullScore.freezePanes.freezeRows(3);

  title(target, `${meta.company_name}｜三项弱点目标反推`, "H");
  target.mergeCells("A2:H2");
  target.getRange("A2:H2").values = [["金额按最新年度、营业收入保持不变的静态情景测算。实际执行可通过价格、产品结构、费用压降和成本改善组合实现。"]];
  target.getRange("A2:H2").format = { fill: COLORS.pale, font: { color: COLORS.dark }, wrapText: true };
  target.getRange("A4:H4").values = [["指标","当前档位","下一目标","当前值","目标值","需改善金额","金额含义","测算说明"]];
  header(target.getRange("A4:H4"));
  const reverseIndexes = [3,4,6];
  const reverseNames = ["销售和管理费用率","毛利率代理","利润增长率"];
  const reverseTargets = reverseIndexes.map((idx, i) => nextTarget(tiers[idx], companyProxy[idx], industryProxy[idx], i === 0));
  target.getRange("A5:E7").values = reverseIndexes.map((idx, i) => [
    reverseNames[i], tiers[idx], reverseTargets[i].level, companyProxy[idx], reverseTargets[i].value
  ]);
  target.getRange("F5").formulas = [["=MAX(0,('三年财务底表'!E6+'三年财务底表'!E7)-'三年财务底表'!E4*E5)"]];
  target.getRange("F6").formulas = [["=MAX(0,'三年财务底表'!E5-'三年财务底表'!E4*(1-E6))"]];
  target.getRange("F7").formulas = [["=MAX(0,'三年财务底表'!D9*(1+E7)-'三年财务底表'!E9)"]];
  target.getRange("G5:G7").values = [["需压降的销售费用与管理费用合计"],["需增加的毛利，等价于收入不变时需压降的营业成本"],["需新增的利润总额"]];
  target.getRange("H5:H7").values = [
    ["目标费用额＝最新营业收入×目标费用率；改善额＝当前销售管理费用－目标费用额"],
    ["目标成本＝最新营业收入×一减目标毛利率；改善额＝当前营业成本－目标成本"],
    ["目标利润＝上年利润总额×一加目标增长率；改善额＝目标利润－本年利润总额"]
  ];
  body(target.getRange("A5:H7"));
  fmtPct(target.getRange("D5:E7")); fmtNum(target.getRange("F5:F7"),"#,##0.00");
  target.getRange("B5:C7").format.horizontalAlignment = "center";
  target.getRange("G5:H7").format.wrapText = true;
  target.getRange("A10:H10").merge(); target.getRange("A10:H10").values = [["执行拆解"]];
  section(target.getRange("A10:H10"));
  target.getRange("A11:H11").values = [["指标","首选抓手","辅助抓手","数据责任人","复盘频率","证据","风险提示","输出"]];
  header(target.getRange("A11:H11"));
  target.getRange("A12:H14").values = [
    ["销售和管理费用率","拆分销售费用、管理费用和研发投入","设置费用预算与收入联动线","财务负责人","月度","费用明细账、预算执行表","不得以削减必要研发投入换取短期达标","费用压降计划"],
    ["毛利率","优化产品结构与定价","降低材料损耗、能耗和制造费用","生产与销售负责人","月度","产品毛利表、成本分析表","收入不变是假设，实际需同步评估销量变化","毛利改善计划"],
    ["利润增长率","扩大高毛利产品贡献","控制非经常性损益和期间费用","财务与经营负责人","季度","利润表、订单和产品贡献表","一次性收益不代表持续经营改善","利润增长计划"]
  ];
  body(target.getRange("A12:H14")); target.getRange("B12:H14").format.wrapText = true;
  setWidths(target, { A: 22, B: 12, C: 15, D: 14, E: 14, F: 16, G: 34, H: 48 });

  title(composition, `${meta.company_name}｜保守、基准、条件三档总分`, "F");
  composition.getRange("A3:F3").values = [["评分层","全指标总分","其中财务八项","其中非财务十四项","状态","说明"]];
  header(composition.getRange("A3:F3"));
  composition.getRange("A4:A6").values = [["保守档"],["基准档"],["条件档"]];
  composition.getRange("B4:B6").formulas = [["='全指标评分底稿'!G26"],["='全指标评分底稿'!H26"],["='全指标评分底稿'!I26"]];
  composition.getRange("C4:C6").formulas = [["='八项对标评分'!G12"],["='八项对标评分'!G12"],["='八项对标评分'!G12"]];
  composition.getRange("D4:D6").formulas = [["=B4-C4"],["=B5-C5"],["=B6-C6"]];
  composition.getRange("E4:E6").values = [
    ["公开证据保守计分"],
    ["材料数据与透明代理"],
    ["明确条件达成后"]
  ];
  composition.getRange("F4:F6").values = [
    ["只计公开已核验、客户财务及可直接复算项目；市场排名和未取得行业均值的数字化指标不计"],
    ["加入申报资料锁定数据及已披露的透明代理规则；所有项目可在全指标评分底稿逐项复算"],
    ["仅加入已写明实现条件的目标分；条件未完成前不得作为当前分使用"]
  ];
  body(composition.getRange("A4:F6")); fmtNum(composition.getRange("B4:D6"),"0.0");
  composition.getRange("F4:F6").format.wrapText = true;
  composition.getRange("A9:F9").merge(); composition.getRange("A9:F9").values = [["自动提升优先级"]];
  section(composition.getRange("A9:F9"));
  composition.getRange("A10:F13").values = [
    ["优先级","弱项","当前判断","目标档位","建议动作","预计影响"],
    ["P1","追赶档指标","自动读取八项评分","至少达标档","先处理费用率、盈利质量和增长稳定性","八项分直接提升"],
    ["P2","非财务逐项指标","全指标底稿逐项读取","补齐证据缺口","核对标准角色、市场排名口径、数字化行业均值和专利网络中心性","保守档和基准档可复算"],
    ["P3","条件项","明确条件后计分","可实现条件档","推进市级或省级绿色工厂、数字化领先档及专利网络评价","条件档转化为可执行计划"]
  ];
  header(composition.getRange("A10:F10")); body(composition.getRange("A11:F13"));
  composition.getRange("B11:F13").format.wrapText = true;
  setWidths(composition, { A: 14, B: 22, C: 24, D: 18, E: 42, F: 22 });

  title(checks, `${meta.company_name}｜数据源与校验`, "G");
  checks.getRange("A3:G3").values = [["检查项","实际值","预期","差异","状态","修复位置","备注"]];
  header(checks.getRange("A3:G3"));
  const checkRows = [
    ["企业名称",meta.company_name,"非空","",meta.company_name ? "OK":"FAIL","输入表B3","用于企查查主体锚定"],
    ["文件名",inputBaseName,`包含${meta.company_name}`,"",inputBaseName.includes(meta.company_name) ? "OK":"FAIL","客户底表文件名","统一命名为企业完整名称_三年财务底表.xlsx"],
    ["三年财务完整性","8项必填字段","全部三年","", "OK","输入表C:E","已通过脚本校验"],
    ["资产负债勾稽","三年资产≥负债","三年成立","", "OK","输入表资产负债","净资产由公式计算"],
    ["行业映射",`${industry.code} ${industry.name}`,"唯一行业","",industry.confidence === "中" ? "REVIEW":"OK","行业映射","低置信度需复核主导产品"],
    ["评估项目层级",meta.project_level,isLittleGiant ? "小巨人" : "省级专精特新","", "OK","输入表B8","项目层级决定行业基准地域"],
    ["行业基准地域",benchmarkRegion,isLittleGiant ? "全国" : "浙江省","", "OK","统计局行业基准",`${meta.project_level}自动路由至${benchmarkAgency}`],
    ["统计局结构基准",`${latestBenchmarkYear}年数据期｜${latestYearbookEdition}年鉴`,`采用同地域官方已发布最近期`,"", "OK","统计局行业基准",`《${latestYearbookTitle}》${latestYearbook.table_label ?? registry.table ?? ""}`],
    ["统计局增长基准",growthBenchmarkYear,`≤${meta.latest_year}`,"", "OK","统计局行业基准",annualIndustry ? "采用同地域最新年度快报":"采用同地域连续年鉴同比"],
    ["评分口径","领先100%、达标60%、追赶40%","三档","", "OK","八项对标评分","费用率反向判断"],
    ["全指标评分底稿",`${ledgerDefs.length}项｜满分${maxLedgerPoints}分`,"22项｜满分100分","",ledgerDefs.length === 22 && maxLedgerPoints === 100 ? "OK":"FAIL","全指标评分底稿","无逐项评分、企业值、规则和证据来源时禁止形成总分"],
    ["模型状态","自动校验完成","无FAIL","", "PASS","本页","PASS不代表项目必然获批"]
  ];
  checks.getRange("A4:G15").values = checkRows; body(checks.getRange("A4:G15"));
  checks.getRange("E4:E15").conditionalFormats.add("containsText",{text:"OK",format:{fill:COLORS.green,font:{color:"#375623"}}});
  checks.getRange("E4:E15").conditionalFormats.add("containsText",{text:"FAIL",format:{fill:COLORS.red,font:{color:"#9C0006"}}});
  checks.getRange("A16:G16").values = [["来源项","期间","来源名称","URL或接口","访问日期","层级","用途"]];
  header(checks.getRange("A16:G16"));
  const sourceRows = industryRows.map(r => [
    "行业结构指标",
    `${r.year}年数据期`,
    `《${registry.years[String(r.year)].yearbook_title ?? `${benchmarkRegion}统计年鉴${r.year + 1}`}》${registry.years[String(r.year)].table_label ?? registry.table ?? ""}`,
    registry.years[String(r.year)].index_url ?? registry.years[String(r.year)].source_url,
    registry.years[String(r.year)].accessed_at,
    benchmarkAgency,
    "行业资产、负债、收入、成本、费用、利润和用工"
  ]);
  if (registry.annual_growth) sourceRows.push([
    "行业增长指标",registry.annual_growth.year,registry.annual_growth.source_name ?? `${benchmarkRegion}规模以上工业企业利润年度快报`,registry.annual_growth.source_url,registry.annual_growth.accessed_at,benchmarkAgency,"行业营业收入和利润总额同比"
  ]);
  sourceRows.push(
    ["企业主体","截至公开查询日","企业登记基本信息","企查查 get_company_registration_info",facts.qcc_checked_at ?? new Date().toISOString().slice(0,10),"企查查｜国家企业信用信息公示系统",facts.qcc_registration ?? "主体锚定与成立年限"],
    ["有效专利","截至公开查询日","有效专利与法律状态","企查查 get_patent_info",facts.qcc_checked_at ?? new Date().toISOString().slice(0,10),"企查查｜国家知识产权局",facts.qcc_patent_summary ?? "专利数量、类型和相关性"],
    ["标准信息","截至公开查询日","企业标准参与信息","企查查 get_standard_info",facts.qcc_checked_at ?? new Date().toISOString().slice(0,10),"企查查｜标准公开信息",facts.qcc_standard_summary ?? "标准数量和参与角色"],
    ["资质证书","截至公开查询日","当前有效资质与认证","企查查 get_qualifications",facts.qcc_checked_at ?? new Date().toISOString().slice(0,10),"企查查｜主管部门公开信息",facts.qcc_qualification_summary ?? "质量体系、产品认证和许可"],
    ["荣誉信息","截至公开查询日","企业荣誉与研发机构","企查查 get_honor_info",facts.qcc_checked_at ?? new Date().toISOString().slice(0,10),"企查查｜政府部门公开信息",facts.qcc_honor_summary ?? "研发机构、数字化和绿色制造称号"],
    ["国际专利","截至公开查询日","PCT或国际专利记录","企查查 get_international_patent",facts.qcc_checked_at ?? new Date().toISOString().slice(0,10),"企查查｜国际专利公开信息","当前检索层未命中；按0分处理，不作不存在的绝对判断"]
  );
  checks.getRange(`A17:G${16 + sourceRows.length}`).values = sourceRows;
  body(checks.getRange(`A17:G${16 + sourceRows.length}`));
  checks.getRange(`C17:D${16 + sourceRows.length}`).format.wrapText = true;
  checks.getRange(`G17:G${16 + sourceRows.length}`).format.wrapText = true;
  checks.getRange(`A17:G${16 + sourceRows.length}`).format.rowHeight = 84;
  setWidths(checks, { A: 22, B: 34, C: 38, D: 32, E: 14, F: 22, G: 46 });

  title(summary, `${meta.company_name}｜${meta.project_level}前期自动评分`, "H");
  summary.mergeCells("A2:H2");
  summary.getRange("A2:H2").values = [[`项目层级：${meta.project_level}｜行业基准：${benchmarkRegion}｜行业映射：${industry.code} ${industry.name}｜结构数据期：${latestBenchmarkYear}年｜来源版本：《${latestYearbookTitle}》｜增长数据期：${growthBenchmarkYear}年｜生成日期：${new Date().toISOString().slice(0,10)}`]];
  summary.getRange("A2:H2").format = {
    fill: COLORS.pale,
    font: { color: COLORS.dark },
    wrapText: true,
    borders: { preset: "outside", style: "medium", color: COLORS.blue }
  };
  summary.getRange("A4:B9").values = [
    ["关键结果","数值"],
    ["八项财务代理分",""],
    ["基准档非财务十四项",""],
    ["保守档总分",""],
    ["基准档总分",""],
    ["条件档总分",""]
  ];
  header(summary.getRange("A4:B4"));
  summary.getRange("B5:B9").formulas = [["='八项对标评分'!G12"],["='三档总分'!D5"],["='三档总分'!B4"],["='三档总分'!B5"],["='三档总分'!B6"]];
  body(summary.getRange("A5:B9")); fmtNum(summary.getRange("B5:B9"),"0.0");
  summary.getRange("D4:H4").values = [["结论","口径","适用","限制","下一步"]];
  header(summary.getRange("D4:H4"));
  summary.getRange("D5:H9").values = [
    ["八项财务对标","统计局行业代理","前期判断强弱项","不是评审官方分","对追赶档逐项设目标"],
    ["非财务十四项","企查查与申报资料逐项计分","解释总分构成","透明代理仍需结合当期通知复核","查看全指标评分底稿"],
    ["保守档","公开事实","当前底线","不含未核验事项","补齐企查查与资质核验"],
    ["基准档","合理代理","客户沟通","保留行业口径误差","建立对标提升清单"],
    ["条件档","明确条件","行动计划","条件未完成不计入保守档","转化为证据和时间表"]
  ];
  body(summary.getRange("D5:H9")); summary.getRange("D5:H9").format.wrapText = true;
  summary.getRange("A10:B10").values = [["目标反推","结果"]];
  header(summary.getRange("A10:B10"));
  summary.getRange("A11:B13").values = [["费用率需改善金额",""],["毛利率需改善金额",""],["利润增长需改善金额",""]];
  summary.getRange("B11:B13").formulas = [["='目标反推'!F5"],["='目标反推'!F6"],["='目标反推'!F7"]];
  body(summary.getRange("A11:B13")); fmtNum(summary.getRange("B11:B13"),"#,##0.00");
  summary.getRange("A15:H15").merge(); summary.getRange("A15:H15").values = [["八项指标雷达式明细"]];
  section(summary.getRange("A15:H15"));
  summary.getRange("A16:H16").values = [["指标","企业值","行业值","差距","档位","得分","满分","提升提示"]];
  header(summary.getRange("A16:H16"));
  for (let i = 0; i < 8; i++) {
    const r = 17 + i;
    const sr = 4 + i;
    summary.getRange(`A${r}:H${r}`).formulas = [[
      `='八项对标评分'!A${sr}`,`='八项对标评分'!C${sr}`,`='八项对标评分'!D${sr}`,`='八项对标评分'!E${sr}`,
      `='八项对标评分'!F${sr}`,`='八项对标评分'!G${sr}`,`='八项对标评分'!B${sr}`,`='八项对标评分'!I${sr}`
    ]];
  }
  body(summary.getRange("A17:H24")); fmtPct(summary.getRange("B18:D24")); fmtNum(summary.getRange("B17:D17")); fmtNum(summary.getRange("F17:G24"),"0.0");
  summary.getRange("H17:H24").format.wrapText = true;
  setWidths(summary, { A: 24, B: 15, C: 15, D: 14, E: 12, F: 10, G: 10, H: 38 });
  summary.freezePanes.freezeRows(2);

  await exportAndVerify(workbook, ["评分总览","三年财务底表","行业映射","统计局行业基准","八项对标评分","全指标评分底稿","目标反推","三档总分","数据源与校验"]);
  const inspect = await workbook.inspect({ kind: "table", range: "评分总览!A1:H24", include: "values,formulas", tableMaxRows: 24, tableMaxCols: 8 });
  console.log(inspect.ndjson);
}

if (mode === "template") {
  const seed = seedPath ? JSON.parse(await fs.readFile(path.resolve(seedPath), "utf8")) : {};
  await createInputWorkbook(seed);
} else if (mode === "score") {
  await buildScore();
} else {
  throw new Error(`未知模式: ${mode}`);
}
