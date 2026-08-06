import fs from "node:fs/promises";
import path from "node:path";


const modulePath = process.env.ARTIFACT_TOOL_MODULE;
if (!modulePath) throw new Error("ARTIFACT_TOOL_MODULE is required");
const { FileBlob, SpreadsheetFile, Workbook } = await import(modulePath);

const outputDir = path.resolve(process.argv[2]);
await fs.mkdir(outputDir, { recursive: true });

const workbook = Workbook.create();
const result = workbook.worksheets.add("分析结果");
const working = workbook.worksheets.add("计算底稿");
const sources = workbook.worksheets.add("数据来源");

for (const sheet of [result, working, sources]) sheet.showGridLines = false;

result.getRange("A1:D1").merge();
result.getRange("A1").values = [["Grounded 市场占有率分析"]];
result.getRange("A1:D1").format = {
  fill: "#0B2545",
  font: { bold: true, color: "#FFFFFF", size: 18 },
  verticalAlignment: "center",
};
result.getRange("A3:D5").values = [
  ["结论", "结果", "证据编号", "使用边界"],
  ["复算市场占有率", 0.1, "[1][2][3]", "可按当前申报测算口径使用"],
  ["排名", "未核验", "—", "不得由占有率数值自动推出"],
];
result.getRange("A3:D3").format = { fill: "#E8EEF5", font: { bold: true, color: "#0B2545" } };
result.getRange("A3:D5").format.borders = { preset: "outside", style: "thin", color: "#B8BCC4" };
result.getRange("B4").format.numberFormat = "0.0%";
result.getRange("A1:D5").format.wrapText = true;
result.getRange("A:A").format.columnWidth = 24;
result.getRange("B:B").format.columnWidth = 16;
result.getRange("C:C").format.columnWidth = 18;
result.getRange("D:D").format.columnWidth = 36;
result.freezePanes.freezeRows(3);

working.getRange("A1:C1").values = [["计算项", "数值", "来源"]];
working.getRange("A2:C5").values = [
  ["企业销售额 万元", 1200, "[1]"],
  ["上位市场规模 万元", 20000, "[2]"],
  ["应用场景系数", 0.6, "[3]"],
  ["复算市场占有率", null, "[1][2][3]"],
];
working.getRange("B5").formulas = [["=B2/(B3*B4)"]];
working.getRange("B4:B5").format.numberFormat = "0.0%";
working.getRange("A1:C1").format = { fill: "#E8EEF5", font: { bold: true, color: "#0B2545" } };
working.getRange("A1:C5").format.borders = { preset: "outside", style: "thin", color: "#B8BCC4" };
working.getRange("A:C").format.autofitColumns();

sources.getRange("A1:E1").merge();
sources.getRange("A1").values = [["数据来源"]];
sources.getRange("A1:E1").format = { fill: "#0B2545", font: { bold: true, color: "#FFFFFF", size: 18 } };
sources.getRange("A3:E6").values = [
  ["编号", "来源类型", "机构或文件", "链接", "检索日期"],
  ["[1]", "用户文件", "分产品销售台账.xlsx", "", "2026-08-05"],
  ["[2]", "研究报告", "示例行业研究机构《全国上位市场规模报告》", "https://example.org/report/market-2025", "2026-08-05"],
  ["[3]", "企业陈述", "主导产品应用场景拆分说明", "", "2026-08-05"],
];
sources.getRange("A3:E3").format = { fill: "#E8EEF5", font: { bold: true, color: "#0B2545" } };
sources.getRange("A3:E6").format.borders = { preset: "outside", style: "thin", color: "#B8BCC4" };
sources.getRange("A:E").format.autofitColumns();
sources.getRange("C:E").format.wrapText = true;
sources.freezePanes.freezeRows(3);

for (const sheetName of ["分析结果", "计算底稿", "数据来源"]) {
  const preview = await workbook.render({ sheetName, autoCrop: "all", scale: 1, format: "png" });
  await fs.writeFile(path.join(outputDir, `${sheetName}.png`), new Uint8Array(await preview.arrayBuffer()));
}

const xlsxPath = path.join(outputDir, "grounded-market-share.xlsx");
const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(xlsxPath);

const imported = await SpreadsheetFile.importXlsx(await FileBlob.load(xlsxPath));
const inspection = await imported.inspect({ kind: "sheet,formula", maxChars: 8000, tableMaxRows: 8, tableMaxCols: 8 });
await fs.writeFile(path.join(outputDir, "grounded-market-share.roundtrip.ndjson"), inspection.ndjson, "utf8");
const importedSheets = imported.worksheets.items.map((sheet) => sheet.name);
if (importedSheets.join("|") !== "分析结果|计算底稿|数据来源") throw new Error(`unexpected sheet order: ${importedSheets.join("|")}`);
if (imported.worksheets.getItem("数据来源").getRange("C4").values[0][0] !== "分产品销售台账.xlsx") throw new Error("knowledge source filename changed during roundtrip");

console.log(JSON.stringify({ status: "pass", xlsx: xlsxPath, sheets: importedSheets }));
