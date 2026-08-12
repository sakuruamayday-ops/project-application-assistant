---
name: application-writing
description: 在项目版本、政策和企业事实核验完成后撰写政府项目正式材料，包括企业简介、主导产品、核心技术、补短板、填空白和产业链作用；不用于政策检索或资格判断。
---

# 申报材料撰写


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 便携运行门禁

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "application-writing" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发先执行`prepare`并应用`active_preferences`；`fail`时停止，`limited`时按已具备能力降级。长期习惯只按协议写入，临时要求不持久化；偏好不得覆盖真实性、安全、验签和质量门禁。完整规则见[便携运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

## 职责

把已核验的政策要求和企业事实组织成正式申报文本。不得用写作替代政策检索、可行性判断或证据补齐。

## 前置门禁

1. 确认项目类型、申报年度、申请书版本、目标章节、字数和评审关注点。
2. 取得已核验政策、企业事实、证据台账及待补项。缺少关键事实时先列缺口。
3. 专精特新和小巨人材料必须确认申请书版本，并对主导产品、补短板、填空白和国产替代保留独立判断。

## 写作流程

1. 形成章节任务单：本段要回答的问题、必须出现的事实、禁止越界的结论和字数。
2. 按“结论→行业问题→企业做法或核心技术→量化指标→客户或产业化验证→项目价值”组织证据链。
3. 数字逐字复用来源，不缩位、不补造；缺失信息使用明确的待核验标记。
4. 正式正文不用中文或英文括号，不写无法核验的“国内领先”“填补空白”等绝对表述。
5. 企业简介和主导产品按 `references/application-section-patterns.md` 选择结构；当期表单有强制结构时以表单为准。
6. 完成后调用 `consistency-check`，未通过不得标记为终稿。
7. 所有事实编号通过 `evidence-ledger` 保持可追溯。若当期申请书存在固定结构或原生来源字段，服从表单；没有容纳来源的位置时另交付来源说明，不得为统一报告格式改动法定表单结构。
8. 用户明确要求去AI味、降低机器腔或自然化润色时，可将已锁定正文交给 `gongchuang-humanizer-zh` 处理表达层；改写完成后必须再次执行 `consistency-check`，不能用自然化改写替代资格、政策或证据判断。

## 用户模板原样填充

用户提供Word模板并要求按模板、按原格式或完全保持版式时，默认只替换模板已有文字节点。禁止用 python-docx 或其他工具重建段落、表格和版式，禁止新增或删除结构。字体、字号、颜色（包括红字）、抬头、页眉页脚、表格布局、合并关系、边框、节属性和页面边距必须保持不变。交付前运行 `skills/_runtime/template-fidelity/scripts/validate_docx_text_only.py`，再逐页检查页数、分页、表格边界、红字、抬头、溢出和重叠；若文字过长导致视觉漂移，压缩文字，不得重排版。

只有用户明确要求增删重复表格时，才进入结构扩展模式；必须复制模板中完整同类OOXML片段，禁止自建相似版式，并单独记录结构变化与视觉验收结果。

## 输出

同时给出正文、采用的事实编号和待补证据。咨询说明与正式正文分离，不把内部风险标签写入客户交付正文。

使用案例包时仅借鉴章节骨架、论证顺序和附件类型；严禁复制案例企业名称、财务、客户、产能、技术参数、知识产权或人员数据。引用前必须回到当前企业证据台账。
