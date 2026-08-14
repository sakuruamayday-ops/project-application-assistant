---
name: project-feasibility
description: 对单个政府项目执行完整可行性分析，覆盖项目与版本确认、硬门槛、评分映射、证据状态、财务计算复核、不确定性、材料差距和结论生成。用户询问某企业能否申报、申报成功条件、差距、预评分或需要补什么材料时使用。
---

# 可行性分析


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 便携运行门禁

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "project-feasibility" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发先执行`prepare`并应用`active_preferences`；`fail`时停止，`limited`时按已具备能力降级。长期习惯只按协议写入，临时要求不持久化；偏好不得覆盖真实性、安全、验签和质量门禁。完整规则见[便携运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

## 强制执行顺序

1. 确认企业主体、项目全称、地区、申报年度、批次以及新申报或复核类型。任一信息可能改变适用规则时，先调用 `policy-retrieval` 取得管理办法、工作指引和当期通知。任务属于前期评估或培育规划时，同时读取 `references/policy-application-path-contract.md`，不得只给资格判断而省略项目的建设和申报路径。用户要求“项目前期评估报告”或“项目申报可行性分析报告”时，还必须完整读取 `references/two-report-contract.md` 和 `references/report-template-registry.json`，并与对应项目领域技能组合执行；在 WorkBuddy 当前轮必须显式调用 `evidence-ledger`，不得只在正文中提及。高企、专精特新中小企业、小巨人、三首、研发中心、制造精品、单项冠军、绿色工厂、数字化及科技计划类命中受控模板时，必须先运行 `python3 scripts/select_report_template.py --project-type <项目> --report-type <preassessment|feasibility> --output-dir <交付目录> --enterprise <企业>`，保留其 `.template-selection.json`，再基于复制出的可编辑 Word 母版回填；不得脱离模板重新排版。进行自动化成稿时，将客户资料、原文锚点和项目事实写入技能树之外的私有夹具，再运行 `python3 scripts/fill_report_template.py --template <已复制母版> --output <成稿.docx> --fixture <私有夹具.json> --report-type <preassessment|feasibility> --release-tag <版本> --public-root <公共源码根目录>`，保留其 `.completion.json`。禁止用空白 `Document()` 重建 Word，禁止用 PyMuPDF 的 china-s 字体或其他未嵌入中文字体手工绘制 PDF 后声称使用了受控母版。自动成稿必须命中真实原文锚点，且不得将客户原件、绝对路径或客户成稿放入公共候选包。索引未命中时才按统一报告骨架生成，且不得冒充已使用受控模板。
2. 读取 `references/feasibility-decision-model.md`，建立规则台账。每条规则标明规则类型、原文、来源、适用范围、时间状态和是否一票否决；不得把历史政策或同类项目规则拼入当期规则。
3. 读取 `references/evidence-state-model.md`，将企业事实逐项映射为“verified、computed、claimed、missing、conflicting、not-applicable”。只有 verified 和复算通过的 computed 可以直接支撑硬门槛。
4. 先判断排除项和硬门槛，再处理评分项。硬门槛出现 `failed` 时结论为不可申报；出现 `missing`、`conflicting` 或关键 `claimed` 时不得给出确定达标结论。
5. 财务门槛先查找 `artifacts/enterprise-financial-facts.v1.json` 或同契约文件，调用 `financial-verification` 核验企业、期间、单位、币种、合并范围和证据。按 `references/calculation-review-rules.md` 展示公式、原始值、单位、结果和复核状态。
6. 将评分细则逐项映射到事实，不以企业入选案例反推评分，不把同一证据重复计入互斥评分项，不将可能得分计入确定得分。政策未公布评分细则时只分析条件和竞争力，不虚构分值。
7. 按 `references/conclusion-contract.md` 生成结论、依据、风险和行动。先给三档结论，再给逐项依据；不承诺获批。

## 结论规则

- `可申报`：所有硬门槛均为 `passed`，不存在一票否决，关键证据已核验；评分项如有，只将确定分计入。
- `有条件申报`：未发现明确硬门槛失败，但存在可在申报前补齐的关键证据、口径冲突或待确认规则。
- `不可申报`：任一适用硬门槛明确失败，或命中当期政策的一票否决项。
- `暂无法判断`：项目版本、政策原文、企业主体或关键数据不足，无法安全落入前三档。此状态不是“有条件申报”。

## 停止与降级

- 同时命中多个政策版本、缺少当期官方通知或政策时效清单标为 `stale` 时，停止形成正式资格结论，先补政策。
- 财务事实属于其他主体、期间不足、口径不一致或质量为 `unverified` 时，停止复用并列出补证要求。
- 只获得企业自述、媒体报道或历史入选名单时，将其作为线索，不升级为硬门槛事实。
- 税务、司法或舆情风险只有在当期政策明确规定为排除项时才转化为资格判断。

## 交付与自检

输出固定包含：项目版本、总体结论、硬门槛矩阵、评分映射、计算复核、证据缺口、不确定性、风险和按截止时间倒排的行动清单。两类报告按双报告合同分别控制深度：前期评估只呈现决定谈单判断的核心条件、现有数据和补强动作；可行性分析在取得现行评分表时完整拆分评分项。前期评估另须按政策路径合同写清主管部门、政策状态、当前起点、先行建设、梯度依赖、建议年度、典型流程、材料证据、停项条件和责任动作；即使当前不可申报或优先级较低也不得省略。形成结构化结果时运行：

`python3 scripts/validate_feasibility_assessment.py <结果.json>`

校验失败时不得交付确定性结论。

生成两类正式报告时，先为本次报告建立 `grounded-evidence/v1` 严格证据台账，显式调用 `evidence-ledger`，再对交付的每一个 Word 和 PDF 分别执行当前轮 Grounded 校验。不得只校验其中一个文件，也不得复用上一轮回执：

`python3 "${CODEBUDDY_PLUGIN_ROOT}/skills/evidence-ledger/scripts/validate_evidence_ledger.py" <证据台账.json> --strict-grounded`

`python3 "${CODEBUDDY_PLUGIN_ROOT}/skills/evidence-ledger/scripts/grounded_evidence.py" validate-delivery <证据台账.json> <报告.docx> --profile analysis-report --visual-status <视觉状态> --receipt-export-dir <交付目录/validator-receipts>`

`python3 "${CODEBUDDY_PLUGIN_ROOT}/skills/evidence-ledger/scripts/grounded_evidence.py" validate-delivery <证据台账.json> <报告.pdf> --profile analysis-report --visual-status <视觉状态> --receipt-export-dir <交付目录/validator-receipts>`

视觉状态只允许填写 passed-host-render 或 pending-device-acceptance。只有实际逐页渲染且未见缺字、空白页、裁切和重叠时才能填写前者；渲染器或中文字体不可用时保持后者并停止正式交付。完成上述 Grounded 文件回执后，必须分别运行报告画像校验并将模板来源、全部文件哈希和内容检查写入当前 WorkBuddy 轮次：

`python3 scripts/validate_report_profile_delivery.py --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --profile-id <project-presale-assessment-report|project-feasibility-analysis-report> --artifact <报告.docx> --artifact <报告.pdf> --template-selection-receipt <母版.template-selection.json> --completion-receipt <成稿.completion.json>`

画像校验会核对必备章节、必备表格、Word 与 PDF 双格式、受控母版哈希链、PDF逐页渲染、中文字体嵌入、文件哈希以及共创红色水印。缺少当前轮次的通过回执时，Stop Hook 必须阻止结束；不得仅在对话中自述“已完成”或“已通过”。

受控 Word 母版只固定结构、表格、项目专属核心对象、补强入口和共创红色水印，不固化政策数值。回填时仍须用当期通知原文替换占位项；母版中的条件只是待核验结构，不得当作现行政策证据。完成 Word 回填后导出 PDF，再对 Word 和 PDF 同时运行上述画像校验。

候选发包前如要验证上述常规项目模板，使用根目录 `scripts/run_workbuddy_report_candidate_pipeline.py`：必须恰好提供十二类私有真实客户夹具，逐类生成前期评估和可行性分析共二十四份 Word/PDF，逐页渲染，仅产出 macOS 与 Windows WorkBuddy 未签名候选包，再从两个最终 ZIP 中重新选模和回填四十八次。自动回执只能保持待视觉复核状态；联系表二十四格的缺字、裁切、重叠、表格可读性、层级与水印均通过后，必须用 `scripts/record_workbuddy_report_visual_review.py` 绑定联系表哈希和检查表。客户资料隔离、ZIP 路径安全、模板哈希、成稿占位符、两端候选包和视觉抽检任一失败时停止。该流水线不生成 ZCode 候选包，也不将源码或模型测试写成 WorkBuddy 真实宿主验收。

案例包可用于比较材料结构、指标分布和证据类型，但不得把案例值当成政策阈值或当前企业事实。可行性结论仍以当期政策和当前企业证据为准。
