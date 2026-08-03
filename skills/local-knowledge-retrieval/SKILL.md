---
name: local-knowledge-retrieval
description: 检索团队统一云端知识服务。需要历史政策、相似案例、模板、企业名单、年份批次核验或既有项目经验时使用；自动执行简称与全称、年份与批次变体、结构化名单与全文双路径检索，并禁止一次未命中即判定资料不存在。
---

# 团队知识检索


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 跨平台首次运行与个人习惯

支持CodeBuddy/WorkBuddy内联命令的宿主会在技能触发时自动执行下面的确定性门禁，并把JSON结果注入当前上下文：

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

作为WorkBuddy插件加载时，还会把本轮实际触发的技能与当前会话和轮次绑定：

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "local-knowledge-retrieval" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发本技能时，第一步必须定位当前`SKILL.md`所在的技能目录，并以该目录为工作目录运行`python3 scripts/portable_skill_runtime.py prepare`。不得因为当前任务看似简单而跳过。将返回的`active_preferences`作为用户个人习惯应用于当前任务；结果为`fail`时停止执行，不得声称安装、自检或升级成功。`capability_check`为`limited`时，只使用宿主已具备的能力，并明确未通过的依赖项，不得声称依赖完整。

用户以“以后、默认、记住、每次、别再”等措辞明确表达长期习惯时：若上下文已出现“偏好桥接轮次已建立”的WorkBuddy钩子提示，不要手动调用`remember`，由停止钩子只向本轮实际触发且已经按会话、轮次绑定的技能写入；其他宿主则在最终答复前调用`python3 scripts/portable_skill_runtime.py remember --instruction '用户原意' --scope default --source agent-confirmed`，再调用`context`确认。未取得`status: pass`和对应偏好记录时，严禁声称“已记住”或“以后会默认采用”。无法执行保存时，只能说明本次会话已理解、尚未形成跨会话偏好。“这次、本次、当前文件、临时”等要求只影响当前任务，禁止写入长期偏好。无需让用户了解或输入存储命令。发生歧义、偏好冲突或可能削弱强制质量门禁时才询问。

个人配置保存在技能目录外并自动备份。不得用个人偏好覆盖真实性、安全、验签、安装自检或本技能的强制质量门禁。完整规则见[跨平台技能运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

先检查当前宿主是否已经连接`jiaotang-kb` MCP。未连接时，引导用户登录门户点击“一键安装”，并直接执行用户粘贴的一段完整指令；手工配置页会自动填入当前登录用户的真实个人Token，不让用户去其他页面寻找后再回来填写。

普通成员通过远程HTTP`jiaotang-kb`访问团队知识。个人Bearer Token只保存在当前用户的WorkBuddy MCP配置中；Skill不读取、不输出、不写入普通日志，也不在最终回复中复述。通过固定协议调用团队知识服务：

1. 先调用`knowledge_service_status`检查连接，只有返回`connected: true`才视为连接成功。
2. 解析企业、项目、地区、年份、批次和文件类型意图，读取 [检索编排协议](references/search-orchestration.md)。
   涉及首台套、首版次或首批次企业与产品名单时，同时读取 [三首项目名单数据协议](references/three-first-project-list-schema.md)。
3. 已知企业查名单时并行调用 `POST /v1/lists/search` 与 `POST /v1/search`；按产品、行业或技术方向反向找已认定企业时，统一调用 `POST /v1/recognition/search` 或 MCP `recognition_search`，由服务端解析全部项目、主题词、地区、年度与状态，并分开返回确切、相关和待核验结果。三首项目统一调用 `POST /v1/three-first/analyze` 或 MCP `three_first_analysis`，一次保留全部项目和地区，由服务端组合产品名单、目录差异和全文结果；其他问题至少调用全文检索。
4. 首轮未命中时自动执行简称、全称、年份、批次、文件类型和地区层级变体，不得停止。
5. 涉及企业跨年名单、复核状态或城市归属时，读取企业身份时间轴；缺少当前身份时优先用天眼查补充统一社会信用代码、现名、曾用名和当前登记地区，企查查补齐缺失或高影响字段，最终冲突回到官方来源裁决。
6. 对关键命中调用 `GET /v1/documents/{id}` 读取完整提取文本和来源路径。
7. 项目检索或企业成长路径中命中当前有效申报通知时，识别企业申报截止时间并按北京时间动态计算剩余天数；企业截止与主管部门报送截止并存时优先企业截止。
8. 结果必须回到原文件核验，政策时效重新确认。
9. 云端服务不可用时，使用当前会话文件、本地个人政策规则和政府官方来源降级核验，不读取团队本地知识库镜像。

上述三首专用查询属于现有 `jiaotang-kb` MCP 的内部能力。根据用户自然语言自动调用，不让用户新增第二个 MCP、重新生成凭据或手工选择工具；现有客户端工具列表未刷新时，只需重新连接原 MCP。

三首项目按“公示—认定—奖励—目录退出”分别记录状态事件，不以后序状态删除前序证据。没有明确目录退出原文时不得推断退出。无法取得具体产品名称时只返回企业、项目、年度和来源，固定提示用户自行查找并补充产品名称，不生成“未展开产品”等占位名称。

通过 MCP 调用时使用同一流程：普通名单由 `public_list_search` 与 `knowledge_search` 并行，关键文档再调用 `knowledge_document`；三首组合任务调用统一入口 `three_first_analysis`；产品或行业反查调用 `recognition_search`。必须检查 `coverage`、`pagination`、全部项目分组和三档结果，不得静默只取第一个项目、地区或第一页，也不得因为任一工具返回空结果而跳过另一条路径。

反向发现结果必须分开保存“产品或行业证据”和“正式认定证据”。`verified_matches` 才能进入已认定主表；`pending_candidates` 只能列为待核验线索。当前知识证据没有覆盖的行业、地区、年度或同义词必须明示，未命中只能写“当前检索层未命中”。

## 案例包分层调用

需要历史案例、建设方案或附件结构时，先用 `knowledge_case_pack` 按 `project_id`、年度、行业、企业规模筛选三至五套案例。首轮只读取申报书或建设方案骨架；写到具体章节时，再用 `section` 展开对应佐证附件。案例只用于结构、指标组织和证据类型参考，不得把案例企业的财务、客户、技术、知识产权或人员事实复制给当前客户。返回 `auto_grouped` 时表示目录关系由系统自动归组，关键结论仍须回到原文件核验。

## 政策资料分层路由

`10_政策与目录` 中保留两类物理分开的资料，不把它们合并成同一文件夹：

- 规则层：管理办法、认定条件、申报指引、材料模板、维护规则和历史案例。
- 动态层：`政策数据库/企策顾问` 下按地区归档的申报通知、公示公告、名单和截止时间线索。

查询“条件、门槛、标准、评分、管理办法、材料、模板、维护”时后台先查规则层，再核验当期官方通知。查询“最新、当前、通知、公示、名单、截止、开放、批次或具体年度”时后台先查动态层，再回到官方原文。只输入“高新”等项目简称且意图不清时，先确认用户要查申报条件还是最新通知，不得静默只选一层。

企策顾问资料只作动态发现和内部索引线索；最终政策条件、申报时间和名单结论必须保留来源路径，并以主管部门官方原文核验。

后台检索必须使用 `source_layer`、`source_labels`、`verification_status` 和 `validity_status` 完成排序与核验，但这些内部字段不得显示在网站答复、报告、申报材料或其他用户交付文件中：

- `规则层`表示管理员维护的办法、规则、指引或稳定资料。
- `动态层`表示企策顾问等动态采集资料。
- `官方原文`只表示系统已识别政府或法定机构来源链接，不等同于已经人工核验全部条款。
- 动态层未识别官方原文时，后台继续核对官方原文或当期通知；对外只给核验后的结论、可追溯文件名称和来源链接。

未连接、无权限或未命中时分别说明当前检索层状态，不写成资料不存在。
