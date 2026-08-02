<h1 align="center">企业全生命周期助手</h1>

<p align="center">
  面向政府项目申报工程师与知识产权顾问的专业 Agent 工作系统。<br>
  把政策、企业、财务、知识产权与申报材料组织成可追溯、可复核的完整工作流。<br>
  当前包含 49 项顶层 Skills，专利能力收敛为 2 个顶层入口；公司级总路由内部执行 P1、P2、P3 三个阶段。
</p>

<p align="center">
  <a href="https://github.com/sakuruamayday-ops/project-application-assistant/releases/tag/V1.5.0"><img src="https://img.shields.io/badge/Release-V1.5.0-C9A760?style=for-the-badge" alt="Release V1.5.0"></a>
  <a href="skills/suite-manifest.json"><img src="https://img.shields.io/badge/Skills-49-17181A?style=for-the-badge" alt="49 Skills"></a>
  <a href="docs/releases/V1.5.0.md"><img src="https://img.shields.io/badge/Release%20Channel-Verified-2F7D5C?style=for-the-badge" alt="Verified release channel"></a>
  <a href="https://zshjiaotang.cn/"><img src="https://img.shields.io/badge/Portal-zshjiaotang.cn-8A6A2F?style=for-the-badge" alt="Team portal"></a>
</p>

---

## 它解决什么问题

申报工作真正困难的不是生成一段文字，而是同时守住政策版本、企业事实、指标口径、证据来源、章节一致性和交付质量。企业全生命周期助手把这些要求编排成 49 项可复用 Skills，并通过统一入口自动路由。

| 核心能力 | 能做什么 |
|---|---|
| 项目发现与评估 | 识别可申报项目、核对门槛、计算差距并形成申报优先级 |
| 政策与证据 | 检索政策原文、记录来源与时效，区分事实、计算、推断和待核验项 |
| 材料写作与体检 | 撰写、复核和对比申报材料，检查数据、产品、知识产权与叙事一致性 |
| 企业与财税 | 形成企业画像、公开信息全景分析、财务复算与制造企业税务风险筛查 |
| 专利全流程 | 总路由统筹查新、挖掘、交底、双中心预审与审查意见分析；申请文件核稿由独立入口执行 |
| 交付与治理 | 执行版本门禁、证据台账、四问复盘、受控进化和可回滚发布 |

```text
用户提出任务
  → project-application-assistant 统一入口
  → project-task-router 识别任务与阶段
  → 专业 Skills 调用知识、企业或专利能力
  → evidence-ledger 记录事实、计算、推断与缺口
  → consistency-check 与专项门禁
  → 输出报告、材料或行动清单
```

## 下载与安装

### 团队成员

登录[团队门户](https://zshjiaotang.cn/)，进入「连接我的 Agent」，点击“一键安装”，把网站生成的一段完整指令粘贴给 WorkBuddy。该指令同时完成49项Skills安装或覆盖、最小行为Hook、远程MCP合并、一次重载和状态验收。

### GitHub 下载

| 使用环境 | 下载 | 安装入口 |
|---|---|---|
| 支持完整 Skills 目录的 Agent | 通用 Skills | 按宿主的 Skill 导入流程加载完整目录 |
| WorkBuddy 5 或更高版本，macOS 与 Windows | 跨平台 WorkBuddy 包 | 在门户复制一段完整指令给 WorkBuddy |
| 其他支持 Streamable HTTP MCP 的 Agent | 通用 Skills 加远程 MCP | 从手工配置页复制已自动填入个人 Token 的完整配置 |

发布目标只有两个：通用Skills与跨平台WorkBuddy插件市场包。WorkBuddy的macOS和Windows使用同一个ZIP，不再分别维护版本。

WorkBuddy用户只复制粘贴一次。安装包不含本地MCP服务、Node启动器、bootstrap、设备登记、钥匙串或DPAPI；用户侧不执行签名审查和插件目录哈希检查。手工配置页自动复用或生成当前登录用户的个人Token并填入完整远程HTTP MCP配置。

V1.5.0 是首个面向外部用户的正式版本。此前版本继续保留为内部演进与审计历史，不覆盖、不改写。V1.5.0 一键安装会把旧版和重复副本移出活动插件搜索路径，在搜索路径外保留一个回滚快照，并在验收后把其余旧副本移入系统回收站，避免旧 Hook 被再次选中。

### WorkBuddy 平台说明

WorkBuddy的系统差异由同一个插件市场包处理。安装完成标准统一为：49项Skills可识别，`tools/list`出现`knowledge_search`、`knowledge_document`、`knowledge_service_status`，并实际调用状态工具返回`connected: true`。

## 安全边界

- 受控发布通道对最终产物和门禁报告执行Ed25519签名与SHA-256校验；WorkBuddy用户侧不重复执行验签或全目录哈希。
- 安装与更新流程拒绝路径穿越、绝对路径、符号链接、重复条目和哈希不一致。
- 主人下达发布指令后由受控发布流程生成正式包；安装指令不包含网页动态命令字段。
- 安装只替换用户配置中的`mcpServers.jiaotang-kb`，保留其他MCP条目。
- 最小Hook只约束Skill调用和交付检查；内部异常失败开放，不因插件变化、更新或卸载阻断普通提问。
- 客户密钥、账号登录态、签名私钥和付费数据库不进入仓库或发布包。

## 49 项 Skills

正式技能、依赖关系、外部服务和发布门禁以 [`skills/suite-manifest.json`](skills/suite-manifest.json) 为唯一机器可读基线。

主要能力组包括：

- 企业画像、同行对标与项目成长路径
- 政策检索、项目匹配、可行性分析与测分
- 申报材料写作、版本对比、一致性检查与归档
- 专精特新、小巨人、高新技术企业与三首项目
- 专利检索、分析、FTO、布局、撰写和审查
- 财务核验、制造企业税务风险、法律法规与标准
- 证据台账、首次配置、偏好继承与受控进化

## 文档导航

| 文档 | 用途 |
|---|---|
| [用户使用手册](docs/user-guide/企业全生命周期助手用户使用手册.docx) | 下载、安装、首次配置和日常使用 |
| [API 与 MCP 配置](docs/user-guide/api-mcp-configuration.md) | 团队知识服务、个人Token和远程MCP边界 |
| [V1.5.0 发布说明](docs/releases/V1.5.0.md) | 当前版本变更、兼容性和已知限制 |
| [产品文档](docs/product/README.md) | 产品定位、PRD、路线图与外部工具评估 |

## 开发与验证

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q tests
cd services/knowledge-portal
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q tests
```

知识库内容更新不要求重新安装 Skills。只有规则、流程、能力或发布门禁发生变化时才创建新版本。

### 两阶段受控发布命令

受控命令只消费已经完成签名的候选包，不生成签名，也不会自动递增版本。先执行只读预检：

```bash
RELEASE_VERSION=按正式发布指令填写
python3 scripts/controlled_release.py \
  --version "$RELEASE_VERSION" \
  --generic-package "dist/企业全生命周期助手-V${RELEASE_VERSION}.zip" \
  --workbuddy-package "dist/企业全生命周期助手-V${RELEASE_VERSION}-WorkBuddy.zip" \
  --gate-report "dist/企业全生命周期助手-V${RELEASE_VERSION}-发布门禁.json" \
  --release-notes "docs/releases/V${RELEASE_VERSION}.md"
```

预检确认版本完全一致、默认分支干净、签名包与发布门禁全部通过后，先在同一命令末尾追加 `--stage`。系统创建 GitHub 预发布，并在知识门户登记“正式发布中”，随后强制暂停：

```text
GitHub 预发布
  → 网站登记同一批候选文件为“正式发布中”
  → 暂停，等待主人独立确认
```

主人明确说出“确认正式发布”后，才执行第二条命令：在原参数后追加
`--promote --confirm-text "确认正式发布"`。系统核对预发布提交和全部候选资产哈希，
随后以通用正式包为唯一升级源，对本机 `~/.codex/skills` 执行原子替换、49 项
Skill 全量验签以及开发源、正式包、隔离验收目录三方哈希比对。部署后门禁通过，
才把同一批候选文件登记为网站正式版，最后将 GitHub 预发布提升为 Latest。

`--execute` 一步直发入口已停用。任一步失败都会停止；没有独立确认时，
候选版本只能保持“正式发布中”，不能替换当前正式版。

每次安装命令、跳过原因、备份、回滚和验签结果分别写入
`~/.config/project-assistant/install-executions.jsonl` 与单次升级报告；三方审计
统一写入 `~/.config/project-assistant/deployment-audits/`。已签名安装目录会移除
写权限，日常开发必须在独立工作树完成。

## 版本口径

| 层级 | 当前值 | 说明 |
|---|---|---|
| 产品标签 | `V1.5.0` | 网站、GitHub Release 和用户可见版本 |
| 组件版本 | `1.5.0` | 套件、插件和 Python 组件版本 |
| 数据规则版本 | 独立命名 | 例如 `policy-cluster-v1.0.0`，不代表产品版本 |
| 历史版本 | `V1.0`、`V1.1`、`V1.2`、`V1.3`、`V1.3.1`、`V1.3.1.1`、`V1.3.1.2`、`V1.3.1.3`、`V1.3.1.4`、`V1.4.0`、`V1.4.1`、`V1.4.2`、`V1.4.3`、`V1.4.4`、`V1.4.5`、`V1.4.6`、`V1.4.7`、`V1.4.8`、`V1.4.9` | 仅保留在历史 Release、迁移脚本、审计和测试中；不覆盖既有产物 |

GitHub 文件列表右侧显示的是“最后修改该路径的提交标题”，不是该目录的当前版本。

## 使用边界

- 不承诺企业一定符合条件或项目一定获批。
- 正式判断优先使用管理办法、当期通知和可核验企业资料。
- 无可靠数据时不补造财务、客户、产能或知识产权状态。
- 未命中只能表述为“当前检索层未命中”。
- 外部提交、云端上传和技能签名核心替换必须获得明确授权。

## 许可证

本项目采用[专有许可](LICENSE)：源码可见，但未经著作权人事先书面许可，不得用于客户交付、咨询服务、SaaS、产品集成、付费培训或其他直接、间接商业用途。公开仓库、Fork、下载或 Pull Request 均不构成商业授权。商业合作请通过下方联系方式联系。

## 联系与商业合作

微信：扫描二维码添加，添加时请备注合作事项。

<img src="docs/assets/contact/wechat-qr.jpg" alt="微信二维码，人生海海" width="280">

QQ：`138500227` · [点击唤起 QQ 聊天](https://wpa.qq.com/msgrd?v=3&uin=138500227&site=qq&menu=yes)
