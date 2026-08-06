import fs from "node:fs/promises";
import path from "node:path";


const modulePath = process.env.ARTIFACT_TOOL_MODULE;
if (!modulePath) throw new Error("ARTIFACT_TOOL_MODULE is required");
const { FileBlob, Presentation, PresentationFile } = await import(modulePath);

const outputDir = path.resolve(process.argv[2]);
await fs.mkdir(outputDir, { recursive: true });

const deck = Presentation.create({ slideSize: { width: 1280, height: 720 } });
const colors = { ink: "#000000", panel: "#EDEDED", rule: "#B8BCC4", accent: "#3D8DFF", canvas: "#FFFFFF" };

function addText(slide, name, text, position, style) {
  const shape = slide.shapes.add({ geometry: "textbox", name, position, fill: "none", line: { style: "solid", fill: "none", width: 0 } });
  shape.text = text;
  shape.text.style = style;
  return shape;
}

function addPageNumber(slide, number) {
  addText(slide, `page-${number}`, String(number), { left: 1200, top: 660, width: 36, height: 24 }, { fontSize: 16, color: colors.ink, alignment: "right" });
}

const cover = deck.slides.add();
cover.background.fill = colors.canvas;
addText(cover, "eyebrow", "GROUNDED CITATIONS", { left: 48, top: 44, width: 420, height: 30 }, { fontSize: 16, bold: true, color: colors.accent });
addText(cover, "title", "每项结论都能回到来源", { left: 48, top: 196, width: 820, height: 140 }, { fontSize: 58, bold: true, color: colors.ink });
addText(cover, "subtitle", "PPT 正文保留轻量编号，完整来源集中在最后一页", { left: 48, top: 376, width: 740, height: 72 }, { fontSize: 24, color: "#4B5563" });
cover.shapes.add({ geometry: "rect", name: "accent-field", position: { left: 930, top: 0, width: 350, height: 720 }, fill: "#D0EDFA", line: { style: "solid", fill: "none", width: 0 } });
addPageNumber(cover, 1);

const evidence = deck.slides.add();
evidence.background.fill = colors.canvas;
addText(evidence, "title", "现有资料允许进入市场说明编制", { left: 48, top: 42, width: 1080, height: 70 }, { fontSize: 40, bold: true, color: colors.ink });
addText(evidence, "lead", "结论不等于市场占有率已经核验", { left: 48, top: 168, width: 610, height: 58 }, { fontSize: 28, bold: true, color: colors.ink });
addText(evidence, "body", "申报通知要求提交主导产品市场说明，企业已形成分产品销售底稿。[1][2]", { left: 48, top: 258, width: 690, height: 148 }, { fontSize: 22, color: colors.ink });
const panel = evidence.shapes.add({ geometry: "rect", name: "validation-panel", position: { left: 822, top: 168, width: 390, height: 382 }, fill: colors.panel, line: { style: "solid", fill: colors.rule, width: 1 } });
addText(evidence, "panel-heading", "自动校验", { left: 858, top: 210, width: 310, height: 42 }, { fontSize: 28, bold: true, color: colors.ink });
addText(evidence, "panel-body", "✓ 主张到来源映射\n✓ 知识库仅显示文件名\n✓ 完整来源位于末页", { left: 858, top: 286, width: 310, height: 170 }, { fontSize: 20, color: colors.ink });
addPageNumber(evidence, 2);

const sourceSlide = deck.slides.add();
sourceSlide.background.fill = colors.canvas;
addText(sourceSlide, "title", "数据来源", { left: 48, top: 42, width: 900, height: 70 }, { fontSize: 40, bold: true, color: colors.ink });
addText(sourceSlide, "source-1-number", "01", { left: 48, top: 176, width: 82, height: 44 }, { fontSize: 28, bold: true, color: colors.accent });
addText(sourceSlide, "source-1", "示例主管部门《现行项目申报通知》\nhttps://example.gov.cn/policy/current\n检索日期 2026-08-05", { left: 150, top: 168, width: 980, height: 110 }, { fontSize: 19, color: colors.ink });
sourceSlide.shapes.add({ geometry: "line", name: "rule-1", position: { left: 48, top: 306, width: 1136, height: 1 }, fill: "none", line: { style: "solid", fill: colors.rule, width: 1 } });
addText(sourceSlide, "source-2-number", "02", { left: 48, top: 354, width: 82, height: 44 }, { fontSize: 28, bold: true, color: colors.accent });
addText(sourceSlide, "source-2", "企业产品销售底稿.xlsx\n知识库来源仅显示文件名", { left: 150, top: 346, width: 980, height: 88 }, { fontSize: 19, color: colors.ink });
addPageNumber(sourceSlide, 3);

for (const [index, slide] of deck.slides.items.entries()) {
  const stem = `slide-${String(index + 1).padStart(2, "0")}`;
  const png = await deck.export({ slide, format: "png", scale: 1 });
  await fs.writeFile(path.join(outputDir, `${stem}.png`), new Uint8Array(await png.arrayBuffer()));
  const layout = await slide.export({ format: "layout" });
  await fs.writeFile(path.join(outputDir, `${stem}.layout.json`), await layout.text(), "utf8");
}
const montage = await deck.export({ format: "webp", montage: true, scale: 1 });
await fs.writeFile(path.join(outputDir, "grounded-citations-montage.webp"), new Uint8Array(await montage.arrayBuffer()));

const pptxPath = path.join(outputDir, "grounded-citations.pptx");
const pptx = await PresentationFile.exportPptx(deck);
await pptx.save(pptxPath);

const imported = await PresentationFile.importPptx(await FileBlob.load(pptxPath));
const snapshot = await imported.inspect({ kind: "slide,textbox,shape,layout", maxChars: 12000 });
await fs.writeFile(path.join(outputDir, "grounded-citations.roundtrip.ndjson"), snapshot.ndjson, "utf8");
if (imported.slides.items.length !== 3) throw new Error("roundtrip slide count mismatch");
if (!snapshot.ndjson.includes("数据来源")) throw new Error("roundtrip source slide missing");
if (!snapshot.ndjson.includes("企业产品销售底稿.xlsx")) throw new Error("roundtrip knowledge filename missing");
if (snapshot.ndjson.includes("client-dossier")) throw new Error("internal knowledge path leaked");

console.log(JSON.stringify({ status: "pass", pptx: pptxPath, slides: imported.slides.items.length }));
