#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

const artifactTool = await import(
  process.env.JIAOTANG_ARTIFACT_TOOL_MODULE
    ? pathToFileURL(process.env.JIAOTANG_ARTIFACT_TOOL_MODULE).href
    : "@oai/artifact-tool"
);
const { FileBlob, SpreadsheetFile } = artifactTool;

const USCC = /^[0-9A-HJ-NPQRTUWXY]{18}$/;
const PUBLIC_SOURCE = "共创研究院知识库";
const ACCEPTED_DECISIONS = new Set(["accept_alias"]);
const EXCLUDED_DECISIONS = new Set(["exclude_unrelated_return"]);

function parseArgs(argv) {
  const args = { result: [] };
  for (let index = 0; index < argv.length; index += 1) {
    const option = argv[index];
    if (!option.startsWith("--")) throw new Error(`无法识别的参数：${option}`);
    const key = option.slice(2).replaceAll("-", "_");
    const value = argv[index + 1];
    if (!value || value.startsWith("--")) throw new Error(`参数缺少值：${option}`);
    index += 1;
    if (key === "result") args.result.push(value);
    else args[key] = value;
  }
  for (const required of [
    "current_master", "review", "output", "file_manifest", "invalid_output", "audit",
  ]) {
    if (!args[required]) throw new Error(`缺少参数：--${required.replaceAll("_", "-")}`);
  }
  if (!args.result.length) throw new Error("至少提供一个 --result XLSX 文件");
  return args;
}

function text(value) {
  return value === null || value === undefined ? "" : String(value).trim();
}

function normalizeName(value) {
  return text(value)
    .replace(/[\s·•・,，。;；:：()（）【】\[\]\\"“”'‘’\-—_]/g, "")
    .toLowerCase();
}

function unique(values) {
  return [...new Set(values.map(text).filter(Boolean))];
}

function splitValues(value) {
  return unique(text(value).split(/[;；、]/));
}

function parseFormerNames(introduction) {
  const matched = text(introduction).match(/曾用名[：:]([\s\S]*?)[）)]，成立于/);
  return matched ? unique(matched[1].split(/[、,，;；]/)) : [];
}

async function sha256(file) {
  return crypto.createHash("sha256").update(await fs.readFile(file)).digest("hex");
}

async function readJsonl(file) {
  return (await fs.readFile(file, "utf8"))
    .split(/\r?\n/)
    .filter((line) => line.trim())
    .map((line) => JSON.parse(line));
}

async function writeJsonl(file, rows) {
  await fs.mkdir(path.dirname(file), { recursive: true });
  const payload = rows.map((row) => JSON.stringify(row)).join("\n") + (rows.length ? "\n" : "");
  await fs.writeFile(`${file}.tmp`, payload, "utf8");
  await fs.rename(`${file}.tmp`, file);
  return crypto.createHash("sha256").update(payload).digest("hex");
}

async function readWorkbook(file) {
  const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(file));
  const sheet = workbook.worksheets.getItemAt(0);
  const values = sheet.getUsedRange(true)?.values ?? [];
  const headerIndex = values.findIndex((row) => {
    const cells = new Set(row.map(text));
    return cells.has("导入名称") && cells.has("企业名称") && cells.has("统一社会信用代码");
  });
  if (headerIndex < 0) throw new Error(`${file} 未找到企业批量查询表头`);
  const headers = values[headerIndex].map(text);
  const indexes = Object.fromEntries(headers.map((header, index) => [header, index]));
  const fileSha256 = await sha256(file);
  const capturedDate = path.basename(file).match(/\d{8}/)?.[0] ?? "";
  const records = [];
  for (let rowIndex = headerIndex + 1; rowIndex < values.length; rowIndex += 1) {
    const row = values[rowIndex];
    const cells = Object.fromEntries(
      headers
        .map((header, index) => [header, text(row[index])])
        .filter(([header]) => header),
    );
    const importedName = cells["导入名称"] ?? "";
    const currentName = cells["企业名称"] ?? "";
    const code = text(cells["统一社会信用代码"]).toUpperCase();
    if (!importedName && !currentName && !code) continue;
    records.push({
      imported_name: importedName,
      current_name: currentName,
      unified_social_credit_code: code,
      values: cells,
      evidence: {
        source_file_name: path.basename(file),
        source_file_sha256: fileSha256,
        source_sheet: sheet.name,
        source_row_number: rowIndex + 1,
        captured_date: capturedDate,
      },
    });
  }
  return {
    file,
    file_name: path.basename(file),
    sha256: fileSha256,
    captured_date: capturedDate,
    source_sheet: sheet.name,
    row_count: records.length,
    valid_code_rows: records.filter((record) => USCC.test(record.unified_social_credit_code)).length,
    records,
  };
}

async function concurrentMap(items, limit, operation) {
  const output = new Array(items.length);
  let cursor = 0;
  async function worker() {
    while (true) {
      const index = cursor++;
      if (index >= items.length) return;
      output[index] = await operation(items[index]);
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, () => worker()));
  return output;
}

function reviewKey(code, importedName) {
  return `${text(code).toUpperCase()}|${normalizeName(importedName)}`;
}

function profileFromSubject(subject, status) {
  const records = [...subject.records].sort((left, right) =>
    right.evidence.captured_date.localeCompare(left.evidence.captured_date)
    || right.evidence.source_file_name.localeCompare(left.evidence.source_file_name)
    || right.evidence.source_row_number - left.evidence.source_row_number,
  );
  const latest = records[0];
  const field = (name) => latest.values[name] ?? "";
  const importedNames = unique(records.map((record) => record.imported_name));
  const currentNames = unique(records.map((record) => record.current_name));
  return {
    schema_version: "enterprise-batch-profile-provenance-v1",
    identity_key: subject.code,
    unified_social_credit_code: subject.code,
    current_name: latest.current_name,
    imported_names: importedNames,
    observed_current_names: currentNames,
    former_names: unique(records.flatMap((record) => parseFormerNames(record.values["企业简介"]))),
    registration_status: field("登记状态"),
    founded_date: field("成立日期"),
    registered_capital: field("注册资本"),
    province: field("所属省份"),
    city: field("所属城市"),
    county: field("所属区县"),
    address: field("企业地址"),
    company_type: field("企业（机构）类型"),
    industry_level_1: field("国行一级分类"),
    industry_level_2: field("国行二级分类"),
    industry_level_3: field("国行三级分类"),
    website: field("官网"),
    company_introduction: field("企业简介"),
    business_scope: field("经营范围"),
    main_product_tags: splitValues(field("主营产品标签")),
    industry_track_tags: splitValues(field("行业赛道标签")),
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
    honors: splitValues(field("荣誉资质")),
    bid_count: field("中标项目数量"),
    standard_count: field("标准数量"),
    listed_status: field("是否上市"),
    identity_candidate_status: status,
    business_profile_evidence_status: "licensed_batch_profile_candidate",
    recognition_evidence_status: "not_linked",
    captured_at: latest.evidence.captured_date,
    source: PUBLIC_SOURCE,
    evidence: records.map((record) => record.evidence),
  };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const currentMaster = await readJsonl(args.current_master);
  const reviews = await readJsonl(args.review);
  const reviewByKey = new Map(
    reviews
      .filter((row) => row.unified_social_credit_code)
      .map((row) => [reviewKey(row.unified_social_credit_code, row.imported_name), row]),
  );
  const masterNames = new Map();
  for (const row of currentMaster) {
    for (const name of [row.current_name, ...(row.former_names ?? []), ...(row.recognition_names ?? [])]) {
      const normalized = normalizeName(name);
      if (!normalized) continue;
      const keys = masterNames.get(normalized) ?? new Set();
      keys.add(text(row.identity_key));
      masterNames.set(normalized, keys);
    }
  }

  const workbooks = await concurrentMap(args.result, 4, readWorkbook);
  const subjects = new Map();
  const invalidRows = [];
  for (const workbook of workbooks) {
    for (const record of workbook.records) {
      if (!USCC.test(record.unified_social_credit_code)) {
        invalidRows.push({
          schema_version: "enterprise-batch-invalid-row-v1",
          imported_name: record.imported_name,
          returned_name: record.current_name,
          returned_code: record.unified_social_credit_code,
          reason: "missing_or_invalid_unified_social_credit_code",
          source: PUBLIC_SOURCE,
          evidence: record.evidence,
        });
        continue;
      }
      const code = record.unified_social_credit_code;
      const subject = subjects.get(code) ?? { code, records: [] };
      subject.records.push(record);
      subjects.set(code, subject);
    }
  }

  const profiles = [];
  for (const subject of subjects.values()) {
    const exact = subject.records.some(
      (record) => normalizeName(record.imported_name) === normalizeName(record.current_name),
    );
    const reviewRows = subject.records
      .map((record) => reviewByKey.get(reviewKey(subject.code, record.imported_name)))
      .filter(Boolean);
    let status = "manual_review_name_mismatch";
    if (exact) status = "accepted_exact_current_name";
    else if (reviewRows.some((row) => ACCEPTED_DECISIONS.has(row.decision))) {
      status = "accepted_reviewed_alias";
    } else if (reviewRows.length && reviewRows.every((row) => EXCLUDED_DECISIONS.has(row.decision))) {
      status = "excluded_unrelated_return";
    }
    const profile = profileFromSubject(subject, status);
    profile.matched_master_identity_keys = unique(
      [...profile.imported_names, ...profile.observed_current_names]
        .flatMap((name) => [...(masterNames.get(normalizeName(name)) ?? [])]),
    );
    profiles.push(profile);
  }
  profiles.sort((left, right) =>
    left.current_name.localeCompare(right.current_name, "zh-CN")
    || left.unified_social_credit_code.localeCompare(right.unified_social_credit_code),
  );

  const fileRows = workbooks.map(({ records, file, ...row }) => ({
    schema_version: "enterprise-batch-file-provenance-v1",
    ...row,
    archived_file: args.raw_archive_root
      ? path.join(args.raw_archive_root, row.file_name)
      : row.file_name,
    source: PUBLIC_SOURCE,
  }));
  const outputSha256 = await writeJsonl(args.output, profiles);
  const manifestSha256 = await writeJsonl(args.file_manifest, fileRows);
  const invalidSha256 = await writeJsonl(args.invalid_output, invalidRows);
  const acceptedProfiles = profiles.filter((row) => row.identity_candidate_status.startsWith("accepted_"));
  const report = {
    schema_version: "enterprise-batch-profile-provenance-audit-v1",
    generated_at: new Date().toISOString(),
    source: PUBLIC_SOURCE,
    result_files: workbooks.length,
    result_rows: workbooks.reduce((sum, row) => sum + row.row_count, 0),
    valid_code_rows: workbooks.reduce((sum, row) => sum + row.valid_code_rows, 0),
    unique_valid_codes: profiles.length,
    accepted_subjects: acceptedProfiles.length,
    accepted_exact_current_name: profiles.filter((row) => row.identity_candidate_status === "accepted_exact_current_name").length,
    accepted_reviewed_alias: profiles.filter((row) => row.identity_candidate_status === "accepted_reviewed_alias").length,
    excluded_unrelated_return: profiles.filter((row) => row.identity_candidate_status === "excluded_unrelated_return").length,
    manual_review_name_mismatch: profiles.filter((row) => row.identity_candidate_status === "manual_review_name_mismatch").length,
    invalid_result_rows: invalidRows.length,
    current_master_rows: currentMaster.length,
    accepted_codes_already_in_master: acceptedProfiles.filter((row) =>
      currentMaster.some((item) => text(item.unified_social_credit_code).toUpperCase() === row.unified_social_credit_code)
    ).length,
    accepted_codes_missing_current_master: acceptedProfiles.filter((row) =>
      !currentMaster.some((item) => text(item.unified_social_credit_code).toUpperCase() === row.unified_social_credit_code)
    ).length,
    privacy_boundary: {
      excluded_fields: ["电话", "联系人", "个人手机", "个人邮箱"],
      note: "仅保留企业级身份、经营、行业、产品标签、汇总统计和文件哈希。",
    },
    evidence_boundary: "批量企业画像可作为主体身份候选和画像补充，不自动形成任何项目认定、资格或生命周期事实。",
    outputs: {
      profiles: path.basename(args.output),
      profiles_sha256: outputSha256,
      file_manifest: path.basename(args.file_manifest),
      file_manifest_sha256: manifestSha256,
      invalid_rows: path.basename(args.invalid_output),
      invalid_rows_sha256: invalidSha256,
    },
  };
  await fs.mkdir(path.dirname(args.audit), { recursive: true });
  await fs.writeFile(args.audit, JSON.stringify(report, null, 2) + "\n", "utf8");
  process.stdout.write(JSON.stringify(report) + "\n");
}

await main();
