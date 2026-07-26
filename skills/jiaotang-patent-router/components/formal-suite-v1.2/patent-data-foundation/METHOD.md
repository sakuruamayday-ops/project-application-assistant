---
name: patent-data-foundation
description: 统一专利检索与分析使用的数据口径，负责专利号规范化、文本版本区分、三级法律状态来源、简单同族与扩展同族去重、申请人和当前权利人归一化、数据授权及可追溯记录。任何批量专利检索、相似专利、FTO、专利质检、预审分类匹配或行业专利布局任务均应先使用本技能建立数据底座。
---

# 专利数据底座


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 跨平台首次运行与个人习惯

支持CodeBuddy/WorkBuddy内联命令的宿主会在技能触发时自动执行下面的确定性门禁，并把JSON结果注入当前上下文：

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

作为WorkBuddy插件加载时，还会把本轮实际触发的技能与当前会话和轮次绑定：

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "patent-data-foundation" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发本技能时，第一步必须定位当前`SKILL.md`所在的技能目录，并以该目录为工作目录运行`python3 scripts/portable_skill_runtime.py prepare`。不得因为当前任务看似简单而跳过。将返回的`active_preferences`作为用户个人习惯应用于当前任务；结果为`fail`时停止执行，不得声称安装、自检或升级成功。`capability_check`为`limited`时，只使用宿主已具备的能力，并明确未通过的依赖项，不得声称依赖完整。

用户以“以后、默认、记住、每次、别再”等措辞明确表达长期习惯时：若上下文已出现“偏好桥接轮次已建立”的WorkBuddy钩子提示，不要手动调用`remember`，由停止钩子只向本轮实际触发且已经按会话、轮次绑定的技能写入；其他宿主则在最终答复前调用`python3 scripts/portable_skill_runtime.py remember --instruction '用户原意' --scope default --source agent-confirmed`，再调用`context`确认。未取得`status: pass`和对应偏好记录时，严禁声称“已记住”或“以后会默认采用”。无法执行保存时，只能说明本次会话已理解、尚未形成跨会话偏好。“这次、本次、当前文件、临时”等要求只影响当前任务，禁止写入长期偏好。无需让用户了解或输入存储命令。发生歧义、偏好冲突或可能削弱强制质量门禁时才询问。

个人配置保存在技能目录外并自动备份。不得用个人偏好覆盖真实性、安全、验签、安装自检或本技能的强制质量门禁。完整规则见[跨平台技能运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

先读取 `first-run-configuration` 生成的能力报告。专利API或MCP未配置时只说明当前数据层限制，不在各专利业务Skill重复索要供应商凭据。

先建立统一记录，再进行任何业务判断。不得由各业务技能自行定义专利身份、同族、法律状态或申请人归属。

## 执行顺序

1. 读取 [data-schema.md](references/data-schema.md) 建立标准记录。
2. 读取 [source-and-license-policy.md](references/source-and-license-policy.md) 选择用户已配置的数据源。
3. 使用 `scripts/normalize_patent_records.py` 规范化编号、日期和主体名称。
4. 分别保留申请公开A版、授权公告B版及复审无效后文本，不覆盖历史版本。
5. 按官方登记簿、官方公报、第三方数据库记录法律状态；冲突时以前两级为准。
6. 同时输出文献数、申请数、简单同族数、扩展同族数和中国有效专利数。
7. 区分原始申请人、当前权利人、集团关联主体、共同申请人和转让取得主体。

## 连接器

- 使用 `scripts/patent_connector.py` 建立本地SQLite专利索引并导入用户自行取得的国家知识产权局批量数据或第三方导出数据。
- 具体数据源顺序和配置见 [connector-guide.md](references/connector-guide.md)。

## 强制边界

- 不把审中申请视为授权专利。
- 不把同一发明的多国文献视为多项独立技术。
- 不根据名称相似直接认定集团关系。
- 不随技能包分发第三方原始数据库、批量全文、密钥或访问令牌。
- 未命中写“当前数据源未命中”，不得写“不存在”。
- 所有业务技能引用本技能口径，不复制维护分类和状态规则。
