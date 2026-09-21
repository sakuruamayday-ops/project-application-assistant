# 客户端技能升级整合记录

来源为 2026-09-15 技能维护工作树，基于 1c90ded。仅整合套件正文、共用运行规则、刷新器同源提示和对应测试。未发布或安装。

原候选中的历史档案删除、WorkBuddy 退出改动、个人记忆、供应商副本和受保护发布器不随套件复制。其状态仍由客户端需求承接清单跟踪。工具链补丁保留为候选，尚未应用到实际发布器。

## 已承接文件

- `skills/agriculture-and-rural-projects/SKILL.md`
- `skills/application-version-diff/SKILL.md`
- `skills/application-writing/SKILL.md`
- `skills/checking-patdocx-cn-single-agent/SKILL.md`
- `skills/consistency-check/SKILL.md`
- `skills/deep-clarification/SKILL.md`
- `skills/digitalization-projects/SKILL.md`
- `skills/enterprise-panorama-analysis/SKILL.md`
- `skills/enterprise-panorama-analysis/references/enterprise-info-verification.md`
- `skills/enterprise-panorama-analysis/references/report-spec.md`
- `skills/enterprise-profile/SKILL.md`
- `skills/evidence-ledger/SKILL.md`
- `skills/evolution-governance/SKILL.md`
- `skills/experience-recorder/SKILL.md`
- `skills/financial-verification/SKILL.md`
- `skills/first-run-configuration/SKILL.md`
- `skills/first-run-configuration/references/preference-inheritance.md`
- `skills/first-run-configuration/scripts/migrate_skill_preferences.py`
- `skills/first-run-configuration/scripts/upgrade_inheritance.py`
- `skills/gongchuang-humanizer-zh/SKILL.md`
- `skills/gongchuang-humanizer-zh/references/evolution.md`
- `skills/gongchuang-humanizer-zh/references/formal-materials.md`
- `skills/graphify/SKILL.md`
- `skills/green-development-projects/SKILL.md`
- `skills/high-tech-enterprise-application-drafting/SKILL.md`
- `skills/high-tech-enterprise-preassessment/SKILL.md`
- `skills/industrialization-projects/SKILL.md`
- `skills/industry-chain-foundation-matcher/SKILL.md`
- `skills/industry-positioning/SKILL.md`
- `skills/industry-positioning/references/automatic-master-matrix-orchestration.md`
- `skills/industry-positioning/references/industry-positioning-assessment.md`
- `skills/intellectual-property-projects/SKILL.md`
- `skills/investment-subsidy-projects/SKILL.md`
- `skills/ip-assessment/SKILL.md`
- `skills/legal-regulations/SKILL.md`
- `skills/legal-regulations/references/local-retrieval.md`
- `skills/local-knowledge-retrieval/SKILL.md`
- `skills/local-knowledge-retrieval/references/three-first-project-list-schema.md`
- `skills/manufacturing-tax-risk-analysis/SKILL.md`
- `skills/manufacturing-tax-risk-analysis/references/report-input-schema.md`
- `skills/manufacturing-tax-risk-analysis/references/report-spec.md`
- `skills/patent-router/SKILL.md`
- `skills/patent-router/references/regression-gates.md`
- `skills/peer-benchmarking/SKILL.md`
- `skills/policy-retrieval/SKILL.md`
- `skills/project-application-assistant/SKILL.md`
- `skills/project-deliverable-archive/SKILL.md`
- `skills/project-feasibility/SKILL.md`
- `skills/project-feasibility/references/evidence-state-model.md`
- `skills/project-feasibility/references/policy-application-path-contract.md`
- `skills/project-matching/SKILL.md`
- `skills/project-matching/references/policy-application-path-contract.md`
- `skills/project-memory/SKILL.md`
- `skills/project-rule-manager/SKILL.md`
- `skills/project-task-router/SKILL.md`
- `skills/project-task-router/references/domain-routing-matrix.md`
- `skills/quality-brand-projects/SKILL.md`
- `skills/regional-special-projects/SKILL.md`
- `skills/skill-authoring/SKILL.md`
- `skills/skill-curator/SKILL.md`
- `skills/skill-evolution/SKILL.md`
- `skills/sme-development-projects/SKILL.md`
- `skills/sme-development-projects/references/current-policy-baseline-2026.md`
- `skills/sme-development-projects/references/evaluation-workflow.md`
- `skills/sme-development-projects/references/key-technology-first-innovation-method.md`
- `skills/sme-development-projects/references/policy-application-path-contract.md`
- `skills/sme-score-preassessment/SKILL.md`
- `skills/sme-score-preassessment/references/direction-card-first-template.md`
- `skills/sme-score-preassessment/references/policy-application-path-contract.md`
- `skills/standard-drafting/SKILL.md`
- `skills/suite-manifest.json`
- `skills/talent-projects/SKILL.md`
- `skills/technology-innovation-projects/SKILL.md`
- `skills/third-party-data-indexing/SKILL.md`
- `skills/trade-and-open-economy-projects/SKILL.md`
- `skills/web-task-operator/SKILL.md`
- `skills/_runtime/policy-application-path-contract.md`
- `skills/_runtime/recognition-source-routing.md`
- `skills/_runtime/task-execution.md`
- `skills/project-application-assistant/references/gongchuang-document-host.md`
- `scripts/refresh_portable_runtime_blocks.py`
- `toolchain-candidates/skill-release-manager/references/portable-runtime-notice.md`
- `toolchain-candidates/skill-release-manager/package-runtime-notice.patch`
- `toolchain-candidates/skill-release-manager/README.md`
- `tests/test_policy_application_path_contract.py`
- `tests/test_v166_minimal_report_prompt_routes.py`
- `tests/test_project_report_profile_delivery.py`

## 外接开发技能核验

本轮另行核验宿主外接技能。grilling 同步原作者 c55ee46 的提问轮次示例；grill-me、grill-with-docs、domain-modeling 无正文变更。业务套件 deep-clarification 的访谈机制无需因纯展示示例变化改写，原许可与来源保留。归藏 PPT 更新宿主模板与演讲者功能，不进入签名业务套件。详细来源、备份及验证保留在工作区外接技能维护任务的独立核验记录中。


## 发布器同源提示实跑

已在 `/private/tmp/gongchuang-publisher-review-20260921` 建立发布器隔离副本并应用已有补丁，未覆盖已安装签名核心、未接触签名私钥。对当前全部 51 项技能分别运行旧发布器和候选的 `ensure_runtime_instructions`：旧发布器会把 51 项新提示全部改回旧正文；候选保留 51 项规范提示，第二次处理 51 项均不再变化。可复现实跑脚本和逐项结果见 [脚本](evidence/publisher-notice-check-20260921.py) 与 [回执](evidence/publisher-notice-check-20260921.json)。

这证明候选补丁消除了已复现的提示回退路径，不代表完整通用 ZIP 已签名或客户端已安装新技能。后续仍需将候选发布器和资源作为同一工具链输入执行现有签名、安装和业务验收。

## 候选投影与内容验证

2026-09-21：客户端现有 stage-skill-suite 在独立临时开发密钥下生成 development-candidate 投影，51 技能、568 文件验签及完整性检查通过。未修改正式信任锚，未安装到正式客户端。六项只读源码验证均通过：对抗结构、技能行为覆盖、内容及路由样例、弃用政策规则、单一知识 MCP、三首黄金样例。对应原始结果位于 evidence/*-20260921.log。这些结果不等于完整正式发行检查或正式签名已经完成。


## 来源定位与最终源码验证

DOCX 候选在不改正文内容的前提下返回部件、段落和 Unicode 字符区间。定位使用 XML 原始位置并映射空白规整，重复文字、文本框嵌套和截断不以文字搜索猜测归属；39 项解析用例及打包 Python 的五项新场景通过。证据见 [来源定位](evidence/docx-source-locations-20260921.json)。旧 PPT 和专有 WPS 本轮维持明确另存提示，不新增自动转换组件。

最终源码检查为 444 项通过、3 项跳过、18 项子测试通过，见 [完整日志](evidence/source-suite-final-20260921.log)。签名安装测试使用原 V1.6.19 签名样本核验只读安装、更新解冻和故障回滚，待签名源码不作为既有签名样本。29 份 Office 和 4 份源码模板的解析与回写检查通过；本轮未重做模板视觉渲染。新版签名安装与实际业务验收尚未完成。
