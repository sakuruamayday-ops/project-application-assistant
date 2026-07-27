const fs = require("node:fs");

const SUPPORT_LABELS = {
  full: "完整同步",
  adapter: "适配导入",
  guided: "引导导入",
  unsupported: "暂不支持",
};

function buildCompatibilityReport(catalog, platforms) {
  const platformRows = platforms.map((platform) => {
    const runtimeReview = catalog.skills.filter((skill) => (
      (skill.runtimeRequirements?.executables || []).length
      || (skill.runtimeRequirements?.python_modules || []).length
    )).length;
    let compatible = catalog.count;
    let review = 0;
    if (platform.support === "adapter") review = catalog.count;
    if (platform.support === "guided") review = catalog.count;
    if (platform.support === "full" && platform.id !== "workbuddy") review = runtimeReview;
    if (platform.support === "unsupported") {
      compatible = 0;
      review = catalog.count;
    }
    return {
      platformId: platform.id,
      platformName: platform.name,
      support: platform.support,
      label: SUPPORT_LABELS[platform.support] || SUPPORT_LABELS.unsupported,
      compatible,
      review,
      total: catalog.count,
      note: platform.notes,
    };
  });
  return {
    schema: "jiaotang-skills-compatibility-report/v1",
    skillCount: catalog.count,
    generatedAt: new Date().toISOString(),
    platforms: platformRows,
  };
}

function readCatalog(catalogPath) {
  const parsed = JSON.parse(fs.readFileSync(catalogPath, "utf8"));
  if (parsed.schema !== "jiaotang-skill-catalog/v1") throw new Error("无法识别技能目录");
  return parsed;
}

module.exports = {
  buildCompatibilityReport,
  readCatalog,
};
