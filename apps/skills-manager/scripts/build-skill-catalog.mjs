import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const appRoot = path.resolve(here, "..");
const repoRoot = path.resolve(appRoot, "..", "..");
const suitePath = path.join(repoRoot, "skills", "suite-manifest.json");
const suite = JSON.parse(fs.readFileSync(suitePath, "utf8"));

function frontmatter(filePath) {
  const text = fs.readFileSync(filePath, "utf8");
  const block = text.match(/^---\s*\n([\s\S]*?)\n---/);
  if (!block) return {};
  const result = {};
  for (const line of block[1].split("\n")) {
    const match = line.match(/^([A-Za-z0-9_-]+):\s*(.*)$/);
    if (!match) continue;
    result[match[1]] = match[2].replace(/^["']|["']$/g, "").trim();
  }
  return result;
}

const skills = suite.skills.map((id) => {
  const skillRoot = path.join(repoRoot, "skills", id);
  const meta = frontmatter(path.join(skillRoot, "SKILL.md"));
  const release = JSON.parse(fs.readFileSync(path.join(skillRoot, "release-manifest.json"), "utf8"));
  return {
    id,
    name: meta.name || id,
    description: meta.description || "",
    releaseTag: release.release_tag,
    runtimeRequirements: release.runtime_requirements || { python_modules: [], executables: [] },
    dependencies: suite.dependencies?.[id]?.required_skills || [],
  };
});

const output = {
  schema: "jiaotang-skill-catalog/v1",
  product: suite.product_name,
  generatedFrom: "skills/suite-manifest.json",
  releaseTag: suite.release.tag,
  count: skills.length,
  skills,
};

const outputPath = path.join(appRoot, "data", "skill-catalog.json");
fs.writeFileSync(outputPath, `${JSON.stringify(output, null, 2)}\n`);
console.log(`catalog: ${skills.length} skills -> ${outputPath}`);
