export function validateInput(meta, metrics) {
  const errors = [];
  if (!meta.company_name) errors.push("企业完整名称为空");
  if (!Number.isInteger(meta.latest_year)) errors.push("最新财务年度无效");
  if (!["省级专精特新中小企业", "专精特新“小巨人”"].includes(meta.project_level)) {
    errors.push("评估版本未确认，请明确选择省级专精特新中小企业或专精特新“小巨人”");
  }
  for (const key of [
    "revenue",
    "operating_cost",
    "selling_expense",
    "admin_expense",
    "total_profit",
    "total_assets",
    "total_liabilities",
    "average_employees",
  ]) {
    if (!metrics[key].every(Number.isFinite)) {
      errors.push(`${key} 未完整填写三年`);
    }
  }
  const periodLabels = ["近三年", "近两年", "近一年"];
  for (let index = 0; index < 3; index += 1) {
    if (metrics.total_assets[index] < metrics.total_liabilities[index]) {
      errors.push(`${periodLabels[index]}负债总额大于资产总额`);
    }
    if (metrics.revenue[index] <= 0 || metrics.average_employees[index] <= 0) {
      errors.push(`${periodLabels[index]}营业收入或从业人数非正数`);
    }
  }
  if (errors.length) {
    throw new Error(`财务底表校验失败：${errors.join("；")}`);
  }
}

export function resolveIndustry(map, meta, facts) {
  if (facts.industry_code) {
    const hit = map.industries.find((item) => item.code === facts.industry_code);
    if (!hit) throw new Error(`facts.industry_code 无法映射：${facts.industry_code}`);
    return {
      ...hit,
      confidence: facts.mapping_confidence ?? "高",
      basis: facts.industry_basis ?? "企业信息与主导产品核验",
    };
  }
  const exact = map.industries.find(
    (item) => item.code === meta.industry_hint || item.name === meta.industry_hint,
  );
  if (exact) return { ...exact, confidence: "高", basis: "底表行业提示精确命中" };
  const text = [
    meta.main_product,
    meta.industry_hint,
    facts.qcc_industry,
    facts.business_scope,
    facts.main_products,
  ]
    .filter(Boolean)
    .join(" ");
  const scored = map.industries
    .map((industry) => ({
      ...industry,
      score: industry.keywords.reduce(
        (sum, keyword) => sum + (text.includes(keyword) ? keyword.length : 0),
        0,
      ),
    }))
    .sort((left, right) => right.score - left.score);
  if (!scored[0] || scored[0].score === 0) {
    throw new Error("行业自动映射未命中。请核验企业主体后在 facts JSON 写入 industry_code。");
  }
  return {
    ...scored[0],
    confidence:
      scored[0].score >= 6 && scored[0].score > (scored[1]?.score ?? 0)
        ? "中高"
        : "中",
    basis: `主导产品及经营范围关键词命中：${scored[0].keywords
      .filter((keyword) => text.includes(keyword))
      .join("、")}`,
  };
}
