#!/usr/bin/env node

import fs from "node:fs/promises";
import path from "node:path";
import crypto from "node:crypto";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const USCC = /^[0-9A-HJ-NPQRTUWXY]{18}$/;
const PUBLIC_SOURCE = "共创研究院知识库";

function parseArgs(argv) {
  const args = { result: [] };
  for (let index = 0; index < argv.length; index += 1) {
    const item = argv[index];
    if (!item.startsWith("--")) throw new Error(`无法识别的参数：${item}`);
    const key = item.slice(2).replaceAll("-", "_");
    const value = argv[index + 1];
    if (!value || value.startsWith("--")) throw new Error(`参数缺少值：${item}`);
    index += 1;
    if (key === "result") args.result.push(value);
    else args[key] = value;
  }
  for (const required of ["queue", "base", "output", "audit"]) {
    if (!args[required]) throw new Error(`缺少参数：--${required.replaceAll("_", "-")}`);
  }
  if (!args.result.length) throw new Error("至少提供一个 --result XLSX 文件");
  return args;
}

function text(value) {
  return value === null || value === undefined ? "" : String(value).trim();
}

function unique(values) {
  return [...new Set(values.map(text).filter(Boolean))];
}

function sanitizePublic(value) {
  if (Array.isArray(value)) return value.map(sanitizePublic);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, sanitizePublic(item)]));
  }
  if (typeof value !== "string") return value;
  return value
    .replaceAll("企知道", PUBLIC_SOURCE)
    .replaceAll("天眼查", PUBLIC_SOURCE)
    .replaceAll("企查查", PUBLIC_SOURCE)
    .replaceAll("焦糖知识库", PUBLIC_SOURCE)
    .replaceAll("焦糖", "共创研究院");
}

function splitValues(value) {
  return unique(text(value).split(/[;；、]/));
}

function csvEscape(value) {
  const normalized = Array.isArray(value) ? value.join("；") : text(value);
  return /[",\r\n]/.test(normalized) ? `"${normalized.replaceAll('"', '""')}"` : normalized;
}

function parseFormerNames(introduction) {
  const matched = text(introduction).match(/曾用名[：:]([\s\S]*?)[）)]，成立于/);
  return matched ? unique(matched[1].split(/[、,，;；]/)) : [];
}

async function readJsonl(filePath) {
  return (await fs.readFile(filePath, "utf8"))
    .split(/\r?\n/)
    .filter((line) => line.trim())
    .map((line) => JSON.parse(line));
}

async function readResult(filePath) {
  const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(filePath));
  const sheet = workbook.worksheets.getItem("查询企业搜索结果");
  const values = sheet.getUsedRange(true).values;
  const headers = values[1].map(text);
  const indexes = Object.fromEntries(headers.map((header, index) => [header, index]));
  for (const required of ["导入名称", "企业名称", "统一社会信用代码"]) {
    if (indexes[required] === undefined) throw new Error(`${filePath} 缺少列：${required}`);
  }
  return values.slice(2)
    .filter((row) => text(row[indexes["导入名称"]]))
    .map((row) => ({
      sourceFile: path.basename(filePath),
      values: Object.fromEntries(headers.filter(Boolean).map((header) => [header, text(row[indexes[header]])])),
    }));
}

function buildBatchProfile(subject, generatedAt) {
  const records = subject.records;
  const currentNames = unique(records.map((record) => record.values["企业名称"]));
  if (currentNames.length !== 1) {
    throw new Error(`同一信用代码出现多个当前名称：${subject.code} ${currentNames.join("；")}`);
  }
  const field = (name) => unique(records.map((record) => record.values[name])).join("；");
  const recognitionNames = unique(subject.queueRows.flatMap((row) => row.recognition_names || [row.enterprise_name]));
  const formerNames = unique(records.flatMap((record) => parseFormerNames(record.values["企业简介"])));
  const projects = unique(subject.queueRows.flatMap((row) => row.recognition_projects || []));
  return {
    schema_version: "zhejiang-enterprise-base-identity-v2",
    identity_key: subject.code,
    master_identity_key: subject.code,
    merged_master_identity_keys: [subject.code],
    unified_social_credit_code: subject.code,
    entity_resolution_status: "resolved_by_complete_batch_receipt",
    current_name: currentNames[0],
    recognition_names: recognitionNames,
    former_names: formerNames,
    current_province: field("所属省份"),
    current_city: field("所属城市"),
    current_county: field("所属区县"),
    current_address: field("企业地址"),
    registration_authority: "",
    registration_status: field("登记状态"),
    founded_date: field("成立日期"),
    registered_capital: field("注册资本"),
    company_type: field("企业（机构）类型"),
    industry_level_1: field("国行一级分类"),
    industry_level_2: field("国行二级分类"),
    industry_level_3: field("国行三级分类"),
    website: field("官网"),
    company_introduction: field("企业简介"),
    business_scope: field("经营范围"),
    main_product_tags: unique(records.flatMap((record) => splitValues(record.values["主营产品标签"]))),
    industry_track_tags: unique(records.flatMap((record) => splitValues(record.values["行业赛道标签"]))),
    ip_statistics: {
      patent_count: field("专利数量"),
      invention_patent_count: field("发明专利数量"),
      granted_invention_count: field("已授权发明数量"),
      valid_invention_count: field("有效发明数量"),
      utility_model_count: field("实用新型专利数量"),
      design_patent_count: field("外观设计专利数量"),
      trademark_count: field("商标数量"),
      software_copyright_count: field("软件著作权数量"),
    },
    honors: unique(records.flatMap((record) => splitValues(record.values["荣誉资质"]))),
    bid_count: field("中标项目数量"),
    standard_count: field("标准数量"),
    listed_status: field("是否上市"),
    recognition_projects: projects,
    category_groups: projects,
    project_lifecycles: [],
    knowledge_verification_status: "knowledge_verified",
    source_layers: {
      knowledge_base: {
        source_type: PUBLIC_SOURCE,
        list_membership_status: "verified",
        enterprise_identity_status: "verified",
        match_status: "complete_batch_receipt_uscc_exact",
      },
    },
    generated_at: generatedAt,
  };
}

function mergeProfile(existing, incoming, generatedAt) {
  if (!existing) return incoming;
  const merged = { ...existing };
  for (const key of [
    "current_name", "current_province", "current_city", "current_county", "current_address",
    "registration_status", "founded_date", "registered_capital", "company_type",
    "industry_level_1", "industry_level_2", "industry_level_3", "website",
    "company_introduction", "business_scope", "bid_count", "standard_count", "listed_status",
  ]) {
    if (incoming[key]) merged[key] = incoming[key];
  }
  for (const key of ["recognition_names", "former_names", "main_product_tags", "industry_track_tags", "honors", "recognition_projects", "category_groups"]) {
    merged[key] = unique([...(existing[key] || []), ...(incoming[key] || [])]);
  }
  merged.ip_statistics = { ...(existing.ip_statistics || {}), ...(incoming.ip_statistics || {}) };
  merged.identity_key = incoming.identity_key;
  merged.master_identity_key = incoming.identity_key;
  merged.unified_social_credit_code = incoming.unified_social_credit_code;
  merged.entity_resolution_status = incoming.entity_resolution_status;
  merged.knowledge_verification_status = "knowledge_verified";
  merged.source_layers = incoming.source_layers;
  merged.generated_at = generatedAt;
  merged.schema_version = incoming.schema_version;
  return merged;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const queue = await readJsonl(args.queue);
  if (queue.length !== 3741 || new Set(queue.map((row) => row.enterprise_name)).size !== 3741) {
    throw new Error(`队列必须是 3,741 个唯一名称，实际 ${queue.length}`);
  }
  const queueByName = new Map(queue.map((row, index) => [row.enterprise_name, { ...row, queue_index: index + 1 }]));
  const resultRows = (await Promise.all(args.result.map(readResult))).flat();
  const byImportName = new Map();
  const ignoredExternalRows = [];
  for (const record of resultRows) {
    const importName = record.values["导入名称"];
    if (!queueByName.has(importName)) {
      ignoredExternalRows.push(record);
      continue;
    }
    const previous = byImportName.get(importName);
    if (previous && JSON.stringify(previous.values) !== JSON.stringify(record.values)) {
      throw new Error(`同一导入名称存在不一致的重复结果：${importName}`);
    }
    byImportName.set(importName, record);
  }
  let reconciledNames = 0;
  if (args.reconciliation_audit) {
    const reconciliationAudit = JSON.parse(await fs.readFile(args.reconciliation_audit, "utf8"));
    for (const row of reconciliationAudit.reconciled || []) {
      const listNames = splitValues(row[2]);
      const code = text(row[4]).toUpperCase();
      if (!USCC.test(code)) throw new Error(`人工对账包含无效信用代码：${code}`);
      const matches = resultRows.filter(
        (record) => text(record.values["统一社会信用代码"]).toUpperCase() === code,
      );
      if (!matches.length) throw new Error(`人工对账代码未命中原始回执：${code}`);
      for (const listName of listNames) {
        if (!queueByName.has(listName)) throw new Error(`人工对账名称不在 3,741 队列：${listName}`);
        if (!byImportName.has(listName)) reconciledNames += 1;
        byImportName.set(listName, matches[0]);
      }
    }
  }
  const missing = queue.filter((row) => !byImportName.has(row.enterprise_name));
  if (missing.length) throw new Error(`六批结果未闭合，仍缺 ${missing.length} 家：${missing.slice(0, 5).map((row) => row.enterprise_name).join("、")}`);

  const subjects = new Map();
  const invalidIdentityNames = [];
  for (const queueRow of queue) {
    const record = byImportName.get(queueRow.enterprise_name);
    const code = record.values["统一社会信用代码"].toUpperCase();
    if (!USCC.test(code)) {
      invalidIdentityNames.push(queueRow.enterprise_name);
      continue;
    }
    const subject = subjects.get(code) || { code, records: [], queueRows: [] };
    subject.records.push(record);
    subject.queueRows.push(queueRow);
    subjects.set(code, subject);
  }

  const baseRows = await readJsonl(args.base);
  const profiles = new Map();
  for (const row of baseRows) {
    const code = text(row.unified_social_credit_code).toUpperCase();
    if (!USCC.test(code)) throw new Error(`基础快照信用代码异常：${code}`);
    if (profiles.has(code)) throw new Error(`基础快照信用代码重复：${code}`);
    profiles.set(code, row);
  }
  const generatedAt = new Date().toISOString();
  let overlapCodes = 0;
  for (const subject of subjects.values()) {
    const incoming = buildBatchProfile(subject, generatedAt);
    if (profiles.has(subject.code)) overlapCodes += 1;
    profiles.set(subject.code, mergeProfile(profiles.get(subject.code), incoming, generatedAt));
  }
  const outputRows = [...profiles.values()].map(sanitizePublic).sort((left, right) =>
    text(left.current_name).localeCompare(text(right.current_name), "zh-CN") ||
    text(left.unified_social_credit_code).localeCompare(text(right.unified_social_credit_code)),
  );
  const outputText = outputRows.map((row) => JSON.stringify(row)).join("\n") + "\n";
  await fs.mkdir(path.dirname(args.output), { recursive: true });
  await fs.writeFile(`${args.output}.tmp`, outputText, "utf8");
  await fs.rename(`${args.output}.tmp`, args.output);
  let csvSha256 = "";
  if (args.csv) {
    const csvHeaders = [
      "identity_key", "unified_social_credit_code", "current_name", "current_province",
      "current_city", "current_county", "registration_status", "founded_date",
      "registered_capital", "industry_level_1", "industry_level_2", "industry_level_3",
      "main_product_tags", "recognition_projects", "category_groups",
      "knowledge_verification_status", "knowledge_match_status",
    ];
    const csvRows = outputRows.map((row) => csvHeaders.map((header) => {
      if (header === "knowledge_match_status") {
        return row.source_layers?.knowledge_base?.match_status || "";
      }
      return row[header] ?? "";
    }).map(csvEscape).join(","));
    const csvText = `\ufeff${csvHeaders.join(",")}\n${csvRows.join("\n")}\n`;
    await fs.writeFile(`${args.csv}.tmp`, csvText, "utf8");
    await fs.rename(`${args.csv}.tmp`, args.csv);
    csvSha256 = crypto.createHash("sha256").update(csvText).digest("hex");
  }
  const jsonlSha256 = crypto.createHash("sha256").update(outputText).digest("hex");
  const audit = {
    generated_at: generatedAt,
    schema_version: 1,
    public_source: PUBLIC_SOURCE,
    queue_names: queue.length,
    raw_result_rows: resultRows.length,
    queue_result_rows: resultRows.length - ignoredExternalRows.length,
    ignored_external_result_rows: ignoredExternalRows.length,
    reconciled_queue_names: reconciledNames,
    returned_unique_names: byImportName.size,
    result_subjects_by_uscc: subjects.size,
    invalid_identity_queue_names: invalidIdentityNames,
    base_subjects: baseRows.length,
    overlap_codes: overlapCodes,
    inserted_subjects: subjects.size - overlapCodes,
    output_subjects: outputRows.length,
    pending_result_names: 0,
    pending_identity_names: invalidIdentityNames.length,
    project_name_counts: Object.fromEntries(
      [...new Set(queue.flatMap((row) => row.recognition_projects || []))]
        .sort()
        .map((project) => [project, queue.filter((row) => (row.recognition_projects || []).includes(project)).length]),
    ),
    result_files: args.result.map((item) => path.basename(item)),
    privacy_boundary: {
      excluded_fields: ["电话", "联系人", "个人手机", "个人邮箱"],
      note: "仅保留企业级基础身份、行业、产品标签和汇总统计，不写入个人联系方式。",
    },
    outputs: {
      jsonl: path.basename(args.output),
      jsonl_sha256: jsonlSha256,
      ...(args.csv ? { csv: path.basename(args.csv), csv_sha256: csvSha256 } : {}),
    },
    rules: [
      "只接受原 3,741 家队列中的精确导入名称。",
      "六批返回必须覆盖全部队列名称；无有效 18 位信用代码的返回仅保留待核，不升级主体身份。",
      "同信用代码合并为一个主体，保留全部名单名称、现名和曾用名。",
      `对外来源统一投影为${PUBLIC_SOURCE}。`,
    ],
  };
  await fs.mkdir(path.dirname(args.audit), { recursive: true });
  await fs.writeFile(args.audit, JSON.stringify(audit, null, 2) + "\n", "utf8");
  process.stdout.write(JSON.stringify(audit) + "\n");
}

await main();
