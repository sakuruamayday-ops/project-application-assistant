# 第二版当前纳入范围

本文件记录主人确认的本轮纳入范围，用于后续审查、提交和发布时核对依赖。当前只确认范围，不代表已经提交、推送或发布。

## 必选能力

### 统一首次配置

- `first-run-configuration`
- 一次检测团队云端、企查查、专利数据、浏览器MCP、本地OCR和文档能力
- 生成当前用户专用凭据文件及不含密钥的能力报告
- 其他Skill读取统一报告，不再分别重复索要凭据

### 企业全景报告

- `enterprise-panorama-analysis`
- 使用团队云端知识、包内企业画像和专利技能组
- 所有模板、品牌资源和检查脚本均使用Skill内相对路径
- PDF、Word和Excel通用能力由Agent提供，不重复打包

### 本地政策规则与自动归档

- `project-rule-manager` 允许成员在本地 `project-rules/` 增改、撤回和修改政策来源
- 成员规则不写团队云端知识库，云端上传和索引仍由管理员执行
- `project-deliverable-archive` 自动整理工作区成果，不依赖Obsidian

### 专利数据底座与检索核心

- `patent-data-foundation`
- `patent-search-core`
- 配套的数据规范、来源许可规则、检索协议和确定性脚本

### 专利业务技能组

- `patent-claim-analysis`
- `patent-similarity-search`
- `patent-fto-analysis`
- `patent-drafting-coach`
- `patent-draft-auditor`
- `patent-direction-planner`
- `patent-benchmark-landscape`
- 更新后的 `patent-layout-planning`
- 更新后的 `ip-assessment`

### 原创与来源记录

- `docs/provenance/patent-skills.md`

### 项目地图与项目匹配

- 更新后的 `project-matching`
- 脱敏项目地图、标准项目索引和高频项目规则
- 地区过滤、项目地图构建和高频规则构建脚本
- 项目地图及地区过滤测试

### 通用网页任务

- `web-task-operator`
- 网页安全执行协议
- 企策顾问浏览器操作规则
- 浏览器本地重放降级方案

### 企业全生命周期助手总入口

- 更新后的 `project-application-assistant`
- 默认地区读取和本地后备配置
- 更新后的 `project-task-router`
- 签单后人工移交终版资料的业务规则

## 实验性加入

### 第三方数据增量索引

- `third-party-data-indexing`
- SQLite 索引、增量更新、断点、去重、版本和导出脚本
- 数据索引测试

发布时必须保留以下标识：

- 默认不启用。
- 仅在用户明确授权和配置后运行。
- 第三方结果只作发现线索。
- 正式项目判断必须回到政府官方原文。
- 登录、验证码、付费限制或访问拒绝时停止，不规避。

## 修正后加入

### 供应商配置

- `docs/config/aiqice.md`
- `docs/config/government-browser.md`
- `docs/config/qcc.md`
- 更新后的 `enterprise-profile`

配置说明统一要求：凭据只进入Agent安全凭据存储、环境变量或密钥管理服务，不在对话、Skill、日志、交付文件或公共仓库中保存。

## 依赖关系

### 专利能力

```text
patent-data-foundation
        ↓
patent-search-core
        ↓
权利要求分析 / 相似检索 / FTO / 方向规划 / 对标布局 / 申请质检
```

- `patent-data-foundation` 是所有批量专利业务的前置依赖。
- 需要现有技术、稳定性、FTO或竞争对手检索时依赖 `patent-search-core`。
- `patent-drafting-coach` 可以整理真实技术材料，但不得虚构技术事实。
- FTO与创造性、稳定性检索必须分开。

### 项目匹配能力

```text
project-application-assistant
        ↓
默认地区 → project-matching → 官方政策核验
                           ↘ 可选 third-party-data-indexing
                                      ↓
                              web-task-operator
```

- 项目地图回答“应该关注什么”，不表示当前开放申报。
- 第三方索引是可选实验性依赖，失败不得阻断官方政策检索。
- 只有核验管理办法、当期通知和企业证据后，才能判断当期可申报性。

### 企业画像能力

```text
enterprise-profile
        ↓
用户材料 / 合法授权数据接口 / 政府公开来源
```

- 企查查不可用时必须降级，不以过期缓存补造企业现状。
- 财务数据仍只使用用户明确提供或授权的可靠来源。

## 本轮暂不纳入

- `agents/` 元数据和转换适配包。
- `scripts/build_standard_package.py` 和已生成的 ZIP 包。
- 独立 `project-handoff` Skill。
- 部门技能权限分级和复杂协作流转。
- 腾讯云知识服务代码和部署产物。
- 企策顾问云端轻量 HTTP 服务及扣子工作流。
- IMA 已退出后续架构，不再安排订阅知识库导出或调用。
- 最终收尾清单中的清理与开箱即用设计。

## 发布前门禁

1. 检查本文件列出的全部依赖均存在。
2. 验证所有新增和修改后的 Skill 格式。
3. 运行全部测试。
4. 以 `ResourceWarning` 作为错误运行测试，确认不存在 SQLite 连接未关闭问题。
5. 扫描明文凭据、客户数据、本机绝对路径和第三方受限原文。
6. 逐项确认暂存区只包含本轮纳入文件。
7. 经主人确认后再提交、推送或发布。
